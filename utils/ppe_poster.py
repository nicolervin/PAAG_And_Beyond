"""PPE Poster Generator (11x17 Landscape) HTML renderer and asset helpers."""

from __future__ import annotations

import base64
import html
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.safety_store import (
    EHS_LOGO_PATH,
    PPE_CATALOG,
    PPE_ICONS_DIR,
    STANDARD_BASELINE_PPE,
    get_ppe_catalog_item,
    resolve_pitch_ppe_rollup,
)


@lru_cache(maxsize=64)
def _file_to_data_uri(path_str: str) -> str:
    """Read an image file and return a base64 data URI, cached in memory."""
    if not path_str:
        return ""
    p = Path(path_str)
    if not p.is_file():
        return ""
    try:
        raw = p.read_bytes()
    except OSError:
        return ""
    ext = p.suffix.lower().lstrip(".")
    mime = "image/png" if ext == "png" else f"image/{ext or 'png'}"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def get_ppe_icon_data_uri(ppe_name: str) -> str:
    """Return a base64 data URI for a catalog PPE item's icon."""
    item = get_ppe_catalog_item(ppe_name)
    if not item:
        return ""
    img_path = item.get("image_path") or ""
    return _file_to_data_uri(str(img_path))


def get_jsa_icon_data_uri(ppe_name: str) -> str:
    """Return a base64 data URI for a catalog PPE item's JSA icon (falling back to standard PPE icon)."""
    item = get_ppe_catalog_item(ppe_name)
    if not item:
        return ""
    jsa_path = str(item.get("jsa_image_path") or "").strip()
    if jsa_path and Path(jsa_path).is_file():
        return _file_to_data_uri(jsa_path)
    img_path = str(item.get("image_path") or "").strip()
    return _file_to_data_uri(img_path)


