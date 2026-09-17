from __future__ import annotations

import math
from collections.abc import Callable

import streamlit as st

from utils.component_payload import json_safe
from utils.time_units import time_unit as time_unit_config


_HTML = """
<div class="board">
  <div class="board-actions">
    <button id="add-pitch" type="button">＋ Add pitch</button>
    <button id="full-screen" type="button" title="Open the Yamazumi board full screen" aria-pressed="false">Full screen</button>
  </div>
  <div class="board-content">
  <div class="legend" id="legend"></div>
  <div class="unassigned-lane" id="unassigned"></div>
  <div class="lane-label">North side · odd pitches</div>
  <div class="lane north" id="north"></div>
  <div class="line"><span>Assembly flow →</span></div>
  <div class="lane south" id="south"></div>
  <div class="lane-label">South side · even pitches</div>
  </div>
</div>
"""

_CSS = """
:host { color: var(--st-text-color); font-family: var(--st-font); }
.board { box-sizing:border-box; min-width:980px; padding:4px 2px 16px; overflow-x:auto; background:var(--st-background-color); }
.board.fullscreen-board { position:fixed; inset:0; z-index:900; width:100vw; height:100vh; min-width:0; padding:12px; overflow:scroll; overscroll-behavior:contain; scrollbar-gutter:stable both-edges; scrollbar-color:var(--st-secondary-text-color) var(--st-secondary-background-color); }
.board.fullscreen-board::-webkit-scrollbar { width:14px; height:14px; }
.board.fullscreen-board::-webkit-scrollbar-track { background:var(--st-secondary-background-color); }
.board.fullscreen-board::-webkit-scrollbar-thumb { border:3px solid var(--st-secondary-background-color); border-radius:10px; background:var(--st-secondary-text-color); }
.board-content { box-sizing:border-box; width:max-content; min-width:100%; }
.board-actions { display:flex; gap:8px; margin:2px 0 10px; }
.board.fullscreen-board .board-actions { position:sticky; top:0; left:0; z-index:30; width:max-content; padding:4px; border-radius:6px; background:var(--st-background-color); }
.board-actions button, .add-element, .edit-pitch, .edit-element { border:1px solid var(--st-primary-color); border-radius:6px; padding:5px 9px; color:var(--st-primary-color); background:var(--st-background-color); cursor:pointer; font-weight:650; }
.board-actions button:disabled { cursor:not-allowed; opacity:.55; }
.lane { position:relative; display:flex; gap:10px; min-height:230px; padding:8px 2px; }
.lane.north { align-items:flex-end; }
.lane.south { align-items:flex-start; }
.takt-line { position:absolute; left:2px; z-index:10; height:0; border-top:2px solid #d32f2f; pointer-events:none; }
.lane-label { margin:8px 2px 0; font-weight:700; color:var(--st-secondary-text-color); }
.line { border-top:4px solid #c62828; margin:0; text-align:center; color:#c62828; font-weight:700; }
.line span { position:relative; top:-13px; padding:0 10px; background:var(--st-background-color); }
.pitch { position:relative; z-index:1; flex:0 0 240px; display:flex; flex-direction:column; border:1px solid var(--st-border-color); border-radius:9px; background:var(--st-background-color); padding:9px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
.pitch.north .variants { order:1; align-items:flex-end; }
.pitch.north .pitch-info { order:2; margin-top:6px; }
.pitch.south .pitch-info { order:1; margin-bottom:6px; }
.pitch.south .variants { order:2; }
.pitch.north .variant { display:flex; flex-direction:column-reverse; }
.pitch.north .variant-title { align-items:flex-start; box-sizing:border-box; margin:4px 0 0; }
.pitch.north .stack { flex-direction:column; justify-content:flex-end; }
.pitch.south .stack { justify-content:flex-start; }
.pitch.blocked { background:repeating-linear-gradient(135deg, #eceff1, #eceff1 8px, #cfd8dc 8px, #cfd8dc 16px); }
.pitch.open { background:#d7eef5; }
.pitch.blocked, .pitch.open { opacity:.78; }
.pitch.blocked .stack, .pitch.open .stack { cursor:not-allowed; }
.pitch.dragover { outline:3px solid var(--st-primary-color); }
.pitch-header { display:flex; justify-content:space-between; gap:8px; margin-bottom:5px; }
.pitch-info { box-sizing:border-box; }
.address { font-weight:800; color:var(--st-primary-color); }
.status { font-size:.75rem; text-transform:uppercase; color:var(--st-secondary-text-color); }
.name { min-height:28px; font-weight:650; }
.pitch-actions { display:flex; gap:6px; margin-top:5px; }
.pitch-actions button { flex:1; font-size:.76rem; padding:4px 6px; }
.variants { display:flex; align-items:flex-start; gap:6px; overflow-x:auto; }
.variant { flex:1 0 155px; border-top:2px solid var(--st-border-color); margin-top:8px; padding-top:6px; }
.variant-title { display:flex; justify-content:space-between; gap:5px; font-size:.78rem; font-weight:750; margin-bottom:4px; }
.stack { min-height:120px; border:1px solid var(--st-border-color); display:flex; flex-direction:column; background:color-mix(in srgb, var(--st-secondary-background-color) 45%, transparent); }
.stack.takt-scale { min-height:155px; }
.drop-slot { flex:0 0 8px; min-height:8px; margin:-4px 0; position:relative; z-index:3; }
.drop-slot.dragover { min-height:14px; flex-basis:14px; margin:-7px 0; background:color-mix(in srgb, var(--st-primary-color) 28%, transparent); outline:2px dashed var(--st-primary-color); }
.element { position:relative; box-sizing:border-box; min-height:0; padding:5px 31px 5px 6px; border-top:1px solid rgba(0,0,0,.14); font-size:.72rem; cursor:grab; overflow:hidden; }
.element strong { position:absolute; top:4px; right:31px; margin-left:5px; }
.element-description { display:block; height:100%; padding-right:30px; overflow:hidden; line-height:1.2; overflow-wrap:anywhere; }
.edit-element { position:absolute; right:3px; bottom:3px; padding:1px 4px; border-color:rgba(0,0,0,.35); color:#111; font-size:.68rem; line-height:1.2; }
.legend { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:4px; font-size:.8rem; }
.swatch { width:12px; height:12px; display:inline-block; border-radius:2px; margin-right:4px; }
.unassigned-lane { display:flex; margin:8px 2px 12px; }
.pitch.unassigned { flex-basis:240px; border-style:dashed; }
"""

