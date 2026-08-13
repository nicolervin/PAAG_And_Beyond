from __future__ import annotations

from collections.abc import Callable

import streamlit as st


_HTML = """
<div class="board">
  <div class="board-actions"><button id="add-pitch" type="button">＋ Add pitch</button></div>
  <div class="legend" id="legend"></div>
  <div class="lane-label">North side · odd pitches</div>
  <div class="lane north" id="north"></div>
  <div class="line"><span>Assembly flow →</span></div>
  <div class="lane south" id="south"></div>
  <div class="lane-label">South side · even pitches</div>
</div>
"""

_CSS = """
:host { color: var(--st-text-color); font-family: var(--st-font); }
.board { min-width: 980px; padding: 4px 2px 16px; overflow-x: auto; }
.board-actions { display:flex; gap:8px; margin:2px 0 10px; }
.board-actions button, .add-element, .edit-pitch, .edit-element { border:1px solid var(--st-primary-color); border-radius:6px; padding:5px 9px; color:var(--st-primary-color); background:var(--st-background-color); cursor:pointer; font-weight:650; }
.lane { display:flex; gap:10px; min-height:230px; padding:8px 2px; }
.lane.north { align-items:flex-end; }
.lane.south { align-items:flex-start; }
.lane-label { margin:8px 2px 0; font-weight:700; color:var(--st-secondary-text-color); }
.line { border-top:4px solid #c62828; margin:0; text-align:center; color:#c62828; font-weight:700; }
.line span { position:relative; top:-13px; padding:0 10px; background:var(--st-background-color); }
.pitch { flex:0 0 240px; display:flex; flex-direction:column; border:1px solid var(--st-border-color); border-radius:9px; background:var(--st-background-color); padding:9px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
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
.element { position:relative; box-sizing:border-box; min-height:34px; padding:5px 31px 5px 6px; border-top:1px solid rgba(0,0,0,.14); font-size:.72rem; cursor:grab; overflow:hidden; }
.element strong { position:absolute; top:4px; right:31px; margin-left:5px; }
.element-description { display:block; height:100%; padding-right:30px; overflow:hidden; line-height:1.2; overflow-wrap:anywhere; }
.edit-element { position:absolute; right:3px; bottom:3px; padding:1px 4px; border-color:rgba(0,0,0,.35); color:#111; font-size:.68rem; line-height:1.2; }
.flags { position:absolute; left:3px; bottom:3px; z-index:2; max-width:calc(100% - 43px); box-sizing:border-box; padding:1px 4px; border:1px solid #8b0000; border-radius:3px; background:#fff3cd; color:#8b0000; font-weight:900; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; pointer-events:none; }
.legend { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:4px; font-size:.8rem; }
.swatch { width:12px; height:12px; display:inline-block; border-radius:2px; margin-right:4px; }
"""

_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component
  const north = parentElement.querySelector('#north')
  const south = parentElement.querySelector('#south')
  const legend = parentElement.querySelector('#legend')
  const addPitch = parentElement.querySelector('#add-pitch')
  if (!north || !south || !legend || !addPitch) return
  addPitch.onclick = () => setTriggerValue('add_pitch', { requested: true })
  const colors = data.colors || {}
  legend.innerHTML = Object.entries(colors).map(([name,color]) => `<span><i class="swatch" style="background:${color}"></i>${name}</span>`).join('')
    + `<span><i class="swatch" style="background:#ffd54f"></i>Periodic</span>`
    + `<span><i class="swatch" style="background:#ef5350"></i>Fluctuation</span>`
  north.innerHTML = ''; south.innerHTML = ''
  const grouped = {}
  for (const element of (data.elements || [])) {
    const pitch = element.pitch_id || '__unassigned__'
    grouped[pitch] ||= {}
    grouped[pitch][element.model_variant || 'Base'] ||= []
    grouped[pitch][element.model_variant || 'Base'].push(element)
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
      block.innerHTML = `<div class="variant-title"><span>${variant}</span><span>${total.toFixed(1)}s / ${Number(data.takt || 0).toFixed(1)}s</span></div><div class="stack"></div>`
      const stack = block.querySelector('.stack')
      for (const item of displayItems) {
        const el = document.createElement('div')
        const regionColor = item.work_region && item.work_region !== 'None'
          ? colors[item.work_region]
          : null
        const color = regionColor
          || (item.work_type === 'Periodic'
            ? '#ffd54f'
            : item.work_type === 'Fluctuation'
              ? '#ef5350'
              : '#35c84a')
        const takt = Math.max(Number(data.takt || 1), 1)
        el.className = 'element'
        el.draggable = true
        el.dataset.id = item.id
        el.style.background = color
        const elementHeight = Math.max(34, Number(item.time_s || 0) / takt * 155)
        el.style.height = `${elementHeight}px`
        el.style.flex = `0 0 ${elementHeight}px`
        const flags = (item.flags || []).map(f => f === 'Safety' ? '⚠ Safety' : '◆ CTQ').join(' ')
        el.innerHTML = `<strong>${Number(item.time_s || 0).toFixed(1)}s</strong><span class="element-description">${item.description}</span>${flags ? `<span class="flags">${flags}</span>` : ''}<button type="button" class="edit-element" title="Edit work element">Edit</button>`
        el.title = `${item.description} · ${Number(item.time_s || 0).toFixed(1)}s · ${item.work_region || 'None'}`
        el.ondragstart = event => event.dataTransfer.setData('text/plain', item.id)
        el.querySelector('.edit-element').onclick = event => {
          event.preventDefault(); event.stopPropagation()
          setTriggerValue('edit_element', { element_id: item.id })
        }
        stack.appendChild(el)
      }
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
        setTriggerValue('move', { element_id: event.dataTransfer.getData('text/plain'), pitch_id: pitch.id || null })
      }
    } else {
      card.title = `${pitch.status} pitches must be changed to Active before work can be assigned.`
    }
    return card
  }
  const numberFrom = value => { const found = String(value || '').match(/(\d+)(?!.*\d)/); return found ? Number(found[1]) : 0 }
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
  // Normalize bands across all pitches after wrapping has been measured. This
  // gives every stack in a lane one shared baseline beside the assembly flow.
  requestAnimationFrame(() => {
    alignLaneBaselines(north)
    alignLaneBaselines(south)
  })
}
"""

_YAMAZUMI_BOARD = st.components.v2.component(
    "paag_yamazumi_drag_board_v12",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def yamazumi_board(
    pitches: list[dict],
    elements: list[dict],
    variants: list[str],
    takt: float,
    colors: dict[str, str],
    *,
    key: str,
    on_move: Callable[[], None],
    on_add_pitch: Callable[[], None],
    on_add_element: Callable[[], None],
    on_edit_pitch: Callable[[], None],
    on_edit_element: Callable[[], None],
):
    return _YAMAZUMI_BOARD(
        key=key,
        data={"pitches": pitches, "elements": elements, "variants": variants, "takt": takt, "colors": colors},
        on_move_change=on_move,
        on_add_pitch_change=on_add_pitch,
        on_add_element_change=on_add_element,
        on_edit_pitch_change=on_edit_pitch,
        on_edit_element_change=on_edit_element,
        width="stretch",
        height="content",
    )