def _resolve_media_data_uri(raw_path: str) -> str:
    """Resolve an uploaded PAAG visual aid path or URL into an embeddable image src."""
    cleaned = str(raw_path or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith(("http://", "https://", "data:")):
        return cleaned
    p = Path(cleaned)
    if not p.is_file():
        from utils.db_core import ROOT, resolve_upload_path
        cand = Path(ROOT) / cleaned
        if cand.is_file():
            p = cand
        else:
            try:
                resolved = resolve_upload_path(cleaned)
                if resolved and Path(resolved).is_file():
                    p = Path(resolved)
            except Exception:
                return ""
    return _file_to_data_uri(str(p)) if p.is_file() else ""


def get_ehs_logo_data_uri() -> str:
    """Return a base64 data URI for the EHS&S logo."""
    return _file_to_data_uri(str(EHS_LOGO_PATH))


def build_ppe_poster_html(
    *,
    job_name: str = "",
    workstation: str = "",
    section_name: str = "",
    selected_ppe_names: list[str] | None = None,
    effective_ppe_items: list[Any] | None = None,
    pitch_label: str = "",
    overridden_items: list[dict[str, Any]] | None = None,
    overrides: list[dict[str, Any]] | None = None,
    allow_interactive_selector: bool = True,
    interactive_controls: bool | None = None,
    default_job: str = "",
    default_workstation: str = "",
    default_section: str = "",
) -> str:
    """Render the self-contained 11x17 landscape PPE Poster HTML component."""
    if interactive_controls is not None:
        allow_interactive_selector = bool(interactive_controls)

    raw_ppe_input: list[str] = []
    if selected_ppe_names is not None:
        raw_ppe_input = [str(x) for x in selected_ppe_names if str(x or "").strip()]
    elif effective_ppe_items is not None:
        for entry in effective_ppe_items:
            if isinstance(entry, dict):
                nm = str(entry.get("canonical_name") or entry.get("name") or "").strip()
                if nm:
                    raw_ppe_input.append(nm)
            elif str(entry or "").strip():
                raw_ppe_input.append(str(entry).strip())

    rollup = resolve_pitch_ppe_rollup(raw_ppe_input)
    effective_names = rollup.get("effective_canonical_names") or rollup["effective_names"]
    initial_mode_class = "mode-standard" if rollup.get("is_standard_mode") else "mode-special"
    initial_badge_class = "standard" if rollup.get("is_standard_mode") else "special"
    initial_badge_text = (
        "Standard Baseline Border (Green)"
        if rollup.get("is_standard_mode")
        else "Special / Elevated PPE Border (Purple)"
    )

    catalog_js_items: list[dict[str, Any]] = []
    seen_catalog_names: set[str] = set()
    for item in PPE_CATALOG:
        name = item["name"]
        seen_catalog_names.add(name)
        catalog_js_items.append(
            {
                "name": name,
                "image": _file_to_data_uri(item["image_path"]),
                "hazard": item["hazard"],
                "mitigation": item["mitigation"],
            }
        )
    # Include any custom non-catalog PPE items assigned to the pitch so they also render on the table/poster
    for eff_item in rollup["effective_items"]:
        if eff_item["name"] not in seen_catalog_names:
            catalog_js_items.append(
                {
                    "name": eff_item["name"],
                    "image": "",
                    "hazard": eff_item.get("hazard") or "Task-specific workplace hazard.",
                    "mitigation": eff_item.get("mitigation")
                    or f"Correctly wear approved {eff_item['name'].upper()}.",
                }
            )

    logo_uri = get_ehs_logo_data_uri()
    catalog_json = json.dumps(catalog_js_items, ensure_ascii=False)
    selected_json = json.dumps(effective_names, ensure_ascii=False)
    baseline_json = json.dumps(list(STANDARD_BASELINE_PPE), ensure_ascii=False)

    safe_job = html.escape(str(job_name or default_job or "").strip())
    safe_ws = html.escape(str(workstation or default_workstation or "").strip())
    safe_sec = html.escape(str(section_name or default_section or "").strip())
    safe_pitch_label = html.escape(str(pitch_label or workstation or default_workstation or "Pitch").strip())

    override_banner_html = ""
    override_source = overridden_items if overridden_items is not None else (overrides or rollup.get("overrides") or [])
    if override_source:
        badges = []
        for ov in override_source:
            if not isinstance(ov, dict):
                continue
            if "overridden_by" in ov and "item" in ov:
                badges.append(
                    f"<strong>{html.escape(str(ov['overridden_by']))}</strong> overrides "
                    f"<em>{html.escape(str(ov['item']))}</em> ({html.escape(str(ov.get('category') or ''))})"
                )
            elif "winner" in ov and "overridden_items" in ov:
                ov_items_str = ", ".join(str(x) for x in (ov.get("overridden_items") or []))
                badges.append(
                    f"<strong>{html.escape(str(ov['winner']))}</strong> overrides "
                    f"<em>{html.escape(ov_items_str)}</em> ({html.escape(str(ov.get('category_label') or ''))})"
                )
            elif "summary" in ov:
                badges.append(html.escape(str(ov["summary"])))
        if badges:
            override_banner_html = (
                '<div class="override-info-banner no-print">'
                "<span>⚡ Automatic Pitch Hierarchy Override applied: "
                + " &bull; ".join(badges)
                + "</span></div>"
            )

    selector_display_style = "" if allow_interactive_selector else "display:none;"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Minimum PPE Requirements Poster - {safe_pitch_label}</title>
<style>
  :root {{
    --page-w: 17in;
    --page-h: 11in;
    --page-pad: 0.25in;
    --border-pad: 0.28in;
    --poster-inner-pad: 0.20in;
    --col-gap: 0.20in;
    --left-col-w: 58%;
    --right-col-w: 42%;
    --brand: #3b4b59;
    --accent: #0f3b5f;
    --ink: #111;
    --muted: #555;
    --card: #f9fafb;
    --grid: #dcdfe4;
  }}

  @page {{
    size: 17in 11in;
    margin: 0.25in;
  }}

  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}

  html, body {{
    margin: 0;
    padding: 0;
    color: var(--ink);
    font-family: Segoe UI, Roboto, Arial, sans-serif;
    background: #eef2f6;
  }}

  .toolbar-wrap {{
    max-width: 16.5in;
    margin: 10px auto 8px auto;
    background: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 10px;
    padding: 12px 16px;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
  }}

  .toolbar-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 10px;
  }}

  .toolbar-actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }}

  .btn {{
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 600;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }}
  .btn:hover {{
    opacity: 0.92;
  }}
  .btn-secondary {{
    background: #475569;
  }}
  .btn-outline {{
    background: #f8fafc;
    color: #0f3b5f;
    border: 1px solid #cbd5e1;
  }}

  .mode-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
  }}
  .mode-badge.standard {{
    background: #dcfce7;
    color: #166534;
    border: 1px solid #86efac;
  }}
  .mode-badge.special {{
    background: #f3e8ff;
    color: #6b21a8;
    border: 1px solid #d8b4fe;
  }}

  .override-info-banner {{
    max-width: 16.5in;
    margin: 6px auto;
    padding: 8px 14px;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    color: #1e3a8a;
    font-size: 13px;
  }}

  .interactive-drawer {{
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid #e2e8f0;
    display: none;
  }}
  .interactive-drawer.open {{
    display: block;
  }}

  .meta-inputs-row {{
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 10px;
  }}
  .meta-inputs-row label {{
    display: flex;
    flex-direction: column;
    font-size: 12px;
    font-weight: 600;
    color: #334155;
    flex: 1 1 200px;
  }}
  .meta-inputs-row input {{
    margin-top: 4px;
    padding: 6px 8px;
    font-size: 13px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
  }}

  .ppe-selector-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: 8px;
    margin-top: 8px;
    max-height: 220px;
    overflow-y: auto;
    padding: 4px;
  }}

  .ppe-item-btn {{
    border: 2px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px;
    text-align: center;
    cursor: pointer;
    background: #fff;
    transition: transform 0.08s ease, box-shadow 0.08s ease, border-color 0.08s ease;
  }}
  .ppe-item-btn:hover {{
    transform: translateY(-1px);
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
  }}
  .ppe-item-btn.selected {{
    border-color: #2563eb;
    background: #eff6ff;
  }}
  .ppe-item-btn img {{
    max-width: 52px;
    max-height: 52px;
    display: block;
    margin: 0 auto 4px;
    object-fit: contain;
  }}
  .ppe-item-btn span {{
    font-size: 11px;
    line-height: 1.2;
    display: block;
    color: #1e293b;
    font-weight: 600;
  }}

  .poster-viewport {{
    width: 100%;
    overflow-x: auto;
    padding: 4px 0 16px 0;
  }}

  #posterPage {{
    width: calc(var(--page-w) - 2*var(--page-pad));
    height: calc(var(--page-h) - 2*var(--page-pad));
    margin: 0 auto;
    padding: var(--border-pad);
    border-radius: 10px;
    position: relative;
    background:
      repeating-linear-gradient(
        135deg,
        #b998ff 0 16px,
        #ffffff 16px 32px
      );
    box-shadow: 0 4px 16px rgba(15, 23, 42, 0.14);
  }}

  #posterPage.mode-standard {{
    background:
      repeating-linear-gradient(
        135deg,
        #19a974 0 16px,
        #ffffff 16px 32px
      );
  }}

  #posterPage.mode-special {{
    background:
      repeating-linear-gradient(
        135deg,
        #6f42c1 0 16px,
        #ffffff 16px 32px
      );
  }}

  #poster {{
    width: 100%;
    height: 100%;
    background: #fff;
    border-radius: 6px;
    border: 2px solid var(--brand);
    padding: var(--poster-inner-pad);
    display: grid;
    grid-template-rows: auto auto 1fr;
    row-gap: 0.14in;
    overflow: hidden;
  }}

  .poster-header {{
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #e9edf2;
    border: 1.5px solid var(--brand);
    border-radius: 6px;
    padding: 0.10in 0.16in;
    min-height: 1.1in;
  }}
  .poster-header h2 {{
    margin: 0;
    font-size: 28pt;
    letter-spacing: 0.5px;
    color: #1f2d3a;
    font-weight: 800;
    text-align: center;
  }}
  .header-logo {{
    position: absolute;
    right: 0.16in;
    top: 50%;
    transform: translateY(-50%);
    max-height: 0.9in;
    max-width: 2.2in;
    width: auto;
    height: auto;
    object-fit: contain;
  }}

  .validation-box {{
    position: absolute;
    left: 0.16in;
    top: 50%;
    transform: translateY(-50%);
    width: 2.6in;
    height: 0.9in;
    border: 2px dashed var(--brand);
    border-radius: 6px;
    background: #fff;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 0.06in 0.1in;
  }}
  .validation-title {{
    font-size: 10pt;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: var(--brand);
    text-transform: uppercase;
  }}
  .validation-sub {{
    font-size: 8.5pt;
    color: var(--muted);
    italic: true;
  }}

  .meta-bar-inline {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 0.12in;
  }}
  .meta-chip {{
    border: 1.5px solid var(--brand);
    border-radius: 6px;
    padding: 0.08in 0.12in;
    background: #f5f7fa;
    font-size: 12pt;
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-height: 0.45in;
  }}
  .meta-chip strong {{
    color: #1f2d3a;
    white-space: nowrap;
  }}
  .meta-chip span {{
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}

  .poster-body {{
    display: grid;
    grid-template-columns: var(--left-col-w) var(--right-col-w);
    column-gap: var(--col-gap);
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }}

  .icons-panel {{
    border: 1.5px solid var(--grid);
    border-radius: 6px;
    padding: 0.14in;
    background: var(--card);
    display: grid;
    grid-template-rows: auto 1fr;
    min-height: 0;
    overflow: hidden;
  }}
  .panel-title {{
    font-size: 12pt;
    font-weight: 700;
    color: var(--brand);
    margin: 0 0 0.08in 0;
  }}

  #posterIcons {{
    --cols: 3;
    --tile-h: 160px;
    --img-h: 110px;
    --cap-fs: 10.5pt;
    display: grid;
    grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
    grid-auto-rows: var(--tile-h);
    gap: 0.12in;
    align-content: start;
    justify-items: stretch;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    background: #fff;
    border: 1px solid var(--grid);
    border-radius: 6px;
    padding: 0.12in;
  }}

  .icon-tile {{
    border: 1px solid #e4e7ec;
    border-radius: 8px;
    background: #fff;
    padding: 0.08in;
    display: grid;
    grid-template-rows: 1fr auto;
    align-items: center;
    justify-items: center;
    overflow: hidden;
  }}
  .icon-tile img {{
    max-width: 100%;
    max-height: var(--img-h);
    width: auto;
    height: auto;
    object-fit: contain;
    display: block;
  }}
  .icon-tile .caption {{
    margin-top: 0.05in;
    text-align: center;
    font-size: var(--cap-fs);
    line-height: 1.15;
    color: #222;
    word-break: break-word;
    max-height: 2.4em;
    overflow: hidden;
  }}

  .table-panel {{
    border: 1.5px solid var(--grid);
    border-radius: 6px;
    padding: 0.14in;
    background: var(--card);
    display: grid;
    grid-template-rows: auto 1fr;
    min-height: 0;
  }}
  .table-wrap {{
    background: #fff;
    border: 1px solid var(--grid);
    border-radius: 6px;
    padding: 0.08in;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    display: grid;
    grid-template-rows: 1fr;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    font-size: 10.5pt;
  }}
  thead th {{
    background: #eef2f7;
    color: #1f2d3a;
    border: 1px solid var(--grid);
    padding: 6px 8px;
    font-weight: 700;
    text-align: left;
  }}
  tbody td {{
    border: 1px solid var(--grid);
    padding: 6px 8px;
    vertical-align: top;
    word-wrap: break-word;
  }}
  col.col-item {{ width: 26%; }}
  col.col-haz  {{ width: 37%; }}
  col.col-mit  {{ width: 37%; }}

  .compact-1 table {{ font-size: 9.5pt; }}
  .compact-1 tbody td, .compact-1 thead th {{ padding: 5px 6px; }}
  .compact-2 table {{ font-size: 8.5pt; }}
  .compact-2 tbody td, .compact-2 thead th {{ padding: 4px 5px; }}
  .compact-3 table {{ font-size: 7.8pt; }}
  .compact-3 tbody td, .compact-3 thead th {{ padding: 3px 4px; }}

  @media print {{
    html, body {{
      background: #fff;
    }}
    .no-print {{
      display: none !important;
    }}
    .poster-viewport {{
      padding: 0;
      overflow: visible;
    }}
    #posterPage {{
      margin: 0 auto;
      box-shadow: none;
      page-break-inside: avoid;
    }}
  }}
