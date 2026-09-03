from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from utils.component_payload import json_safe


_HTML = """
<div class="grid-shell">
  <div class="toolbar"><button id="add-category" type="button">＋ Add Subassembly</button></div>
  <div class="grid-wrap"><table id="assembly-grid"></table></div>
</div>
"""

_CSS = """
:host { color:var(--st-text-color); font-family:var(--st-font); }
.grid-shell { border:1px solid var(--st-border-color); border-radius:8px; overflow:hidden; background:var(--st-background-color); }
.toolbar { display:flex; padding:8px; border-bottom:1px solid var(--st-border-color); }
button { border:1px solid var(--st-primary-color); border-radius:6px; padding:5px 9px; color:var(--st-primary-color); background:var(--st-background-color); cursor:pointer; font-weight:650; }
.danger { border-color:#c62828; color:#c62828; }
.grid-wrap { overflow:auto; max-height:680px; }
table { border-collapse:separate; border-spacing:0; min-width:100%; font-size:.82rem; }
th, td { border-right:1px solid var(--st-border-color); border-bottom:1px solid var(--st-border-color); padding:6px; min-width:180px; vertical-align:top; background:var(--st-background-color); }
thead th { position:sticky; top:0; z-index:5; background:var(--st-secondary-background-color); }
.feature-row th { top:42px; font-weight:500; color:var(--st-secondary-text-color); }
.sticky-1 { position:sticky; left:0; z-index:4; min-width:190px; max-width:190px; }
.sticky-2 { position:sticky; left:203px; z-index:4; min-width:180px; max-width:180px; }
thead .sticky-1, thead .sticky-2 { z-index:8; background:var(--st-secondary-background-color); }
.category-row td { background:var(--st-background-color); }
input, select { box-sizing:border-box; width:100%; border:1px solid var(--st-border-color); border-radius:5px; padding:6px; color:var(--st-text-color); background:var(--st-background-color); }
.cell-actions { display:flex; gap:5px; margin-top:5px; flex-wrap:wrap; }
.cell-actions button { padding:3px 6px; font-size:.74rem; }
.field-label { display:block; margin-bottom:4px; color:var(--st-secondary-text-color); font-size:.72rem; }
.component-row td { background:color-mix(in srgb, var(--st-secondary-background-color) 55%, transparent); font-size:.76rem; }
.component-label { padding-left:18px; color:var(--st-secondary-text-color); }
.component { display:grid; grid-template-columns:minmax(100px,1fr) 70px auto; gap:5px; align-items:center; margin:3px 0; }
.component-identity { display:flex; flex-direction:column; gap:1px; min-width:0; }
.component-identity strong, .component-identity span { overflow-wrap:anywhere; }
.component input { padding:4px; }
.component button { padding:3px 6px; }
.muted { color:var(--st-secondary-text-color); }
.merged input:not(:focus) { color:transparent; }
.merged { position:relative; }
.merged:after { content:'↳ same assembly'; position:absolute; left:10px; top:34px; color:var(--st-secondary-text-color); pointer-events:none; font-size:.72rem; }
.merged:focus-within:after { display:none; }
"""

