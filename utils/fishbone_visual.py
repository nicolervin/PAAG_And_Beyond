import base64
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageOps
import streamlit as st


_HTML = """
<div class="fishbone-shell">
  <div class="fishbone-toolbar">
    <div class="fishbone-title">
      <strong>Interactive assembly fishbone</strong>
      <span id="fishbone-summary"></span>
    </div>
    <div class="fishbone-actions">
      <button id="add-section-btn" type="button" title="Add new section block" class="btn-tool" style="background:#2563eb; color:white; border-color:#2563eb; font-weight:700;">➕ Add Section</button>
      <button id="toggle-palette" type="button" title="Toggle parts palette" class="btn-tool">📦 Parts palette</button>
      <button id="auto-arrange" type="button" title="Auto-arrange sections" class="btn-tool">⚡ Auto-arrange</button>
      <button id="zoom-out" type="button" title="Zoom out">−</button>
      <button id="zoom-in" type="button" title="Zoom in">+</button>
      <button id="fit-view" type="button" title="Fit the entire fishbone">Fit</button>
      <button id="full-screen" type="button" title="Open the fishbone full screen">Full screen</button>
    </div>
  </div>
  <div class="fishbone-body">
    <aside id="fishbone-palette" class="fishbone-palette">
      <div class="palette-header">
        <strong>Parts & Assemblies</strong>
        <span id="palette-count"></span>
      </div>
      <div class="palette-search-box">
        <input type="text" id="palette-search" placeholder="Search parts / assemblies..." />
      </div>
      <div class="palette-filter-row">
        <label><input type="checkbox" id="palette-unplaced-only" checked /> Unplaced only</label>
      </div>
      <div id="palette-list" class="palette-list">
        <!-- Rendered draggable part cards -->
      </div>
    </aside>
    <div class="fishbone-viewport">
      <svg id="fishbone-svg" role="img" aria-label="Interactive assembly fishbone">
        <defs>
          <marker id="arrow-flow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#2563eb" />
          </marker>
          <marker id="arrow-buffer" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#64748b" />
          </marker>
          <marker id="arrow-selected" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#ef4444" />
          </marker>
        </defs>
        <g id="fishbone-world"></g>
      </svg>
      <div id="fishbone-tooltip" class="fishbone-tooltip" hidden>
        <div class="tooltip-header">
          <div class="tooltip-media">
            <img id="tooltip-image" alt="Part CAD" />
            <div id="tooltip-no-image">No photo</div>
          </div>
          <div class="tooltip-title-block">
            <strong id="tooltip-number"></strong>
            <span id="tooltip-name"></span>
          </div>
        </div>
        <div class="tooltip-details">
          <small id="tooltip-meta"></small>
        </div>
      </div>
      <!-- Assembly Drop Modal -->
      <div id="assembly-drop-modal" class="canvas-modal" hidden>
        <div class="modal-card">
          <h4>Place assembly</h4>
          <p id="assembly-drop-desc"></p>
          <div id="assembly-children-container" style="display:flex; flex-direction:column; gap:6px; margin-bottom:8px;">
            <span style="display:block; font-size:.78rem; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--st-secondary-text-color);">Sub-components:</span>
            <div id="assembly-children-list" class="assembly-children-box"></div>
          </div>
          <div class="modal-form">
            <div style="margin-bottom:8px; padding:10px 12px; background:var(--st-secondary-background-color, #f8fafc); border:1px solid var(--st-border-color, #e2e8f0); border-radius:8px;">
              <span style="display:block; font-size:.82rem; font-weight:600; color:var(--st-text-color); margin-bottom:6px;">Placement mode:</span>
              <label style="display:flex; align-items:center; gap:8px; font-size:.84rem; cursor:pointer; margin-bottom:6px;">
                <input type="radio" name="assembly-mode" id="assembly-mode-both" value="both" checked />
                <span><strong>Place assembly & bring in child parts</strong></span>
              </label>
              <label style="display:flex; align-items:center; gap:8px; font-size:.84rem; cursor:pointer;">
                <input type="radio" name="assembly-mode" id="assembly-mode-group-only" value="group_only" />
                <span><strong>Bring in group part only</strong> (keep children in parts palette)</span>
              </label>
            </div>
            <div id="assembly-built-group">
              <label class="modal-label">
                Where is this assembly built?
                <select id="assembly-built-select" class="modal-select"></select>
              </label>
            </div>
            <label class="modal-label">
              <span id="assembly-installed-label">Where is this assembly installed?</span>
              <select id="assembly-installed-select" class="modal-select"></select>
            </label>
          </div>
          <div class="modal-buttons">
            <button id="btn-assembly-confirm" type="button" class="btn-modal btn-primary">Confirm Placement</button>
            <button id="btn-assembly-cancel" type="button" class="btn-modal btn-cancel">Cancel</button>
          </div>
        </div>
      </div>
      <!-- Add Section Modal -->
      <div id="add-section-modal" class="canvas-modal" hidden>
        <div class="modal-card">
          <h4>Add Assembly Section</h4>
          <p>Create a new section block directly on the interactive canvas.</p>
          <div class="modal-form">
            <label class="modal-label">
              Section name
              <input type="text" id="add-section-name" placeholder="e.g. Door Subassembly, Freezer Op 1" style="box-sizing:border-box; width:100%; padding:8px 10px; border:1px solid var(--st-border-color); border-radius:6px; background:var(--st-background-color); color:var(--st-text-color); font-size:.88rem; font-family:inherit;" />
            </label>
            <label class="modal-label">
              Section category
              <select id="add-section-type" class="modal-select">
                <option value="Subassembly" selected>Assembly Section</option>
                <option value="Support Operations">Support Operations / Fabrication</option>
              </select>
            </label>
            <label class="modal-label" id="add-section-parent-label">
              <span id="add-section-parent-title">Feeds into (Downstream assembly / line)</span>
              <select id="add-section-parent" class="modal-select"></select>
            </label>
          </div>
          <div class="modal-buttons">
            <button id="btn-add-section-confirm" type="button" class="btn-modal btn-primary">Create Section</button>
            <button id="btn-add-section-cancel" type="button" class="btn-modal btn-cancel">Cancel</button>
          </div>
        </div>
      </div>
      <!-- Connection Edit / Move Modal -->
      <div id="conn-edit-modal" class="canvas-modal" hidden>
        <div class="modal-card">
          <h4>Re-route Connection</h4>
          <p id="conn-edit-desc">Move this connection to a different section, or delete it:</p>
          <div class="modal-form">
            <label class="modal-label">
              <span>Feeds into (Target Section):</span>
              <select id="conn-target-select" class="modal-select"></select>
            </label>
          </div>
          <div class="modal-buttons">
            <button id="btn-conn-move" type="button" class="btn-modal btn-primary">Move Connection</button>
            <button id="btn-conn-delete" type="button" class="btn-modal" style="background:#fee2e2; color:#b91c1c; border-color:#fca5a5;">Delete Connection</button>
            <button id="btn-conn-cancel" type="button" class="btn-modal btn-cancel">Cancel</button>
          </div>
        </div>
      </div>
      <div class="fishbone-hint">Drag blocks to arrange · Drag circle handle (•) to connect · Drag end of arrow or click × to move connector · Drag parts to re-order within section or move between sections · Click stacked cards to cycle variants</div>
    </div>
  </div>
</div>
"""

