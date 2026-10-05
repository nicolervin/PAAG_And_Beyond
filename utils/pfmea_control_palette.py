from __future__ import annotations

import html
from collections.abc import Callable
import pandas as pd
import streamlit as st

from utils.component_payload import json_safe
from utils.pfmea_store import pfmea_control_candidates, pfmea_control_options
from utils.quality_store import quality_requirement_assignments
from utils.table_ui import request_table_editor_reset

_HTML = """
<div class="pfmea-drawer-root">
  <div class="drawer-header">
    <div class="search-box">
      <input type="text" id="filter-input" placeholder="🔍 Search available controls..." autocomplete="off" />
    </div>
  </div>

  <div class="drawer-layout">
    <div class="palette-column">
      <div class="section-title">
        <span class="title-badge quality">🔷</span>
        <span>Drawing Requirements</span>
        <span class="count-pill" id="quality-count">0</span>
      </div>
      <div class="card-list" id="quality-list"></div>

      <div class="section-title" style="margin-top: 10px;">
        <span class="title-badge manual">🟢</span>
        <span>Catalog Controls</span>
        <span class="count-pill" id="manual-count">0</span>
      </div>
      <div class="card-list" id="manual-list"></div>
    </div>

    <div class="zones-column" style="margin-top: 6px; border-top: 1px solid var(--st-border-color, #e8e8e8); padding-top: 10px;">
      <div class="zone-wrapper">
        <div class="zone-title">
          <span>🛡️ Prevention Controls</span>
          <span class="count-pill" id="prev-count">0</span>
        </div>
        <div class="drop-zone" id="zone-prevention" data-target="prevention">
          <div class="empty-drop-msg">Drop Prevention controls here or click &quot;+ Prev&quot;</div>
        </div>
      </div>

      <div class="zone-wrapper" style="margin-top: 10px;">
        <div class="zone-title">
          <span>🔍 Detection Controls</span>
          <span class="count-pill" id="det-count">0</span>
        </div>
        <div class="drop-zone" id="zone-detection" data-target="detection">
          <div class="empty-drop-msg">Drop Detection controls here or click &quot;+ Det&quot;</div>
        </div>
      </div>
    </div>
  </div>
</div>
"""