_JS = r"""
export default function(component) {
  const { parentElement, data, setStateValue, setTriggerValue } = component
  const table = parentElement.querySelector('#assembly-grid')
  const addButton = parentElement.querySelector('#add-category')
  if (!table || !addButton) return
  const clone = value => JSON.parse(JSON.stringify(value || []))
  const draft = clone(data.draft)
  const models = data.models || []
  const features = data.features || []
  const sections = data.sections || []
  const escapeHtml = value => String(value ?? '').replace(
    /[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch]
  )
  const emitDraft = () => setStateValue('draft', draft)
  const valueFor = (category, modelId) => {
    category.cells ||= {}
    category.cells[modelId] ||= {mapping_id:'', assembly_id:'', assembly_number:'', components:[]}
    return category.cells[modelId]
  }
  const featureValue = (model, featureId) => (model.features || {})[featureId] || '—'
  const sectionOptions = selected => `<option value="">Not assigned</option>` + sections.map(
    section => `<option value="${escapeHtml(section.id)}" ${section.id === selected ? 'selected' : ''}>${escapeHtml(section.name)}</option>`
  ).join('')
  const render = () => {
    let html = '<thead><tr><th class="sticky-1">Category</th><th class="sticky-2">Installed section</th>'
    html += models.map(model => `<th>${escapeHtml(model.model_number)}<br><span class="muted">${escapeHtml(model.display_name || '')}</span></th>`).join('') + '</tr>'
    for (const feature of features) {
      html += `<tr class="feature-row"><th class="sticky-1">${escapeHtml(feature.label)}</th><th class="sticky-2"></th>`
      html += models.map(model => `<th>${escapeHtml(featureValue(model, feature.id))}</th>`).join('') + '</tr>'
    }
    html += '</thead><tbody>'
    draft.forEach((category, categoryIndex) => {
      html += `<tr class="category-row" data-category="${categoryIndex}">`
      html += `<td class="sticky-1"><input data-field="display_name" value="${escapeHtml(category.display_name)}" placeholder="Display name"><input data-field="ebom_name" value="${escapeHtml(category.ebom_name)}" placeholder="Official EBOM name" style="margin-top:4px"><div class="cell-actions"><button class="danger delete-category" type="button">Delete</button></div></td>`
      html += `<td class="sticky-2"><select data-field="installed_section_id">${sectionOptions(category.installed_section_id || '')}</select></td>`
      let priorNumber = ''
      models.forEach(model => {
        const cell = valueFor(category, model.id)
        const repeated = cell.assembly_number && cell.assembly_number === priorNumber
        priorNumber = cell.assembly_number || ''
        html += `<td class="${repeated ? 'merged' : ''}" data-model="${escapeHtml(model.id)}"><label class="field-label">Part number</label><input class="assembly-entry" value="${escapeHtml(cell.assembly_number)}" placeholder="Part number"><div class="cell-actions">${cell.assembly_id ? '<button class="details" type="button">Details</button><button class="danger clear-mapping" type="button">Clear</button>' : ''}</div></td>`
      })
      html += '</tr>'
      const hasMappedAssembly = models.some(model => valueFor(category, model.id).assembly_id)
      if (hasMappedAssembly) {
        html += `<tr class="component-row" data-category="${categoryIndex}"><td class="sticky-1 component-label">↳ Mini-BOM components</td><td class="sticky-2"></td>`
        models.forEach(model => {
          const cell = valueFor(category, model.id)
          const usedIds = new Set((cell.components || []).map(item => item.fishbone_assignment_id))
          const availableUses = (data.uses || []).filter(item => !usedIds.has(item.id))
          const addControl = cell.assembly_id
            ? `<div class="component"><select class="component-use"><option value="">Choose Fishbone use</option>${availableUses.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join('')}</select><span></span><button class="add-component" type="button">＋ Add part</button></div>`
            : ''
          html += '<td>' + (cell.components || []).map((item, componentIndex) => `<div class="component" data-component="${componentIndex}"><span class="component-identity"><strong>${escapeHtml(item.part_number)}</strong><span class="muted">${escapeHtml(item.part_name || '')}</span></span><input class="component-quantity" type="number" min="0.000001" step="0.01" value="${escapeHtml(item.quantity)}"><button class="danger delete-component" type="button">×</button></div>`).join('') + addControl + '</td>'
        })
        html += '</tr>'
      }
    })
    table.innerHTML = html + '</tbody>'
    table.querySelectorAll('.category-row').forEach(row => {
      const categoryIndex = Number(row.dataset.category)
      row.querySelectorAll('[data-field]').forEach(input => input.onchange = () => {
        draft[categoryIndex][input.dataset.field] = input.value
        emitDraft()
      })
      row.querySelector('.delete-category').onclick = () => {
        const category = draft[categoryIndex]
        if (!category.id) {
          draft.splice(categoryIndex, 1)
          emitDraft()
          render()
          return
        }
        setTriggerValue('delete_category', {category_id:category.id, category_index:categoryIndex, display_name:category.display_name})
      }
      row.querySelectorAll('td[data-model]').forEach(cellElement => {
        const modelId = cellElement.dataset.model
        const cell = valueFor(draft[categoryIndex], modelId)
        const entry = cellElement.querySelector('.assembly-entry')
        entry.onchange = () => {
          cell.assembly_number = entry.value.trim()
          emitDraft()
        }
        const details = cellElement.querySelector('.details')
        if (details) details.onclick = () => setTriggerValue('details', {assembly_id:cell.assembly_id})
        const clear = cellElement.querySelector('.clear-mapping')
        if (clear) clear.onclick = () => setTriggerValue('clear_mapping', {category_id:draft[categoryIndex].id, model_id:modelId, mapping_id:cell.mapping_id, assembly_id:cell.assembly_id, assembly_number:cell.assembly_number})
      })
    })
    table.querySelectorAll('.component-row').forEach(row => {
      const categoryIndex = Number(row.dataset.category)
      row.querySelectorAll('td').forEach(cellElement => {
        const modelColumn = cellElement.cellIndex - 2
        if (modelColumn < 0 || !models[modelColumn]) return
        const cell = valueFor(draft[categoryIndex], models[modelColumn].id)
        cellElement.querySelectorAll('.component').forEach(componentElement => {
          const componentIndex = Number(componentElement.dataset.component)
          if (!Number.isFinite(componentIndex)) return
          componentElement.querySelector('.component-quantity').onchange = event => {
            const componentId = cell.components[componentIndex].id
            draft.forEach(category => Object.values(category.cells || {}).forEach(otherCell => {
              if (otherCell.assembly_id !== cell.assembly_id) return
              const matching = (otherCell.components || []).find(item => item.id === componentId)
              if (matching) matching.quantity = event.target.value
            }))
            emitDraft()
          }
          componentElement.querySelector('.delete-component').onclick = () => setTriggerValue('delete_component', {category_index:categoryIndex, model_id:models[modelColumn].id, component_index:componentIndex, assembly_id:cell.assembly_id, component_id:cell.components[componentIndex].id, part_number:cell.components[componentIndex].part_number})
        })
        const add = cellElement.querySelector('.add-component')
        const use = cellElement.querySelector('.component-use')
        if (add && use) add.onclick = () => {
          const selectedUse = (data.uses || []).find(item => item.id === use.value)
          if (!selectedUse) return
          draft.forEach(category => Object.values(category.cells || {}).forEach(otherCell => {
            if (otherCell.assembly_id !== cell.assembly_id) return
            otherCell.components ||= []
            if (otherCell.components.some(item => item.fishbone_assignment_id === selectedUse.id)) return
            otherCell.components.push({
              id:'',
              fishbone_assignment_id:selectedUse.id,
              part_number:selectedUse.part_number,
              part_name:selectedUse.part_name,
              quantity:selectedUse.quantity,
            })
          }))
          emitDraft()
          render()
        }
      })
    })
  }
  addButton.onclick = () => {
    draft.push({id:'', ebom_name:'', display_name:'', installed_section_id:'', sequence:(draft.length + 1) * 10, cells:{}})
    emitDraft(); render()
  }
  render()
}
"""


_ASSEMBLY_GRID = st.components.v2.component(
    "paag_assembly_grid_v5", html=_HTML, css=_CSS, js=_JS
)


def assembly_grid(
    *,
    key: str,
    draft: list[dict],
    models: list[dict],
    features: list[dict],
    sections: list[dict],
    uses: list[dict],
    on_draft_change: Callable[[], None],
    on_details_change: Callable[[], None],
    on_delete_category_change: Callable[[], None],
    on_clear_mapping_change: Callable[[], None],
    on_delete_component_change: Callable[[], None],
):
    component_state = st.session_state.get(key, {})
    current_draft = json_safe(component_state.get("draft", draft))
    component_data = json_safe(
        {
            "draft": current_draft,
            "models": models,
            "features": features,
            "sections": sections,
            "uses": uses,
        }
    )
    return _ASSEMBLY_GRID(
        key=key,
        data=component_data,
        default={"draft": current_draft},
        on_draft_change=on_draft_change,
        on_details_change=on_details_change,
        on_delete_category_change=on_delete_category_change,
        on_clear_mapping_change=on_clear_mapping_change,
        on_delete_component_change=on_delete_component_change,
        width="stretch",
        height="content",
    )