_CSS = """
:host { color: var(--st-text-color); font-family: var(--st-font); }
.fishbone-shell { box-sizing: border-box; width: 100%; height: 750px; min-height: 750px; display: flex; flex-direction: column; border: 1px solid var(--st-border-color); border-radius: var(--st-base-radius); overflow: hidden; background: var(--st-background-color); }
.fishbone-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; border-bottom: 1px solid var(--st-border-color); background: var(--st-secondary-background-color); flex-shrink: 0; }
.fishbone-title { min-width: 0; display: flex; align-items: baseline; gap: 10px; }
.fishbone-title span { color: var(--st-secondary-text-color); font-size: .84rem; white-space: nowrap; }
.fishbone-actions { display: flex; gap: 6px; align-items: center; }
.fishbone-actions button { min-width: 32px; height: 32px; padding: 0 10px; border: 1px solid var(--st-border-color); border-radius: var(--st-button-radius); color: var(--st-text-color); background: var(--st-background-color); cursor: pointer; font: inherit; font-size: .84rem; font-weight: 600; }
.fishbone-actions button:hover { border-color: var(--st-primary-color); color: var(--st-primary-color); }
.fishbone-actions button.btn-tool { background: var(--st-secondary-background-color); }

.fishbone-body { display: flex; flex: 1 1 auto; min-height: 0; position: relative; overflow: hidden; }

/* Palette styling */
.fishbone-palette { width: 280px; min-width: 280px; max-width: 340px; display: flex; flex-direction: column; border-right: 1px solid var(--st-border-color); background: var(--st-secondary-background-color); flex-shrink: 0; transition: width .2s ease, margin .2s ease; overflow: hidden; }
.fishbone-palette.collapsed { width: 0; min-width: 0; border-right: none; display: none; }
.palette-header { display: flex; justify-content: space-between; align-items: baseline; padding: 10px 12px 6px; font-size: .88rem; }
.palette-header span { font-size: .78rem; color: var(--st-secondary-text-color); }
.palette-search-box { padding: 0 12px 6px; }
.palette-search-box input { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid var(--st-border-color); border-radius: 6px; background: var(--st-background-color); color: var(--st-text-color); font-size: .82rem; }
.palette-filter-row { padding: 0 12px 8px; font-size: .78rem; color: var(--st-secondary-text-color); display: flex; align-items: center; gap: 6px; }
.palette-list { flex: 1 1 auto; overflow-y: auto; padding: 4px 12px 12px; display: flex; flex-direction: column; gap: 6px; }
.palette-card { display: flex; gap: 8px; align-items: center; padding: 6px 8px; border: 1px solid var(--st-border-color); border-radius: 8px; background: var(--st-background-color); cursor: grab; user-select: none; transition: border-color .15s ease, box-shadow .15s ease; }
.palette-card:hover { border-color: var(--st-primary-color); box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
.palette-card.placed { opacity: 0.65; border-style: dashed; }
.palette-thumb { width: 38px; height: 38px; border-radius: 4px; object-fit: contain; background: var(--st-secondary-background-color); flex-shrink: 0; }
.palette-no-thumb { width: 38px; height: 38px; border-radius: 4px; background: var(--st-secondary-background-color); display: grid; place-items: center; font-size: .65rem; color: var(--st-secondary-text-color); flex-shrink: 0; }
.palette-info { min-width: 0; display: flex; flex-direction: column; gap: 2px; flex: 1; }
.palette-pn { font-weight: 700; font-size: .82rem; color: var(--st-primary-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.palette-desc { font-size: .74rem; color: var(--st-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.1; }
.palette-meta { font-size: .7rem; color: var(--st-secondary-text-color); display: flex; gap: 6px; align-items: center; }
.palette-badge { padding: 1px 5px; border-radius: 4px; font-size: .65rem; font-weight: 700; background: #6366f1; color: white; }

/* Viewport styling */
.fishbone-viewport { position: relative; flex: 1 1 auto; min-height: 0; overflow: hidden; background-color: var(--st-background-color); background-image: radial-gradient(circle, color-mix(in srgb, var(--st-text-color) 13%, transparent) 1px, transparent 1px); background-size: 20px 20px; touch-action: none; }
#fishbone-svg { display: block; width: 100%; height: 100%; cursor: grab; user-select: none; }
#fishbone-svg.dragging { cursor: grabbing; }

/* Section node styling */
.section-node { cursor: grab; }
.section-node.dragging { cursor: grabbing; opacity: 0.85; }
.section-node-rect { transition: stroke-width .15s ease, filter .15s ease; }
.section-node:hover .section-node-rect { filter: drop-shadow(0 4px 12px rgba(0, 0, 0, .18)); }
.section-drop-hover .section-node-rect { stroke: #10b981 !important; stroke-width: 4px !important; stroke-dasharray: 6 4; }

/* Connection port handle */
.port-handle { cursor: crosshair; fill: #3b82f6; stroke: white; stroke-width: 2; opacity: 0.88; transition: r .12s ease, opacity .12s ease; }
.port-handle:hover { r: 10; opacity: 1; fill: #1d4ed8; }

/* Connection line */
.conn-line { cursor: pointer; fill: none !important; stroke-linecap: round; transition: stroke .15s ease, stroke-width .15s ease; pointer-events: stroke; }
.conn-line:hover { stroke-width: 5 !important; filter: drop-shadow(0 0 5px rgba(37,99,235,0.4)); }
.conn-line.selected { stroke: #ef4444 !important; stroke-width: 5 !important; }
.conn-hit-area { cursor: pointer; stroke: transparent !important; fill: none !important; stroke-width: 22px; pointer-events: stroke; }
.conn-delete-btn { cursor: pointer; opacity: 0.92; transition: opacity .12s ease; }
.conn-delete-btn:hover { opacity: 1; }

/* Section delete button styling - keep stationary without scale transform to prevent jitter */
.section-remove-btn { cursor: pointer; opacity: 0; pointer-events: none; transition: opacity .12s ease; }
.section-node:hover .section-remove-btn,
.section-node.selected .section-remove-btn { opacity: 0.88; pointer-events: auto; }
.section-remove-btn:hover { opacity: 1 !important; }
.section-remove-btn circle.sec-del-circle { transition: fill .12s ease; }
.section-remove-btn:hover circle.sec-del-circle { fill: #dc2626; }

/* Part card styling */
.part-card { cursor: grab; user-select: none; }
.part-card > rect { transition: stroke-width .12s ease, filter .12s ease; }
.part-card:hover > rect { stroke-width: 2.5; stroke: var(--st-primary-color); filter: drop-shadow(0 3px 6px rgba(0, 0, 0, .2)); }
.part-cluster { user-select: none; }
.cascade-badge { cursor: pointer; }
.cascade-badge rect { transition: fill .12s ease; }
.cascade-badge:hover rect { fill: #3730a3; }
.part-remove-btn { cursor: pointer; opacity: 0; transition: opacity .12s ease; }
.part-card:hover .part-remove-btn { opacity: 0.95; }
.part-remove-btn:hover { opacity: 1; }
.part-drag-ghost { pointer-events: none; }

.fishbone-hint { position: absolute; right: 12px; bottom: 10px; padding: 5px 8px; border-radius: 6px; color: var(--st-secondary-text-color); background: color-mix(in srgb, var(--st-background-color) 88%, transparent); font-size: .75rem; pointer-events: none; }
.fishbone-tooltip { position: absolute; z-index: 20; width: 360px; max-width: 90vw; box-sizing: border-box; display: flex; flex-direction: column; gap: 8px; padding: 12px; border: 1px solid var(--st-primary-color); border-radius: 10px; background: var(--st-background-color); box-shadow: 0 12px 32px rgba(0, 0, 0, .24); pointer-events: none; }
.fishbone-tooltip[hidden] { display: none !important; }
.tooltip-header { display: flex; align-items: center; gap: 12px; min-width: 0; }
.tooltip-media { width: 92px; min-width: 92px; height: 80px; border-radius: 8px; background: var(--st-secondary-background-color); overflow: hidden; display: flex; align-items: center; justify-content: center; border: 1px solid var(--st-border-color); flex-shrink: 0; }
.tooltip-media img { width: 100%; height: 100%; object-fit: contain; }
.tooltip-media img[hidden] { display: none !important; }
#tooltip-no-image { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: var(--st-secondary-text-color); font-size: .78rem; text-align: center; padding: 4px; }
#tooltip-no-image[hidden] { display: none !important; }
.tooltip-title-block { min-width: 0; flex: 1 1 auto; display: flex; flex-direction: column; gap: 4px; }
.tooltip-title-block strong { font-size: .92rem; color: var(--st-primary-color); overflow-wrap: anywhere; line-height: 1.25; }
.tooltip-title-block span { font-size: .84rem; color: var(--st-text-color); line-height: 1.3; overflow-wrap: anywhere; }
.tooltip-details { border-top: 1px solid var(--st-border-color); padding-top: 6px; display: flex; flex-direction: column; }
.tooltip-details small { color: var(--st-text-color); font-size: .8rem; line-height: 1.45; white-space: pre-line; word-break: break-word; }

/* Modals */
.canvas-modal { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.45); backdrop-filter: blur(2px); display: flex; align-items: center; justify-content: center; z-index: 50; }
.canvas-modal[hidden] { display: none; }
.modal-card { background: var(--st-background-color); border: 1px solid var(--st-border-color); border-radius: 12px; padding: 22px; max-width: 480px; width: 90%; max-height: 90vh; overflow-y: auto; box-shadow: 0 16px 36px rgba(0,0,0,0.3); display: flex; flex-direction: column; gap: 12px; }
.modal-card h4 { margin: 0; font-size: 1.15rem; color: var(--st-text-color); }
.modal-card p { margin: 0; font-size: .88rem; color: var(--st-secondary-text-color); line-height: 1.4; }
.assembly-children-box { max-height: 140px; overflow-y: auto; background: var(--st-secondary-background-color, #f8fafc); border: 1px solid var(--st-border-color, #e2e8f0); border-radius: 8px; padding: 8px 12px; display: flex; flex-direction: column; gap: 5px; }
.assembly-child-item { display: flex; align-items: center; gap: 8px; font-size: .83rem; line-height: 1.3; }
.assembly-child-num { font-weight: 600; color: var(--st-primary-color); font-family: monospace; white-space: nowrap; }
.assembly-child-name { color: var(--st-text-color); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assembly-child-qty { color: var(--st-secondary-text-color); font-size: .78rem; font-weight: 500; white-space: nowrap; }
.modal-form { display: flex; flex-direction: column; gap: 10px; }
.modal-label { font-size: .84rem; font-weight: 600; display: flex; flex-direction: column; gap: 4px; }
.modal-select { padding: 8px 10px; border: 1px solid var(--st-border-color); border-radius: 6px; background: var(--st-background-color); color: var(--st-text-color); font-size: .88rem; }
.modal-buttons { display: flex; flex-direction: column; gap: 8px; margin-top: 6px; }
.btn-modal { padding: 9px 14px; border: 1px solid var(--st-border-color); border-radius: 6px; font-weight: 600; font-size: .86rem; cursor: pointer; text-align: center; }
.btn-primary { background: var(--st-primary-color); color: white; border-color: var(--st-primary-color); }
.btn-cancel { background: transparent; color: var(--st-secondary-text-color); }
.conn-arrow-handle { cursor: grab; opacity: 0.88; transition: r .12s ease, fill .12s ease, opacity .12s ease; filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.3)); }
.conn-arrow-handle:hover { r: 10px !important; opacity: 1 !important; fill: #1d4ed8 !important; }
.conn-arrow-handle:active { cursor: grabbing; }
.buffer-badge rect { fill: #1e293b; stroke: #94a3b8; stroke-width: 1.5; rx: 6px; }
.buffer-badge text { fill: #f8fafc; font-size: 10px; font-weight: 700; user-select: none; }

.fishbone-shell:fullscreen { width: 100vw; height: 100vh; min-height: 0; border: 0; border-radius: 0; }
.fishbone-shell:fullscreen .fishbone-viewport { min-height: 0; }
"""