</style>
</head>
<body>

<div class="toolbar-wrap no-print">
  <div class="toolbar-header">
    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
      <strong style="font-size:15px; color:#0f3b5f;">11&quot;&times;17&quot; Landscape PPE Poster — {safe_pitch_label}</strong>
      <span id="modeBadge" class="mode-badge {initial_badge_class}">{initial_badge_text}</span>
    </div>
    <div class="toolbar-actions">
      <button type="button" class="btn" onclick="printPoster()">🖨️ Print PPE Poster</button>
      <button type="button" class="btn btn-secondary" onclick="openPrintableWindow()">↗ Open Printable Tab</button>
      <button type="button" class="btn btn-outline" onclick="savePosterJSON()">💾 Save as JSON</button>
      <label class="btn btn-outline" style="margin:0;">
        📂 Import JSON
        <input type="file" accept=".json" onchange="importPosterJSON(event)" style="display:none;" />
      </label>
      <button type="button" class="btn btn-outline" style="{selector_display_style}" onclick="toggleInteractiveDrawer()">
        ⚙️ Customize Preview / Test PPE
      </button>
    </div>
  </div>

  <div id="interactiveDrawer" class="interactive-drawer">
    <div class="meta-inputs-row">
      <label>
        Job Name (Preview)
        <input type="text" id="jobName" value="{safe_job}" oninput="updatePoster()" />
      </label>
      <label>
        Workstation # (Preview)
        <input type="text" id="workstation" value="{safe_ws}" oninput="updatePoster()" />
      </label>
      <label>
        Section # (Preview)
        <input type="text" id="section" value="{safe_sec}" oninput="updatePoster()" />
      </label>
    </div>
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">
      <span style="font-size:12px; font-weight:700; color:#334155;">Click PPE tiles below to test poster layout &amp; border mode:</span>
      <div style="display:flex; gap:6px;">
        <button type="button" class="btn btn-outline" style="padding:4px 10px; font-size:11px;" onclick="resetToPitchPPE()">Reset to Pitch PPE</button>
        <button type="button" class="btn btn-outline" style="padding:4px 10px; font-size:11px;" onclick="applyBaselinePreview()">Select Standard 3 Baseline</button>
      </div>
    </div>
    <div class="ppe-selector-grid" id="ppeSelector"></div>
  </div>
</div>

{override_banner_html}

<div class="poster-viewport">
  <div id="posterPage" class="{initial_mode_class}">
    <div id="poster">
      <div class="poster-header">
        <div class="validation-box" aria-label="Validation Sticker Slot">
          <div class="validation-title">VALIDATION</div>
          <div class="validation-sub">Place annual review sticker here</div>
        </div>
        <h2>MINIMUM PPE REQUIREMENTS</h2>
        <img class="header-logo" src="{logo_uri}" alt="EHS&amp;S Logo" />
      </div>

      <div class="meta-bar-inline">
        <div class="meta-chip"><strong>Job:</strong> <span id="posterJob">{safe_job}</span></div>
        <div class="meta-chip"><strong>Workstation:</strong> <span id="posterWorkstation">{safe_ws}</span></div>
        <div class="meta-chip"><strong>Section:</strong> <span id="posterSection">{safe_sec}</span></div>
      </div>

      <div class="poster-body">
        <div class="icons-panel">
          <div class="panel-title">Required PPE (Visual)</div>
          <div id="posterIcons"></div>
        </div>

        <div class="table-panel">
          <div class="panel-title">Hazards &amp; Mitigations</div>
          <div class="table-wrap" id="tableWrap">
            <table id="posterTable" aria-label="PPE Hazards and Mitigations">
              <colgroup>
                <col class="col-item" />
                <col class="col-haz" />
                <col class="col-mit" />
              </colgroup>
              <thead>
                <tr>
                  <th>PPE Item</th>
                  <th>Hazard</th>
                  <th>Mitigation</th>
                </tr>
              </thead>
              <tbody></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const ppeData = {catalog_json};
