from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from utils.component_payload import json_safe


_HTML = """
<div class="grid-shell">
  <div class="toolbar"><select id="add-section" aria-label="Fishbone section"></select><button id="add-category" type="button">＋ Add Subassembly</button></div>
  <div class="grid-wrap"><table id="assembly-grid"></table></div>
</div>
"""

_CSS = """
:host { color:var(--st-text-color); font-family:var(--st-font); }
.grid-shell { border:1px solid var(--st-border-color); border-radius:8px; overflow:hidden; background:var(--st-background-color); }
.toolbar { display:flex; gap:8px; padding:8px; border-bottom:1px solid var(--st-border-color); }
.toolbar select { width:auto; min-width:220px; }
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
.top-level-row td { background:color-mix(in srgb, var(--st-primary-color) 9%, var(--st-background-color)); border-bottom-width:2px; }
.top-level-title { display:block; margin-bottom:6px; font-weight:800; color:var(--st-primary-color); }
.section-row td { padding:8px 10px; font-weight:700; background:var(--st-secondary-background-color); }
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
const focusState = new WeakMap()

export default function(component) {
  const { parentElement, data, setStateValue, setTriggerValue } = component
  const table = parentElement.querySelector('#assembly-grid')
  const addButton = parentElement.querySelector('#add-category')
  const addSection = parentElement.querySelector('#add-section')
  if (!table || !addButton || !addSection) return
  const instanceFocus = focusState.get(parentElement) || {key:''}
  focusState.set(parentElement, instanceFocus)
  const clone = value => JSON.parse(JSON.stringify(value || []))
  const draft = clone(data.draft)
  const models = data.models || []
  const features = data.features || []
  const sections = data.sections || []
  const gridSections = data.grid_sections || []
  const displayedSectionIds = new Set(gridSections.map(section => section.id))
  const escapeHtml = value => String(value ?? '').replace(
    /[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch]
  )
  const emitDraft = () => setStateValue('draft', draft)
  const focusableControls = () => Array.from(
    table.querySelectorAll('[data-grid-focus]:not([disabled])')
  )
  const queueFocusRestore = focusKey => {
    instanceFocus.key = focusKey || ''
    setTimeout(() => {
      if (instanceFocus.key === focusKey) instanceFocus.key = ''
    }, 5000)
  }
  const restoreQueuedFocus = () => {
    const focusKey = instanceFocus.key
    if (!focusKey) return
    const target = focusableControls().find(control => control.dataset.gridFocus === focusKey)
    instanceFocus.key = ''
    if (target) target.focus({preventScroll:true})
  }
  const wireFocusNavigation = () => {
    table.onpointerdown = event => {
      let target = event.target.closest('[data-grid-focus]')
      if (!target) {
        const modelCell = event.target.closest('td[data-model]')
        target = modelCell && modelCell.querySelector('.assembly-entry')
        if (target) {
          event.preventDefault()
          queueFocusRestore(target.dataset.gridFocus)
          target.focus({preventScroll:true})
          return
        }
      }
      const root = parentElement.getRootNode ? parentElement.getRootNode() : parentElement
      const active = parentElement.activeElement || root.activeElement
      if (target && active && active !== target) {
        queueFocusRestore(target.dataset.gridFocus)
      }
    }
    table.onkeydown = event => {
      if (event.key !== 'Tab' || event.altKey || event.ctrlKey || event.metaKey) return
      const current = event.target.closest('[data-grid-focus]')
      if (!current) return
      const controls = focusableControls()
      const currentIndex = controls.indexOf(current)
      const nextIndex = currentIndex + (event.shiftKey ? -1 : 1)
      if (currentIndex < 0 || nextIndex < 0 || nextIndex >= controls.length) return
      event.preventDefault()
      const next = controls[nextIndex]
      queueFocusRestore(next.dataset.gridFocus)
      next.focus({preventScroll:true})
    }
    requestAnimationFrame(restoreQueuedFocus)
  }
  const valueFor = (category, modelId) => {
    category.cells ||= {}
    category.cells[modelId] ||= {mapping_id:'', assembly_id:'', assembly_number:'', components:[]}
    return category.cells[modelId]
  }
  const featureValue = (model, featureId) => (model.features || {})[featureId] || '—'
  const sectionOptions = selected => `<option value="">Not assigned</option>` + sections.map(
    section => `<option value="${escapeHtml(section.id)}" ${section.id === selected ? 'selected' : ''}>${escapeHtml(section.name)}</option>`
  ).join('')
  const builtSectionOptions = selected => `<option value="">Choose final Built section</option>` + sections.map(
    section => `<option value="${escapeHtml(section.id)}" ${section.id === selected ? 'selected' : ''}>${escapeHtml(section.name)}</option>`
  ).join('')
  const render = () => {
    addSection.innerHTML = gridSections.map(section => `<option value="${escapeHtml(section.id)}">Add to ${escapeHtml(section.name)}</option>`).join('')
    let html = '<thead><tr><th class="sticky-1">Category</th><th class="sticky-2">Installed section</th>'
    html += models.map(model => `<th>${escapeHtml(model.model_number)}<br><span class="muted">${escapeHtml(model.display_name || '')}</span></th>`).join('') + '</tr>'
    for (const feature of features) {
      html += `<tr class="feature-row"><th class="sticky-1">${escapeHtml(feature.label)}</th><th class="sticky-2"></th>`
      html += models.map(model => `<th>${escapeHtml(featureValue(model, feature.id))}</th>`).join('') + '</tr>'
    }
    html += '</thead><tbody>'
    ;[{id:'__top_level__', name:''}, ...gridSections].forEach(gridSection => {
      if (gridSection.id !== '__top_level__') html += `<tr class="section-row"><td colspan="${models.length + 2}">${escapeHtml(gridSection.name)}</td></tr>`
      draft.forEach((category, categoryIndex) => {
      const topLevel = Boolean(category.is_top_level)
      if (gridSection.id === '__top_level__' ? !topLevel : topLevel || category.section_id !== gridSection.id) return
      html += `<tr class="category-row ${topLevel ? 'top-level-row' : ''}" data-category="${categoryIndex}">`
      html += topLevel
        ? `<td class="sticky-1"><span class="top-level-title">Top-level packaged unit</span><label class="field-label">Final Built section</label><select data-grid-focus="category-${categoryIndex}-built" data-field="section_id">${builtSectionOptions(category.section_id || '')}</select></td>`
        : `<td class="sticky-1"><input data-grid-focus="category-${categoryIndex}-display" data-field="display_name" value="${escapeHtml(category.display_name)}" placeholder="Display name"><input data-grid-focus="category-${categoryIndex}-ebom" data-field="ebom_name" value="${escapeHtml(category.ebom_name)}" placeholder="Official EBOM name" style="margin-top:4px"><div class="cell-actions"><button data-grid-focus="category-${categoryIndex}-delete" class="danger delete-category" type="button">Delete</button></div></td>`
      html += `<td class="sticky-2"><select data-grid-focus="category-${categoryIndex}-installed" data-field="installed_section_id">${sectionOptions(category.installed_section_id || '')}</select></td>`
      let priorNumber = ''
      models.forEach(model => {
        const cell = valueFor(category, model.id)
        const repeated = cell.assembly_number && cell.assembly_number === priorNumber
        priorNumber = cell.assembly_number || ''
        const cellFocus = `category-${categoryIndex}-model-${model.id}`
        html += `<td class="${repeated ? 'merged' : ''}" data-model="${escapeHtml(model.id)}"><label class="field-label">Part number</label><input data-grid-focus="${escapeHtml(cellFocus)}-part-number" class="assembly-entry" value="${escapeHtml(cell.assembly_number)}" placeholder="Part number"><div class="cell-actions">${cell.assembly_id ? `<button data-grid-focus="${escapeHtml(cellFocus)}-details" class="details" type="button">Details</button><button data-grid-focus="${escapeHtml(cellFocus)}-clear" class="danger clear-mapping" type="button">Clear</button>` : ''}</div></td>`
      })
      html += '</tr>'
      const hasMappedAssembly = models.some(model => valueFor(category, model.id).assembly_id)
      if (hasMappedAssembly) {
        html += `<tr class="component-row" data-category="${categoryIndex}"><td class="sticky-1 component-label">↳ Mini-BOM components</td><td class="sticky-2"></td>`
        models.forEach(model => {
          const cell = valueFor(category, model.id)
          const usedIds = new Set((cell.components || []).map(item => item.fishbone_assignment_id || `assembly:${item.nested_assembly_id || ''}`))
          const availableUses = (data.uses || []).filter(item => !usedIds.has(item.id) && (item.kind === 'assembly' ? item.nested_assembly_id !== cell.assembly_id && (topLevel || displayedSectionIds.has(item.section_id)) : item.section_id === category.section_id))
          const componentFocus = `category-${categoryIndex}-model-${model.id}`
          const addControl = cell.assembly_id
            ? `<div class="component"><select data-grid-focus="${escapeHtml(componentFocus)}-new-part" class="component-use"><option value="">Choose part or subassembly</option>${availableUses.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join('')}</select><span></span><button data-grid-focus="${escapeHtml(componentFocus)}-add-part" class="add-component" type="button">＋ Add part</button></div>`
            : ''
          html += '<td>' + (cell.components || []).map((item, componentIndex) => `<div class="component" data-component="${componentIndex}"><span class="component-identity"><strong>${escapeHtml(item.part_number)}${item.nested_assembly_id ? ' · Subassembly' : ''}</strong><span class="muted">${escapeHtml(item.part_name || '')}</span></span><input data-grid-focus="${escapeHtml(componentFocus)}-component-${componentIndex}-quantity" class="component-quantity" type="number" min="0.000001" step="0.01" value="${escapeHtml(item.quantity)}"><button data-grid-focus="${escapeHtml(componentFocus)}-component-${componentIndex}-delete" class="danger delete-component" type="button">×</button></div>`).join('') + addControl + '</td>'
        })
        html += '</tr>'
      }
      })
    })
    table.innerHTML = html + '</tbody>'
    table.querySelectorAll('.category-row').forEach(row => {
      const categoryIndex = Number(row.dataset.category)
      row.querySelectorAll('[data-field]').forEach(input => input.onchange = () => {
        draft[categoryIndex][input.dataset.field] = input.value
        if (!instanceFocus.key) queueFocusRestore(input.dataset.gridFocus)
        emitDraft()
      })
      const deleteCategory = row.querySelector('.delete-category')
      if (deleteCategory) deleteCategory.onclick = () => {
        const category = draft[categoryIndex]
        if (!category.id) {
          draft.splice(categoryIndex, 1)
          emitDraft()
          render()
          return
        }
        setTriggerValue('delete_category', {category_id:category.id, category_index:categoryIndex, section_id:category.section_id, display_name:category.display_name})
      }
      row.querySelectorAll('td[data-model]').forEach(cellElement => {
        const modelId = cellElement.dataset.model
        const cell = valueFor(draft[categoryIndex], modelId)
        const entry = cellElement.querySelector('.assembly-entry')
        entry.onchange = () => {
          cell.assembly_number = entry.value.trim()
          if (!instanceFocus.key) queueFocusRestore(entry.dataset.gridFocus)
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
            if (!instanceFocus.key) {
              queueFocusRestore(event.target.dataset.gridFocus)
            }
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
            if (otherCell.components.some(item => (item.fishbone_assignment_id || `assembly:${item.nested_assembly_id || ''}`) === selectedUse.id)) return
            otherCell.components.push({
              id:'',
              fishbone_assignment_id:selectedUse.kind === 'assembly' ? '' : selectedUse.id,
              nested_assembly_id:selectedUse.nested_assembly_id || '',
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
    wireFocusNavigation()
  }
  addButton.onclick = () => {
    if (!addSection.value) return
    draft.push({id:'', section_id:addSection.value, ebom_name:'', display_name:'', installed_section_id:'', sequence:(draft.length + 1) * 10, cells:{}})
    queueFocusRestore(`category-${draft.length - 1}-display`)
    emitDraft(); render()
  }
  render()
}
"""


_ASSEMBLY_GRID = st.components.v2.component(
    "paag_assembly_grid_v8", html=_HTML, css=_CSS, js=_JS
)


def assembly_grid(
    *,
    key: str,
    draft: list[dict],
    models: list[dict],
    features: list[dict],
    sections: list[dict],
    grid_sections: list[dict],
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
            "grid_sections": grid_sections,
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