_JS = """
const SVG_NS = "http://www.w3.org/2000/svg"
const instanceState = new WeakMap()

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name)
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)))
  return element
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value))
}

function snap(val, step = 20) {
  return Math.round(val / step) * step
}

export default function renderFishbone(component) {
  const { data, parentElement } = component
  const shell = parentElement.querySelector(".fishbone-shell")
  const viewport = parentElement.querySelector(".fishbone-viewport")
  const svg = parentElement.querySelector("#fishbone-svg")
  const world = parentElement.querySelector("#fishbone-world")
  const tooltip = parentElement.querySelector("#fishbone-tooltip")
  const tooltipImage = parentElement.querySelector("#tooltip-image")
  const tooltipNoImage = parentElement.querySelector("#tooltip-no-image")
  const tooltipNumber = parentElement.querySelector("#tooltip-number")
  const tooltipName = parentElement.querySelector("#tooltip-name")
  const tooltipMeta = parentElement.querySelector("#tooltip-meta")
  const summary = parentElement.querySelector("#fishbone-summary")

  const palette = parentElement.querySelector("#fishbone-palette")
  const paletteList = parentElement.querySelector("#palette-list")
  const paletteCount = parentElement.querySelector("#palette-count")
  const paletteSearch = parentElement.querySelector("#palette-search")
  const paletteUnplacedOnly = parentElement.querySelector("#palette-unplaced-only")
  const togglePaletteBtn = parentElement.querySelector("#toggle-palette")
  const autoArrangeBtn = parentElement.querySelector("#auto-arrange")

  const assemblyModal = parentElement.querySelector("#assembly-drop-modal")
  const assemblyDropDesc = parentElement.querySelector("#assembly-drop-desc")
  const assemblyModeBoth = parentElement.querySelector("#assembly-mode-both")
  const assemblyModeGroupOnly = parentElement.querySelector("#assembly-mode-group-only")
  const assemblyBuiltGroup = parentElement.querySelector("#assembly-built-group")
  const assemblyBuiltSelect = parentElement.querySelector("#assembly-built-select")
  const assemblyInstalledLabel = parentElement.querySelector("#assembly-installed-label")
  const assemblyInstalledSelect = parentElement.querySelector("#assembly-installed-select")
  const btnAssemblyConfirm = parentElement.querySelector("#btn-assembly-confirm")
  const btnAssemblyCancel = parentElement.querySelector("#btn-assembly-cancel")

  function updateAssemblyModalMode() {
    const isGroupOnly = assemblyModeGroupOnly && assemblyModeGroupOnly.checked
    if (assemblyBuiltGroup) assemblyBuiltGroup.hidden = isGroupOnly
    if (assemblyInstalledLabel) {
      assemblyInstalledLabel.textContent = isGroupOnly ? "Place assembly in section:" : "Where is this assembly installed?"
    }
  }
  if (assemblyModeBoth) assemblyModeBoth.onchange = updateAssemblyModalMode
  if (assemblyModeGroupOnly) assemblyModeGroupOnly.onchange = updateAssemblyModalMode

  const addSectionBtn = parentElement.querySelector("#add-section-btn")
  const addSectionModal = parentElement.querySelector("#add-section-modal")
  const addSectionName = parentElement.querySelector("#add-section-name")
  const addSectionType = parentElement.querySelector("#add-section-type")
  const addSectionParentLabel = parentElement.querySelector("#add-section-parent-label")
  const addSectionParent = parentElement.querySelector("#add-section-parent")
  const btnAddSectionConfirm = parentElement.querySelector("#btn-add-section-confirm")
  const btnAddSectionCancel = parentElement.querySelector("#btn-add-section-cancel")

  const connModal = parentElement.querySelector("#conn-edit-modal")
  const connDesc = parentElement.querySelector("#conn-edit-desc")
  const connTargetSelect = parentElement.querySelector("#conn-target-select")
  const btnConnMove = parentElement.querySelector("#btn-conn-move")
  const btnConnDelete = parentElement.querySelector("#btn-conn-delete")
  const btnConnCancel = parentElement.querySelector("#btn-conn-cancel")

  if (!shell || !viewport || !svg || !world || !data) return

  let state = instanceState.get(parentElement)
  if (!state) {
    state = {
      scale: 1, x: 0, y: 0, dragging: false, pointerX: 0, pointerY: 0, fitted: false, signature: "",
      selectedConnId: null, selectedSectionId: null, pendingConnection: null, reconnectingConnection: null,
      hasUserInteracted: false, observerAttached: false, clusterActiveIndices: new Map()
    }
    instanceState.set(parentElement, state)
  }
  if (!state.clusterActiveIndices) {
    state.clusterActiveIndices = new Map()
  }
  world.replaceChildren()

  const sections = (data.sections || []).map(s => ({ ...s }))
  const connections = (data.connections || []).map(c => ({ ...c }))
  const parts = data.parts || []
  const paletteItems = data.palette_items || []
  const allSections = data.all_sections || sections

  const dataSignature = `${sections.map(s => `${s.id}:${s.grid_x}:${s.grid_y}`).join("|")}::${connections.map(c => `${c.id}:${c.from_section_id}:${c.to_section_id}`).join("|")}::${parts.map(p => `${p.id}:${p.section_id}`).join("|")}::${paletteItems.length}`
  if (state.signature !== dataSignature) {
    state.signature = dataSignature
    state.fitted = false
  }
  summary.textContent = `${sections.length} sections · ${connections.length} connections · ${parts.length} placed parts`

  // Palette toggle
  togglePaletteBtn.onclick = () => {
    palette.classList.toggle("collapsed")
  }

  // Add Section Modal Handling
  if (addSectionBtn && addSectionModal) {
    function updateAddSectionParentVisibility() {
      const isSupport = addSectionType ? addSectionType.value === "Support Operations" : false
      const parentTitle = parentElement.querySelector("#add-section-parent-title")
      if (parentTitle) {
        parentTitle.textContent = isSupport ? "Feeds into (Downstream assembly / line)" : "Feeds into (Parent assembly)"
      }
      if (addSectionParentLabel) {
        addSectionParentLabel.style.display = "flex"
      }
      if (addSectionParent) {
        addSectionParent.replaceChildren()
        const noneOpt = document.createElement("option")
        noneOpt.value = ""
        noneOpt.textContent = isSupport ? "(None - Standalone fabrication)" : "(None - Root assembly / Main spine)"
        addSectionParent.appendChild(noneOpt)
        allSections.forEach(s => {
          const opt = document.createElement("option")
          opt.value = s.id
          opt.textContent = `${s.name}`
          addSectionParent.appendChild(opt)
        })
      }
    }

    addSectionBtn.onclick = () => {
      if (addSectionName) addSectionName.value = ""
      if (addSectionType) addSectionType.value = "Subassembly"
      updateAddSectionParentVisibility()
      addSectionModal.hidden = false
      setTimeout(() => { if (addSectionName) addSectionName.focus() }, 50)
    }

    if (addSectionType) {
      addSectionType.onchange = updateAddSectionParentVisibility
    }

    if (btnAddSectionCancel) {
      btnAddSectionCancel.onclick = () => {
        addSectionModal.hidden = true
      }
    }

    if (btnAddSectionConfirm) {
      btnAddSectionConfirm.onclick = () => {
        const name = (addSectionName ? addSectionName.value : "").trim()
        if (!name) {
          alert("Please enter a section name.")
          return
        }
        const categoryVal = addSectionType ? addSectionType.value : "Subassembly"
        let chosenType = categoryVal
        let parentId = addSectionParent && addSectionParent.value ? addSectionParent.value : null
        if (categoryVal === "Support Operations") {
          chosenType = "Support Operations"
        } else {
          chosenType = parentId ? "Subassembly" : "Main spine"
        }
        addSectionModal.hidden = true

        let nextX = 160
        let nextY = 200
        if (sections.length > 0) {
          const maxX = Math.max(...sections.map(s => s.grid_x || s.sx || 0))
          const maxY = Math.max(...sections.map(s => s.grid_y || s.sy || 0))
          if (chosenType === "Support Operations") {
            if (parentId) {
              const parentSec = sectionById.get(parentId)
              nextX = snap(parentSec ? parentSec.sx - 80 : maxX + 260, 20)
              nextY = snap(parentSec ? parentSec.sy - 220 : -220, 20)
            } else {
              nextX = snap(maxX + 260, 20)
              nextY = -220
            }
          } else if (!parentId) {
            nextX = snap(maxX + 320, 20)
            nextY = 220
          } else {
            nextX = snap(maxX > 200 ? maxX - 100 : 200, 20)
            nextY = snap(maxY + 200, 20)
          }
        }

        component.setTriggerValue("create_section", {
          name: name,
          section_type: chosenType,
          parent_id: parentId,
          grid_x: nextX,
          grid_y: nextY,
        })
      }
    }
  }

  // Connection Re-route / Edit Modal Handling
  function openConnEditModal(rConn) {
    if (!connModal) return
    const fromSec = sectionById.get(rConn.fromId)
    const oldToSec = sectionById.get(rConn.oldToId)
    const fromName = fromSec ? fromSec.name : (rConn.fromName || "section")
    const oldToName = oldToSec ? oldToSec.name : "target"

    if (connDesc) {
      connDesc.textContent = `Flow connection from "${fromName}" to "${oldToName}". Choose a new target section to move it, or delete it:`
    }
    if (connTargetSelect) {
      connTargetSelect.replaceChildren()
      allSections.forEach(s => {
        if (s.id !== rConn.fromId) {
          const opt = document.createElement("option")
          opt.value = s.id
          opt.textContent = s.name
          if (s.id === rConn.oldToId) opt.selected = true
          connTargetSelect.appendChild(opt)
        }
      })
    }

    if (btnConnMove) {
      btnConnMove.onclick = () => {
        const newToId = connTargetSelect ? connTargetSelect.value : ""
        connModal.hidden = true
        if (newToId && newToId !== rConn.oldToId) {
          state.selectedConnId = null
          component.setTriggerValue("move_connection", {
            connection_id: rConn.connId,
            from_section_id: rConn.fromId,
            to_section_id: newToId,
            old_to_section_id: rConn.oldToId,
            connection_type: rConn.connType
          })
        }
      }
    }

    if (btnConnDelete) {
      btnConnDelete.onclick = () => {
        connModal.hidden = true
        state.selectedConnId = null
        component.setTriggerValue("delete_connection", {
          connection_id: rConn.connId
        })
      }
    }

    if (btnConnCancel) {
      btnConnCancel.onclick = () => {
        connModal.hidden = true
      }
    }

    connModal.hidden = false
  }

  if (connModal) {
    connModal.onclick = (e) => {
      if (e.target === connModal) connModal.hidden = true
    }
  }

  // Populate Palette
  function renderPalette() {
    paletteList.replaceChildren()
    const query = (paletteSearch.value || "").toLowerCase().trim()
    const unplacedOnly = paletteUnplacedOnly.checked
    const placedPartIds = new Set(parts.map(p => p.part_id))

    const filtered = paletteItems.filter(item => {
      const isPlaced = placedPartIds.has(item.part_id)
      if (unplacedOnly && isPlaced) return false
      if (!query) return true
      return (
        (item.part_number || "").toLowerCase().includes(query) ||
        (item.description || "").toLowerCase().includes(query)
      )
    })

    paletteCount.textContent = `${filtered.length} of ${paletteItems.length}`

    filtered.forEach(item => {
      const isPlaced = placedPartIds.has(item.part_id)
      const card = document.createElement("div")
      card.className = `palette-card${isPlaced ? " placed" : ""}`
      card.draggable = true
      card.dataset.partId = item.part_id
      card.dataset.partNumber = item.part_number
      card.dataset.isAssembly = String(Boolean(item.is_assembly))

      if (item.image) {
        const thumb = document.createElement("img")
        thumb.className = "palette-thumb"
        thumb.src = item.image
        thumb.alt = item.part_number
        card.appendChild(thumb)
      } else {
        const thumb = document.createElement("div")
        thumb.className = "palette-no-thumb"
        thumb.textContent = item.is_assembly ? "ASM" : "PART"
        card.appendChild(thumb)
      }

      const info = document.createElement("div")
      info.className = "palette-info"

      const pn = document.createElement("div")
      pn.className = "palette-pn"
      pn.textContent = item.part_number
      info.appendChild(pn)

      const desc = document.createElement("div")
      desc.className = "palette-desc"
      desc.textContent = item.description || "—"
      info.appendChild(desc)

      const meta = document.createElement("div")
      meta.className = "palette-meta"
      meta.textContent = `Qty ${item.quantity || 1}`
      if (item.is_assembly) {
        const badge = document.createElement("span")
        badge.className = "palette-badge"
        badge.textContent = `Asm (${item.child_count})`
        meta.appendChild(badge)
      }
      info.appendChild(meta)

      card.appendChild(info)

      card.ondragstart = (e) => {
        e.dataTransfer.setData("application/json", JSON.stringify(item))
        e.dataTransfer.effectAllowed = "copy"
      }

      paletteList.appendChild(card)
    })
  }

  paletteSearch.oninput = renderPalette
  paletteUnplacedOnly.onchange = renderPalette
  renderPalette()

  // Helper for clustering similar parts (same base drawing number, differing suffix)
  function getPartBaseCode(pn) {
    const clean = String(pn || "").trim().toUpperCase()
    const match = clean.match(/^([A-Z0-9]+?)([PG]\\d{2,4}[A-Z]?)$/)
    if (match && match[1].length >= 5) {
      return match[1]
    }
    if (clean.length >= 10) {
      return clean.slice(0, 8)
    }
    return clean
  }

  function clusterSectionParts(secPartsList, secId) {
    const clusters = []
    const map = new Map()
    secPartsList.forEach(p => {
      const pNum = String(p.part_number || "").trim().toUpperCase()
      const base = getPartBaseCode(pNum)
      const clusterKey = `${secId}:${base}`
      if (!map.has(base)) {
        const activeIdx = (state.clusterActiveIndices && state.clusterActiveIndices.get(clusterKey)) || 0
        const cl = {
          baseCode: base,
          clusterKey: clusterKey,
          parts: [],
          activeIdx: activeIdx
        }
        map.set(base, cl)
        clusters.push(cl)
      }
      const cl = map.get(base)
      // Check if this EXACT part (same part_number or same part_id) is already in the cluster
      const existing = cl.parts.find(item => 
        (p.part_id && item.part_id === p.part_id) || 
        (pNum && String(item.part_number || "").trim().toUpperCase() === pNum)
      )
      if (existing) {
        // Same exact part number/name/photo: DO NOT duplicate! Combine quantity and IDs.
        existing.quantity = (Number(existing.quantity) || 1) + (Number(p.quantity) || 1)
        if (!existing.assignment_ids) existing.assignment_ids = [existing.id]
        if (p.id && !existing.assignment_ids.includes(p.id)) existing.assignment_ids.push(p.id)
        if (p.models && p.models !== "All models" && existing.models && !existing.models.includes(p.models)) {
          existing.models = `${existing.models}, ${p.models}`
        }
      } else {
        const copy = Object.assign({}, p, {
          assignment_ids: [p.id]
        })
        cl.parts.push(copy)
      }
    })
    return clusters
  }

  // Map parts by section
  const partsBySection = new Map()
  parts.forEach((part) => {
    const sid = part.section_id
    if (!partsBySection.has(sid)) partsBySection.set(sid, [])
    partsBySection.get(sid).push(part)
  })

  // Group sections by connection hierarchy
  const sectionById = new Map()
  sections.forEach((sec, idx) => {
    sec.sx = (sec.grid_x !== null && sec.grid_x !== undefined) ? Number(sec.grid_x) : (160 + (idx % 4) * 280)
    sec.sy = (sec.grid_y !== null && sec.grid_y !== undefined) ? Number(sec.grid_y) : (160 + Math.floor(idx / 4) * 220)

    const secParts = partsBySection.get(sec.id) || []
    sec.partClusters = clusterSectionParts(secParts, sec.id)
    const cardW = 68
    const gap = 12
    let rowW = 28
    sec.partClusters.forEach(cl => {
      rowW += (cl.parts.length > 1 ? cardW + 10 : cardW) + gap
    })
    sec.secWidth = Math.max(220, rowW)
    sec.secHeight = secParts.length > 0 ? 146 : 64

    sectionById.set(sec.id, sec)
  })

  // Layers
  const edgeLayer = svgElement("g", { id: "edge-layer" })
  const sectionLayer = svgElement("g", { id: "section-layer" })
  const ghostLayer = svgElement("g", { id: "ghost-layer" })
  world.appendChild(edgeLayer)
  world.appendChild(sectionLayer)
  world.appendChild(ghostLayer)

  // Auto-arrange sections logically
  autoArrangeBtn.onclick = () => {
    state.hasUserInteracted = false
    const supportSections = sections.filter(s => s.type === "Support Operations")
    const assemblySections = sections.filter(s => s.type !== "Support Operations")

    let suppX = 140
    supportSections.forEach((s) => {
      s.autoX = snap(suppX, 20)
      s.autoY = -220
      suppX += s.secWidth + 50
    })

    // Assembly sections layout: identify outgoing connections
    const outgoingMap = new Map()
    connections.forEach(c => {
      if (c.from_section_id && c.to_section_id) {
        outgoingMap.set(c.from_section_id, c.to_section_id)
      }
    })
    const incomingMap = new Map()
    connections.forEach(c => {
      if (c.from_section_id && c.to_section_id) {
        if (!incomingMap.has(c.to_section_id)) incomingMap.set(c.to_section_id, [])
        incomingMap.get(c.to_section_id).push(c.from_section_id)
      }
    })

    // Root sections (no outgoing connection to another section)
    const roots = assemblySections.filter(s => !outgoingMap.has(s.id))
    if (roots.length === 0 && assemblySections.length > 0) roots.push(assemblySections[0])

    const visited = new Set()
    let currentColumnX = 750

    function layoutSubtree(nodeId, colX, startY) {
      if (visited.has(nodeId)) return startY
      visited.add(nodeId)
      const sec = sectionById.get(nodeId)
      if (!sec) return startY

      const feeders = (incomingMap.get(nodeId) || []).filter(fid => !visited.has(fid))
      let childY = startY
      feeders.forEach(fid => {
        childY = layoutSubtree(fid, colX - (sec.secWidth + 80), childY)
      })

      sec.autoX = snap(colX, 20)
      sec.autoY = snap(feeders.length > 0 ? (startY + childY - 200) / 2 : startY, 20)
      return Math.max(childY, startY + sec.secHeight + 60)
    }

    let rootY = 160
    roots.forEach(r => {
      rootY = layoutSubtree(r.id, currentColumnX, rootY) + 60
    })

    // Any remaining assembly sections
    assemblySections.forEach(s => {
      if (!visited.has(s.id)) {
        s.autoX = snap(currentColumnX - 350, 20)
        s.autoY = snap(rootY, 20)
        rootY += s.secHeight + 60
      }
    })

    const positions = {}
    sections.forEach(s => {
      positions[s.id] = [s.autoX !== undefined ? s.autoX : s.sx, s.autoY !== undefined ? s.autoY : s.sy]
    })
    component.setTriggerValue("auto_arrange", { positions })
  }

  // Draw Connections (Smooth Parent / Child Flow Arrows)
  connections.forEach((conn) => {
    const start = sectionById.get(conn.from_section_id)
    const end = sectionById.get(conn.to_section_id)
    if (!start || !end) return

    const isFromSupport = start.type === "Support Operations"
    const isSelected = state.selectedConnId === conn.id

    // Start from right handle of start section
    const p1x = start.sx + start.secWidth / 2
    const p1y = start.sy - start.secHeight / 2 + 21
    // End at left border of target section
    const p2x = end.sx - end.secWidth / 2
    const p2y = end.sy - end.secHeight / 2 + 21

    const cdx = Math.max(40, Math.abs(p2x - p1x) * 0.45)
    const pathData = `M ${p1x} ${p1y} C ${p1x + cdx} ${p1y}, ${p2x - cdx} ${p2y}, ${p2x} ${p2y}`

    let marker = "url(#arrow-flow)"
    let color = "#2563eb"
    if (isSelected) {
      marker = "url(#arrow-selected)"
      color = "#ef4444"
    } else if (isFromSupport) {
      marker = "url(#arrow-buffer)"
      color = "#64748b"
    }

    const path = svgElement("path", {
      d: pathData,
      fill: "none",
      stroke: color,
      "stroke-width": isSelected ? 4.5 : 3,
      "stroke-linecap": "round",
      "marker-end": marker,
      class: `conn-line${isSelected ? " selected" : ""}`
    })
    if (isFromSupport) {
      path.setAttribute("stroke-dasharray", "6 4")
    }

    const hitArea = svgElement("path", {
      d: pathData,
      fill: "none",
      stroke: "transparent",
      "stroke-width": 22,
      class: "conn-hit-area"
    })

    const midX = (p1x + p2x) / 2
    const midY = (p1y + p2y) / 2

    hitArea.onclick = (e) => {
      e.stopPropagation()
      state.selectedConnId = isSelected ? null : conn.id
      renderWorld()
    }

    edgeLayer.appendChild(path)
    edgeLayer.appendChild(hitArea)

    // Storage Buffer badge for Support Operations
    if (isFromSupport && !isSelected) {
      const bufGroup = svgElement("g", {
        transform: `translate(${midX} ${midY})`,
        class: "buffer-badge",
        title: "Fabrication buffer / storage supermarket"
      })
      bufGroup.appendChild(svgElement("rect", {
        x: -56, y: -12, width: 112, height: 24, rx: 6
      }))
      const bufTxt = svgElement("text", {
        x: 0, y: 4, "text-anchor": "middle"
      })
      bufTxt.textContent = "📦 Buffer / Storage"
      bufGroup.appendChild(bufTxt)
      edgeLayer.appendChild(bufGroup)
    }

    // Arrow-end handle for dragging to a different section or clicking to re-route
    const endHandle = svgElement("circle", {
      cx: p2x,
      cy: p2y,
      r: isSelected ? 8.5 : 6.5,
      fill: isSelected ? "#ef4444" : (isFromSupport ? "#64748b" : "#2563eb"),
      stroke: "white",
      "stroke-width": 2,
      class: "conn-arrow-handle",
      title: "Drag end of arrow to connect to a different section, or click to re-route"
    })
    endHandle.onmousedown = (e) => {
      e.stopPropagation()
      state.reconnectingConnection = {
        connId: conn.id,
        fromId: start.id,
        fromName: start.name,
        oldToId: end.id,
        connType: conn.connection_type || "subassembly",
        startX: p1x,
        startY: p1y,
        isDrag: false,
        originX: e.clientX,
        originY: e.clientY,
        isFromDelGroup: false
      }
    }
    edgeLayer.appendChild(endHandle)

    // Selected Connection Action Button (Red X)
    if (isSelected) {
      const delGroup = svgElement("g", {
        transform: `translate(${midX} ${midY})`,
        class: "conn-delete-btn",
        title: "Click to move or delete connection, or drag to reconnect"
      })
      delGroup.appendChild(svgElement("circle", { cx: 0, cy: 0, r: 12, fill: "#ef4444", stroke: "white", "stroke-width": 2 }))
      const delText = svgElement("text", {
        x: 0, y: 4, "text-anchor": "middle", fill: "white", "font-size": 13, "font-weight": 700
      })
      delText.textContent = "×"
      delGroup.appendChild(delText)

      delGroup.onmousedown = (e) => {
        e.stopPropagation()
        state.reconnectingConnection = {
          connId: conn.id,
          fromId: start.id,
          fromName: start.name,
          oldToId: end.id,
          connType: conn.connection_type || "subassembly",
          startX: p1x,
          startY: p1y,
          isDrag: false,
          originX: e.clientX,
          originY: e.clientY,
          isFromDelGroup: true
        }
      }
      edgeLayer.appendChild(delGroup)
    }
  })

  // Draw Simple Section Blocks
  if (sections.length === 0) {
    const emptyGroup = svgElement("g", { transform: "translate(340 180)" })
    const emptyCard = svgElement("rect", {
      x: -180, y: -50, width: 360, height: 100, rx: 12,
      fill: "var(--st-secondary-background-color)", stroke: "var(--st-border-color)", "stroke-width": 1.5
    })
    emptyGroup.appendChild(emptyCard)
    const emptyTitle = svgElement("text", {
      x: 0, y: -15, "text-anchor": "middle", fill: "var(--st-text-color)", "font-size": 15, "font-weight": 700
    })
    emptyTitle.textContent = "Start Your Fishbone Diagram"
    emptyGroup.appendChild(emptyTitle)
    const emptySub = svgElement("text", {
      x: 0, y: 15, "text-anchor": "middle", fill: "var(--st-secondary-text-color)", "font-size": 12
    })
    emptySub.textContent = "Click '➕ Add Section' in toolbar to create your first section"
    emptyGroup.appendChild(emptySub)
    world.appendChild(emptyGroup)
  }

  sections.forEach((section) => {
    const isSupport = section.type === "Support Operations"
    const secParts = partsBySection.get(section.id) || []
    const secWidth = section.secWidth
    const secHeight = section.secHeight
    const isSelected = state.selectedSectionId === section.id

    const group = svgElement("g", {
      class: `section-node${isSelected ? " selected" : ""}`,
      transform: `translate(${section.sx} ${section.sy})`,
      "data-section-id": section.id
    })

    // Card background
    const bgRect = svgElement("rect", {
      x: -secWidth / 2, y: -secHeight / 2, width: secWidth, height: secHeight, rx: 10,
      fill: isSupport ? "#1e293b" : "var(--st-secondary-background-color)",
      stroke: isSelected ? "#3b82f6" : (isSupport ? "#475569" : "var(--st-border-color)"),
      "stroke-width": isSelected ? 3.5 : 2,
      class: "section-node-rect"
    })
    if (isSelected) {
      bgRect.setAttribute("filter", "drop-shadow(0 0 8px rgba(59,130,246,0.6))")
    }
    group.appendChild(bgRect)

    // Header strip
    const headerBg = svgElement("rect", {
      x: -secWidth / 2, y: -secHeight / 2, width: secWidth, height: 42, rx: 10,
      fill: isSupport ? "#334155" : "#1e40af"
    })
    group.appendChild(headerBg)

    // Section title
    const label = svgElement("text", {
      x: -secWidth / 2 + 12, y: -secHeight / 2 + 18,
      fill: "white", "font-size": 13, "font-weight": 700
    })
    label.textContent = section.name
    group.appendChild(label)

    // Subtitle / parts count
    const count = svgElement("text", {
      x: -secWidth / 2 + 12, y: -secHeight / 2 + 33,
      fill: "rgba(255, 255, 255, 0.85)", "font-size": 10
    })
    if (isSupport) {
      let targetName = ""
      if (section.parent_id) {
        const pSec = sectionById.get(section.parent_id)
        if (pSec) targetName = pSec.name
      }
      if (!targetName) {
        const outConn = connections.find(c => c.from_section_id === section.id)
        if (outConn) {
          const tSec = sectionById.get(outConn.to_section_id)
          if (tSec) targetName = tSec.name
        }
      }
      if (targetName) {
        count.textContent = `🏭 Built here ➔ Feeds ${targetName} · ${secParts.length} parts`
      } else {
        count.textContent = `🏭 Fabrication / Support Ops · ${secParts.length} parts`
      }
    } else {
      count.textContent = `${secParts.length} part${secParts.length === 1 ? "" : "s"} assigned`
    }
    group.appendChild(count)

    // Connection Port Handle (on right border of header)
    const port = svgElement("circle", {
      cx: secWidth / 2, cy: -secHeight / 2 + 21, r: 8, class: "port-handle",
      title: "Drag to connect this section to another section"
    })
    port.onmousedown = (e) => {
      e.stopPropagation()
      state.pendingConnection = {
        fromId: section.id,
        fromName: section.name,
        startX: section.sx + secWidth / 2,
        startY: section.sy - secHeight / 2 + 21
      }
    }
    group.appendChild(port)

    // Section Delete Button (red × on hover or click)
    const secDelBtn = svgElement("g", {
      class: "section-remove-btn",
      transform: `translate(${secWidth / 2 - 16} ${-secHeight / 2 + 16})`,
      title: `Delete section "${section.name}"`
    })
    // Transparent expanded hit area for smooth steady interaction
    secDelBtn.appendChild(svgElement("circle", { cx: 0, cy: 0, r: 14, fill: "transparent" }))
    // Visible red circle badge
    secDelBtn.appendChild(svgElement("circle", { cx: 0, cy: 0, r: 9, fill: "#ef4444", class: "sec-del-circle" }))
    const secDelTxt = svgElement("text", {
      x: 0, y: 3.5, "text-anchor": "middle", fill: "white", "font-size": 12, "font-weight": 700,
      "pointer-events": "none"
    })
    secDelTxt.textContent = "×"
    secDelBtn.appendChild(secDelTxt)
    secDelBtn.onmousedown = (e) => {
      e.stopPropagation()
    }
    secDelBtn.onclick = (e) => {
      e.stopPropagation()
      component.setTriggerValue("delete_section_request", {
        section_id: section.id,
        section_name: section.name
      })
    }
    group.appendChild(secDelBtn)

    // Parts Tray inside the block
    if (secParts.length === 0) {
      const placeholder = svgElement("text", {
        x: 0, y: -secHeight / 2 + 54, "text-anchor": "middle",
        fill: "var(--st-secondary-text-color)", "font-size": 10.5, "font-style": "italic"
      })
      placeholder.textContent = "Drop parts here from palette"
      group.appendChild(placeholder)
    } else {
      const cardW = 68
      const cardH = 78
      const gap = 12
      let curX = -secWidth / 2 + 14

      section.partClusters.forEach((cluster) => {
        const hasMultiple = cluster.parts.length > 1
        const activeIdx = cluster.activeIdx % cluster.parts.length
        const activePart = cluster.parts[activeIdx]
        const cardX = curX
        const cardY = -secHeight / 2 + 48
        const clusterW = hasMultiple ? cardW + 10 : cardW
        cluster.cardX = cardX
        cluster.cardY = cardY
        cluster.cardW = clusterW
        cluster.cardH = cardH
        cluster.midX = cardX + clusterW / 2

        const clusterGroup = svgElement("g", {
          class: `part-cluster${hasMultiple ? " cascaded" : ""}`,
          "data-base-code": cluster.baseCode
        })

        // Cascading background cards if multiple variants share base code
        if (hasMultiple) {
          if (cluster.parts.length >= 3) {
            clusterGroup.appendChild(svgElement("rect", {
              x: cardX + 8, y: cardY - 6, width: cardW, height: cardH, rx: 6,
              fill: "var(--st-secondary-background-color)",
              stroke: "#818cf8", "stroke-width": 1.5, opacity: 0.55
            }))
          }
          if (cluster.parts.length >= 2) {
            clusterGroup.appendChild(svgElement("rect", {
              x: cardX + 4, y: cardY - 3, width: cardW, height: cardH, rx: 6,
              fill: "var(--st-secondary-background-color)",
              stroke: "#6366f1", "stroke-width": 1.5, opacity: 0.8
            }))
          }
        }

        // Active front card
        const card = svgElement("g", {
          class: "part-card",
          "data-part-id": activePart.part_id,
          "data-assignment-id": activePart.id,
          style: "cursor: grab;"
        })

        const cardRect = svgElement("rect", {
          x: cardX, y: cardY, width: cardW, height: cardH, rx: 6,
          fill: "var(--st-background-color)",
          stroke: hasMultiple ? "#4f46e5" : "var(--st-border-color)",
          "stroke-width": hasMultiple ? 2 : 1.5
        })
        card.appendChild(cardRect)

        if (activePart.image) {
          const img = svgElement("image", {
            href: activePart.image,
            x: cardX + 4, y: cardY + 4,
            width: cardW - 8, height: 48,
            preserveAspectRatio: "xMidYMid meet"
          })
          card.appendChild(img)
        } else {
          const noImg = svgElement("text", {
            x: cardX + cardW / 2, y: cardY + 28, "text-anchor": "middle",
            fill: "var(--st-secondary-text-color)", "font-size": 9
          })
          noImg.textContent = "No photo"
          card.appendChild(noImg)
        }

        const pnText = svgElement("text", {
          x: cardX + cardW / 2, y: cardY + 66, "text-anchor": "middle",
          fill: "var(--st-text-color)", "font-size": 8.8, "font-weight": 700
        })
        const pnStr = activePart.part_number || ""
        pnText.textContent = pnStr.length > 10 ? `${pnStr.slice(0, 9)}…` : pnStr
        card.appendChild(pnText)

        // Variant badge and suffix counter for cascaded clusters
        if (hasMultiple) {
          const badgeG = svgElement("g", {
            class: "cascade-badge",
            title: `Click card to cycle ${cluster.parts.length} variants`
          })
          badgeG.appendChild(svgElement("rect", {
            x: cardX + 2, y: cardY - 7, width: 32, height: 14, rx: 4,
            fill: "#4f46e5", stroke: "white", "stroke-width": 1
          }))
          const badgeTxt = svgElement("text", {
            x: cardX + 18, y: cardY + 3.5, "text-anchor": "middle",
            fill: "white", "font-size": 8.5, "font-weight": 700
          })
          badgeTxt.textContent = `${cluster.parts.length}×`
          badgeG.appendChild(badgeTxt)
          card.appendChild(badgeG)

          // Suffix indicator at bottom
          const sufTxt = svgElement("text", {
            x: cardX + cardW / 2, y: cardY + 76, "text-anchor": "middle",
            fill: "#6366f1", "font-size": 7.5, "font-weight": 600
          })
          const suf = pnStr.length >= 8 ? pnStr.slice(8) : pnStr
          sufTxt.textContent = `[${activeIdx + 1}/${cluster.parts.length}] ${suf}`
          card.appendChild(sufTxt)
        }

        // Remove (x) Button
        const removeBtn = svgElement("g", {
          class: "part-remove-btn",
          title: `Remove ${activePart.part_number} from section`,
          style: "cursor: pointer;"
        })
        removeBtn.appendChild(svgElement("circle", {
          cx: cardX + cardW - 6, cy: cardY + 6, r: 7.5,
          fill: "#ef4444", stroke: "white", "stroke-width": 1.5
        }))
        const rmTxt = svgElement("text", {
          x: cardX + cardW - 6, y: cardY + 9, "text-anchor": "middle",
          fill: "white", "font-size": 10, "font-weight": 700
        })
        rmTxt.textContent = "×"
        removeBtn.appendChild(rmTxt)
        removeBtn.onclick = (e) => {
          e.stopPropagation()
          component.setTriggerValue("remove_part", {
            assignment_id: activePart.id,
            assignment_ids: activePart.assignment_ids || [activePart.id],
            part_id: activePart.part_id,
            section_id: section.id
          })
        }
        card.appendChild(removeBtn)

        // Mouse Drag to re-order within section or move to another section & Click to cycle variants
        card.onmousedown = (e) => {
          if (e.target.closest(".part-remove-btn")) return
          e.stopPropagation()
          const startMouseX = e.clientX
          const startMouseY = e.clientY
          let isDragging = false
          let ghostEl = null

          const onMouseMove = (moveEvt) => {
            const dist = Math.hypot(moveEvt.clientX - startMouseX, moveEvt.clientY - startMouseY)
            if (dist > 4 && !isDragging) {
              isDragging = true
              tooltip.hidden = true
              ghostEl = document.createElement("div")
              ghostEl.className = "part-drag-ghost"
              ghostEl.style.position = "fixed"
              ghostEl.style.zIndex = "9999"
              ghostEl.style.pointerEvents = "none"
              ghostEl.style.padding = "6px 10px"
              ghostEl.style.background = "#1e293b"
              ghostEl.style.color = "white"
              ghostEl.style.border = "2px solid #3b82f6"
              ghostEl.style.borderRadius = "8px"
              ghostEl.style.fontSize = "12px"
              ghostEl.style.fontWeight = "700"
              ghostEl.style.boxShadow = "0 8px 24px rgba(0,0,0,0.3)"
              ghostEl.textContent = `📦 ${activePart.part_number} (${activePart.quantity || 1})`
              document.body.appendChild(ghostEl)
            }
            if (isDragging && ghostEl) {
              ghostEl.style.left = `${moveEvt.clientX + 12}px`
              ghostEl.style.top = `${moveEvt.clientY + 12}px`

              const rect = svg.getBoundingClientRect()
              const currX = (moveEvt.clientX - rect.left - state.x) / state.scale
              const currY = (moveEvt.clientY - rect.top - state.y) / state.scale

              document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))
              const oldIndicator = ghostLayer.querySelector(".part-insert-indicator")
              if (oldIndicator) oldIndicator.remove()

              const hoveredSec = sections.find(s => {
                const w = s.secWidth || 220
                const h = s.secHeight || 64
                return Math.abs(currX - s.sx) < w / 2 && Math.abs(currY - s.sy) < h / 2
              })
              if (hoveredSec) {
                if (hoveredSec.id !== section.id) {
                  const nodeElem = parentElement.querySelector(`[data-section-id="${hoveredSec.id}"]`)
                  if (nodeElem) nodeElem.classList.add("section-drop-hover")
                }

                // Show insertion line between parts if section has clusters
                const clusters = hoveredSec.partClusters || []
                if (clusters.length > 0) {
                  const localX = currX - hoveredSec.sx
                  let insertLocalX = 0
                  const gap = 12

                  if (localX < clusters[0].midX) {
                    insertLocalX = clusters[0].cardX - gap / 2
                  } else if (localX >= clusters[clusters.length - 1].midX) {
                    const lastCl = clusters[clusters.length - 1]
                    insertLocalX = lastCl.cardX + lastCl.cardW + gap / 2
                  } else {
                    for (let i = 0; i < clusters.length - 1; i++) {
                      const clA = clusters[i]
                      const clB = clusters[i + 1]
                      const splitX = (clA.cardX + clA.cardW + clB.cardX) / 2
                      if (localX < splitX) {
                        insertLocalX = splitX
                        break
                      }
                    }
                  }

                  const worldInsertX = hoveredSec.sx + insertLocalX
                  const cardY = -hoveredSec.secHeight / 2 + 48
                  const topY = hoveredSec.sy + cardY - 4
                  const indicatorH = 86

                  const indicatorG = svgElement("g", { class: "part-insert-indicator", "pointer-events": "none" })
                  const bar = svgElement("rect", {
                    x: worldInsertX - 2,
                    y: topY,
                    width: 4,
                    height: indicatorH,
                    rx: 2,
                    fill: "#3b82f6",
                    filter: "drop-shadow(0 0 5px rgba(59, 130, 246, 0.7))"
                  })
                  indicatorG.appendChild(bar)
                  const topDot = svgElement("circle", {
                    cx: worldInsertX,
                    cy: topY,
                    r: 4.5,
                    fill: "#2563eb",
                    stroke: "white",
                    "stroke-width": 1.5
                  })
                  indicatorG.appendChild(topDot)
                  const botDot = svgElement("circle", {
                    cx: worldInsertX,
                    cy: topY + indicatorH,
                    r: 4.5,
                    fill: "#2563eb",
                    stroke: "white",
                    "stroke-width": 1.5
                  })
                  indicatorG.appendChild(botDot)
                  ghostLayer.appendChild(indicatorG)
                }
              }
            }
          }

          const onMouseUp = (upEvt) => {
            window.removeEventListener("mousemove", onMouseMove)
            window.removeEventListener("mouseup", onMouseUp)
            window.removeEventListener("keydown", onKeyDown)
            document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))
            const oldIndicator = ghostLayer.querySelector(".part-insert-indicator")
            if (oldIndicator) oldIndicator.remove()
            if (ghostEl) {
              ghostEl.remove()
              ghostEl = null
            }
            if (isDragging) {
              const rect = svg.getBoundingClientRect()
              const currX = (upEvt.clientX - rect.left - state.x) / state.scale
              const currY = (upEvt.clientY - rect.top - state.y) / state.scale

              const targetSec = sections.find(s => {
                const w = s.secWidth || 220
                const h = s.secHeight || 64
                return Math.abs(currX - s.sx) < w / 2 && Math.abs(currY - s.sy) < h / 2
              })
              if (targetSec) {
                const clusters = targetSec.partClusters || []
                let targetIdx = clusters.length
                const localX = currX - targetSec.sx
                if (clusters.length > 0) {
                  if (localX < clusters[0].midX) {
                    targetIdx = 0
                  } else if (localX >= clusters[clusters.length - 1].midX) {
                    targetIdx = clusters.length
                  } else {
                    for (let i = 0; i < clusters.length - 1; i++) {
                      const clA = clusters[i]
                      const clB = clusters[i + 1]
                      const splitX = (clA.cardX + clA.cardW + clB.cardX) / 2
                      if (localX < splitX) {
                        targetIdx = i + 1
                        break
                      }
                    }
                  }
                }

                if (targetSec.id === section.id) {
                  // Reorder within the same section
                  if (clusters.length > 1) {
                    const sourceIdx = clusters.indexOf(cluster)
                    if (sourceIdx !== -1 && targetIdx !== sourceIdx && targetIdx !== sourceIdx + 1) {
                      const newClusters = [...clusters]
                      const [movedCluster] = newClusters.splice(sourceIdx, 1)
                      const insertAt = targetIdx > sourceIdx ? targetIdx - 1 : targetIdx
                      newClusters.splice(insertAt, 0, movedCluster)

                      const orderedAssignmentIds = []
                      newClusters.forEach(cl => {
                        cl.parts.forEach(p => {
                          if (p.assignment_ids && p.assignment_ids.length > 0) {
                            p.assignment_ids.forEach(aid => {
                              if (!orderedAssignmentIds.includes(aid)) orderedAssignmentIds.push(aid)
                            })
                          } else if (p.id && !orderedAssignmentIds.includes(p.id)) {
                            orderedAssignmentIds.push(p.id)
                          }
                        })
                      })

                      component.setTriggerValue("move_part_assignment", {
                        assignment_id: activePart.id,
                        assignment_ids: activePart.assignment_ids || [activePart.id],
                        part_id: activePart.part_id,
                        from_section_id: section.id,
                        to_section_id: section.id,
                        target_index: insertAt,
                        ordered_assignment_ids: orderedAssignmentIds
                      })
                    }
                  }
                } else {
                  // Move to another section
                  const targetClusters = [...clusters]
                  const insertAt = Math.min(Math.max(0, targetIdx), targetClusters.length)
                  targetClusters.splice(insertAt, 0, cluster)

                  const orderedTargetAssignmentIds = []
                  targetClusters.forEach(cl => {
                    cl.parts.forEach(p => {
                      if (p.assignment_ids && p.assignment_ids.length > 0) {
                        p.assignment_ids.forEach(aid => {
                          if (!orderedTargetAssignmentIds.includes(aid)) orderedTargetAssignmentIds.push(aid)
                        })
                      } else if (p.id && !orderedTargetAssignmentIds.includes(p.id)) {
                        orderedTargetAssignmentIds.push(p.id)
                      }
                    })
                  })

                  component.setTriggerValue("move_part_assignment", {
                    assignment_id: activePart.id,
                    assignment_ids: activePart.assignment_ids || [activePart.id],
                    part_id: activePart.part_id,
                    from_section_id: section.id,
                    to_section_id: targetSec.id,
                    target_index: insertAt,
                    ordered_assignment_ids: orderedTargetAssignmentIds
                  })
                }
              }
            } else {
              // Clicked without dragging: cycle variant if cascaded
              if (hasMultiple) {
                cluster.activeIdx = (activeIdx + 1) % cluster.parts.length
                state.clusterActiveIndices.set(cluster.clusterKey, cluster.activeIdx)
                renderWorld()
              }
            }
          }

          const onKeyDown = (keyEvt) => {
            if (keyEvt.key === "Escape") {
              window.removeEventListener("mousemove", onMouseMove)
              window.removeEventListener("mouseup", onMouseUp)
              window.removeEventListener("keydown", onKeyDown)
              document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))
              const oldIndicator = ghostLayer.querySelector(".part-insert-indicator")
              if (oldIndicator) oldIndicator.remove()
              if (ghostEl) {
                ghostEl.remove()
                ghostEl = null
              }
              isDragging = false
            }
          }

          window.addEventListener("mousemove", onMouseMove)
          window.addEventListener("mouseup", onMouseUp)
          window.addEventListener("keydown", onKeyDown)
        }

        // Hover tooltip
        card.onmouseenter = (e) => {
          if (activePart.image) {
            tooltipImage.src = activePart.image
            tooltipImage.hidden = false
            tooltipImage.style.display = "block"
            tooltipNoImage.hidden = true
            tooltipNoImage.style.display = "none"
          } else {
            tooltipImage.src = ""
            tooltipImage.hidden = true
            tooltipImage.style.display = "none"
            tooltipNoImage.hidden = false
            tooltipNoImage.style.display = "flex"
          }
          if (hasMultiple) {
            tooltipNumber.textContent = `${cluster.baseCode} (${cluster.parts.length} variants)`
            tooltipName.textContent = activePart.description || "Similar Part Family"
            const lines = cluster.parts.map((p, i) => `${i === activeIdx ? "▶ " : "• "}${p.part_number}: ${p.description || ""} (Qty: ${p.quantity})`).join("\\n")
            tooltipMeta.textContent = `${lines}\n\n💡 Click card to cycle active variant · Drag to re-order or move between sections`
          } else {
            tooltipNumber.textContent = activePart.part_number
            tooltipName.textContent = activePart.description || "—"
            tooltipMeta.textContent = `Qty: ${activePart.quantity} · ${activePart.models || "All models"}${activePart.use_description ? ` · ${activePart.use_description}` : ""}\n\n💡 Drag to re-order or move between sections`
          }
          tooltip.hidden = false
          const rect = viewport.getBoundingClientRect()
          const tipWidth = tooltip.offsetWidth || 360
          const tipHeight = tooltip.offsetHeight || 150
          tooltip.style.left = `${clamp(e.clientX - rect.left + 16, 12, Math.max(12, rect.width - tipWidth - 16))}px`
          tooltip.style.top = `${clamp(e.clientY - rect.top + 16, 12, Math.max(12, rect.height - tipHeight - 16))}px`
        }
        card.onmouseleave = () => {
          tooltip.hidden = true
          tooltipImage.src = ""
        }

        clusterGroup.appendChild(card)
        group.appendChild(clusterGroup)

        curX += (hasMultiple ? cardW + 10 : cardW) + gap
      })
    }

    // Section Dragging to move node & Click selection
    group.onclick = (e) => {
      if (e.target.closest(".section-remove-btn")) return
      e.stopPropagation()
      state.selectedSectionId = (state.selectedSectionId === section.id) ? null : section.id
      renderWorld()
    }

    group.onmousedown = (e) => {
      if (e.target === port || e.target.closest(".part-card") || e.target.closest(".section-remove-btn")) return
      e.stopPropagation()
      const startMouseX = e.clientX
      const startMouseY = e.clientY
      const origSx = section.sx
      const origSy = section.sy
      let didMove = false

      const onMouseMove = (moveEvt) => {
        const dx = (moveEvt.clientX - startMouseX) / state.scale
        const dy = (moveEvt.clientY - startMouseY) / state.scale
        if (Math.hypot(dx, dy) > 3) {
          didMove = true
          group.classList.add("dragging")
          section.sx = origSx + dx
          section.sy = origSy + dy
          group.setAttribute("transform", `translate(${section.sx} ${section.sy})`)
        }
      }

      const onMouseUp = () => {
        window.removeEventListener("mousemove", onMouseMove)
        window.removeEventListener("mouseup", onMouseUp)
        group.classList.remove("dragging")
        if (didMove) {
          section.sx = snap(section.sx, 20)
          section.sy = snap(section.sy, 20)
          component.setTriggerValue("move_node", {
            section_id: section.id,
            grid_x: section.sx,
            grid_y: section.sy
          })
        }
      }

      window.addEventListener("mousemove", onMouseMove)
      window.addEventListener("mouseup", onMouseUp)
    }

    sectionLayer.appendChild(group)
  })

  // Connection Dragging & Reconnecting Ghost Lines
  window.onmousemove = (e) => {
    if (state.pendingConnection) {
      ghostLayer.replaceChildren()
      const rect = svg.getBoundingClientRect()
      const currX = (e.clientX - rect.left - state.x) / state.scale
      const currY = (e.clientY - rect.top - state.y) / state.scale
      const ghost = svgElement("line", {
        x1: state.pendingConnection.startX,
        y1: state.pendingConnection.startY,
        x2: currX,
        y2: currY,
        stroke: "#3b82f6",
        "stroke-width": 3,
        "stroke-dasharray": "6 4"
      })
      ghostLayer.appendChild(ghost)
      return
    }

    if (state.reconnectingConnection) {
      const dist = Math.hypot(e.clientX - state.reconnectingConnection.originX, e.clientY - state.reconnectingConnection.originY)
      if (dist > 4) {
        state.reconnectingConnection.isDrag = true
      }
      if (state.reconnectingConnection.isDrag) {
        ghostLayer.replaceChildren()
        const rect = svg.getBoundingClientRect()
        const currX = (e.clientX - rect.left - state.x) / state.scale
        const currY = (e.clientY - rect.top - state.y) / state.scale

        const cdx = Math.max(40, Math.abs(currX - state.reconnectingConnection.startX) * 0.45)
        const ghost = svgElement("path", {
          d: `M ${state.reconnectingConnection.startX} ${state.reconnectingConnection.startY} C ${state.reconnectingConnection.startX + cdx} ${state.reconnectingConnection.startY}, ${currX - cdx} ${currY}, ${currX} ${currY}`,
          fill: "none",
          stroke: "#ef4444",
          "stroke-width": 3.5,
          "stroke-dasharray": "6 4",
          "marker-end": "url(#arrow-selected)"
        })
        ghostLayer.appendChild(ghost)

        const hoverSec = sections.find(s => {
          const w = s.secWidth || 220
          const h = s.secHeight || 64
          return Math.abs(currX - s.sx) < w / 2 + 15 && Math.abs(currY - s.sy) < h / 2 + 15 && s.id !== state.reconnectingConnection.fromId
        })
        if (hoverSec) {
          const w = hoverSec.secWidth || 220
          const h = hoverSec.secHeight || 64
          const ring = svgElement("rect", {
            x: hoverSec.sx - w / 2 - 4,
            y: hoverSec.sy - h / 2 - 4,
            width: w + 8,
            height: h + 8,
            rx: 14,
            fill: "none",
            stroke: hoverSec.id === state.reconnectingConnection.oldToId ? "#94a3b8" : "#22c55e",
            "stroke-width": 3,
            "stroke-dasharray": "6 3"
          })
          ghostLayer.appendChild(ring)
        }
      }
      return
    }
  }

  window.onmouseup = (e) => {
    if (state.pendingConnection) {
      ghostLayer.replaceChildren()
      const fromId = state.pendingConnection.fromId
      state.pendingConnection = null

      const rect = svg.getBoundingClientRect()
      const currX = (e.clientX - rect.left - state.x) / state.scale
      const currY = (e.clientY - rect.top - state.y) / state.scale

      const targetSec = sections.find(s => {
        const w = s.secWidth || 220
        const h = s.secHeight || 64
        return Math.abs(currX - s.sx) < w / 2 + 10 && Math.abs(currY - s.sy) < h / 2 + 10 && s.id !== fromId
      })

      if (targetSec) {
        component.setTriggerValue("create_connection", {
          from_section_id: fromId,
          to_section_id: targetSec.id,
          connection_type: "subassembly"
        })
      }
      return
    }

    if (state.reconnectingConnection) {
      ghostLayer.replaceChildren()
      const rConn = state.reconnectingConnection
      state.reconnectingConnection = null

      if (rConn.isDrag) {
        const rect = svg.getBoundingClientRect()
        const currX = (e.clientX - rect.left - state.x) / state.scale
        const currY = (e.clientY - rect.top - state.y) / state.scale

        const targetSec = sections.find(s => {
          const w = s.secWidth || 220
          const h = s.secHeight || 64
          return Math.abs(currX - s.sx) < w / 2 + 15 && Math.abs(currY - s.sy) < h / 2 + 15 && s.id !== rConn.fromId
        })

        if (targetSec && targetSec.id !== rConn.oldToId) {
          state.selectedConnId = null
          component.setTriggerValue("move_connection", {
            connection_id: rConn.connId,
            from_section_id: rConn.fromId,
            to_section_id: targetSec.id,
            old_to_section_id: rConn.oldToId,
            connection_type: rConn.connType
          })
        }
      } else {
        openConnEditModal(rConn)
      }
    }
  }

  window.onkeydown = (e) => {
    if (e.key === "Escape") {
      if (connModal && !connModal.hidden) connModal.hidden = true
      if (assemblyModal && !assemblyModal.hidden) assemblyModal.hidden = true
      if (addSectionModal && !addSectionModal.hidden) addSectionModal.hidden = true
    }
  }

  // HTML5 Drag and Drop into SVG
  svg.ondragover = (e) => {
    e.preventDefault()
    const rect = svg.getBoundingClientRect()
    const currX = (e.clientX - rect.left - state.x) / state.scale
    const currY = (e.clientY - rect.top - state.y) / state.scale

    document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))

    const targetSec = sections.find(s => {
      const w = s.secWidth || 220
      const h = s.secHeight || 64
      return Math.abs(currX - s.sx) < w / 2 && Math.abs(currY - s.sy) < h / 2
    })
    if (targetSec) {
      const nodeElem = parentElement.querySelector(`[data-section-id="${targetSec.id}"]`)
      if (nodeElem) nodeElem.classList.add("section-drop-hover")
    }
  }

  svg.ondragleave = () => {
    document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))
  }

  svg.ondrop = (e) => {
    e.preventDefault()
    document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))
    const rawData = e.dataTransfer.getData("application/json")
    if (!rawData) return
    const item = JSON.parse(rawData)

    const rect = svg.getBoundingClientRect()
    const currX = (e.clientX - rect.left - state.x) / state.scale
    const currY = (e.clientY - rect.top - state.y) / state.scale

    const targetSec = sections.find(s => {
      const w = s.secWidth || 220
      const h = s.secHeight || 64
      return Math.abs(currX - s.sx) < w / 2 && Math.abs(currY - s.sy) < h / 2
    })
    if (!targetSec) return

    if (item.is_assembly) {
      const isSupport = targetSec.type === "Support Operations"
      const asmName = item.description ? ` — ${item.description}` : ""
      const count = item.child_count || (item.child_parts ? item.child_parts.length : 0)
      assemblyDropDesc.textContent = isSupport
        ? `Assembly ${item.part_number}${asmName} (${count} subcomponents). Formed/built in ${targetSec.name}. Choose placement mode:`
        : `Assembly ${item.part_number}${asmName} (${count} subcomponents). Choose placement mode:`

      const childrenContainer = parentElement.querySelector("#assembly-children-container")
      const childrenList = parentElement.querySelector("#assembly-children-list")
      if (childrenList) {
        childrenList.replaceChildren()
        const childParts = item.child_parts || []
        if (childParts.length > 0) {
          childParts.forEach(ch => {
            const row = document.createElement("div")
            row.className = "assembly-child-item"

            const num = document.createElement("span")
            num.className = "assembly-child-num"
            num.textContent = ch.part_number || "—"

            const name = document.createElement("span")
            name.className = "assembly-child-name"
            name.textContent = ch.description || "—"

            const qty = document.createElement("span")
            qty.className = "assembly-child-qty"
            qty.textContent = `(Qty: ${ch.quantity || 1})`

            row.appendChild(num)
            row.appendChild(name)
            row.appendChild(qty)
            childrenList.appendChild(row)
          })
          if (childrenContainer) childrenContainer.hidden = false
        } else {
          if (childrenContainer) childrenContainer.hidden = true
        }
      }

      if (assemblyModeBoth) assemblyModeBoth.checked = true
      updateAssemblyModalMode()

      assemblyBuiltSelect.replaceChildren()
      assemblyInstalledSelect.replaceChildren()
      allSections.forEach(s => {
        const opt1 = document.createElement("option")
        opt1.value = s.id
        opt1.textContent = s.name
        if (s.id === targetSec.id) opt1.selected = true
        assemblyBuiltSelect.appendChild(opt1)

        const opt2 = document.createElement("option")
        opt2.value = s.id
        opt2.textContent = s.name
        if (targetSec.parent_id ? s.id === targetSec.parent_id : s.id !== targetSec.id) opt2.selected = true
        assemblyInstalledSelect.appendChild(opt2)
      })

      if (assemblyModeGroupOnly) {
        assemblyModeGroupOnly.onclick = () => {
          if (assemblyModeGroupOnly.checked && assemblyInstalledSelect) {
            assemblyInstalledSelect.value = targetSec.id
          }
        }
      }

      assemblyModal.hidden = false

      btnAssemblyConfirm.onclick = () => {
        assemblyModal.hidden = true
        const isGroupOnly = assemblyModeGroupOnly && assemblyModeGroupOnly.checked
        component.setTriggerValue("drop_assembly", {
          assembly_part_id: item.part_id,
          built_section_id: isGroupOnly ? null : assemblyBuiltSelect.value,
          installed_section_id: isGroupOnly ? (assemblyInstalledSelect.value || targetSec.id) : assemblyInstalledSelect.value,
          include_children: !isGroupOnly,
        })
      }
      btnAssemblyCancel.onclick = () => {
        assemblyModal.hidden = true
      }
    } else {
      let useDesc = ""
      if (targetSec.type === "Support Operations") {
        if (targetSec.parent_id) {
          const fedSec = allSections.find(s => s.id === targetSec.parent_id)
          useDesc = fedSec ? `Formed in ${targetSec.name} · Installed in ${fedSec.name}` : `Formed in ${targetSec.name}`
        } else {
          useDesc = `Formed in ${targetSec.name}`
        }
      }
      component.setTriggerValue("drop_part", {
        part_id: item.part_id,
        section_id: targetSec.id,
        quantity: item.quantity || 1,
        use_description: useDesc
      })
    }
  }

  // Viewport Pan and Zoom
  function updateTransform() {
    world.setAttribute("transform", `translate(${state.x} ${state.y}) scale(${state.scale})`)
  }

  function renderWorld() {
    renderFishbone(component)
  }

  function fitView() {
    const rect = viewport.getBoundingClientRect()
    if (!rect || rect.width <= 50 || rect.height <= 50) {
      return false
    }

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity

    if (sections.length === 0) {
      minX = 140
      maxX = 540
      minY = 110
      maxY = 250
    } else {
      sections.forEach(s => {
        const hw = (s.secWidth || 220) / 2
        const hh = (s.secHeight || 64) / 2
        minX = Math.min(minX, s.sx - hw)
        maxX = Math.max(maxX, s.sx + hw)
        minY = Math.min(minY, s.sy - hh)
        maxY = Math.max(maxY, s.sy + hh)
      })
      connections.forEach(c => {
        const start = sectionById.get(c.from_section_id)
        const end = sectionById.get(c.to_section_id)
        if (start && end) {
          minX = Math.min(minX, start.sx, end.sx)
          maxX = Math.max(maxX, start.sx, end.sx)
          minY = Math.min(minY, start.sy, end.sy)
          maxY = Math.max(maxY, start.sy, end.sy)
        }
      })
    }

    const padX = 50
    const padY = 50
    const contentW = Math.max(maxX - minX + padX * 2, 200)
    const contentH = Math.max(maxY - minY + padY * 2, 160)
    const midX = (minX + maxX) / 2
    const midY = (minY + maxY) / 2

    const availW = Math.max(rect.width - 40, 100)
    const availH = Math.max(rect.height - 40, 100)
    const fitScale = clamp(Math.min(availW / contentW, availH / contentH), 0.25, 1.35)

    state.scale = fitScale
    state.x = rect.width / 2 - midX * fitScale
    state.y = rect.height / 2 - midY * fitScale
    updateTransform()
    state.fitted = true
    return true
  }

  if (!state.fitted) {
    const ok = fitView()
    if (!ok) {
      requestAnimationFrame(() => {
        if (!state.fitted) fitView()
      })
    }
  } else {
    updateTransform()
  }

  // Setup ResizeObserver and IntersectionObserver so canvas defaults to Fit screen when clicked or revealed
  if (!state.observerAttached && typeof ResizeObserver !== "undefined") {
    state.observerAttached = true
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        if (width > 80 && height > 80) {
          if (!state.fitted || !state.hasUserInteracted) {
            requestAnimationFrame(() => {
              fitView()
            })
          }
        }
      }
    })
    ro.observe(viewport)

    if (typeof IntersectionObserver !== "undefined") {
      const io = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            if (!state.fitted || !state.hasUserInteracted) {
              requestAnimationFrame(() => {
                fitView()
              })
            }
          }
        }
      })
      io.observe(shell)
    }
  }

  // Pan interaction
  svg.onmousedown = (e) => {
    if (e.target !== svg && e.target.tagName !== "svg") return
    state.dragging = true
    state.pointerX = e.clientX
    state.pointerY = e.clientY
    svg.classList.add("dragging")
  }
  window.addEventListener("mousemove", (e) => {
    if (!state.dragging) return
    state.hasUserInteracted = true
    state.x += (e.clientX - state.pointerX)
    state.y += (e.clientY - state.pointerY)
    state.pointerX = e.clientX
    state.pointerY = e.clientY
    updateTransform()
  })
  window.addEventListener("mouseup", () => {
    if (state.dragging) {
      state.dragging = false
      svg.classList.remove("dragging")
    }
  })

  // Zoom interaction
  viewport.onwheel = (e) => {
    e.preventDefault()
    state.hasUserInteracted = true
    const rect = viewport.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top
    const delta = e.deltaY < 0 ? 1.12 : 0.89
    const newScale = clamp(state.scale * delta, 0.2, 3.0)
    state.x = mouseX - (mouseX - state.x) * (newScale / state.scale)
    state.y = mouseY - (mouseY - state.y) * (newScale / state.scale)
    state.scale = newScale
    updateTransform()
  }

  parentElement.querySelector("#zoom-in").onclick = () => {
    state.hasUserInteracted = true
    const rect = viewport.getBoundingClientRect()
    const cx = rect.width / 2
    const cy = rect.height / 2
    const newScale = clamp(state.scale * 1.2, 0.2, 3.0)
    state.x = cx - (cx - state.x) * (newScale / state.scale)
    state.y = cy - (cy - state.y) * (newScale / state.scale)
    state.scale = newScale
    updateTransform()
  }
  parentElement.querySelector("#zoom-out").onclick = () => {
    state.hasUserInteracted = true
    const rect = viewport.getBoundingClientRect()
    const cx = rect.width / 2
    const cy = rect.height / 2
    const newScale = clamp(state.scale / 1.2, 0.2, 3.0)
    state.x = cx - (cx - state.x) * (newScale / state.scale)
    state.y = cy - (cy - state.y) * (newScale / state.scale)
    state.scale = newScale
    updateTransform()
  }
  parentElement.querySelector("#fit-view").onclick = () => {
    state.hasUserInteracted = false
    fitView()
  }
  parentElement.querySelector("#full-screen").onclick = () => {
    if (!document.fullscreenElement) {
      shell.requestFullscreen().catch(() => {})
    } else {
      document.exitFullscreen().catch(() => {})
    }
  }
}
"""