const initialPitchPPE = {selected_json};
const standardBaselinePPE = new Set({baseline_json});
const selectedPPE = new Set(initialPitchPPE);

const selectorContainer = document.getElementById("ppeSelector");
const posterIcons = document.getElementById("posterIcons");
const posterTableBody = document.querySelector("#posterTable tbody");
const tableWrap = document.getElementById("tableWrap");
const posterPage = document.getElementById("posterPage");
const modeBadge = document.getElementById("modeBadge");

function renderSelectorTiles() {{
  if (!selectorContainer) return;
  selectorContainer.innerHTML = "";
  ppeData.forEach(item => {{
    const div = document.createElement("div");
    div.className = "ppe-item-btn" + (selectedPPE.has(item.name) ? " selected" : "");
    div.dataset.name = item.name;
    const imgHtml = item.image ? `<img src="${{item.image}}" alt="${{item.name}}">` : "";
    div.innerHTML = `${{imgHtml}}<span>${{item.name}}</span>`;
    div.onclick = () => {{
      if (selectedPPE.has(item.name)) {{
        selectedPPE.delete(item.name);
        div.classList.remove("selected");
      }} else {{
        selectedPPE.add(item.name);
        div.classList.add("selected");
      }}
      updatePoster();
    }};
    selectorContainer.appendChild(div);
  }});
}}

function toggleInteractiveDrawer() {{
  const drawer = document.getElementById("interactiveDrawer");
  if (drawer) {{
    drawer.classList.toggle("open");
  }}
}}

function resetToPitchPPE() {{
  selectedPPE.clear();
  initialPitchPPE.forEach(n => selectedPPE.add(n));
  renderSelectorTiles();
  updatePoster();
}}

function applyBaselinePreview() {{
  selectedPPE.clear();
  standardBaselinePPE.forEach(n => selectedPPE.add(n));
  renderSelectorTiles();
  updatePoster();
}}

function isExactStandardSelection(set) {{
  if (set.size !== standardBaselinePPE.size) return false;
  for (const name of standardBaselinePPE) {{
    if (!set.has(name)) return false;
  }}
  return true;
}}

function updateBorderMode() {{
  const isStd = isExactStandardSelection(selectedPPE);
  posterPage.classList.toggle("mode-standard", isStd);
  posterPage.classList.toggle("mode-special", !isStd);
  if (modeBadge) {{
    if (isStd) {{
      modeBadge.className = "mode-badge standard";
      modeBadge.textContent = "Standard Baseline Border (Green)";
    }} else {{
      modeBadge.className = "mode-badge special";
      modeBadge.textContent = "Elevated / Special PPE Border (Purple)";
    }}
  }}
}}