_CSS = """
:host {
  color: var(--st-text-color, #1a1a1a);
  font-family: var(--st-font, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
}

.pfmea-drawer-root {
  box-sizing: border-box;
  padding: 6px 4px 12px;
  background: var(--st-background-color, #ffffff);
  border: 1px solid var(--st-border-color, #e0e0e0);
  border-radius: 8px;
}

.drawer-header {
  margin-bottom: 8px;
}

.search-box input {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 10px;
  font-size: 0.80rem;
  border: 1px solid var(--st-border-color, #ccc);
  border-radius: 6px;
  background: var(--st-secondary-background-color, #f9f9f9);
  color: var(--st-text-color, #222);
}

.search-box input:focus {
  outline: 2px solid var(--st-primary-color, #0d6efd);
  background: #ffffff;
}

.drawer-layout {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title, .zone-title {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.77rem;
  font-weight: 700;
  margin-bottom: 4px;
  color: var(--st-text-color, #333);
}

.count-pill {
  font-size: 0.68rem;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 10px;
  background: var(--st-secondary-background-color, #e9ecef);
  color: var(--st-secondary-text-color, #555);
  margin-left: auto;
}

.card-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 130px;
  overflow-y: auto;
  padding: 2px;
}

.card-list::-webkit-scrollbar, .drop-zone::-webkit-scrollbar {
  width: 5px;
}

.card-list::-webkit-scrollbar-thumb, .drop-zone::-webkit-scrollbar-thumb {
  background: var(--st-border-color, #ccc);
  border-radius: 4px;
}

.control-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 4px 6px;
  font-size: 0.75rem;
  border-radius: 5px;
  border: 1px solid var(--st-border-color, #ddd);
  background: var(--st-background-color, #fff);
  cursor: grab;
  user-select: none;
  transition: transform 0.1s, box-shadow 0.1s, border-color 0.1s;
}

.control-card:hover {
  box-shadow: 0 2px 4px rgba(0,0,0,0.08);
  border-color: var(--st-primary-color, #0d6efd);
}

.control-card:active {
  cursor: grabbing;
}

.control-card.quality {
  border-left: 3px solid #1976d2;
  background: color-mix(in srgb, #1976d2 4%, var(--st-background-color, #fff));
}

.control-card.manual {
  border-left: 3px solid #2e7d32;
  background: color-mix(in srgb, #2e7d32 4%, var(--st-background-color, #fff));
}

.card-info {
  flex: 1;
  min-width: 0;
  line-height: 1.2;
}

.card-title {
  font-weight: 650;
  font-size: 0.75rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-meta {
  font-size: 0.68rem;
  color: var(--st-secondary-text-color, #666);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-actions {
  display: flex;
  gap: 3px;
  flex-shrink: 0;
}

.quick-btn {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 2px 4px;
  border-radius: 3px;
  border: 1px solid var(--st-border-color, #bbb);
  background: var(--st-secondary-background-color, #f0f0f0);
  cursor: pointer;
  color: var(--st-text-color, #333);
  white-space: nowrap;
}

.quick-btn:hover {
  background: var(--st-primary-color, #0d6efd);
  color: #fff;
  border-color: var(--st-primary-color, #0d6efd);
}

.drop-zone {
  box-sizing: border-box;
  min-height: 75px;
  max-height: 120px;
  overflow-y: auto;
  border: 2px dashed var(--st-border-color, #bbb);
  border-radius: 6px;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--st-secondary-background-color, #fafafa);
  transition: background 0.15s, border-color 0.15s;
}

.drop-zone.dragover {
  border-color: var(--st-primary-color, #0d6efd);
  background: color-mix(in srgb, var(--st-primary-color, #0d6efd) 12%, #fff);
}

.empty-drop-msg {
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  min-height: 55px;
  font-size: 0.72rem;
  font-style: italic;
  color: var(--st-secondary-text-color, #888);
  pointer-events: none;
}

.assigned-badge {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 5px;
  padding: 3px 6px;
  font-size: 0.74rem;
  border-radius: 4px;
  border: 1px solid var(--st-border-color, #ccc);
  background: var(--st-background-color, #fff);
  cursor: grab;
  user-select: none;
}

.assigned-badge.quality {
  border-left: 3px solid #1976d2;
}

.assigned-badge.manual {
  border-left: 3px solid #2e7d32;
}

.assigned-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.74rem;
  line-height: 1.2;
}

.remove-btn {
  border: none;
  background: transparent;
  color: #d32f2f;
  font-size: 0.80rem;
  font-weight: bold;
  cursor: pointer;
  padding: 0 3px;
  border-radius: 3px;
  line-height: 1;
}

.remove-btn:hover {
  background: #ffebee;
}

.reorder-handle {
  color: #888;
  cursor: grab;
  font-size: 0.80rem;
  margin-right: 2px;
}
"""