_FISHBONE_COMPONENT = st.components.v2.component(
    "paag_interactive_fishbone_builder_v16",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


@st.cache_data(show_spinner=False, max_entries=512)
def _thumbnail_data_url(image_path: str, modified_ns: int) -> str:
    del modified_ns
    path = Path(image_path)
    if not path.is_file():
        return ""
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((240, 180))
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=78, optimize=True)
        return f"data:image/jpeg;base64,{base64.b64encode(output.getvalue()).decode('ascii')}"
    except (OSError, ValueError):
        return ""


def part_thumbnail(image_path: object) -> str:
    raw = str(image_path or "").strip()
    if raw.startswith(("http://", "https://", "data:")):
        return raw
    path = Path(raw)
    try:
        return _thumbnail_data_url(str(path), path.stat().st_mtime_ns)
    except OSError:
        return ""


def interactive_fishbone(
    sections: list[dict],
    connections: list[dict],
    parts: list[dict],
    palette_items: list[dict] | None = None,
    all_sections: list[dict] | None = None,
    *,
    key: str,
    on_create_section: Callable[[], None] | None = None,
    on_move_node: Callable[[], None] | None = None,
    on_auto_arrange: Callable[[], None] | None = None,
    on_create_connection: Callable[[], None] | None = None,
    on_move_connection: Callable[[], None] | None = None,
    on_delete_connection: Callable[[], None] | None = None,
    on_delete_section_request: Callable[[], None] | None = None,
    on_drop_part: Callable[[], None] | None = None,
    on_drop_assembly: Callable[[], None] | None = None,
    on_remove_part: Callable[[], None] | None = None,
    on_move_part_assignment: Callable[[], None] | None = None,
) -> Any:
    """Render the simplified interactive Fishbone builder canvas with simple blocks and direct parent/child flow."""
    kwargs = {
        "key": key,
        "data": {
            "sections": sections,
            "connections": connections,
            "parts": parts,
            "palette_items": palette_items or [],
            "all_sections": all_sections or sections,
        },
        "width": "stretch",
        "height": "content",
    }
    if on_create_section:
        kwargs["on_create_section_change"] = on_create_section
    if on_move_node:
        kwargs["on_move_node_change"] = on_move_node
    if on_auto_arrange:
        kwargs["on_auto_arrange_change"] = on_auto_arrange
    if on_create_connection:
        kwargs["on_create_connection_change"] = on_create_connection
    if on_move_connection:
        kwargs["on_move_connection_change"] = on_move_connection
    if on_delete_connection:
        kwargs["on_delete_connection_change"] = on_delete_connection
    if on_delete_section_request:
        kwargs["on_delete_section_request_change"] = on_delete_section_request
    if on_drop_part:
        kwargs["on_drop_part_change"] = on_drop_part
    if on_drop_assembly:
        kwargs["on_drop_assembly_change"] = on_drop_assembly
    if on_remove_part:
        kwargs["on_remove_part_change"] = on_remove_part
    if on_move_part_assignment:
        kwargs["on_move_part_assignment_change"] = on_move_part_assignment

    return _FISHBONE_COMPONENT(**kwargs)