function updatePoster() {{
  document.getElementById("posterJob").textContent = document.getElementById("jobName").value || "";
  document.getElementById("posterWorkstation").textContent = document.getElementById("workstation").value || "";
  document.getElementById("posterSection").textContent = document.getElementById("section").value || "";

  updateBorderMode();

  const selectedItems = ppeData.filter(item => selectedPPE.has(item.name));

  posterIcons.innerHTML = "";
  selectedItems.forEach(item => {{
    const tile = document.createElement("div");
    tile.className = "icon-tile";
    const imgHtml = item.image ? `<img src="${{item.image}}" alt="${{item.name}}" />` : `<div style="font-weight:700;font-size:14pt;text-align:center;">${{item.name}}</div>`;
    tile.innerHTML = `
      ${{imgHtml}}
      <div class="caption">${{item.name}}</div>
    `;
    posterIcons.appendChild(tile);
  }});

  posterTableBody.innerHTML = "";
  selectedItems.forEach(item => {{
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${{item.name}}</strong></td>
      <td>${{item.hazard}}</td>
      <td>${{item.mitigation}}</td>
    `;
    posterTableBody.appendChild(tr);
  }});

  fitAll();
}}

function fitAll() {{
  fitTableDensity();
  fitIconsNoCutoff();
}}

function fitTableDensity() {{
  tableWrap.classList.remove("compact-1", "compact-2", "compact-3");
  const count = selectedPPE.size;
  if (count > 8 && count <= 12) {{
    tableWrap.classList.add("compact-1");
  }} else if (count > 12 && count <= 16) {{
    tableWrap.classList.add("compact-2");
  }} else if (count > 16) {{
    tableWrap.classList.add("compact-3");
  }}
  let step = 0;
  while (tableWrap.scrollHeight > tableWrap.clientHeight && step < 3) {{
    step++;
    tableWrap.classList.add(`compact-${{step}}`);
  }}
}}

function fitIconsNoCutoff() {{
  const count = selectedPPE.size;
  const W = posterIcons.clientWidth;
  const H = posterIcons.clientHeight;

  if (count === 0 || W === 0 || H === 0) {{
    posterIcons.style.setProperty("--cols", 3);
    posterIcons.style.setProperty("--tile-h", "160px");
    posterIcons.style.setProperty("--img-h", "110px");
    posterIcons.style.setProperty("--cap-fs", "10.5pt");
    return;
  }}

  const cs = getComputedStyle(posterIcons);
  const gap = parseFloat(cs.gap) || 10;
  const padV = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);

  const maxCols = Math.min(6, count);
  let best = null;

  for (let cols = 1; cols <= maxCols; cols++) {{
    const rows = Math.ceil(count / cols);
    const totalGapsH = gap * (rows - 1);
    const availH = H - padV - totalGapsH;
    if (availH <= 0) continue;

    const tileH = Math.floor(availH / rows);
    if (tileH < 60) continue;

    const capFS = Math.max(8, Math.min(11, Math.floor(tileH * 0.09)));
    const reserveForCaption = Math.ceil(capFS * 2.4) + 12;
    const imgH = Math.max(36, tileH - reserveForCaption);

    const score = imgH * 1000 - cols;
    if (!best || score > best.score) {{
      best = {{ cols, tileH, imgH, capFS, score }};
    }}
  }}

  if (!best) {{
    const cols = Math.min(6, Math.max(1, count));
    const rows = Math.ceil(count / cols);
    const totalGapsH = gap * (rows - 1);
    const availH = Math.max(60, H - padV - totalGapsH);
    const tileH = Math.max(60, Math.floor(availH / rows));
    const capFS = 8;
    const imgH = Math.max(32, tileH - 28);
    best = {{ cols, tileH, imgH, capFS }};
  }}

  posterIcons.style.setProperty("--cols", best.cols);
  posterIcons.style.setProperty("--tile-h", `${{best.tileH}}px`);
  posterIcons.style.setProperty("--img-h", `${{best.imgH}}px`);
  posterIcons.style.setProperty("--cap-fs", `${{best.capFS}}pt`);
}}

function printPoster() {{
  fitAll();
  window.print();
}}

function openPrintableWindow() {{
  fitAll();
  const w = window.open("", "_blank");
  if (!w) {{
    window.print();
    return;
  }}
  w.document.open();
  w.document.write(document.documentElement.outerHTML);
  w.document.close();
  setTimeout(() => {{
    w.focus();
    w.print();
  }}, 350);
}}

function savePosterJSON() {{
  const data = {{
    jobName: document.getElementById("jobName").value,
    workstation: document.getElementById("workstation").value,
    section: document.getElementById("section").value,
    selectedPPE: Array.from(selectedPPE)
  }};
  const blob = new Blob([JSON.stringify(data, null, 2)], {{ type: "application/json" }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${{data.jobName || "ppe_poster"}}_${{data.workstation || "pitch"}}.json`;
  a.click();
  URL.revokeObjectURL(url);
}}

function importPosterJSON(event) {{
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(e) {{
    try {{
      const data = JSON.parse(e.target.result);
      document.getElementById("jobName").value = data.jobName || "";
      document.getElementById("workstation").value = data.workstation || "";
      document.getElementById("section").value = data.section || "";
      selectedPPE.clear();
      (data.selectedPPE || []).forEach(name => {{
        const normalized = (name === "Chemiclal Resistant Galoshes") ? "Chemical Resistant Galoshes" : name;
        selectedPPE.add(normalized);
      }});
      renderSelectorTiles();
      updatePoster();
    }} catch (err) {{
      alert("Invalid JSON file.");
    }}
  }};
  reader.readAsText(file);
}}

window.addEventListener("resize", fitAll);
window.addEventListener("beforeprint", fitAll);
renderSelectorTiles();
updatePoster();
</script>
</body>
</html>
"""


def build_jsa_poster_html(
    *,
    job_title: str = "",
    plant_code: str = "AP1",
    important_notice: str = "",
    effective_ppe_items: list[Any] | None = None,
    jsa_rows: list[dict[str, Any]] | None = None,
    pitch_photos: list[dict[str, Any]] | None = None,
    include_pitch_photos: bool = True,
    overrides: list[dict[str, Any]] | None = None,
    min_table_rows: int = 10,
) -> str:
    """Render the portrait Job Safety Analysis (JSA) Poster (FRM-GEA-SAF-085 Rev 0) HTML component."""
    raw_ppe_input: list[str] = []
    if effective_ppe_items:
        for entry in effective_ppe_items:
            if isinstance(entry, dict):
                nm = str(entry.get("canonical_name") or entry.get("name") or "").strip()
                if nm:
                    raw_ppe_input.append(nm)
            elif str(entry or "").strip():
                raw_ppe_input.append(str(entry).strip())

    rollup = resolve_pitch_ppe_rollup(raw_ppe_input)
    effective_names = rollup.get("effective_canonical_names") or rollup["effective_names"]
    override_list = overrides if overrides is not None else rollup.get("overrides", [])

    catalog_js_items: list[dict[str, Any]] = []
    seen_catalog_names: set[str] = set()
    for item in PPE_CATALOG:
        name = str(item["name"])
        seen_catalog_names.add(name)
        catalog_js_items.append(
            {
                "name": name,
                "jsa_image": get_jsa_icon_data_uri(name),
                "card_image": get_ppe_icon_data_uri(name),
                "hazard": str(item.get("hazard") or ""),
                "mitigation": str(item.get("mitigation") or ""),
            }
        )
    for eff_item in rollup["effective_items"]:
        if eff_item["name"] not in seen_catalog_names:
            catalog_js_items.append(
                {
                    "name": eff_item["name"],
                    "jsa_image": "",
                    "card_image": "",
                    "hazard": str(eff_item.get("hazard") or "Task-specific workplace hazard."),
                    "mitigation": str(
                        eff_item.get("mitigation")
                        or f"Correctly wear approved {eff_item['name'].upper()}."
                    ),
                }
            )

    embedded_photos: list[dict[str, str]] = []
    for photo in pitch_photos or []:
        uri = _resolve_media_data_uri(str(photo.get("file_path") or ""))
        if uri:
            embedded_photos.append(
                {
                    "caption": str(photo.get("caption") or "Workstation Photo"),
                    "src": uri,
                }
            )

    rows_data: list[dict[str, Any]] = []
    for r in jsa_rows or []:
        rows_data.append(
            {
                "job_step": str(r.get("job_step") or ""),
                "potential_hazards": str(r.get("potential_hazards") or ""),
                "proposed_actions": str(r.get("proposed_actions") or ""),
                "is_auto_ppe_row": bool(r.get("is_auto_ppe_row")),
            }
        )
    if not rows_data:
        eff_ppe_text = (
            ", ".join(effective_names)
            if effective_names
            else "Safety toed shoes, safety glasses, cut-resistant gloves"
        )
        rows_data.append(
            {
                "job_step": "Put on PPE",
                "potential_hazards": "None",
                "proposed_actions": eff_ppe_text,
                "is_auto_ppe_row": True,
            }
        )

    while len(rows_data) < max(1, int(min_table_rows)):
        rows_data.append(
            {
                "job_step": "",
                "potential_hazards": "",
                "proposed_actions": "",
                "is_auto_ppe_row": False,
            }
        )

    override_pills_html = ""
    if override_list:
        pills: list[str] = []
        for ov in override_list:
            summary_txt = str(ov.get("summary") or "").strip()
            if summary_txt:
                pills.append(f'<span class="override-pill">⚡ {html.escape(summary_txt)}</span>')
        if pills:
            override_pills_html = (
                '<div class="override-banner no-print">'
                '<strong>Hierarchy Overrides Active:</strong> '
                + " ".join(pills)
                + "</div>"
            )

    ehs_logo_uri = get_ehs_logo_data_uri()
    escaped_job_title = html.escape(job_title or "Enter Job Title")
    escaped_plant_code = html.escape(plant_code or "AP1")
    default_notice = (
        "The JSA should be reviewed by all employees operating this workstation. "
        "This JSA should be reviewed & updated when changes to equipment / processes occur."
    )
    escaped_notice = html.escape(important_notice or default_notice)

    catalog_json = json.dumps(catalog_js_items)
    selected_json = json.dumps(effective_names)
    photos_json = json.dumps(embedded_photos)
    rows_json = json.dumps(rows_data)
    initial_show_photos_js = "true" if (include_pitch_photos and embedded_photos) else "false"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Job Safety Analysis (JSA) - {escaped_job_title}</title>
<style>
  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }}
  body {{
    font-family: Arial, Helvetica, sans-serif;
    margin: 0;
    padding: 12px;
    background: #eef2f6;
    color: #111;
  }}
  .toolbar {{
    max-width: 900px;
    margin: 0 auto 10px auto;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 14px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .toolbar-group {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }}
  .btn {{
    padding: 7px 12px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #f8fafc;
    color: #1e293b;
    transition: all 0.15s ease;
  }}
  .btn:hover {{
    background: #e2e8f0;
  }}
  .btn-primary {{
    background: #008a5e;
    color: #ffffff;
    border-color: #00724d;
  }}
  .btn-primary:hover {{
    background: #006e4a;
  }}
  .override-banner {{
    max-width: 900px;
    margin: 0 auto 10px auto;
    background: #f5f3ff;
    border: 1px solid #c4b5fd;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    color: #4c1d95;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }}
  .override-pill {{
    background: #ede9fe;
    border: 1px solid #a78bfa;
    border-radius: 999px;
    padding: 2px 8px;
    font-weight: 600;
  }}
  .selector-drawer {{
    max-width: 900px;
    margin: 0 auto 12px auto;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 12px;
    display: none;
  }}
  .selector-drawer.open {{
    display: block;
  }}
  .selector-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(125px, 1fr));
    gap: 6px;
    max-height: 220px;
    overflow-y: auto;
    margin-top: 8px;
  }}
  .sel-tile {{
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px;
    text-align: center;
    cursor: pointer;
    background: #fff;
    font-size: 11px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }}
  .sel-tile.active {{
    border: 2px solid #008a5e;
    background: #ecfdf5;
    font-weight: 700;
  }}
  .sel-tile img {{
    height: 38px;
    object-fit: contain;
  }}

  /* JSA Sheet (Portrait 8.5 x 11 / 11 x 17 scalable) */
  .jsa-outer-frame {{
    width: 850px;
    min-height: 1100px;
    margin: 0 auto;
    padding: 28px;
    background: repeating-linear-gradient(
      135deg,
      #00b377 0px,
      #00b377 34px,
      #000000 34px,
      #000000 68px
    );
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
  }}
  .jsa-outer-frame.border-purple {{
    background: repeating-linear-gradient(
      135deg,
      #7851a9 0px,
      #7851a9 34px,
      #000000 34px,
      #000000 68px
    );
  }}
  .jsa-inner-sheet {{
    background: #ffffff;
    border: 2px solid #000000;
    min-height: 1044px;
    padding: 14px 18px 16px 18px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}
  .jsa-top-section {{
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .jsa-header-row {{
    display: grid;
    grid-template-columns: 120px 1fr 110px;
    align-items: center;
    gap: 10px;
  }}
  .jsa-plant-code {{
    font-size: 36px;
    font-weight: 900;
    letter-spacing: 0.5px;
    color: #000;
    text-align: left;
    padding-left: 6px;
    outline: none;
  }}
  .jsa-title-block {{
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }}
  .jsa-main-heading {{
    font-size: 26px;
    font-weight: 900;
    letter-spacing: 0.6px;
    margin: 0;
    color: #000;
  }}
  .jsa-job-title-box {{
    border: 1.5px solid #222;
    background: #e5e7eb;
    padding: 4px 14px;
    font-size: 16px;
    font-weight: 700;
    min-width: 360px;
    max-width: 95%;
    text-align: center;
    color: #000;
    outline: none;
  }}
  .jsa-operation-sub {{
    font-size: 16px;
    font-weight: 800;
    color: #000;
    margin-top: 1px;
  }}
  .jsa-logo-box {{
    display: flex;
    justify-content: flex-end;
    align-items: center;
  }}
  .jsa-logo-box img {{
    max-height: 68px;
    max-width: 105px;
    object-fit: contain;
  }}

  /* IMPORTANT Banner */
  .jsa-important-box {{
    border: 1.8px solid #000;
    margin-top: 2px;
  }}
  .jsa-important-header {{
    background: #10c486;
    border-bottom: 1.5px solid #000;
    text-align: center;
    font-weight: 900;
    font-size: 16px;
    padding: 3px 8px;
    letter-spacing: 0.5px;
    color: #000;
  }}
  .jsa-important-body {{
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 700;
    line-height: 1.35;
    color: #000;
    outline: none;
  }}

  /* Middle Visual Area: Add Photos / PPE Icons */
  .jsa-visual-zone {{
    min-height: 215px;
    max-height: 275px;
    margin: 8px 0;
    padding: 8px 10px;
    border: 1px dashed #cbd5e1;
    border-radius: 6px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 12px;
    overflow: hidden;
  }}
  .jsa-visual-empty {{
    font-size: 28px;
    color: #64748b;
    text-align: center;
    font-weight: 500;
  }}
  .jsa-ppe-tile {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: var(--icon-w, 108px);
    padding: 3px;
    text-align: center;
  }}
  .jsa-ppe-tile img {{
    height: var(--icon-h, 88px);
    max-width: 100%;
    object-fit: contain;
  }}
  .jsa-ppe-tile .jsa-ppe-cap {{
    font-size: 9.5px;
    font-weight: 700;
    color: #111;
    margin-top: 2px;
    line-height: 1.15;
  }}
  .jsa-photo-card {{
    display: flex;
    flex-direction: column;
    align-items: center;
    border: 1px solid #94a3b8;
    border-radius: 4px;
    padding: 4px;
    background: #fff;
    max-width: 190px;
  }}
  .jsa-photo-card img {{
    height: var(--photo-h, 120px);
    max-width: 180px;
    object-fit: contain;
  }}
  .jsa-photo-card span {{
    font-size: 9.5px;
    font-weight: 700;
    color: #1e293b;
    margin-top: 3px;
    text-align: center;
    max-width: 175px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}

  /* Job Steps Table */
  .jsa-steps-table {{
    width: 100%;
    border-collapse: collapse;
    border: 2.5px solid #000;
    table-layout: fixed;
    margin-top: 2px;
  }}
  .jsa-steps-table th {{
    border: 1.5px solid #000;
    padding: 6px 8px;
    font-size: 12px;
    font-weight: 900;
    text-align: left;
    text-transform: uppercase;
    background: #ffffff;
    color: #000;
  }}
  .jsa-steps-table td {{
    border: 1.2px solid #000;
    padding: 6px 8px;
    font-size: 11.5px;
    vertical-align: top;
    line-height: 1.3;
    height: 38px;
    color: #000;
    word-wrap: break-word;
    outline: none;
  }}
  .jsa-steps-table tr.auto-ppe-row td {{
    background: #f8fafc;
  }}
  .col-step {{ width: 28%; }}
  .col-hazard {{ width: 33%; }}
  .col-action {{ width: 39%; }}

  /* Bottom Footer & Annual Review Sticker Box */
  .jsa-footer-row {{
    display: flex;
    justify-content: flex-end;
    margin-top: 12px;
  }}
  .jsa-sticker-box {{
    width: 265px;
    border: 1.5px dashed #64748b;
    text-align: center;
  }}
  .jsa-sticker-area {{
    padding: 8px 10px 6px 10px;
    font-family: "Times New Roman", Times, serif;
    font-size: 13px;
    font-weight: 700;
    color: #cbd5e1;
    line-height: 1.25;
    letter-spacing: 0.4px;
    text-transform: uppercase;
  }}
  .jsa-template-rev {{
    border-top: 1px solid #94a3b8;
    padding: 3px 6px;
    font-size: 9px;
    color: #64748b;
    font-family: Arial, sans-serif;
  }}

  @page {{
    size: portrait;
    margin: 0.25in;
  }}
  @media print {{
    body {{
      background: #ffffff;
      padding: 0;
      margin: 0;
    }}
    .no-print {{
      display: none !important;
    }}
    .jsa-outer-frame {{
      box-shadow: none;
      width: 100%;
      margin: 0;
    }}
    .jsa-visual-zone {{
      border-color: transparent;
    }}
  }}
</style>
</head>
<body>

<div class="toolbar no-print">
  <div class="toolbar-group">
    <button class="btn btn-primary" onclick="window.print()">🖨️ Print JSA Poster</button>
    <button class="btn" onclick="openPrintableJSA()">🗗 Open Printable Tab</button>
    <button class="btn" onclick="toggleSelectorDrawer()">🛡️ Toggle PPE Icons (<span id="ppeCountBadge">0</span>)</button>
    <button class="btn" id="btnIconStyle" onclick="toggleIconStyle()">🎨 Style: JSA Icons</button>
    <button class="btn" id="btnPhotoToggle" onclick="togglePhotos()">📷 Pitch Photos</button>
    <button class="btn" onclick="addBlankStepRow()">➕ Add Blank Row</button>
  </div>
  <div class="toolbar-group">
    <button class="btn" onclick="toggleBorderTheme()">🟩/🟪 Border Color</button>
    <button class="btn" onclick="saveJsaJSON()">💾 Save JSON</button>
  </div>
</div>

{override_pills_html}

<div class="selector-drawer no-print" id="selectorDrawer">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <strong style="font-size:12.5px;">Select / Preview PPE Icons on JSA Poster (Hierarchy Overrides Applied Automatically):</strong>
    <button class="btn" onclick="toggleSelectorDrawer()">Close ✕</button>
  </div>
  <div class="selector-grid" id="selectorGrid"></div>
</div>

<div class="jsa-outer-frame" id="jsaOuterFrame">
  <div class="jsa-inner-sheet">
    <div class="jsa-top-section">
      <div class="jsa-header-row">
        <div class="jsa-plant-code" id="jsaPlantCode" contenteditable="true" title="Click to edit Plant/Building code">{escaped_plant_code}</div>
        <div class="jsa-title-block">
          <h1 class="jsa-main-heading">JOB SAFETY ANALYSIS</h1>
          <div class="jsa-job-title-box" id="jsaJobTitle" contenteditable="true" title="Click to edit Job Title">{escaped_job_title}</div>
          <div class="jsa-operation-sub">Operation</div>
        </div>
        <div class="jsa-logo-box">
          <img src="{ehs_logo_uri}" alt="EHS&S Logo" />
        </div>
      </div>

      <div class="jsa-important-box">
        <div class="jsa-important-header">IMPORTANT</div>
        <div class="jsa-important-body" id="jsaImportantNotice" contenteditable="true" title="Click to edit Important Notice">{escaped_notice}</div>
      </div>

      <div class="jsa-visual-zone" id="jsaVisualZone"></div>

      <table class="jsa-steps-table" id="jsaStepsTable">
        <thead>
          <tr>
            <th class="col-step">JOB STEPS</th>
            <th class="col-hazard">POTENTIAL ERRORS / HAZARDS</th>
            <th class="col-action">ACTION</th>
          </tr>
        </thead>
        <tbody id="jsaStepsBody"></tbody>
      </table>
    </div>

    <div class="jsa-footer-row">
      <div class="jsa-sticker-box">
        <div class="jsa-sticker-area">
          PLACE ANNUAL<br/>REVIEW<br/>STICKER HERE
        </div>
        <div class="jsa-template-rev">
          JSA Template - FRM-GEA-SAF-085 Rev 0 2/28/2024
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const ppeCatalog = {catalog_json};
const selectedPPE = new Set({selected_json});
const pitchPhotos = {photos_json};
const initialRows = {rows_json};
let useJsaIcons = true;
let showPitchPhotos = {initial_show_photos_js};

const CUT_GLOVE_RANKS = {{
  "Cut Level 1 Gloves": 1,
  "Cut Level 2 Gloves": 2,
  "Cut Level 3 Gloves": 3,
  "Cut Level 4 Gloves": 4,
  "Cut Level 5 Gloves": 5,
  "Cut Level 6 Gloves": 6
}};
const FOOTWEAR_RANKS = {{
  "Sturdy Closed Toe and Heel Shoes": 1,
  "Safety Toe Shoes": 2
}};
const EYE_RANKS = {{
  "Safety Glasses": 1,
  "Foam Lined Safety Glasses": 2
}};
const HEAD_RANKS = {{
  "Bump Cap": 1,
  "Hard Hat": 2
}};

function resolveEffectivePPEList() {{
  let maxCut = 0, maxFoot = 0, maxEye = 0, maxHead = 0;
  selectedPPE.forEach(name => {{
    if (CUT_GLOVE_RANKS[name]) maxCut = Math.max(maxCut, CUT_GLOVE_RANKS[name]);
    if (FOOTWEAR_RANKS[name]) maxFoot = Math.max(maxFoot, FOOTWEAR_RANKS[name]);
    if (EYE_RANKS[name]) maxEye = Math.max(maxEye, EYE_RANKS[name]);
    if (HEAD_RANKS[name]) maxHead = Math.max(maxHead, HEAD_RANKS[name]);
  }});
  return ppeCatalog.filter(item => {{
    if (!selectedPPE.has(item.name)) return false;
    if (CUT_GLOVE_RANKS[item.name] && CUT_GLOVE_RANKS[item.name] < maxCut) return false;
    if (FOOTWEAR_RANKS[item.name] && FOOTWEAR_RANKS[item.name] < maxFoot) return false;
    if (EYE_RANKS[item.name] && EYE_RANKS[item.name] < maxEye) return false;
    if (HEAD_RANKS[item.name] && HEAD_RANKS[item.name] < maxHead) return false;
    return true;
  }});
}}

function renderSelectorDrawer() {{
  const grid = document.getElementById("selectorGrid");
  grid.innerHTML = "";
  ppeCatalog.forEach(item => {{
    const div = document.createElement("div");
    div.className = "sel-tile" + (selectedPPE.has(item.name) ? " active" : "");
    const imgSrc = (useJsaIcons && item.jsa_image) ? item.jsa_image : item.card_image;
    div.innerHTML = (imgSrc ? `<img src="${{imgSrc}}" alt="${{item.name}}"/>` : "") + `<span>${{item.name}}</span>`;
    div.onclick = () => {{
      if (selectedPPE.has(item.name)) selectedPPE.delete(item.name);
      else selectedPPE.add(item.name);
      renderSelectorDrawer();
      renderVisualZone();
      updateAutoPpeRow();
    }};
    grid.appendChild(div);
  }});
}}

function renderVisualZone() {{
  const zone = document.getElementById("jsaVisualZone");
  const effective = resolveEffectivePPEList();
  document.getElementById("ppeCountBadge").textContent = effective.length;
  zone.innerHTML = "";

  const activePhotos = showPitchPhotos ? pitchPhotos : [];
  const totalItems = effective.length + activePhotos.length;

  if (totalItems === 0) {{
    zone.innerHTML = '<div class="jsa-visual-empty">Add Photos / PPE Icons</div>';
    return;
  }}

  // Dynamically scale icon height based on how many icons + photos are shown
  let iconH = 105;
  let iconW = 115;
  if (totalItems > 8) {{ iconH = 74; iconW = 88; }}
  else if (totalItems > 5) {{ iconH = 88; iconW = 100; }}
  zone.style.setProperty("--icon-h", iconH + "px");
  zone.style.setProperty("--icon-w", iconW + "px");
  zone.style.setProperty("--photo-h", Math.min(135, iconH + 22) + "px");

  effective.forEach(item => {{
    const tile = document.createElement("div");
    tile.className = "jsa-ppe-tile";
    const src = (useJsaIcons && item.jsa_image) ? item.jsa_image : item.card_image;
    if (src) {{
      const img = document.createElement("img");
      img.src = src;
      img.alt = item.name;
      tile.appendChild(img);
    }} else {{
      const cap = document.createElement("div");
      cap.className = "jsa-ppe-cap";
      cap.textContent = item.name;
      tile.appendChild(cap);
    }}
    zone.appendChild(tile);
  }});

  activePhotos.forEach(photo => {{
    const card = document.createElement("div");
    card.className = "jsa-photo-card";
    const img = document.createElement("img");
    img.src = photo.src;
    img.alt = photo.caption;
    const span = document.createElement("span");
    span.textContent = photo.caption;
    card.appendChild(img);
    card.appendChild(span);
    zone.appendChild(card);
  }});
}}

function renderStepsTable() {{
  const tbody = document.getElementById("jsaStepsBody");
  tbody.innerHTML = "";
  initialRows.forEach((row, idx) => {{
    const tr = document.createElement("tr");
    if (row.is_auto_ppe_row) tr.className = "auto-ppe-row";
    const tdStep = document.createElement("td");
    tdStep.contentEditable = "true";
    tdStep.textContent = row.job_step || "";
    const tdHaz = document.createElement("td");
    tdHaz.contentEditable = "true";
    tdHaz.textContent = row.potential_hazards || "";
    const tdAct = document.createElement("td");
    tdAct.contentEditable = "true";
    tdAct.textContent = row.proposed_actions || "";
    if (row.is_auto_ppe_row) tdAct.id = "autoPpeActionCell";
    tr.appendChild(tdStep);
    tr.appendChild(tdHaz);
    tr.appendChild(tdAct);
    tbody.appendChild(tr);
  }});
}}

function updateAutoPpeRow() {{
  const cell = document.getElementById("autoPpeActionCell");
  if (!cell) return;
  const effective = resolveEffectivePPEList().map(i => i.name);
  cell.textContent = effective.length
    ? effective.join(", ")
    : "Safety toed shoes, safety glasses, cut-resistant gloves";
}}

function addBlankStepRow() {{
  const tbody = document.getElementById("jsaStepsBody");
  const tr = document.createElement("tr");
  for (let i = 0; i < 3; i++) {{
    const td = document.createElement("td");
    td.contentEditable = "true";
    tr.appendChild(td);
  }}
  tbody.appendChild(tr);
}}

function toggleSelectorDrawer() {{
  document.getElementById("selectorDrawer").classList.toggle("open");
}}

function toggleIconStyle() {{
  useJsaIcons = !useJsaIcons;
  document.getElementById("btnIconStyle").textContent = useJsaIcons
    ? "🎨 Style: JSA Icons"
    : "🎨 Style: Photo Cards";
  renderSelectorDrawer();
  renderVisualZone();
}}

function togglePhotos() {{
  showPitchPhotos = !showPitchPhotos;
  renderVisualZone();
}}

function toggleBorderTheme() {{
  document.getElementById("jsaOuterFrame").classList.toggle("border-purple");
}}

function openPrintableJSA() {{
  const w = window.open("", "_blank");
  if (!w) {{
    window.print();
    return;
  }}
  w.document.open();
  w.document.write(document.documentElement.outerHTML);
  w.document.close();
  setTimeout(() => {{
    w.focus();
    w.print();
  }}, 350);
}}

function saveJsaJSON() {{
  const stepRows = [];
  document.querySelectorAll("#jsaStepsBody tr").forEach(tr => {{
    const cells = tr.querySelectorAll("td");
    if (cells.length === 3) {{
      stepRows.push({{
        job_step: cells[0].textContent.trim(),
        potential_hazards: cells[1].textContent.trim(),
        proposed_actions: cells[2].textContent.trim()
      }});
    }}
  }});
  const payload = {{
    plantCode: document.getElementById("jsaPlantCode").textContent.trim(),
    jobTitle: document.getElementById("jsaJobTitle").textContent.trim(),
    importantNotice: document.getElementById("jsaImportantNotice").textContent.trim(),
    effectivePPE: resolveEffectivePPEList().map(i => i.name),
    steps: stepRows
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `JSA_${{payload.jobTitle.replace(/[^a-zA-Z0-9_-]+/g, "_") || "pitch"}}.json`;
  a.click();
  URL.revokeObjectURL(url);
}}

renderSelectorDrawer();
renderVisualZone();
renderStepsTable();
</script>
</body>
</html>
"""