_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component
  if (!parentElement || !data) return

  const filterInput = parentElement.querySelector('#filter-input')
  const qualityList = parentElement.querySelector('#quality-list')
  const manualList = parentElement.querySelector('#manual-list')
  const qualityCount = parentElement.querySelector('#quality-count')
  const manualCount = parentElement.querySelector('#manual-count')
  const zonePrev = parentElement.querySelector('#zone-prevention')
  const zoneDet = parentElement.querySelector('#zone-detection')
  const prevCount = parentElement.querySelector('#prev-count')
  const detCount = parentElement.querySelector('#det-count')

  let preventionKeys = [...(data.selected_prevention || [])]
  let detectionKeys = [...(data.selected_detection || [])]

  const labelMap = data.all_labels || {}

  function escapeHtml(text) {
    const div = document.createElement('div')
    div.textContent = text || ''
    return div.innerHTML
  }

  function emitChange() {
    setTriggerValue('change', {
      cause_key: data.cause_key,
      prevention: [...preventionKeys],
      detection: [...detectionKeys]
    })
  }

  function renderPalettes() {
    const query = (filterInput.value || '').trim().toLowerCase()

    // Quality list
    const qualityItems = (data.available_quality || []).filter(item => {
      if (!query) return true
      return (item.identifier || '').toLowerCase().includes(query)
        || (item.type || '').toLowerCase().includes(query)
        || (item.description || '').toLowerCase().includes(query)
        || (item.label || '').toLowerCase().includes(query)
    })

    qualityCount.textContent = qualityItems.length
    qualityList.innerHTML = ''
    if (qualityItems.length === 0) {
      qualityList.innerHTML = `<div style="font-size:0.75rem; color:#888; font-style:italic; padding:6px;">No matching drawing requirements</div>`
    } else {
      qualityItems.forEach(item => {
        const card = document.createElement('div')
        card.className = 'control-card quality'
        card.draggable = true
        card.dataset.sourceKey = item.source_key
        card.innerHTML = `
          <div class="card-info">
            <div class="card-title">${escapeHtml(item.identifier || 'Drawing Req')}</div>
            <div class="card-meta">${escapeHtml(item.description || item.type || '')}</div>
          </div>
          <div class="card-actions">
            <button class="quick-btn prev-btn" type="button" title="Add to Prevention">+ Prev</button>
            <button class="quick-btn det-btn" type="button" title="Add to Detection">+ Det</button>
          </div>
        `

        card.ondragstart = (e) => {
          e.dataTransfer.setData('text/plain', item.source_key)
          e.dataTransfer.effectAllowed = 'copy'
        }

        card.querySelector('.prev-btn').onclick = (e) => {
          e.stopPropagation()
          if (!preventionKeys.includes(item.source_key)) {
            preventionKeys.push(item.source_key)
            renderZones()
            emitChange()
          }
        }

        card.querySelector('.det-btn').onclick = (e) => {
          e.stopPropagation()
          if (!detectionKeys.includes(item.source_key)) {
            detectionKeys.push(item.source_key)
            renderZones()
            emitChange()
          }
        }

        qualityList.appendChild(card)
      })
    }

    // Manual catalog list
    const manualItems = (data.available_manual || []).filter(item => {
      if (!query) return true
      return (item.label || '').toLowerCase().includes(query)
        || (item.control_type || '').toLowerCase().includes(query)
    })

    manualCount.textContent = manualItems.length
    manualList.innerHTML = ''
    if (manualItems.length === 0) {
      manualList.innerHTML = `<div style="font-size:0.75rem; color:#888; font-style:italic; padding:6px;">No matching catalog controls</div>`
    } else {
      manualItems.forEach(item => {
        const card = document.createElement('div')
        card.className = 'control-card manual'
        card.draggable = true
        card.dataset.sourceKey = item.source_key
        card.innerHTML = `
          <div class="card-info">
            <div class="card-title">${escapeHtml(item.label || 'Catalog Control')}</div>
            <div class="card-meta">${escapeHtml(item.control_type || 'Standard Control')}</div>
          </div>
          <div class="card-actions">
            <button class="quick-btn prev-btn" type="button" title="Add to Prevention">+ Prev</button>
            <button class="quick-btn det-btn" type="button" title="Add to Detection">+ Det</button>
          </div>
        `

        card.ondragstart = (e) => {
          e.dataTransfer.setData('text/plain', item.source_key)
          e.dataTransfer.effectAllowed = 'copy'
        }

        card.querySelector('.prev-btn').onclick = (e) => {
          e.stopPropagation()
          if (!preventionKeys.includes(item.source_key)) {
            preventionKeys.push(item.source_key)
            renderZones()
            emitChange()
          }
        }

        card.querySelector('.det-btn').onclick = (e) => {
          e.stopPropagation()
          if (!detectionKeys.includes(item.source_key)) {
            detectionKeys.push(item.source_key)
            renderZones()
            emitChange()
          }
        }

        manualList.appendChild(card)
      })
    }
  }

  function renderZones() {
    prevCount.textContent = preventionKeys.length
    detCount.textContent = detectionKeys.length

    // Render Prevention Zone
    zonePrev.innerHTML = ''
    if (preventionKeys.length === 0) {
      zonePrev.innerHTML = `<div class="empty-drop-msg">Drag Prevention controls here or click &quot;+ Prev&quot;</div>`
    } else {
      preventionKeys.forEach((key, index) => {
        const badge = document.createElement('div')
        const isQuality = key.startsWith('quality:')
        badge.className = `assigned-badge ${isQuality ? 'quality' : 'manual'}`
        badge.draggable = true
        badge.dataset.index = index
        badge.dataset.sourceKey = key

        badge.innerHTML = `
          <span class="reorder-handle">⋮⋮</span>
          <span class="assigned-label" title="${escapeHtml(labelMap[key] || key)}">${escapeHtml(labelMap[key] || key)}</span>
          <button class="remove-btn" type="button" title="Remove control">✖</button>
        `

        badge.ondragstart = (e) => {
          e.dataTransfer.setData('text/reorder-prev', String(index))
          e.dataTransfer.effectAllowed = 'move'
        }

        badge.querySelector('.remove-btn').onclick = (e) => {
          e.stopPropagation()
          preventionKeys.splice(index, 1)
          renderZones()
          emitChange()
        }

        zonePrev.appendChild(badge)
      })
    }

    // Render Detection Zone
    zoneDet.innerHTML = ''
    if (detectionKeys.length === 0) {
      zoneDet.innerHTML = `<div class="empty-drop-msg">Drag Detection controls here or click &quot;+ Det&quot;</div>`
    } else {
      detectionKeys.forEach((key, index) => {
        const badge = document.createElement('div')
        const isQuality = key.startsWith('quality:')
        badge.className = `assigned-badge ${isQuality ? 'quality' : 'manual'}`
        badge.draggable = true
        badge.dataset.index = index
        badge.dataset.sourceKey = key

        badge.innerHTML = `
          <span class="reorder-handle">⋮⋮</span>
          <span class="assigned-label" title="${escapeHtml(labelMap[key] || key)}">${escapeHtml(labelMap[key] || key)}</span>
          <button class="remove-btn" type="button" title="Remove control">✖</button>
        `

        badge.ondragstart = (e) => {
          e.dataTransfer.setData('text/reorder-det', String(index))
          e.dataTransfer.effectAllowed = 'move'
        }

        badge.querySelector('.remove-btn').onclick = (e) => {
          e.stopPropagation()
          detectionKeys.splice(index, 1)
          renderZones()
          emitChange()
        }

        zoneDet.appendChild(badge)
      })
    }
  }

  // Setup Drop Zone listeners
  [zonePrev, zoneDet].forEach(zone => {
    const isPrev = zone.dataset.target === 'prevention'

    zone.ondragover = (e) => {
      e.preventDefault()
      zone.classList.add('dragover')
    }

    zone.ondragleave = (e) => {
      if (!zone.contains(e.relatedTarget)) {
        zone.classList.remove('dragover')
      }
    }

    zone.ondrop = (e) => {
      e.preventDefault()
      zone.classList.remove('dragover')

      const reorderPrevIdx = e.dataTransfer.getData('text/reorder-prev')
      const reorderDetIdx = e.dataTransfer.getData('text/reorder-det')

      if (isPrev && reorderPrevIdx !== '') {
        // Internal reorder in prevention
        const fromIdx = parseInt(reorderPrevIdx, 10)
        const targetBadge = e.target.closest('.assigned-badge')
        if (targetBadge && targetBadge.dataset.index !== undefined) {
          const toIdx = parseInt(targetBadge.dataset.index, 10)
          if (fromIdx !== toIdx) {
            const item = preventionKeys.splice(fromIdx, 1)[0]
            preventionKeys.splice(toIdx, 0, item)
            renderZones()
            emitChange()
          }
        }
        return
      }

      if (!isPrev && reorderDetIdx !== '') {
        // Internal reorder in detection
        const fromIdx = parseInt(reorderDetIdx, 10)
        const targetBadge = e.target.closest('.assigned-badge')
        if (targetBadge && targetBadge.dataset.index !== undefined) {
          const toIdx = parseInt(targetBadge.dataset.index, 10)
          if (fromIdx !== toIdx) {
            const item = detectionKeys.splice(fromIdx, 1)[0]
            detectionKeys.splice(toIdx, 0, item)
            renderZones()
            emitChange()
          }
        }
        return
      }

      // External drop from palette
      const sourceKey = e.dataTransfer.getData('text/plain')
      if (!sourceKey) return

      if (isPrev) {
        if (!preventionKeys.includes(sourceKey)) {
          preventionKeys.push(sourceKey)
          renderZones()
          emitChange()
        }
      } else {
        if (!detectionKeys.includes(sourceKey)) {
          detectionKeys.push(sourceKey)
          renderZones()
          emitChange()
        }
      }
    }
  })

  filterInput.oninput = () => renderPalettes()

  renderPalettes()
  renderZones()
}
"""

_PFMEA_CONTROL_PALETTE = st.components.v2.component(
    "paag_pfmea_control_palette_v1",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def pfmea_control_palette(
    cause_key: str,
    cause_label: str,
    available_quality: list[dict],
    available_manual: list[dict],
    selected_prevention: list[str],
    selected_detection: list[str],
    all_labels: dict[str, str],
    *,
    key: str,
    on_change: Callable[[], None] | None = None,
):
    """Render the interactive drag-and-drop control assignment palette."""
    return _PFMEA_CONTROL_PALETTE(
        key=key,
        default={"change": None},
        data=json_safe(
            {
                "cause_key": cause_key,
                "cause_label": cause_label,
                "available_quality": available_quality,
                "available_manual": available_manual,
                "selected_prevention": selected_prevention,
                "selected_detection": selected_detection,
                "all_labels": all_labels,
            }
        ),
        on_change_change=on_change,
        width="stretch",
        height="content",
    )


def _plain_text(value) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _cause_target_key(row: pd.Series) -> str:
    cause_id = _plain_text(row.get("cause_id"))
    if cause_id:
        return f"cause:{cause_id}"
    draft_id = _plain_text(row.get("draft_row_id")) or _plain_text(row.get("id"))
    return f"draft:{draft_id}"


def render_pfmea_control_drawer(
    project_id: str,
    scenario_id: str,
    rows: pd.DataFrame,
    draft_key: str,
    editor_key: str,
    step_by_id: dict[str, dict | pd.Series],
    control_labels: dict[str, str],
    on_close: Callable[[], None] | None = None,
) -> None:
    """Render the collapsible side drawer for drag-and-drop control assignment."""
    with st.container(border=True):
        header_cols = st.columns([7, 3], vertical_alignment="center")
        with header_cols[0]:
            st.markdown("#### 🎛️ Control Drawer")
        with header_cols[1]:
            if st.button("✖ Close", key=f"pfmea_drawer_close_btn_{project_id}_{scenario_id}", help="Close side drawer"):
                if on_close:
                    on_close()
                st.rerun()

        st.caption(
            "Drag controls into drop-zones or use **+ Prev** / **+ Det**."
        )

        # Identify targets
        targets: dict[str, pd.Series] = {}
        for _, row in rows.iterrows():
            work_element_id = _plain_text(row.get("work_element_id"))
            if work_element_id:
                t_key = _cause_target_key(row)
                if t_key and t_key != "draft:":
                    targets.setdefault(t_key, row)

        if not targets:
            st.info("No PFMEA Causes available yet. Stage or select a Process Function first.")
            return

        selector_key = f"pfmea_drawer_target_cause_{project_id}_{scenario_id}"
        target_options = list(targets)

        def _format_target(k: str) -> str:
            target_row = targets[k]
            step = step_by_id.get(_plain_text(target_row.get("work_element_id")), {})
            step_name = _plain_text(step.get("work_element")) or _plain_text(target_row.get("process_function")) or "Op"
            cause = _plain_text(target_row.get("potential_causes")) or "Unspecified Cause"
            item = _plain_text(target_row.get("item_number")) or _plain_text(step.get("pitch"))
            prefix = f"[{item}] " if item else ""
            return f"{prefix}{step_name} — Cause: {cause}"

        selected_target_key = st.selectbox(
            "Target PFMEA Cause",
            options=target_options,
            format_func=_format_target,
            key=selector_key,
            help="Select which PFMEA Cause you are configuring controls for.",
        )

        if not selected_target_key or selected_target_key not in targets:
            return

        target_row = targets[selected_target_key]
        work_element_id = _plain_text(target_row.get("work_element_id"))
        cause_label = _format_target(selected_target_key)

        # Current selections on target
        def _to_list(val) -> list[str]:
            if val is None:
                return []
            try:
                if bool(pd.isna(val)):
                    return []
            except (TypeError, ValueError):
                pass
            if isinstance(val, (list, tuple)):
                return [str(v) for v in val if str(v).strip()]
            if isinstance(val, str) and val.strip():
                return [s.strip() for s in val.split("\n") if s.strip()]
            return []

        current_prevention = _to_list(target_row.get("prevention_controls"))
        current_detection = _to_list(target_row.get("detection_controls"))

        # Fetch available drawing quality requirements for this work element
        quality_df = quality_requirement_assignments(project_id, scenario_id, work_element_id=work_element_id)
        available_quality: list[dict] = []
        for _, qrow in quality_df.iterrows():
            source_key = f"quality:{qrow['id']}"
            ident = _plain_text(qrow.get("unique_identifier")) or "Drawing Req"
            req_type = _plain_text(qrow.get("requirement_type")) or "Specification"
            desc = _plain_text(qrow.get("description"))
            q_label = f"Quality — {ident} ({req_type}) {desc}".strip()
            control_labels[source_key] = q_label
            available_quality.append(
                {
                    "source_key": source_key,
                    "identifier": ident,
                    "type": req_type,
                    "description": desc,
                    "label": q_label,
                }
            )

        # Also ensure any quality items already attached to this row are in available_quality so they can be shown
        existing_quality_keys = {
            k for k in (*current_prevention, *current_detection) if k.startswith("quality:")
        }
        seen_quality_keys = {item["source_key"] for item in available_quality}
        for qkey in existing_quality_keys:
            if qkey not in seen_quality_keys:
                available_quality.append(
                    {
                        "source_key": qkey,
                        "identifier": "Drawing Req",
                        "type": "Linked Requirement",
                        "description": control_labels.get(qkey, qkey),
                        "label": control_labels.get(qkey, qkey),
                    }
                )

        # Fetch catalog options
        prev_opts = pfmea_control_options(project_id, "Prevention")
        det_opts = pfmea_control_options(project_id, "Detection")

        available_manual: list[dict] = []
        seen_manual_keys: set[str] = set()

        for _, opt in prev_opts.iterrows():
            active_val = opt.get("active")
            is_active = True
            if active_val is not None:
                try:
                    if not pd.isna(active_val):
                        is_active = bool(active_val)
                except (TypeError, ValueError):
                    pass
            if not is_active:
                continue
            skey = f"manual:{opt['id']}"
            if skey not in seen_manual_keys:
                seen_manual_keys.add(skey)
                lbl = _plain_text(opt.get("label"))
                control_labels[skey] = lbl
                available_manual.append(
                    {
                        "source_key": skey,
                        "label": lbl,
                        "control_type": "Prevention / Catalog",
                    }
                )

        for _, opt in det_opts.iterrows():
            active_val = opt.get("active")
            is_active = True
            if active_val is not None:
                try:
                    if not pd.isna(active_val):
                        is_active = bool(active_val)
                except (TypeError, ValueError):
                    pass
            if not is_active:
                continue
            skey = f"manual:{opt['id']}"
            if skey not in seen_manual_keys:
                seen_manual_keys.add(skey)
                lbl = _plain_text(opt.get("label"))
                control_labels[skey] = lbl
                available_manual.append(
                    {
                        "source_key": skey,
                        "label": lbl,
                        "control_type": "Detection / Catalog",
                    }
                )

        # Component key
        palette_key = f"pfmea_dnd_palette_{project_id}_{scenario_id}_{selected_target_key}"

        def _apply_control_change(change: dict | Any) -> bool:
            if not change:
                return False
            if hasattr(change, "get"):
                new_prev = list(change.get("prevention") or [])
                new_det = list(change.get("detection") or [])
            else:
                new_prev = list(getattr(change, "prevention", []) or [])
                new_det = list(getattr(change, "detection", []) or [])

            # Check if there's an actual change compared to current_prevention / current_detection
            if new_prev == current_prevention and new_det == current_detection:
                return False

            # Update target row in session state draft
            current_draft = st.session_state.get(draft_key)
            if not isinstance(current_draft, pd.DataFrame):
                current_draft = rows.copy()
            else:
                current_draft = current_draft.copy()

            # Target mask
            mask = current_draft.apply(lambda r: _cause_target_key(r) == selected_target_key, axis=1)
            if not mask.any():
                mask = (
                    current_draft["id"].astype(str).eq(selected_target_key)
                    | current_draft["draft_row_id"].astype(str).eq(selected_target_key)
                )
            if mask.any():
                current_draft.loc[mask, "prevention_controls"] = pd.Series(
                    [new_prev] * int(mask.sum()),
                    index=current_draft.index[mask],
                    dtype="object",
                )
                current_draft.loc[mask, "detection_controls"] = pd.Series(
                    [new_det] * int(mask.sum()),
                    index=current_draft.index[mask],
                    dtype="object",
                )
                current_draft.loc[mask, "detection_review_required"] = True
                st.session_state[draft_key] = current_draft
                request_table_editor_reset(editor_key)
                return True
            return False

        def handle_dnd_change():
            palette_state = st.session_state.get(palette_key)
            change = getattr(palette_state, "change", None) if palette_state is not None else None
            if not change and isinstance(palette_state, dict):
                change = palette_state.get("change")
            if change:
                _apply_control_change(change)

        palette_res = pfmea_control_palette(
            selected_target_key,
            cause_label,
            available_quality,
            available_manual,
            current_prevention,
            current_detection,
            control_labels,
            key=palette_key,
            on_change=handle_dnd_change,
        )

        res_change = getattr(palette_res, "change", None) if palette_res is not None else None
        if not res_change and isinstance(palette_res, dict):
            res_change = palette_res.get("change")
        if res_change and _apply_control_change(res_change):
            st.rerun()