_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component
  const escapeHtml = value => String(value ?? '').replace(
    /[&<>"']/g,
    character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[character]
  )
  const north = parentElement.querySelector('#north')
  const south = parentElement.querySelector('#south')
  const unassigned = parentElement.querySelector('#unassigned')
  const legend = parentElement.querySelector('#legend')
  const addPitch = parentElement.querySelector('#add-pitch')
  const fullScreen = parentElement.querySelector('#full-screen')
  const board = parentElement.querySelector('.board')
  if (!north || !south || !unassigned || !legend || !addPitch || !fullScreen || !board) return
  const fullScreenTarget = document.documentElement
  const isBoardFullScreen = () => document.fullscreenElement === fullScreenTarget
  addPitch.onclick = () => setTriggerValue('add_pitch', { requested: true })
  legend.innerHTML = `<span><i class="swatch" style="background:#35c84a"></i>Cycle</span>`
    + `<span><i class="swatch" style="background:#ffd54f"></i>Periodic</span>`
    + `<span><i class="swatch" style="background:#ef5350"></i>Fluctuation</span>`
  north.innerHTML = ''; south.innerHTML = ''; unassigned.innerHTML = ''
  const grouped = {}
  const secondsPerUnit = Math.max(Number(data.seconds_per_unit || 1), Number.EPSILON)
  const timeDecimals = Math.max(0, Number(data.time_decimals || 0))
  const timeSuffix = String(data.time_suffix || 's')
  const taktSecondsPerUnit = Math.max(Number(data.takt_seconds_per_unit || 1), Number.EPSILON)
  const taktDecimals = Math.max(0, Number(data.takt_decimals || 0))
  const taktSuffix = String(data.takt_suffix || 's')
  const taktPixels = 155
  const hasTakt = Number.isFinite(Number(data.takt)) && Number(data.takt) > 0
  const displayTime = value => Number(value || 0) / secondsPerUnit
  const formatTime = value => `${displayTime(value).toFixed(timeDecimals)} ${timeSuffix}`
  const formatTakt = value => `${(Number(value || 0) / taktSecondsPerUnit).toFixed(taktDecimals)} ${taktSuffix}`
  for (const element of (data.elements || [])) {
    const pitch = element.pitch_id || '__unassigned__'
    grouped[pitch] ||= {}
    let elementVariants = element.model_variants
    if (typeof elementVariants === 'string') {
      try { elementVariants = JSON.parse(elementVariants) } catch { elementVariants = [elementVariants] }
    }
    if (!Array.isArray(elementVariants) || !elementVariants.length) {
      elementVariants = [element.model_variant || 'Base']
    }
    for (const variant of [...new Set(elementVariants)]) {
      grouped[pitch][variant] ||= []
      grouped[pitch][variant].push(element)
    }
  }
  const makePitch = (pitch, side = 'neutral') => {
    const card = document.createElement('div')
    card.className = `pitch ${side} ${(pitch.status || '').toLowerCase()}`
    card.dataset.pitch = pitch.id || ''
    const pitchVariants = pitch.id ? (pitch.model_variants || ['Base']) : [...new Set(Object.keys(grouped.__unassigned__ || {}).concat(['Base']))]
    card.style.flexBasis = `${Math.max(240, pitchVariants.length * 165 + 18)}px`
    const pitchMeta = [pitch.pitch_type, pitch.status].filter(Boolean).join(' · ')
    card.innerHTML = `<div class="pitch-info"><div class="pitch-header"><span class="address">${pitch.pitch_number || 'Unassigned'}</span><span class="status">${pitchMeta}</span></div><div class="name">${pitch.pitch_name || ''}</div><div class="pitch-actions"></div></div><div class="variants"></div>`
    const variantWrap = card.querySelector('.variants')
    const pitchActions = card.querySelector('.pitch-actions')
    for (const variant of pitchVariants) {
      const items = [...((grouped[pitch.id || '__unassigned__'] || {})[variant] || [])]
      items.sort((a, b) => {
        const sequenceDifference = Number(a.sequence || 0) - Number(b.sequence || 0)
        if (sequenceDifference !== 0) return sequenceDifference
        return String(a.description || '').localeCompare(String(b.description || ''))
      })
      const total = items.reduce((sum,item) => sum + Number(item.time_s || 0), 0)
      const displayItems = side === 'north' ? [...items].reverse() : items
      const block = document.createElement('div')
      block.className = 'variant'
      block.innerHTML = `<div class="variant-title"><span>${variant}</span><span>${formatTime(total)} / ${formatTakt(data.takt)}</span></div><div class="stack"></div>`
      const stack = block.querySelector('.stack')
      if (pitch.id && hasTakt) stack.classList.add('takt-scale')
      const appendDropSlot = logicalIndex => {
        const slot = document.createElement('div')
        slot.className = 'drop-slot'
        slot.dataset.insertIndex = String(logicalIndex)
        slot.ondragover = event => {
          event.preventDefault(); event.stopPropagation(); slot.classList.add('dragover')
        }
        slot.ondragleave = () => slot.classList.remove('dragover')
        slot.ondrop = event => {
          event.preventDefault(); event.stopPropagation(); slot.classList.remove('dragover')
          setTriggerValue('move', {
            element_id: event.dataTransfer.getData('text/plain'),
            pitch_id: pitch.id || null,
            insert_index: logicalIndex,
            before_element_id: items[logicalIndex]?.id || null,
            after_element_id: logicalIndex > 0 ? items[logicalIndex - 1]?.id || null : null,
          })
        }
        stack.appendChild(slot)
      }
      if (side !== 'north') appendDropSlot(0)
      for (const item of displayItems) {
        const logicalIndex = items.findIndex(candidate => candidate.id === item.id)
        if (side === 'north') appendDropSlot(logicalIndex + 1)
        const el = document.createElement('div')
        const color = item.work_type === 'Periodic'
          ? '#ffd54f'
          : item.work_type === 'Fluctuation'
            ? '#ef5350'
            : '#35c84a'
        const displayTakt = Math.max(displayTime(data.takt), Number.EPSILON)
        el.className = 'element'
        el.draggable = true
        el.dataset.id = item.id
        el.style.background = color
        const elementHeight = hasTakt && pitch.id
          ? Math.max(0, displayTime(item.time_s) / displayTakt * taktPixels)
          : 34
        el.style.height = `${elementHeight}px`
        el.style.flex = `0 0 ${elementHeight}px`
        el.innerHTML = `<strong>${formatTime(item.time_s)}</strong><span class="element-description">${item.description}</span><button type="button" class="edit-element" title="Edit work element">Edit</button>`
        el.title = `${item.description} · ${formatTime(item.time_s)} · ${item.work_region || 'None'}`
        el.ondragstart = event => event.dataTransfer.setData('text/plain', item.id)
        el.querySelector('.edit-element').onclick = event => {
          event.preventDefault(); event.stopPropagation()
          setTriggerValue('edit_element', { element_id: item.id })
        }
        stack.appendChild(el)
        if (side !== 'north') appendDropSlot(logicalIndex + 1)
      }
      if (side === 'north') appendDropSlot(0)
      variantWrap.appendChild(block)
    }
    const acceptsWork = !pitch.id || pitch.status === 'Active'
    if (pitch.id) {
      const editButton = document.createElement('button')
      editButton.type = 'button'
      editButton.className = 'edit-pitch'
      editButton.textContent = 'Edit pitch'
      editButton.onclick = event => {
        event.preventDefault(); event.stopPropagation()
        setTriggerValue('edit_pitch', { pitch_id: pitch.id })
      }
      pitchActions.appendChild(editButton)
    }
    if (acceptsWork) {
      const addButton = document.createElement('button')
      addButton.type = 'button'
      addButton.className = 'add-element'
      addButton.textContent = '＋ Add element'
      addButton.onclick = () => setTriggerValue('add_element', { pitch_id: pitch.id || null, pitch_number: pitch.pitch_number || 'Unassigned' })
      pitchActions.appendChild(addButton)
      card.ondragover = event => { event.preventDefault(); card.classList.add('dragover') }
      card.ondragleave = () => card.classList.remove('dragover')
      card.ondrop = event => {
        event.preventDefault(); card.classList.remove('dragover')
        setTriggerValue('move', {
          element_id: event.dataTransfer.getData('text/plain'),
          pitch_id: pitch.id || null,
          before_element_id: null,
          after_element_id: null,
        })
      }
    } else {
      card.title = `${pitch.status} pitches must be changed to Active before work can be assigned.`
    }
    return card
  }
  const numberFrom = value => { const found = String(value || '').match(/(\d+)(?!.*\d)/); return found ? Number(found[1]) : 0 }
  if (data.show_unassigned && Object.keys(grouped.__unassigned__ || {}).length) {
    unassigned.appendChild(makePitch({
      id: null,
      pitch_number: 'Unassigned',
      pitch_name: 'Drop work here',
      status: 'Active',
      model_variants: ['Base'],
    }, 'unassigned'))
  }
  for (const pitch of (data.pitches || [])) {
    const lane = numberFrom(pitch.pitch_number) % 2 ? north : south
    lane.appendChild(makePitch(pitch, lane === north ? 'north' : 'south'))
  }
  const alignLaneBaselines = lane => {
    const pitchInfos = [...lane.querySelectorAll('.pitch-info')]
    const titles = [...lane.querySelectorAll('.variant-title')]
    for (const element of [...pitchInfos, ...titles]) element.style.minHeight = ''
    const infoBandHeight = Math.max(0, ...pitchInfos.map(element => element.scrollHeight))
    const titleBandHeight = Math.max(0, ...titles.map(element => element.scrollHeight))
    for (const element of pitchInfos) element.style.minHeight = `${infoBandHeight}px`
    for (const element of titles) element.style.minHeight = `${titleBandHeight}px`
  }
  const drawTaktLine = (lane, side) => {
    lane.querySelectorAll('.takt-line').forEach(line => line.remove())
    if (!hasTakt) return
    const stack = lane.querySelector('.stack.takt-scale')
    if (!stack) return
    const laneRect = lane.getBoundingClientRect()
    const stackRect = stack.getBoundingClientRect()
    const line = document.createElement('div')
    line.className = 'takt-line'
    line.setAttribute('aria-hidden', 'true')
    line.style.top = `${side === 'north'
      ? stackRect.bottom - laneRect.top - taktPixels
      : stackRect.top - laneRect.top + taktPixels}px`
    line.style.width = `${Math.max(0, lane.scrollWidth - 4)}px`
    lane.appendChild(line)
  }
  const layoutBoard = () => {
    alignLaneBaselines(north)
    alignLaneBaselines(south)
    drawTaktLine(north, 'north')
    drawTaktLine(south, 'south')
  }
  const scheduleLayout = () => {
    requestAnimationFrame(() => requestAnimationFrame(layoutBoard))
  }
  const updateFullScreenControl = () => {
    const isFullScreen = isBoardFullScreen()
    fullScreen.textContent = isFullScreen ? 'Exit full screen' : 'Full screen'
    fullScreen.title = isFullScreen
      ? 'Exit the full-screen Yamazumi board'
      : 'Open the Yamazumi board full screen'
    fullScreen.setAttribute('aria-pressed', String(isFullScreen))
    board.classList.toggle('fullscreen-board', isFullScreen)
    scheduleLayout()
  }
  if (typeof fullScreenTarget.requestFullscreen !== 'function') {
    fullScreen.disabled = true
    fullScreen.title = 'Full screen is not available in this browser'
  } else {
    fullScreen.onclick = async () => {
      try {
        if (isBoardFullScreen()) await document.exitFullscreen()
        else await fullScreenTarget.requestFullscreen()
      } catch {
        updateFullScreenControl()
      }
    }
  }
  document.addEventListener('fullscreenchange', updateFullScreenControl)
  const resizeObserver = new ResizeObserver(scheduleLayout)
  resizeObserver.observe(board)
  // Normalize bands across all pitches after wrapping has been measured. This
  // gives every stack in a lane one shared baseline beside the assembly flow.
  scheduleLayout()
  updateFullScreenControl()
  return () => {
    document.removeEventListener('fullscreenchange', updateFullScreenControl)
    resizeObserver.disconnect()
  }
}
"""

_YAMAZUMI_BOARD = st.components.v2.component(
    "paag_yamazumi_drag_board_v25",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def yamazumi_board(
    pitches: list[dict],
    elements: list[dict],
    variants: list[str],
    takt: float,
    *,
    time_unit: str,
    takt_time_unit: str,
    key: str,
    on_move: Callable[[], None],
    on_add_pitch: Callable[[], None],
    on_add_element: Callable[[], None],
    on_edit_pitch: Callable[[], None],
    on_edit_element: Callable[[], None],
):
    safe_takt = float(takt)
    if not math.isfinite(safe_takt):
        safe_takt = 0.0
    unit = time_unit_config(time_unit)
    takt_unit = time_unit_config(takt_time_unit)
    safe_elements = json_safe(elements)
    return _YAMAZUMI_BOARD(
        key=key,
        data=json_safe(
            {
                "pitches": pitches,
                "elements": safe_elements,
                "show_unassigned": any(
                    not element.get("pitch_id") for element in safe_elements
                ),
                "variants": variants,
                "takt": safe_takt,
                "time_unit": unit.key,
                "seconds_per_unit": unit.seconds_per_unit,
                "time_decimals": unit.decimals,
                "time_suffix": unit.suffix,
                "takt_time_unit": takt_unit.key,
                "takt_seconds_per_unit": takt_unit.seconds_per_unit,
                "takt_decimals": takt_unit.decimals,
                "takt_suffix": takt_unit.suffix,
            }
        ),
        on_move_change=on_move,
        on_add_pitch_change=on_add_pitch,
        on_add_element_change=on_add_element,
        on_edit_pitch_change=on_edit_pitch,
        on_edit_element_change=on_edit_element,
        width="stretch",
        height="content",
    )
