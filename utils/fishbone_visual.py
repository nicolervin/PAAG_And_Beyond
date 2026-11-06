import base64
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageOps
import streamlit as st

from utils.media_cache import cached_image_data_url


_HTML = """
<div class="fishbone-shell">
  <div class="fishbone-toolbar">
    <div class="fishbone-title">
      <strong>Interactive assembly fishbone</strong>
      <span id="fishbone-summary"></span>
    </div>
    <div class="fishbone-actions">
      <button id="print-fishbone-btn" type="button" title="Print the fishbone diagram with readable part numbers" class="btn-tool">🖨️ Print</button>
      <button id="add-section-btn" type="button" title="Add new section block" class="btn-tool" style="background:#2563eb; color:white; border-color:#2563eb; font-weight:700;">➕ Add Section</button>
      <button id="toggle-palette" type="button" title="Toggle parts palette" class="btn-tool">📦 Parts palette</button>
      <button id="auto-arrange" type="button" title="Auto-arrange sections" class="btn-tool">⚡ Auto-arrange</button>
      <button id="clear-fishbone-btn" type="button" title="Clear parts and/or delete sections from Fishbone" class="btn-tool" style="background:#dc2626; color:white; border-color:#dc2626; font-weight:700;">🗑️ Clear</button>
      <button id="zoom-out" type="button" title="Zoom out">−</button>
      <button id="zoom-in" type="button" title="Zoom in">+</button>
      <button id="fit-view" type="button" title="Fit the entire fishbone">Fit</button>
      <button id="full-screen" type="button" title="Open the fishbone full screen" aria-pressed="false">Full Screen</button>
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
          <marker id="arrow-snap" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#22c55e" />
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
              <div id="add-section-error" style="display:none; color:#dc2626; font-size:.8rem; font-weight:600; margin-top:4px;"></div>
            </label>
            <label class="modal-label">
              Section type
              <select id="add-section-type" class="modal-select">
                <option value="Assembly" selected>Assembly</option>
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
      <!-- Part Replicate / Manage Section Uses Modal -->
      <div id="part-uses-modal" class="canvas-modal" hidden>
        <div class="modal-card part-uses-modal-card">
          <h4 id="part-uses-title">Replicate / Manage Section Uses</h4>
          <p id="part-uses-desc">Select all Fishbone sections where this part or assembly is used, and adjust the quantity per section:</p>
          <div class="part-uses-quick-bar">
            <span id="part-uses-summary-badge" class="part-uses-badge">Used in 1 section</span>
            <div class="part-uses-quick-actions">
              <button id="btn-part-uses-same-qty" type="button" class="btn-quick-action" title="Set every selected section to the same quantity">Same qty in each</button>
              <button id="btn-part-uses-split-qty" type="button" class="btn-quick-action" title="Split total quantity evenly across selected sections">Split qty evenly</button>
            </div>
          </div>
          <div id="part-uses-sections-list" class="part-uses-list"></div>
          <label id="part-uses-children-wrap" class="part-uses-children-toggle" hidden>
            <input id="part-uses-include-children" type="checkbox" checked />
            <span id="part-uses-children-label">Also replicate sub-component parts into newly selected sections</span>
          </label>
          <div class="modal-buttons">
            <button id="btn-part-uses-confirm" type="button" class="btn-modal btn-primary">Apply Section Uses</button>
            <button id="btn-part-uses-cancel" type="button" class="btn-modal btn-cancel">Cancel</button>
          </div>
        </div>
      </div>
      <!-- Edit Model Variant Ties Modal -->
      <div id="variant-ties-modal" class="canvas-modal" hidden>
        <div class="modal-card part-uses-modal-card">
          <h4 id="variant-ties-title">Edit Model Variant Ties</h4>
          <p id="variant-ties-desc">Uncheck any part below to disconnect it from this model variant stack, or add another part to this variant group:</p>
          <div class="part-uses-quick-bar">
            <span id="variant-ties-summary-badge" class="part-uses-badge" style="color:#4f46e5; background:rgba(79, 70, 229, 0.12);">2 parts tied</span>
            <div class="part-uses-quick-actions">
              <button id="btn-variant-ties-untie-all" type="button" class="btn-quick-action" title="Disconnect all parts in this stack into separate cards">Untie all</button>
            </div>
          </div>
          <div id="variant-ties-list" class="part-uses-list"></div>
          <div class="variant-ties-add-bar">
            <select id="variant-ties-add-select" class="modal-select" style="flex:1; min-width:0; padding:6px 8px; font-size:.82rem;"></select>
            <button id="btn-variant-ties-add-part" type="button" class="btn-quick-action" style="padding:6px 10px; font-weight:700; color:#4f46e5; border-color:#6366f1;">+ Tie Part</button>
          </div>
          <div class="modal-buttons">
            <button id="btn-variant-ties-confirm" type="button" class="btn-modal btn-primary">Apply Variant Ties</button>
            <button id="btn-variant-ties-cancel" type="button" class="btn-modal btn-cancel">Cancel</button>
          </div>
        </div>
      </div>
      <div class="fishbone-hint">Drag blocks to arrange · Drag part onto another part to stack as model variants (click N× badge to edit variant ties) · Drag circle handle or edge snap nodes to connect · Click arrow or × to edit/delete</div>
    </div>
  </div>
</div>
"""

_CSS = """
:host { color: var(--st-text-color); font-family: var(--st-font); }
.fishbone-shell { box-sizing: border-box; width: 100%; height: 750px; min-height: 750px; display: flex; flex-direction: column; border: 1px solid var(--st-border-color); border-radius: var(--st-base-radius); overflow: hidden; background: var(--st-background-color); }
.fishbone-toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px; padding: 8px 14px; border-bottom: 1px solid var(--st-border-color); background: var(--st-secondary-background-color); flex-shrink: 0; }
.fishbone-title { min-width: 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; }
.fishbone-title strong { white-space: nowrap; }
.fishbone-title span { color: var(--st-secondary-text-color); font-size: .82rem; white-space: nowrap; }
.fishbone-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.fishbone-actions button { display: inline-flex; align-items: center; justify-content: center; gap: 4px; min-width: 30px; min-height: 30px; height: auto; padding: 4px 10px; white-space: nowrap; flex-shrink: 0; line-height: 1.2; box-sizing: border-box; border: 1px solid var(--st-border-color); border-radius: var(--st-button-radius); color: var(--st-text-color); background: var(--st-background-color); cursor: pointer; font: inherit; font-size: .81rem; font-weight: 600; }
.fishbone-actions button:hover { border-color: var(--st-primary-color); color: var(--st-primary-color); }
.fishbone-actions button.btn-tool { background: var(--st-secondary-background-color); }
@media (max-width: 1100px) {
  .fishbone-toolbar { padding: 8px 10px; gap: 6px 10px; }
  .fishbone-actions { gap: 5px; }
  .fishbone-actions button { padding: 4px 8px; font-size: .78rem; min-height: 28px; }
}

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
.palette-card.placed { opacity: 0.78; border-style: dashed; cursor: pointer; }
.palette-card.placed:hover { opacity: 1; border-color: #f59e0b; box-shadow: 0 2px 8px rgba(245, 158, 11, 0.22); }
.palette-card.search-focused { opacity: 1 !important; border-style: solid !important; border-color: #f59e0b !important; box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.28) !important; background: color-mix(in srgb, #fef3c7 22%, var(--st-background-color)); }
.palette-sec-pills { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px; }
.palette-sec-pill { display: inline-flex; align-items: center; gap: 3px; padding: 1px 6px; border-radius: 999px; font-size: .66rem; font-weight: 600; background: rgba(245, 158, 11, 0.14); color: #b45309; border: 1px solid rgba(245, 158, 11, 0.38); cursor: pointer; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.palette-sec-pill:hover { background: #f59e0b; color: white; border-color: #d97706; }
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

/* Edge Snap Node Points on section blocks */
.section-snap-node { cursor: crosshair; fill: white; stroke: #94a3b8; stroke-width: 1.5; opacity: 0; transition: opacity .15s ease, r .12s ease, fill .12s ease, stroke .12s ease; }
.section-node:hover .section-snap-node { opacity: 0.75; }
.section-snap-node:hover { opacity: 1 !important; r: 7.5px !important; fill: #2563eb !important; stroke: white !important; stroke-width: 2px !important; filter: drop-shadow(0 0 4px rgba(37,99,235,0.6)); }
.section-snap-node.connecting-active { opacity: 0.8 !important; stroke: #3b82f6 !important; }
.section-snap-node.snap-target-highlight { opacity: 1 !important; r: 8.5px !important; fill: #22c55e !important; stroke: white !important; stroke-width: 2.5px !important; filter: drop-shadow(0 0 6px rgba(34,197,94,0.7)); }

/* Connection line */
.conn-line { cursor: pointer; fill: none !important; stroke-linecap: round; transition: stroke .15s ease, stroke-width .15s ease, opacity .15s ease; pointer-events: stroke; }
.conn-line:hover { stroke-width: 5 !important; filter: drop-shadow(0 0 5px rgba(37,99,235,0.4)); }
.conn-line.selected { stroke: #ef4444 !important; stroke-width: 5 !important; }
.conn-line.dragging-dimmed, .conn-handle-group.dragging-dimmed, .conn-hit-area.dragging-dimmed { opacity: 0.2 !important; pointer-events: none !important; }
.conn-hit-area { cursor: grab; stroke: transparent !important; fill: none !important; stroke-width: 26px; pointer-events: stroke; }
.conn-hit-area:active { cursor: grabbing; }
.conn-start-handle, .conn-arrow-handle { cursor: grab; transition: r .12s ease, fill .12s ease; }
.conn-start-handle:hover, .conn-arrow-handle:hover { r: 9px !important; }
.conn-handle-group { cursor: grab; }
.conn-handle-group:active { cursor: grabbing; }
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
.part-card.part-card-stack-target > rect { stroke: #4f46e5 !important; stroke-width: 3px !important; stroke-dasharray: 4 2; filter: drop-shadow(0 0 8px rgba(79, 70, 229, 0.65)); }
.part-cluster { user-select: none; transition: opacity .18s ease, filter .18s ease; }
.section-node { transition: opacity .18s ease; }
#fishbone-world.search-highlight-active .section-node:not(.search-highlight) { opacity: 0.52; }
#fishbone-world.search-highlight-active .section-node.search-highlight { opacity: 1; }
.section-node.search-highlight .section-node-rect { stroke: #f59e0b !important; stroke-width: 3.5px !important; filter: drop-shadow(0 0 12px rgba(245, 158, 11, 0.58)); }
#fishbone-world.search-highlight-active .part-cluster:not(.search-highlight) { opacity: 0.35; }
#fishbone-world.search-highlight-active .part-cluster.search-highlight { opacity: 1; filter: drop-shadow(0 0 10px rgba(245, 158, 11, 0.85)); }
.part-card.search-highlight > rect:first-of-type { stroke: #f59e0b !important; stroke-width: 3px !important; fill: color-mix(in srgb, #fef3c7 42%, var(--st-background-color)) !important; }
.cascade-badge { cursor: pointer; }
.cascade-badge rect { transition: fill .12s ease, transform .12s ease; }
.cascade-badge:hover rect { fill: #312e81; }
.part-remove-btn { cursor: pointer; opacity: 0; transition: opacity .12s ease; }
.part-card:hover .part-remove-btn { opacity: 0.95; }
.part-remove-btn:hover { opacity: 1; }
.part-replicate-btn { cursor: pointer; opacity: 0; transition: opacity .12s ease; }
.part-card:hover .part-replicate-btn { opacity: 0.95; }
.part-replicate-btn:hover { opacity: 1; }
.part-multiuse-badge { cursor: pointer; }
.part-multiuse-badge rect { transition: fill .12s ease; }
.part-multiuse-badge:hover rect { fill: #0369a1; }
.palette-replicate-btn { margin-left: auto; padding: 2px 6px; font-size: .7rem; font-weight: 700; border: 1px solid #0284c7; border-radius: 4px; background: rgba(2, 132, 199, 0.1); color: #0284c7; cursor: pointer; flex-shrink: 0; white-space: nowrap; }
.palette-replicate-btn:hover { background: #0284c7; color: white; }
.part-drag-ghost { pointer-events: none; }

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
.part-uses-modal-card { max-width: 540px; }
.part-uses-quick-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; padding: 6px 10px; background: var(--st-secondary-background-color); border: 1px solid var(--st-border-color); border-radius: 8px; }
.part-uses-badge { font-size: .78rem; font-weight: 700; color: #0284c7; background: rgba(2, 132, 199, 0.12); padding: 3px 8px; border-radius: 999px; }
.part-uses-quick-actions { display: flex; align-items: center; gap: 6px; }
.btn-quick-action { padding: 4px 8px; font-size: .75rem; font-weight: 600; border: 1px solid var(--st-border-color); border-radius: 5px; background: var(--st-background-color); color: var(--st-text-color); cursor: pointer; }
.btn-quick-action:hover { border-color: var(--st-primary-color); color: var(--st-primary-color); }
.part-uses-list { max-height: 290px; overflow-y: auto; border: 1px solid var(--st-border-color); border-radius: 8px; display: flex; flex-direction: column; background: var(--st-background-color); }
.part-use-row { display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--st-border-color); transition: background .12s ease; }
.part-use-row:last-child { border-bottom: none; }
.part-use-row.active-use { background: rgba(2, 132, 199, 0.06); }
.part-use-row-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.part-use-check-label { display: flex; align-items: center; gap: 8px; font-size: .85rem; font-weight: 600; color: var(--st-text-color); cursor: pointer; flex: 1; min-width: 0; }
.part-use-sec-type { font-size: .72rem; font-weight: 500; color: var(--st-secondary-text-color); background: var(--st-secondary-background-color); padding: 2px 6px; border-radius: 4px; white-space: nowrap; }
.part-use-header-actions { display: flex; align-items: center; gap: 6px; }
.btn-split-sec-use { padding: 2px 7px; font-size: .72rem; font-weight: 700; border: 1px solid #0284c7; border-radius: 4px; background: rgba(2, 132, 199, 0.1); color: #0284c7; cursor: pointer; white-space: nowrap; }
.btn-split-sec-use:hover { background: #0284c7; color: white; }
.btn-split-sec-use[hidden] { display: none !important; }
.part-use-cards-list { display: flex; flex-direction: column; gap: 5px; padding-left: 24px; }
.part-use-cards-list[hidden] { display: none !important; }
.part-use-controls { display: flex; align-items: center; gap: 8px; }
.part-use-controls[hidden] { display: none !important; }
.part-use-card-index { font-size: .72rem; font-weight: 700; color: #0284c7; background: rgba(2, 132, 199, 0.12); padding: 2px 6px; border-radius: 4px; white-space: nowrap; }
.part-use-card-index[hidden] { display: none !important; }
.btn-remove-sec-card { padding: 2px 6px; font-size: .78rem; font-weight: 700; border: 1px solid rgba(239, 68, 68, 0.45); border-radius: 4px; background: rgba(239, 68, 68, 0.08); color: #ef4444; cursor: pointer; line-height: 1; }
.btn-remove-sec-card:hover { background: #ef4444; color: white; }
.btn-remove-sec-card[hidden] { display: none !important; }
.part-use-qty-wrap { display: flex; align-items: center; gap: 4px; font-size: .78rem; color: var(--st-secondary-text-color); font-weight: 600; }
.part-use-qty-input { width: 68px; padding: 4px 6px; border: 1px solid var(--st-border-color); border-radius: 5px; background: var(--st-background-color); color: var(--st-text-color); font-size: .82rem; font-weight: 600; }
.part-use-note-input { flex: 1; min-width: 0; padding: 4px 8px; border: 1px solid var(--st-border-color); border-radius: 5px; background: var(--st-background-color); color: var(--st-text-color); font-size: .8rem; }
.part-uses-children-toggle { display: flex; align-items: center; gap: 8px; font-size: .82rem; font-weight: 600; color: var(--st-text-color); padding: 8px 10px; border-radius: 8px; background: rgba(79, 70, 229, 0.08); border: 1px solid rgba(79, 70, 229, 0.25); cursor: pointer; }
.part-uses-children-toggle[hidden] { display: none !important; }
.variant-ties-add-bar { display: flex; align-items: center; gap: 8px; padding: 6px 8px; background: var(--st-secondary-background-color); border: 1px solid var(--st-border-color); border-radius: 8px; }
.variant-tie-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 10px; border-bottom: 1px solid var(--st-border-color); transition: background .12s ease; }
.variant-tie-row:last-child { border-bottom: none; }
.variant-tie-row.active-tie { background: rgba(79, 70, 229, 0.06); }
.variant-tie-row.untied-row { background: rgba(239, 68, 68, 0.05); opacity: 0.82; }
.variant-tie-status-pill { font-size: .72rem; font-weight: 700; padding: 2px 7px; border-radius: 999px; white-space: nowrap; cursor: pointer; user-select: none; }
.variant-tie-status-pill.tied { background: rgba(79, 70, 229, 0.14); color: #4f46e5; border: 1px solid rgba(79, 70, 229, 0.3); }
.variant-tie-status-pill.untied { background: rgba(217, 119, 6, 0.15); color: #d97706; border: 1px solid rgba(217, 119, 6, 0.35); }

/* Start and End Arrow Handles */
.conn-arrow-handle { cursor: grab; opacity: 0.88; transition: r .12s ease, fill .12s ease, opacity .12s ease; filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.3)); }
.conn-arrow-handle:hover { r: 10px !important; opacity: 1 !important; fill: #1d4ed8 !important; }
.conn-arrow-handle:active { cursor: grabbing; }

.conn-start-handle { cursor: grab; opacity: 0.85; transition: r .12s ease, fill .12s ease, opacity .12s ease; filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.3)); }
.conn-start-handle:hover { r: 9px !important; opacity: 1 !important; fill: #1d4ed8 !important; }
.conn-start-handle:active { cursor: grabbing; }

.buffer-badge rect { fill: #1e293b; stroke: #94a3b8; stroke-width: 1.5; rx: 6px; }
.buffer-badge text { fill: #f8fafc; font-size: 10px; font-weight: 700; user-select: none; }

.fishbone-shell:fullscreen { width: 100vw; height: 100vh; min-height: 0; border: 0; border-radius: 0; }
.fishbone-shell:fullscreen .fishbone-viewport { min-height: 0; }
"""

_JS = """
const SVG_NS = "http://www.w3.org/2000/svg"
const instanceState = new WeakMap()

function getSavedFishboneView(key) {
  if (typeof window === "undefined" || !key) return null
  window.__paag_fishbone_views = window.__paag_fishbone_views || {}
  const mem = window.__paag_fishbone_views[key]
  if (mem && typeof mem.scale === "number" && isFinite(mem.scale) && mem.scale > 0 && typeof mem.x === "number" && isFinite(mem.x) && typeof mem.y === "number" && isFinite(mem.y)) {
    return mem
  }
  try {
    const raw = sessionStorage.getItem("paag_fishbone_view_" + key)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed.scale === "number" && isFinite(parsed.scale) && parsed.scale > 0 && typeof parsed.x === "number" && isFinite(parsed.x) && typeof parsed.y === "number" && isFinite(parsed.y)) {
        window.__paag_fishbone_views[key] = parsed
        return parsed
      }
    }
  } catch (e) {}
  return null
}

function saveFishboneView(key, vState) {
  if (typeof window === "undefined" || !key || !vState) return
  if (typeof vState.scale !== "number" || !isFinite(vState.scale) || vState.scale <= 0) return
  if (typeof vState.x !== "number" || !isFinite(vState.x)) return
  if (typeof vState.y !== "number" || !isFinite(vState.y)) return
  window.__paag_fishbone_views = window.__paag_fishbone_views || {}
  const toStore = {
    scale: vState.scale,
    x: vState.x,
    y: vState.y,
    fitted: Boolean(vState.fitted),
    hasUserInteracted: Boolean(vState.hasUserInteracted)
  }
  window.__paag_fishbone_views[key] = toStore
  try {
    sessionStorage.setItem("paag_fishbone_view_" + key, JSON.stringify(toStore))
  } catch (e) {}
}

function getSavedConnNodes(key) {
  if (typeof window === "undefined" || !key) return {}
  window.__paag_fishbone_conn_nodes = window.__paag_fishbone_conn_nodes || {}
  if (window.__paag_fishbone_conn_nodes[key]) {
    return { ...window.__paag_fishbone_conn_nodes[key] }
  }
  try {
    const raw = localStorage.getItem("paag_fishbone_nodes_" + key) || sessionStorage.getItem("paag_fishbone_nodes_" + key)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === "object") {
        window.__paag_fishbone_conn_nodes[key] = parsed
        return { ...parsed }
      }
    }
  } catch (e) {}
  return {}
}

function saveConnNodes(key, overrides) {
  if (typeof window === "undefined" || !key || !overrides) return
  window.__paag_fishbone_conn_nodes = window.__paag_fishbone_conn_nodes || {}
  window.__paag_fishbone_conn_nodes[key] = { ...overrides }
  try {
    const serialized = JSON.stringify(overrides)
    sessionStorage.setItem("paag_fishbone_nodes_" + key, serialized)
    localStorage.setItem("paag_fishbone_nodes_" + key, serialized)
  } catch (e) {}
}

function clearSavedConnNodes(key) {
  if (typeof window === "undefined" || !key) return
  if (window.__paag_fishbone_conn_nodes) {
    delete window.__paag_fishbone_conn_nodes[key]
  }
  try {
    sessionStorage.removeItem("paag_fishbone_nodes_" + key)
    localStorage.removeItem("paag_fishbone_nodes_" + key)
  } catch (e) {}
}

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

function getSectionNodePoints(sec) {
  const w = sec.secWidth || 220
  const h = sec.secHeight || 64
  const halfW = w / 2
  const halfH = h / 2
  const nodes = []

  // Top edge (5 points, outward normal: 0, -1)
  const topFractions = [-0.4, -0.2, 0, 0.2, 0.4]
  topFractions.forEach((f, i) => {
    const lx = f * w
    const ly = -halfH
    nodes.push({
      id: `top_${i}`,
      edge: 'top',
      lx: lx,
      ly: ly,
      x: sec.sx + lx,
      y: sec.sy + ly,
      nx: 0,
      ny: -1
    })
  })

  // Bottom edge (5 points, outward normal: 0, 1)
  const botFractions = [-0.4, -0.2, 0, 0.2, 0.4]
  botFractions.forEach((f, i) => {
    const lx = f * w
    const ly = halfH
    nodes.push({
      id: `bottom_${i}`,
      edge: 'bottom',
      lx: lx,
      ly: ly,
      x: sec.sx + lx,
      y: sec.sy + ly,
      nx: 0,
      ny: 1
    })
  })

  // Left edge (3 points, outward normal: -1, 0)
  const leftFractions = [-0.25, 0, 0.25]
  leftFractions.forEach((f, i) => {
    const lx = -halfW
    const ly = f * h
    nodes.push({
      id: `left_${i}`,
      edge: 'left',
      lx: lx,
      ly: ly,
      x: sec.sx + lx,
      y: sec.sy + ly,
      nx: -1,
      ny: 0
    })
  })

  // Right edge (3 points, outward normal: 1, 0)
  const rightFractions = [-0.25, 0, 0.25]
  rightFractions.forEach((f, i) => {
    const lx = halfW
    const ly = f * h
    nodes.push({
      id: `right_${i}`,
      edge: 'right',
      lx: lx,
      ly: ly,
      x: sec.sx + lx,
      y: sec.sy + ly,
      nx: 1,
      ny: 0
    })
  })

  return nodes
}

function findNearestNodePoint(sec, wx, wy) {
  const nodes = getSectionNodePoints(sec)
  let best = null
  let bestDist = Infinity
  for (const node of nodes) {
    const d = Math.hypot(node.x - wx, node.y - wy)
    if (d < bestDist) {
      bestDist = d
      best = node
    }
  }
  return best
}

function findBestSnapTarget(candidateSections, currX, currY, snapRadius = 180) {
  let bestSec = null
  let bestNode = null
  let bestDist = Infinity

  for (const sec of candidateSections) {
    const w = sec.secWidth || 220
    const h = sec.secHeight || 64
    const halfW = w / 2
    const halfH = h / 2

    const isInside = (Math.abs(currX - sec.sx) <= halfW + 24) && (Math.abs(currY - sec.sy) <= halfH + 24)

    const nodes = getSectionNodePoints(sec)
    for (const node of nodes) {
      const d = Math.hypot(node.x - currX, node.y - currY)
      const effectiveDist = isInside ? d * 0.7 : d
      if (effectiveDist < bestDist) {
        bestDist = effectiveDist
        bestSec = sec
        bestNode = node
      }
    }
  }

  if (bestNode && (bestDist <= snapRadius || (bestSec && Math.abs(currX - bestSec.sx) <= (bestSec.secWidth || 220) / 2 + 60 && Math.abs(currY - bestSec.sy) <= (bestSec.secHeight || 64) / 2 + 60))) {
    return { section: bestSec, node: bestNode, distance: bestDist }
  }
  return null
}

function computeSmoothConnectionPath(p1, p2) {
  const dist = Math.hypot(p2.x - p1.x, p2.y - p1.y)
  const k = Math.max(35, Math.min(180, dist * 0.45))
  const c1x = p1.x + (p1.nx !== undefined ? p1.nx : 1) * k
  const c1y = p1.y + (p1.ny !== undefined ? p1.ny : 0) * k
  const c2x = p2.x + (p2.nx !== undefined ? p2.nx : -1) * k
  const c2y = p2.y + (p2.ny !== undefined ? p2.ny : 0) * k

  const pathData = `M ${p1.x} ${p1.y} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`
  const midX = 0.125 * p1.x + 0.375 * c1x + 0.375 * c2x + 0.125 * p2.x
  const midY = 0.125 * p1.y + 0.375 * c1y + 0.375 * c2y + 0.125 * p2.y

  return {
    d: pathData,
    midX,
    midY,
    c1: { x: c1x, y: c1y },
    c2: { x: c2x, y: c2y }
  }
}

function resolveConnectionEndpoints(connections, sectionById) {
  const usedNodes = new Set()

  connections.forEach(conn => {
    if (conn.from_section_id && conn.from_node) {
      usedNodes.add(`${conn.from_section_id}:${conn.from_node}`)
    }
    if (conn.to_section_id && conn.to_node) {
      usedNodes.add(`${conn.to_section_id}:${conn.to_node}`)
    }
  })

  return connections.map(conn => {
    const start = sectionById.get(conn.from_section_id)
    const end = sectionById.get(conn.to_section_id)
    if (!start || !end) return null

    const startNodes = getSectionNodePoints(start)
    const endNodes = getSectionNodePoints(end)

    const startNodeMap = new Map(startNodes.map(n => [n.id, n]))
    const endNodeMap = new Map(endNodes.map(n => [n.id, n]))

    let p1 = null
    let p2 = null

    if (conn.from_node && startNodeMap.has(conn.from_node)) {
      p1 = startNodeMap.get(conn.from_node)
    }
    if (conn.to_node && endNodeMap.has(conn.to_node)) {
      p2 = endNodeMap.get(conn.to_node)
    }

    const dx = end.sx - start.sx
    const dy = end.sy - start.sy
    const startW = start.secWidth || 220
    const startH = start.secHeight || 64
    const endW = end.secWidth || 220
    const endH = end.secHeight || 64
    const overlapLeft = Math.max(start.sx - startW / 2, end.sx - endW / 2)
    const overlapRight = Math.min(start.sx + startW / 2, end.sx + endW / 2)
    const horizOverlap = overlapRight - overlapLeft
    const vertGap = Math.abs(dy) - (startH / 2 + endH / 2)
    const isVertical = (vertGap > 0 && horizOverlap > 0) || (Math.abs(dy) > Math.abs(dx) * 1.5)
    const anchorX = horizOverlap > 0 ? (overlapLeft + overlapRight) / 2 : (start.sx + end.sx) / 2

    if (!p1) {
      if (isVertical) {
        const edgePrefix = dy > 0 ? "bottom" : "top"
        const candidates = startNodes
          .filter(n => n.edge === edgePrefix)
          .sort((a, b) => Math.abs(a.x - anchorX) - Math.abs(b.x - anchorX))
        p1 = candidates.find(n => !usedNodes.has(`${start.id}:${n.id}`)) || candidates[0] || startNodeMap.get(`${edgePrefix}_2`)
      } else {
        const edgePrefix = dx >= 0 ? "right" : "left"
        const slotOrder = [1, 0, 2]
        const candidates = slotOrder.map(s => startNodeMap.get(`${edgePrefix}_${s}`)).filter(Boolean)
        p1 = candidates.find(n => !usedNodes.has(`${start.id}:${n.id}`)) || candidates[0]
      }
      if (p1) usedNodes.add(`${start.id}:${p1.id}`)
    }

    if (!p2) {
      if (isVertical) {
        const edgePrefix = dy > 0 ? "top" : "bottom"
        const targetX = p1 ? p1.x : anchorX
        const candidates = endNodes
          .filter(n => n.edge === edgePrefix)
          .sort((a, b) => Math.abs(a.x - targetX) - Math.abs(b.x - targetX))
        p2 = candidates.find(n => !usedNodes.has(`${end.id}:${n.id}`)) || candidates[0] || endNodeMap.get(`${edgePrefix}_2`)
      } else {
        const edgePrefix = dx >= 0 ? "left" : "right"
        const slotOrder = [1, 0, 2]
        const candidates = slotOrder.map(s => endNodeMap.get(`${edgePrefix}_${s}`)).filter(Boolean)
        p2 = candidates.find(n => !usedNodes.has(`${end.id}:${n.id}`)) || candidates[0]
      }
      if (p2) usedNodes.add(`${end.id}:${p2.id}`)
    }

    return {
      conn,
      start,
      end,
      p1,
      p2
    }
  }).filter(Boolean)
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
  const clearFishboneBtn = parentElement.querySelector("#clear-fishbone-btn")
  const printFishboneBtn = parentElement.querySelector("#print-fishbone-btn")

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

  const partUsesModal = parentElement.querySelector("#part-uses-modal")
  const partUsesTitle = parentElement.querySelector("#part-uses-title")
  const partUsesDesc = parentElement.querySelector("#part-uses-desc")
  const partUsesSummaryBadge = parentElement.querySelector("#part-uses-summary-badge")
  const btnPartUsesSameQty = parentElement.querySelector("#btn-part-uses-same-qty")
  const btnPartUsesSplitQty = parentElement.querySelector("#btn-part-uses-split-qty")
  const partUsesSectionsList = parentElement.querySelector("#part-uses-sections-list")
  const partUsesChildrenWrap = parentElement.querySelector("#part-uses-children-wrap")
  const partUsesIncludeChildren = parentElement.querySelector("#part-uses-include-children")
  const partUsesChildrenLabel = parentElement.querySelector("#part-uses-children-label")
  const btnPartUsesConfirm = parentElement.querySelector("#btn-part-uses-confirm")
  const btnPartUsesCancel = parentElement.querySelector("#btn-part-uses-cancel")

  const variantTiesModal = parentElement.querySelector("#variant-ties-modal")
  const variantTiesTitle = parentElement.querySelector("#variant-ties-title")
  const variantTiesDesc = parentElement.querySelector("#variant-ties-desc")
  const variantTiesSummaryBadge = parentElement.querySelector("#variant-ties-summary-badge")
  const btnVariantTiesUntieAll = parentElement.querySelector("#btn-variant-ties-untie-all")
  const variantTiesList = parentElement.querySelector("#variant-ties-list")
  const variantTiesAddSelect = parentElement.querySelector("#variant-ties-add-select")
  const btnVariantTiesAddPart = parentElement.querySelector("#btn-variant-ties-add-part")
  const btnVariantTiesConfirm = parentElement.querySelector("#btn-variant-ties-confirm")
  const btnVariantTiesCancel = parentElement.querySelector("#btn-variant-ties-cancel")

  if (!shell || !viewport || !svg || !world || !data) return

  const storageKey = (data && data.component_key) ? data.component_key : "fishbone_default"
  let state = instanceState.get(parentElement)
  if (!state || (state.storageKey && state.storageKey !== storageKey)) {
    const saved = getSavedFishboneView(storageKey)
    state = {
      storageKey: storageKey,
      scale: saved ? saved.scale : 1,
      x: saved ? saved.x : 0,
      y: saved ? saved.y : 0,
      dragging: false,
      pointerX: 0,
      pointerY: 0,
      fitted: saved ? Boolean(saved.fitted) : false,
      signature: "",
      selectedConnId: null,
      selectedSectionId: null,
      pendingConnection: null,
      reconnectingConnection: null,
      hasUserInteracted: saved ? Boolean(saved.hasUserInteracted) : false,
      observerAttached: false,
      clusterActiveIndices: new Map()
    }
    instanceState.set(parentElement, state)
  } else if (!state.fitted) {
    const saved = getSavedFishboneView(storageKey)
    if (saved) {
      state.scale = saved.scale
      state.x = saved.x
      state.y = saved.y
      state.fitted = Boolean(saved.fitted)
      state.hasUserInteracted = Boolean(saved.hasUserInteracted)
    }
  }
  if (!state.clusterActiveIndices) {
    state.clusterActiveIndices = new Map()
  }
  if (!state.connNodeOverrides) {
    state.connNodeOverrides = getSavedConnNodes(storageKey)
  }
  world.replaceChildren()

  const sections = (data.sections || []).map(s => ({ ...s }))
  let overridesChanged = false
  const connections = (data.connections || []).map(c => {
    const copy = { ...c }
    const pairKey = `${copy.from_section_id}->${copy.to_section_id}`
    const saved = (copy.id && state.connNodeOverrides[copy.id]) || state.connNodeOverrides[pairKey] || null
    if (copy.from_node || copy.to_node) {
      const merged = {
        from_node: copy.from_node || (saved && saved.from_node) || null,
        to_node: copy.to_node || (saved && saved.to_node) || null
      }
      copy.from_node = merged.from_node
      copy.to_node = merged.to_node
      if (copy.id) state.connNodeOverrides[copy.id] = merged
      state.connNodeOverrides[pairKey] = merged
      overridesChanged = true
    } else if (saved) {
      if (saved.from_node) copy.from_node = saved.from_node
      if (saved.to_node) copy.to_node = saved.to_node
    }
    return copy
  })
  if (overridesChanged) {
    saveConnNodes(storageKey, state.connNodeOverrides)
  }
  const parts = data.parts || []
  const paletteItems = data.palette_items || []
  const allSections = data.all_sections || sections

  const dataSignature = `${sections.map(s => `${s.id}:${s.grid_x}:${s.grid_y}`).join("|")}::${connections.map(c => `${c.id}:${c.from_section_id}:${c.to_section_id}:${c.from_node || ''}:${c.to_node || ''}`).join("|")}::${parts.map(p => `${p.id}:${p.section_id}:${p.quantity}:${p.use_description || ''}`).join("|")}::${paletteItems.length}`

  // Track which sections each part_id is placed in (and individual cards/uses per section)
  const partSectionsMap = new Map()
  const partTotalUsesMap = new Map()
  parts.forEach((p) => {
    if (!p.part_id || !p.section_id) return
    partTotalUsesMap.set(p.part_id, (partTotalUsesMap.get(p.part_id) || 0) + 1)
    if (!partSectionsMap.has(p.part_id)) partSectionsMap.set(p.part_id, new Map())
    const secMap = partSectionsMap.get(p.part_id)
    const pQty = Number(p.quantity) || 1
    const pNote = p.use_description || ""
    if (secMap.has(p.section_id)) {
      const entry = secMap.get(p.section_id)
      entry.quantity = (Number(entry.quantity) || 0) + pQty
      if (pNote && !entry.use_description) entry.use_description = pNote
      entry.assignment_ids.push(p.id)
      entry.uses.push({
        assignment_id: p.id,
        quantity: pQty,
        use_description: pNote
      })
    } else {
      secMap.set(p.section_id, {
        quantity: pQty,
        use_description: pNote,
        assignment_ids: [p.id],
        uses: [{
          assignment_id: p.id,
          quantity: pQty,
          use_description: pNote
        }]
      })
    }
  })
  const paletteByPartId = new Map(paletteItems.map(item => [item.part_id, item]))
  const sectionNameById = new Map(allSections.map(s => [s.id, s.name]))
  function partMatchesQuery(p, query) {
    if (!query) return false
    return (
      String(p.part_number || "").toLowerCase().includes(query) ||
      String(p.description || "").toLowerCase().includes(query) ||
      String(p.use_description || "").toLowerCase().includes(query)
    )
  }
  if (state.signature !== dataSignature) {
    state.signature = dataSignature
  }
  summary.textContent = `${sections.length} sections · ${connections.length} connections · ${parts.length} placed parts`

  // Palette toggle
  togglePaletteBtn.onclick = () => {
    palette.classList.toggle("collapsed")
  }
  if (clearFishboneBtn) {
    clearFishboneBtn.onclick = () => {
      component.setTriggerValue("clear_fishbone_request", { timestamp: Date.now() })
    }
  }

  // Add Section Modal Handling
  if (addSectionBtn && addSectionModal) {
    const addSectionError = parentElement.querySelector("#add-section-error")

    function findExistingSectionByName(rawName) {
      const normalized = String(rawName || "").trim().toLowerCase()
      if (!normalized) return null
      const pool = Array.isArray(allSections) && allSections.length > 0 ? allSections : sections
      return pool.find(s => String(s.name || "").trim().toLowerCase() === normalized) || null
    }

    function validateAddSectionName(showEmptyError = false) {
      const name = (addSectionName ? addSectionName.value : "").trim()
      const duplicate = name ? findExistingSectionByName(name) : null
      if (duplicate) {
        if (addSectionError) {
          addSectionError.textContent = `A section named "${duplicate.name}" already exists. Section names must be unique.`
          addSectionError.style.display = "block"
        }
        if (addSectionName) {
          addSectionName.style.borderColor = "#dc2626"
        }
        if (btnAddSectionConfirm) {
          btnAddSectionConfirm.disabled = true
          btnAddSectionConfirm.style.opacity = "0.55"
          btnAddSectionConfirm.style.cursor = "not-allowed"
        }
        return false
      }
      if (!name && showEmptyError) {
        if (addSectionError) {
          addSectionError.textContent = "Please enter a unique section name."
          addSectionError.style.display = "block"
        }
        if (addSectionName) {
          addSectionName.style.borderColor = "#dc2626"
        }
        return false
      }
      if (addSectionError) {
        addSectionError.textContent = ""
        addSectionError.style.display = "none"
      }
      if (addSectionName) {
        addSectionName.style.borderColor = "var(--st-border-color)"
      }
      if (btnAddSectionConfirm) {
        btnAddSectionConfirm.disabled = false
        btnAddSectionConfirm.style.opacity = ""
        btnAddSectionConfirm.style.cursor = ""
      }
      return Boolean(name)
    }

    if (addSectionName) {
      addSectionName.oninput = () => {
        validateAddSectionName(false)
      }
      addSectionName.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault()
          if (btnAddSectionConfirm) btnAddSectionConfirm.click()
        } else if (e.key === "Escape") {
          e.preventDefault()
          addSectionModal.hidden = true
        }
      }
    }
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
        noneOpt.textContent = isSupport ? "(None - Standalone fabrication)" : "(None - Root / final assembly)"
        addSectionParent.appendChild(noneOpt)
        allSections.forEach(s => {
          if (s.inactive) return
          const opt = document.createElement("option")
          opt.value = s.id
          opt.textContent = `${s.name}`
          addSectionParent.appendChild(opt)
        })
      }
    }

    addSectionBtn.onclick = () => {
      if (addSectionName) addSectionName.value = ""
      validateAddSectionName(false)
      if (addSectionType) addSectionType.value = "Assembly"
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
        if (!validateAddSectionName(true)) {
          if (addSectionName) addSectionName.focus()
          return
        }
        const name = (addSectionName ? addSectionName.value : "").trim()
        if (!name) {
          alert("Please enter a section name.")
          return
        }
        const categoryVal = addSectionType ? addSectionType.value : "Assembly"
        const chosenType = categoryVal === "Support Operations" ? "Support Operations" : "Assembly"
        let parentId = addSectionParent && addSectionParent.value ? addSectionParent.value : null
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

  // Replicate / Manage Section Uses Modal Handling
  function openPartUsesModal(targetPart, currentSection) {
    if (!partUsesModal || !partUsesSectionsList || !targetPart) return
    const partId = targetPart.part_id
    const partNumber = targetPart.part_number || "Part"
    const partDesc = targetPart.description || ""
    const paletteItem = paletteByPartId.get(partId) || paletteItems.find(it => it.part_number === partNumber) || null
    const secMap = partSectionsMap.get(partId) || new Map()
    const defaultCatalogQty = (paletteItem && Number(paletteItem.quantity) > 0)
      ? Number(paletteItem.quantity)
      : (Number(targetPart.quantity) > 0 ? Number(targetPart.quantity) : 1)

    if (partUsesTitle) {
      partUsesTitle.textContent = `Replicate / Split Uses: ${partNumber}`
    }
    if (partUsesDesc) {
      partUsesDesc.textContent = partDesc
        ? `${partDesc} — Check every Fishbone section where this item is used, or click "+ Split card" on a section to display multiple cards of this part in the same section:`
        : `Check every Fishbone section where this item is used, or click "+ Split card" on a section to display multiple cards of this part in the same section:`
    }

    const sortedSections = [...allSections].sort((a, b) => {
      const aCurr = (currentSection && a.id === currentSection.id) ? 1 : 0
      const bCurr = (currentSection && b.id === currentSection.id) ? 1 : 0
      if (aCurr !== bCurr) return bCurr - aCurr
      const aPlaced = secMap.has(a.id) ? 1 : 0
      const bPlaced = secMap.has(b.id) ? 1 : 0
      if (aPlaced !== bPlaced) return bPlaced - aPlaced
      return 0
    })

    partUsesSectionsList.replaceChildren()
    const rowRecords = []

    function getActiveCardEntries() {
      const list = []
      rowRecords.forEach(r => {
        if (r.checkbox.checked) {
          r.cardEntries.forEach(ce => list.push({ rowRecord: r, cardEntry: ce }))
        }
      })
      return list
    }

    function updateSummaryBadge() {
      const checkedRows = rowRecords.filter(r => r.checkbox.checked)
      const secCount = checkedRows.length
      const activeCards = getActiveCardEntries()
      const cardCount = activeCards.length
      const totalQty = activeCards.reduce((acc, item) => acc + (parseFloat(item.cardEntry.qtyInput.value) || 0), 0)
      const roundedTotal = Math.round(totalQty * 1000) / 1000
      if (partUsesSummaryBadge) {
        if (cardCount !== secCount) {
          partUsesSummaryBadge.textContent = `Used in ${secCount} section${secCount === 1 ? "" : "s"} (${cardCount} cards) · Total Qty: ${roundedTotal}`
        } else {
          partUsesSummaryBadge.textContent = `Used in ${secCount} section${secCount === 1 ? "" : "s"} · Total Qty: ${roundedTotal}`
        }
      }
    }

    sortedSections.forEach(sec => {
      const existingUse = secMap.get(sec.id)
      const isChecked = Boolean(existingUse) || Boolean(currentSection && sec.id === currentSection.id)
      const initialUses = (existingUse && Array.isArray(existingUse.uses) && existingUse.uses.length > 0)
        ? existingUse.uses.map(u => ({
            assignmentId: u.assignment_id || null,
            quantity: Number(u.quantity) || 1,
            useDescription: u.use_description || ""
          }))
        : [{
            assignmentId: null,
            quantity: existingUse ? existingUse.quantity : defaultCatalogQty,
            useDescription: existingUse ? (existingUse.use_description || "") : ""
          }]

      const row = document.createElement("div")
      row.className = `part-use-row${isChecked ? " active-use" : ""}`

      const header = document.createElement("div")
      header.className = "part-use-row-header"

      const checkLabel = document.createElement("label")
      checkLabel.className = "part-use-check-label"

      const checkbox = document.createElement("input")
      checkbox.type = "checkbox"
      checkbox.checked = isChecked

      const nameSpan = document.createElement("span")
      nameSpan.textContent = sec.name + (currentSection && sec.id === currentSection.id ? " (current)" : "")

      checkLabel.appendChild(checkbox)
      checkLabel.appendChild(nameSpan)
      header.appendChild(checkLabel)

      const headerActions = document.createElement("div")
      headerActions.className = "part-use-header-actions"

      const splitBtn = document.createElement("button")
      splitBtn.type = "button"
      splitBtn.className = "btn-split-sec-use"
      splitBtn.textContent = "+ Split card"
      splitBtn.title = "Split quantity into another separate card in this section"
      splitBtn.hidden = !isChecked
      headerActions.appendChild(splitBtn)

      const typeBadge = document.createElement("span")
      typeBadge.className = "part-use-sec-type"
      typeBadge.textContent = (sec.type === "Main spine" || sec.type === "Subassembly") ? "Assembly" : (sec.type || "Assembly")
      headerActions.appendChild(typeBadge)
      header.appendChild(headerActions)

      const cardsList = document.createElement("div")
      cardsList.className = "part-use-cards-list"
      cardsList.hidden = !isChecked

      const cardEntries = []
      const rowRecord = {
        sectionId: sec.id,
        sectionName: sec.name,
        checkbox,
        cardsList,
        splitBtn,
        cardEntries,
        addCardEntry: null
      }

      function refreshCardIndices() {
        const multi = cardEntries.length > 1
        cardEntries.forEach((ce, idx) => {
          ce.cardIndexBadge.hidden = !multi
          ce.cardIndexBadge.textContent = `Card #${idx + 1}`
          ce.removeBtn.hidden = !multi
        })
      }

      function addCardEntry(useObj) {
        const controls = document.createElement("div")
        controls.className = "part-use-controls"

        const cardIndexBadge = document.createElement("span")
        cardIndexBadge.className = "part-use-card-index"
        cardIndexBadge.hidden = true

        const qtyWrap = document.createElement("label")
        qtyWrap.className = "part-use-qty-wrap"
        const qtySpan = document.createElement("span")
        qtySpan.textContent = "Qty:"
        const qtyInput = document.createElement("input")
        qtyInput.type = "number"
        qtyInput.className = "part-use-qty-input"
        qtyInput.step = "any"
        qtyInput.min = "0.01"
        qtyInput.value = String(useObj.quantity !== undefined ? useObj.quantity : 1)
        qtyInput.oninput = updateSummaryBadge
        qtyWrap.appendChild(qtySpan)
        qtyWrap.appendChild(qtyInput)

        const noteInput = document.createElement("input")
        noteInput.type = "text"
        noteInput.className = "part-use-note-input"
        noteInput.placeholder = "Location / note (e.g. Front LH/RH, Rear)..."
        noteInput.value = useObj.useDescription || ""

        const removeBtn = document.createElement("button")
        removeBtn.type = "button"
        removeBtn.className = "btn-remove-sec-card"
        removeBtn.textContent = "×"
        removeBtn.title = "Remove this split card and merge its quantity back"
        removeBtn.hidden = true

        const entryRecord = {
          assignmentId: useObj.assignmentId || null,
          controlsEl: controls,
          cardIndexBadge,
          qtyInput,
          noteInput,
          removeBtn
        }

        removeBtn.onclick = (e) => {
          e.preventDefault()
          e.stopPropagation()
          if (cardEntries.length <= 1) return
          const idx = cardEntries.indexOf(entryRecord)
          if (idx === -1) return
          const removedQty = parseFloat(qtyInput.value) || 0
          cardEntries.splice(idx, 1)
          controls.remove()
          const targetNeighbor = cardEntries[Math.max(0, idx - 1)]
          if (targetNeighbor && removedQty > 0) {
            const neighborQty = parseFloat(targetNeighbor.qtyInput.value) || 0
            targetNeighbor.qtyInput.value = String(Math.round((neighborQty + removedQty) * 10000) / 10000)
          }
          refreshCardIndices()
          updateSummaryBadge()
        }

        controls.appendChild(cardIndexBadge)
        controls.appendChild(qtyWrap)
        controls.appendChild(noteInput)
        controls.appendChild(removeBtn)
        cardsList.appendChild(controls)

        cardEntries.push(entryRecord)
        refreshCardIndices()
        return entryRecord
      }

      rowRecord.addCardEntry = addCardEntry
      initialUses.forEach(u => addCardEntry(u))

      splitBtn.onclick = (e) => {
        e.preventDefault()
        e.stopPropagation()
        if (!checkbox.checked) {
          checkbox.checked = true
          cardsList.hidden = false
          splitBtn.hidden = false
          row.classList.add("active-use")
        }
        const lastEntry = cardEntries[cardEntries.length - 1]
        const currQty = lastEntry ? (parseFloat(lastEntry.qtyInput.value) || 1) : 1
        let newCardQty = 1
        if (lastEntry && currQty > 1) {
          let firstHalf
          if (Number.isInteger(currQty)) {
            firstHalf = Math.ceil(currQty / 2)
            newCardQty = Math.floor(currQty / 2)
          } else {
            firstHalf = Math.round((currQty / 2) * 10000) / 10000
            newCardQty = Math.round((currQty - firstHalf) * 10000) / 10000
          }
          lastEntry.qtyInput.value = String(firstHalf)
        }
        addCardEntry({
          assignmentId: null,
          quantity: newCardQty > 0 ? newCardQty : 1,
          useDescription: ""
        })
        updateSummaryBadge()
      }

      checkbox.onchange = () => {
        const on = checkbox.checked
        cardsList.hidden = !on
        splitBtn.hidden = !on
        row.classList.toggle("active-use", on)
        updateSummaryBadge()
      }

      row.appendChild(header)
      row.appendChild(cardsList)
      partUsesSectionsList.appendChild(row)

      rowRecords.push(rowRecord)
    })

    updateSummaryBadge()

    if (btnPartUsesSameQty) {
      btnPartUsesSameQty.onclick = () => {
        const activeCards = getActiveCardEntries()
        if (activeCards.length === 0) return
        const refQty = parseFloat(activeCards[0].cardEntry.qtyInput.value) || defaultCatalogQty || 1
        activeCards.forEach(item => {
          item.cardEntry.qtyInput.value = String(refQty)
        })
        updateSummaryBadge()
      }
    }

    if (btnPartUsesSplitQty) {
      btnPartUsesSplitQty.onclick = () => {
        const checkedRows = rowRecords.filter(r => r.checkbox.checked)
        if (checkedRows.length === 0) return
        let activeCards = getActiveCardEntries()
        // If only 1 section is checked with 1 card, automatically add a 2nd card in that section to split into
        if (activeCards.length === 1 && checkedRows.length === 1 && checkedRows[0].addCardEntry) {
          checkedRows[0].addCardEntry({
            assignmentId: null,
            quantity: 1,
            useDescription: ""
          })
          activeCards = getActiveCardEntries()
        }
        if (activeCards.length === 0) return
        const currentSum = activeCards.reduce((acc, item) => acc + (parseFloat(item.cardEntry.qtyInput.value) || 0), 0)
        const baseTotal = defaultCatalogQty > 1 ? defaultCatalogQty : (currentSum > 0 ? currentSum : 1)
        const splitVal = Math.round((baseTotal / activeCards.length) * 10000) / 10000
        activeCards.forEach(item => {
          item.cardEntry.qtyInput.value = String(splitVal)
        })
        updateSummaryBadge()
      }
    }

    const hasChildren = Boolean(paletteItem && paletteItem.is_assembly && Array.isArray(paletteItem.child_parts) && paletteItem.child_parts.length > 0)
    if (partUsesChildrenWrap) {
      partUsesChildrenWrap.hidden = !hasChildren
      if (hasChildren && partUsesChildrenLabel) {
        partUsesChildrenLabel.textContent = `Also replicate ${paletteItem.child_parts.length} sub-component part(s) into newly selected sections`
      }
      if (partUsesIncludeChildren) {
        partUsesIncludeChildren.checked = true
      }
    }

    if (btnPartUsesCancel) {
      btnPartUsesCancel.onclick = () => {
        partUsesModal.hidden = true
      }
    }

    if (btnPartUsesConfirm) {
      btnPartUsesConfirm.onclick = () => {
        const selectedUses = []
        rowRecords.forEach(r => {
          if (!r.checkbox.checked) return
          r.cardEntries.forEach(ce => {
            const q = parseFloat(ce.qtyInput.value)
            selectedUses.push({
              assignment_id: ce.assignmentId || null,
              section_id: r.sectionId,
              quantity: (isFinite(q) && q > 0) ? q : 1,
              use_description: (ce.noteInput.value || "").trim()
            })
          })
        })
        partUsesModal.hidden = true
        component.setTriggerValue("replicate_part_uses", {
          part_id: partId,
          part_number: partNumber,
          source_section_id: currentSection ? currentSection.id : null,
          include_children: Boolean(hasChildren && partUsesIncludeChildren && partUsesIncludeChildren.checked),
          section_uses: selectedUses
        })
      }
    }

    partUsesModal.hidden = false
  }

  if (partUsesModal) {
    partUsesModal.onclick = (e) => {
      if (e.target === partUsesModal) partUsesModal.hidden = true
    }
  }

  // Edit Model Variant Ties Modal Handling (triggered by clicking N× badge)
  function openVariantTiesModal(cluster, currentSection) {
    if (!variantTiesModal || !variantTiesList || !cluster || !Array.isArray(cluster.parts)) return
    const secName = currentSection ? currentSection.name : "Section"
    const initialItems = []
    const stackPartNumbersUpper = new Set()

    cluster.parts.forEach((p, idx) => {
      const pn = String(p.part_number || "").trim()
      if (!pn) return
      const key = pn.toUpperCase()
      stackPartNumbersUpper.add(key)
      initialItems.push({
        assignment_id: p.id || "",
        part_id: p.part_id || "",
        part_number: pn,
        description: p.description || "",
        use_description: p.use_description || "",
        image: p.image || "",
        quantity: p.quantity || 1,
        models: p.models || "All models",
        in_stack: true,
        stack_idx: idx,
        is_added: false,
      })
    })

    // Also include any catalog variant peers linked to parts in this stack
    const seenPeerUpper = new Set(stackPartNumbersUpper)
    cluster.parts.forEach((p) => {
      const peers = parseVariantGroup(p.variant_group)
      peers.forEach((peerUpper) => {
        if (seenPeerUpper.has(peerUpper)) return
        seenPeerUpper.add(peerUpper)
        const palMatch = paletteItems.find(
          it => String(it.part_number || "").trim().toUpperCase() === peerUpper
        )
        const placedMatch = parts.find(
          it => String(it.part_number || "").trim().toUpperCase() === peerUpper
        )
        const ref = placedMatch || palMatch
        initialItems.push({
          assignment_id: placedMatch ? (placedMatch.id || "") : "",
          part_id: ref ? (ref.part_id || "") : "",
          part_number: ref ? (ref.part_number || peerUpper) : peerUpper,
          description: ref ? (ref.description || "") : "",
          use_description: placedMatch ? (placedMatch.use_description || "") : "",
          image: ref ? (ref.image || "") : "",
          quantity: ref ? (ref.quantity || 1) : 1,
          models: (placedMatch && placedMatch.models) ? placedMatch.models : "Catalog variant peer",
          in_stack: false,
          stack_idx: -1,
          is_added: false,
        })
      })
    })

    if (variantTiesTitle) {
      variantTiesTitle.textContent = `Edit Model Variant Ties (${cluster.parts.length}× stack)`
    }
    if (variantTiesDesc) {
      variantTiesDesc.textContent = `Section "${secName}" — Uncheck any part below to disconnect it from this model variant group so it displays as a separate card:`
    }

    variantTiesList.replaceChildren()
    const rowRecords = []

    function updateVariantSummary() {
      const tiedCount = rowRecords.filter(r => r.checkbox.checked).length
      const untiedCount = rowRecords.length - tiedCount
      if (variantTiesSummaryBadge) {
        if (tiedCount < 2) {
          variantTiesSummaryBadge.textContent = `All ${rowRecords.length} parts will be untied into separate cards`
          variantTiesSummaryBadge.style.color = "#d97706"
          variantTiesSummaryBadge.style.background = "rgba(217, 119, 6, 0.14)"
        } else if (untiedCount > 0) {
          variantTiesSummaryBadge.textContent = `${tiedCount} tied · ${untiedCount} to disconnect`
          variantTiesSummaryBadge.style.color = "#4f46e5"
          variantTiesSummaryBadge.style.background = "rgba(79, 70, 229, 0.12)"
        } else {
          variantTiesSummaryBadge.textContent = `${tiedCount} parts tied in variant group`
          variantTiesSummaryBadge.style.color = "#4f46e5"
          variantTiesSummaryBadge.style.background = "rgba(79, 70, 229, 0.12)"
        }
      }
    }

    function populateAddSelect() {
      if (!variantTiesAddSelect) return
      variantTiesAddSelect.replaceChildren()
      const placeholder = document.createElement("option")
      placeholder.value = ""
      placeholder.textContent = "Optional: select another part to tie into this variant group..."
      variantTiesAddSelect.appendChild(placeholder)

      const existingKeys = new Set(rowRecords.map(r => r.partNumber.toUpperCase()))
      const sectionPartUpper = new Set(
        parts
          .filter(p => currentSection && p.section_id === currentSection.id)
          .map(p => String(p.part_number || "").trim().toUpperCase())
          .filter(Boolean)
      )

      const candidates = []
      const seenCand = new Set()
      parts.forEach(p => {
        const pn = String(p.part_number || "").trim()
        const up = pn.toUpperCase()
        if (!pn || existingKeys.has(up) || seenCand.has(up)) return
        seenCand.add(up)
        candidates.push({
          part_id: p.part_id || "",
          part_number: pn,
          description: p.description || "",
          image: p.image || "",
          quantity: p.quantity || 1,
          models: p.models || "All models",
          in_current_section: sectionPartUpper.has(up),
        })
      })
      paletteItems.forEach(it => {
        const pn = String(it.part_number || "").trim()
        const up = pn.toUpperCase()
        if (!pn || pn === "—" || existingKeys.has(up) || seenCand.has(up)) return
        seenCand.add(up)
        candidates.push({
          part_id: it.part_id || "",
          part_number: pn,
          description: it.description || "",
          image: it.image || "",
          quantity: it.quantity || 1,
          models: "Catalog part",
          in_current_section: sectionPartUpper.has(up),
        })
      })

      candidates.sort((a, b) => {
        if (a.in_current_section !== b.in_current_section) {
          return a.in_current_section ? -1 : 1
        }
        return a.part_number.localeCompare(b.part_number)
      })

      candidates.forEach(c => {
        const opt = document.createElement("option")
        opt.value = c.part_number
        const prefix = c.in_current_section ? `[In ${secName}] ` : ""
        opt.textContent = `${prefix}${c.part_number}${c.description ? ` — ${c.description}` : ""}`
        opt.dataset.partJson = JSON.stringify(c)
        variantTiesAddSelect.appendChild(opt)
      })
    }

    function appendVariantRow(item) {
      const row = document.createElement("div")
      row.className = "variant-tie-row active-tie"

      const leftLabel = document.createElement("label")
      leftLabel.className = "part-use-check-label"
      leftLabel.style.gap = "10px"

      const checkbox = document.createElement("input")
      checkbox.type = "checkbox"
      checkbox.checked = true

      let thumbEl
      if (item.image) {
        thumbEl = document.createElement("img")
        thumbEl.className = "palette-thumb"
        thumbEl.style.width = "34px"
        thumbEl.style.height = "34px"
        thumbEl.src = item.image
        thumbEl.alt = item.part_number
      } else {
        thumbEl = document.createElement("div")
        thumbEl.className = "palette-no-thumb"
        thumbEl.style.width = "34px"
        thumbEl.style.height = "34px"
        thumbEl.textContent = "PART"
      }

      const textCol = document.createElement("div")
      textCol.style.display = "flex"
      textCol.style.flexDirection = "column"
      textCol.style.minWidth = "0"
      textCol.style.flex = "1"
      textCol.style.gap = "2px"

      const pnLine = document.createElement("div")
      pnLine.style.display = "flex"
      pnLine.style.alignItems = "center"
      pnLine.style.gap = "6px"
      const pnStrong = document.createElement("strong")
      pnStrong.style.fontSize = ".85rem"
      pnStrong.style.color = "var(--st-primary-color)"
      pnStrong.textContent = item.part_number
      pnLine.appendChild(pnStrong)

      if (item.in_stack) {
        const stackTag = document.createElement("span")
        stackTag.className = "part-use-sec-type"
        stackTag.textContent = item.use_description
          ? `Qty ${item.quantity || 1} · ${item.use_description}`
          : `Qty ${item.quantity || 1}`
        pnLine.appendChild(stackTag)
      } else {
        const peerTag = document.createElement("span")
        peerTag.className = "part-use-sec-type"
        peerTag.textContent = item.is_added ? "Added to group" : "Linked in catalog"
        pnLine.appendChild(peerTag)
      }

      const descLine = document.createElement("div")
      descLine.style.fontSize = ".76rem"
      descLine.style.color = "var(--st-secondary-text-color)"
      descLine.style.whiteSpace = "nowrap"
      descLine.style.overflow = "hidden"
      descLine.style.textOverflow = "ellipsis"
      descLine.textContent = `${item.description || "—"}${item.models ? ` · ${item.models}` : ""}`

      textCol.appendChild(pnLine)
      textCol.appendChild(descLine)

      leftLabel.appendChild(checkbox)
      leftLabel.appendChild(thumbEl)
      leftLabel.appendChild(textCol)

      const rightControls = document.createElement("div")
      rightControls.style.display = "flex"
      rightControls.style.alignItems = "center"
      rightControls.style.gap = "6px"

      const statusPill = document.createElement("span")
      statusPill.className = "variant-tie-status-pill tied"
      statusPill.textContent = "Tied"
      statusPill.title = "Click to toggle tie / untie"

      function syncRowVisual() {
        const on = checkbox.checked
        row.classList.toggle("active-tie", on)
        row.classList.toggle("untied-row", !on)
        statusPill.className = `variant-tie-status-pill ${on ? "tied" : "untied"}`
        statusPill.textContent = on ? "Tied" : "Untie"
        updateVariantSummary()
      }

      checkbox.onchange = syncRowVisual
      statusPill.onclick = (e) => {
        e.preventDefault()
        e.stopPropagation()
        checkbox.checked = !checkbox.checked
        syncRowVisual()
      }

      rightControls.appendChild(statusPill)
      row.appendChild(leftLabel)
      row.appendChild(rightControls)
      variantTiesList.appendChild(row)

      rowRecords.push({
        assignmentId: item.assignment_id || "",
        partId: item.part_id,
        partNumber: item.part_number,
        inStack: Boolean(item.in_stack),
        isAdded: Boolean(item.is_added),
        checkbox,
        syncRowVisual,
      })
    }

    initialItems.forEach(item => appendVariantRow(item))
    updateVariantSummary()
    populateAddSelect()

    if (btnVariantTiesUntieAll) {
      btnVariantTiesUntieAll.onclick = () => {
        rowRecords.forEach(r => {
          r.checkbox.checked = false
          r.syncRowVisual()
        })
      }
    }

    if (btnVariantTiesAddPart && variantTiesAddSelect) {
      btnVariantTiesAddPart.onclick = () => {
        const selOpt = variantTiesAddSelect.options[variantTiesAddSelect.selectedIndex]
        if (!selOpt || !selOpt.value) return
        let parsed = null
        try {
          parsed = JSON.parse(selOpt.dataset.partJson || "{}")
        } catch (e) {}
        const pn = (parsed && parsed.part_number) ? parsed.part_number : selOpt.value
        appendVariantRow({
          assignment_id: (parsed && parsed.assignment_id) || "",
          part_id: (parsed && parsed.part_id) || "",
          part_number: pn,
          description: (parsed && parsed.description) || "",
          use_description: (parsed && parsed.use_description) || "",
          image: (parsed && parsed.image) || "",
          quantity: (parsed && parsed.quantity) || 1,
          models: "Added to variant group",
          in_stack: false,
          stack_idx: -1,
          is_added: true,
        })
        updateVariantSummary()
        populateAddSelect()
      }
    }

    if (btnVariantTiesCancel) {
      btnVariantTiesCancel.onclick = () => {
        variantTiesModal.hidden = true
      }
    }

    if (btnVariantTiesConfirm) {
      btnVariantTiesConfirm.onclick = () => {
        const checkedRecords = rowRecords.filter(r => r.checkbox.checked)
        const uncheckedRecords = rowRecords.filter(r => !r.checkbox.checked)
        let untiedPartNumbers = []
        let keptPartNumbers = []
        let addedPartNumbers = []
        let untiedAssignmentIds = []
        let keptAssignmentIds = []
        let addedAssignmentIds = []

        if (checkedRecords.length < 2) {
          // Fewer than 2 cards remain checked -> disconnect all cards in the stack
          untiedPartNumbers = Array.from(new Set(rowRecords.filter(r => !r.isAdded).map(r => r.partNumber)))
          keptPartNumbers = []
          untiedAssignmentIds = rowRecords.filter(r => !r.isAdded && r.assignmentId).map(r => r.assignmentId)
          keptAssignmentIds = []
        } else {
          const checkedUpperSet = new Set(checkedRecords.map(r => r.partNumber.toUpperCase()))
          untiedPartNumbers = Array.from(
            new Set(
              uncheckedRecords
                .filter(r => !r.isAdded && !checkedUpperSet.has(r.partNumber.toUpperCase()))
                .map(r => r.partNumber)
            )
          )
          keptPartNumbers = Array.from(new Set(checkedRecords.map(r => r.partNumber)))
          addedPartNumbers = Array.from(new Set(checkedRecords.filter(r => r.isAdded).map(r => r.partNumber)))
          untiedAssignmentIds = uncheckedRecords.filter(r => !r.isAdded && r.assignmentId).map(r => r.assignmentId)
          keptAssignmentIds = checkedRecords.filter(r => r.assignmentId).map(r => r.assignmentId)
          addedAssignmentIds = checkedRecords.filter(r => r.isAdded && r.assignmentId).map(r => r.assignmentId)
        }

        variantTiesModal.hidden = true
        if (
          untiedPartNumbers.length > 0 ||
          addedPartNumbers.length > 0 ||
          untiedAssignmentIds.length > 0 ||
          addedAssignmentIds.length > 0
        ) {
          component.setTriggerValue("unstack_part_variant", {
            untied_part_numbers: untiedPartNumbers,
            kept_part_numbers: keptPartNumbers,
            added_part_numbers: addedPartNumbers,
            untied_assignment_ids: untiedAssignmentIds,
            kept_assignment_ids: keptAssignmentIds,
            added_assignment_ids: addedAssignmentIds,
            section_id: currentSection ? currentSection.id : null
          })
        }
      }
    }

    variantTiesModal.hidden = false
  }

  if (variantTiesModal) {
    variantTiesModal.onclick = (e) => {
      if (e.target === variantTiesModal) variantTiesModal.hidden = true
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
      if (!query) {
        if (unplacedOnly && isPlaced) return false
        return true
      }
      return (
        (item.part_number || "").toLowerCase().includes(query) ||
        (item.description || "").toLowerCase().includes(query)
      )
    })

    paletteCount.textContent = `${filtered.length} of ${paletteItems.length}`

    filtered.forEach(item => {
      const isPlaced = placedPartIds.has(item.part_id)
      const isFocused = Boolean(state.focusedPartId && state.focusedPartId === item.part_id)
      const card = document.createElement("div")
      card.className = `palette-card${isPlaced ? " placed" : ""}${isFocused ? " search-focused" : ""}`
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

      if (isPlaced && partSectionsMap.has(item.part_id)) {
        const secMap = partSectionsMap.get(item.part_id)
        const pillsWrap = document.createElement("div")
        pillsWrap.className = "palette-sec-pills"
        secMap.forEach((_, secId) => {
          const secName = sectionNameById.get(secId) || "Section"
          const pill = document.createElement("span")
          pill.className = "palette-sec-pill"
          pill.textContent = `📍 ${secName}`
          pill.title = `Click to zoom to "${secName}" and highlight ${item.part_number}`
          pill.onclick = (e) => {
            e.stopPropagation()
            state.focusedPartId = item.part_id
            state.focusedSectionId = secId
            if (syncClusterActiveIndicesForSearch()) {
              state.pendingSearchZoom = true
              renderWorld()
            } else {
              renderPalette()
              applySearchHighlightAndZoom({ zoomToMatch: true })
            }
          }
          pillsWrap.appendChild(pill)
        })
        info.appendChild(pillsWrap)
      }

      const meta = document.createElement("div")
      meta.className = "palette-meta"
      const secCount = partSectionsMap.has(item.part_id) ? partSectionsMap.get(item.part_id).size : 0
      const totalUsesCount = partTotalUsesMap.get(item.part_id) || 0
      meta.textContent = secCount > 1
        ? `Qty ${item.quantity || 1} · ${secCount} sections`
        : (totalUsesCount > 1 ? `Qty ${item.quantity || 1} · ${totalUsesCount} cards` : `Qty ${item.quantity || 1}`)
      if (item.is_assembly) {
        const badge = document.createElement("span")
        badge.className = "palette-badge"
        badge.textContent = `Asm (${item.child_count})`
        meta.appendChild(badge)
      }
      const repBtn = document.createElement("button")
      repBtn.type = "button"
      repBtn.className = "palette-replicate-btn"
      repBtn.title = "Place, replicate across sections, or split quantity into multiple cards"
      repBtn.textContent = totalUsesCount > 0 ? `+ Uses (${totalUsesCount})` : "+ Multi-use"
      repBtn.onclick = (e) => {
        e.stopPropagation()
        e.preventDefault()
        openPartUsesModal(item, null)
      }
      meta.appendChild(repBtn)
      info.appendChild(meta)

      card.appendChild(info)

      if (isPlaced) {
        card.title = "Click to zoom to and highlight this part in the Fishbone (or drag to place again)"
        card.onclick = (e) => {
          if (e.target.closest(".palette-replicate-btn") || e.target.closest(".palette-sec-pill")) return
          state.focusedPartId = item.part_id
          state.focusedSectionId = null
          if (syncClusterActiveIndicesForSearch()) {
            state.pendingSearchZoom = true
            renderWorld()
          } else {
            renderPalette()
            applySearchHighlightAndZoom({ zoomToMatch: true })
          }
        }
      }

      card.ondragstart = (e) => {
        e.dataTransfer.setData("application/json", JSON.stringify(item))
        e.dataTransfer.effectAllowed = "copy"
      }

      paletteList.appendChild(card)
    })
  }

  paletteSearch.oninput = () => {
    state.focusedPartId = null
    state.focusedSectionId = null
    if (syncClusterActiveIndicesForSearch()) {
      state.pendingSearchZoom = true
      renderWorld()
    } else {
      renderPalette()
      applySearchHighlightAndZoom({ zoomToMatch: true })
    }
  }
  paletteUnplacedOnly.onchange = () => {
    renderPalette()
  }
  renderPalette()

  // Helper for clustering similar parts (same base drawing number, differing suffix, segregated by P vs G, or manual Variant group)
  function getPartBaseCode(pn) {
    const clean = String(pn || "").trim().toUpperCase()
    // Match base drawing number, followed by P (piece part) or G (group/assembly), followed by sequence/variant
    const match = clean.match(/^([A-Z0-9#]+?)[-_\\s]?([PG])[-_\\s]?(\\d{1,5}[A-Z]?|[#X]+)(?:_.*)?$/)
    if (match && match[1].length >= 4) {
      return `${match[1]}-${match[2]}`
    }
    return clean
  }

  function parseVariantGroup(val) {
    if (!val) return []
    if (Array.isArray(val)) {
      return val.map(v => String(v || "").trim().toUpperCase()).filter(Boolean)
    }
    return String(val).split(",").map(v => v.trim().toUpperCase()).filter(Boolean)
  }

  function clusterSectionParts(secPartsList, secId) {
    const clusters = []
    const stackGroupCounts = new Map()
    secPartsList.forEach(item => {
      const sg = Number(item.stack_group || 0) > 1 ? Number(item.stack_group) : 0
      if (sg > 0) stackGroupCounts.set(sg, (stackGroupCounts.get(sg) || 0) + 1)
    })

    secPartsList.forEach(p => {
      const pNum = String(p.part_number || "").trim().toUpperCase()
      const base = getPartBaseCode(pNum)
      const hasResolvedVariantGroup = Array.isArray(p.variant_group)
      const peers = parseVariantGroup(p.variant_group)
      const rawStackGroup = Number(p.stack_group || 0) > 1 ? Number(p.stack_group) : 0
      const activeStackGroup = (rawStackGroup > 0 && (stackGroupCounts.get(rawStackGroup) || 0) >= 2) ? rawStackGroup : 0

      let matchingClusters = []
      if (activeStackGroup > 0) {
        matchingClusters = clusters.filter(cl => cl.stackGroups && cl.stackGroups.has(activeStackGroup))
      } else {
        matchingClusters = clusters.filter(cl => {
          // Do NOT merge an unstacked card into an explicit canvas stack group if that stack group already has this part
          const alreadyHasSamePart = cl.parts.some(item =>
            (p.part_id && item.part_id === p.part_id) ||
            (pNum && String(item.part_number || "").trim().toUpperCase() === pNum)
          )
          if (alreadyHasSamePart) return false
          if (cl.stackGroups && cl.stackGroups.size > 0) return false
          if (!hasResolvedVariantGroup && base && cl.baseCodes.has(base)) return true
          if (pNum && cl.memberPartNumbers.has(pNum)) return true
          for (const peer of peers) {
            if (cl.memberPartNumbers.has(peer)) return true
          }
          return false
        })
      }
      let cl
      if (matchingClusters.length === 0) {
        const keyToken = activeStackGroup > 0
          ? `sg_${activeStackGroup}`
          : ((!hasResolvedVariantGroup || peers.length > 0) ? (base || pNum) : pNum)
        const sameKeyCount = clusters.filter(c => c.baseKeyToken === keyToken).length
        const clusterKey = sameKeyCount === 0 ? `${secId}:${keyToken}` : `${secId}:${keyToken}#${sameKeyCount + 1}`
        const activeIdx = (state.clusterActiveIndices && state.clusterActiveIndices.get(clusterKey)) || 0
        cl = {
          baseCode: base || pNum,
          baseKeyToken: keyToken,
          clusterKey: clusterKey,
          baseCodes: new Set(base ? [base] : []),
          memberPartNumbers: new Set(),
          stackGroups: new Set(activeStackGroup > 0 ? [activeStackGroup] : []),
          parts: [],
          activeIdx: activeIdx
        }
        clusters.push(cl)
      } else {
        cl = matchingClusters[matchingClusters.length - 1]
        for (let m = 0; m < matchingClusters.length - 1; m++) {
          const other = matchingClusters[m]
          const sharesExplicitGroup = activeStackGroup > 0 && other.stackGroups && other.stackGroups.has(activeStackGroup)
          const sharesPart = other.parts.some(op =>
            cl.parts.some(cp =>
              (op.part_id && cp.part_id === op.part_id) ||
              (op.part_number && cp.part_number && String(op.part_number).trim().toUpperCase() === String(cp.part_number).trim().toUpperCase())
            )
          )
          if (sharesPart && !sharesExplicitGroup) continue
          other.baseCodes.forEach(bc => cl.baseCodes.add(bc))
          other.memberPartNumbers.forEach(mpn => cl.memberPartNumbers.add(mpn))
          if (other.stackGroups) other.stackGroups.forEach(sg => cl.stackGroups.add(sg))
          other.parts.forEach(op => cl.parts.push(op))
          const idx = clusters.indexOf(other)
          if (idx !== -1) clusters.splice(idx, 1)
        }
      }
      if (base) cl.baseCodes.add(base)
      if (pNum) cl.memberPartNumbers.add(pNum)
      if (activeStackGroup > 0) cl.stackGroups.add(activeStackGroup)
      peers.forEach(peer => cl.memberPartNumbers.add(peer))

      const copy = Object.assign({}, p, {
        assignment_ids: [p.id]
      })
      cl.parts.push(copy)
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
  partsBySection.forEach((secList) => {
    secList.sort((a, b) => (Number(a.sequence) || 0) - (Number(b.sequence) || 0))
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

  function syncClusterActiveIndicesForSearch() {
    const query = (paletteSearch.value || "").trim().toLowerCase()
    const focusedPartId = state.focusedPartId ? String(state.focusedPartId) : null
    const focusedSectionId = state.focusedSectionId ? String(state.focusedSectionId) : null
    if (!query && !focusedPartId) return false
    let changed = false
    sections.forEach((sec) => {
      if (focusedSectionId && String(sec.id) !== focusedSectionId) return
      ;(sec.partClusters || []).forEach((cl) => {
        if (!cl.parts || cl.parts.length <= 1) return
        const curIdx = (cl.activeIdx || 0) % cl.parts.length
        const curPart = cl.parts[curIdx]
        const matchesTarget = (p) => {
          if (focusedPartId) return String(p.part_id || p.id) === focusedPartId
          return partMatchesQuery(p, query)
        }
        if (curPart && matchesTarget(curPart)) return
        const matchIdx = cl.parts.findIndex(matchesTarget)
        if (matchIdx >= 0 && matchIdx !== curIdx) {
          cl.activeIdx = matchIdx
          state.clusterActiveIndices.set(cl.clusterKey, matchIdx)
          changed = true
        }
      })
    })
    return changed
  }
  syncClusterActiveIndicesForSearch()

  // Layers
  const edgeLayer = svgElement("g", { id: "edge-layer" })
  const sectionLayer = svgElement("g", { id: "section-layer" })
  const activeEdgeLayer = svgElement("g", { id: "active-edge-layer" })
  const handleLayer = svgElement("g", { id: "handle-layer" })
  const ghostLayer = svgElement("g", { id: "ghost-layer" })
  world.appendChild(edgeLayer)
  world.appendChild(sectionLayer)
  world.appendChild(activeEdgeLayer)
  world.appendChild(handleLayer)
  world.appendChild(ghostLayer)

  // Auto-arrange sections logically
  autoArrangeBtn.onclick = () => {
    state.hasUserInteracted = false
    state.fitted = false
    state.connNodeOverrides = {}
    clearSavedConnNodes(storageKey)
    try {
      sessionStorage.removeItem("paag_fishbone_view_" + storageKey)
      if (window.__paag_fishbone_views) delete window.__paag_fishbone_views[storageKey]
    } catch (e) {}
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

  // Draw Connections (Smooth Parent / Child Flow Arrows with Edge Snap Points)
  const resolvedConns = resolveConnectionEndpoints(connections, sectionById)
  const edgeRefs = []

  const selectedResolved = resolvedConns.find(rc => rc.conn.id === state.selectedConnId) || null
  const orderedConns = [...resolvedConns].sort((a, b) => {
    const aSel = a.conn.id === state.selectedConnId ? 1 : 0
    const bSel = b.conn.id === state.selectedConnId ? 1 : 0
    return aSel - bSel
  })

  orderedConns.forEach(({ conn, start, end, p1, p2 }) => {
    const targetEdgeLayer = (state.selectedConnId === conn.id) ? activeEdgeLayer : edgeLayer
    const isFromSupport = start.type === "Support Operations"
    const isSelected = state.selectedConnId === conn.id

    const curve = computeSmoothConnectionPath(p1, p2)
    const pathData = curve.d
    const midX = curve.midX
    const midY = curve.midY

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
      id: "conn-path-" + conn.id,
      d: pathData,
      fill: "none",
      stroke: color,
      "stroke-width": isSelected ? 4.5 : 3,
      "stroke-linecap": "round",
      "marker-end": marker,
      "data-conn-id": conn.id,
      class: `conn-line${isSelected ? " selected" : ""}`
    })
    if (isFromSupport) {
      path.setAttribute("stroke-dasharray", "6 4")
    }

    const hitArea = svgElement("path", {
      d: pathData,
      fill: "none",
      stroke: "transparent",
      "stroke-width": 26,
      "data-conn-id": conn.id,
      class: "conn-hit-area"
    })

    hitArea.onmousedown = (e) => {
      e.stopPropagation()
      const rect = svg.getBoundingClientRect()
      const clickX = (e.clientX - rect.left - state.x) / state.scale
      const clickY = (e.clientY - rect.top - state.y) / state.scale
      if (!isSelected && selectedResolved) {
        const sd1 = Math.hypot(clickX - selectedResolved.p1.x, clickY - selectedResolved.p1.y)
        const sd2 = Math.hypot(clickX - selectedResolved.p2.x, clickY - selectedResolved.p2.y)
        if (sd1 <= 28 || sd2 <= 28) {
          const selHandleType = (sd1 <= sd2) ? "start" : "end"
          state.hasUserInteracted = true
          state.reconnectingConnection = {
            handleType: selHandleType,
            connId: selectedResolved.conn.id,
            fromId: selectedResolved.start.id,
            fromName: selectedResolved.start.name,
            oldToId: selectedResolved.end.id,
            fromNode: selectedResolved.p1.id,
            toNode: selectedResolved.p2.id,
            p1: selectedResolved.p1,
            p2: selectedResolved.p2,
            fixedPoint: (selHandleType === "start") ? selectedResolved.p2 : selectedResolved.p1,
            connType: selectedResolved.conn.connection_type || "subassembly",
            originX: e.clientX,
            originY: e.clientY,
            isDrag: false,
            fromHandle: true
          }
          return
        }
      }
      const d1 = Math.hypot(clickX - p1.x, clickY - p1.y)
      const d2 = Math.hypot(clickX - p2.x, clickY - p2.y)
      const handleType = (d1 < d2) ? "start" : "end"
      state.reconnectingConnection = {
        handleType: handleType,
        connId: conn.id,
        fromId: start.id,
        fromName: start.name,
        oldToId: end.id,
        fromNode: p1.id,
        toNode: p2.id,
        p1: p1,
        p2: p2,
        fixedPoint: (handleType === "start") ? p2 : p1,
        connType: conn.connection_type || "subassembly",
        originX: e.clientX,
        originY: e.clientY,
        isDrag: false,
        fromHandle: false
      }
    }

    hitArea.onclick = (e) => {
      e.stopPropagation()
    }

    targetEdgeLayer.appendChild(path)
    targetEdgeLayer.appendChild(hitArea)

    // Storage Buffer badge for Support Operations
    let bufGroup = null
    if (isFromSupport && !isSelected) {
      bufGroup = svgElement("g", {
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
      targetEdgeLayer.appendChild(bufGroup)
    }

    // Start-point handle for adjusting where the arrow leaves the source section
    const startHandleG = svgElement("g", {
      class: "conn-handle-group",
      "data-conn-id": conn.id,
      title: "Drag to change start snap node on this section"
    })
    const startHit = svgElement("circle", {
      cx: p1.x, cy: p1.y, r: isSelected ? 22 : 18,
      fill: "transparent", stroke: "transparent"
    })
    const startDot = svgElement("circle", {
      cx: p1.x, cy: p1.y,
      r: isSelected ? 8 : 6.5,
      fill: isSelected ? "#ef4444" : "#3b82f6",
      stroke: "white", "stroke-width": 2,
      class: "conn-start-handle"
    })
    startHandleG.appendChild(startHit)
    startHandleG.appendChild(startDot)
    startHandleG.onmousedown = (e) => {
      e.stopPropagation()
      state.hasUserInteracted = true
      state.reconnectingConnection = {
        handleType: "start",
        connId: conn.id,
        fromId: start.id,
        fromName: start.name,
        oldToId: end.id,
        fromNode: p1.id,
        toNode: p2.id,
        p1: p1,
        p2: p2,
        fixedPoint: p2,
        fromHandle: true,
        connType: conn.connection_type || "subassembly",
        originX: e.clientX,
        originY: e.clientY,
        isDrag: false
      }
    }
    if (!isSelected && selectedResolved) {
      const sharesWithSelectedStart = (selectedResolved.start.id === start.id && selectedResolved.p1.id === p1.id)
      const sharesWithSelectedEnd = (selectedResolved.end.id === start.id && selectedResolved.p2.id === p1.id)
      if (sharesWithSelectedStart || sharesWithSelectedEnd) {
        startHandleG.style.pointerEvents = "none"
      }
    }
    handleLayer.appendChild(startHandleG)

    // Arrow-end handle for dragging to a different snap node or different section
    const endHandleG = svgElement("g", {
      class: "conn-handle-group",
      "data-conn-id": conn.id,
      title: "Drag arrowhead to snap to any node on this section, or move to another section"
    })
    const endHit = svgElement("circle", {
      cx: p2.x, cy: p2.y, r: isSelected ? 24 : 20,
      fill: "transparent", stroke: "transparent"
    })
    const endDot = svgElement("circle", {
      cx: p2.x, cy: p2.y,
      r: isSelected ? 8.5 : 7,
      fill: isSelected ? "#ef4444" : (isFromSupport ? "#64748b" : "#2563eb"),
      stroke: "white", "stroke-width": 2,
      class: "conn-arrow-handle"
    })
    endHandleG.appendChild(endHit)
    endHandleG.appendChild(endDot)
    endHandleG.onmousedown = (e) => {
      e.stopPropagation()
      state.hasUserInteracted = true
      state.reconnectingConnection = {
        handleType: "end",
        connId: conn.id,
        fromId: start.id,
        fromName: start.name,
        oldToId: end.id,
        fromNode: p1.id,
        toNode: p2.id,
        p1: p1,
        p2: p2,
        fixedPoint: p1,
        fromHandle: true,
        connType: conn.connection_type || "subassembly",
        originX: e.clientX,
        originY: e.clientY,
        isDrag: false
      }
    }
    if (!isSelected && selectedResolved) {
      const sharesWithSelectedStart = (selectedResolved.start.id === end.id && selectedResolved.p1.id === p2.id)
      const sharesWithSelectedEnd = (selectedResolved.end.id === end.id && selectedResolved.p2.id === p2.id)
      if (sharesWithSelectedStart || sharesWithSelectedEnd) {
        endHandleG.style.pointerEvents = "none"
      }
    }
    handleLayer.appendChild(endHandleG)

    // Selected Connection Action Button (Red X)
    let delGroup = null
    if (isSelected) {
      delGroup = svgElement("g", {
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

      delGroup.onclick = (e) => {
        e.stopPropagation()
        openConnEditModal({
          connId: conn.id,
          fromId: start.id,
          fromName: start.name,
          oldToId: end.id,
          connType: conn.connection_type || "subassembly"
        })
      }
      handleLayer.appendChild(delGroup)
    }

    edgeRefs.push({
      conn,
      start,
      end,
      fromNodeId: p1.id,
      toNodeId: p2.id,
      path,
      hitArea,
      startHit,
      startDot,
      endHit,
      endDot,
      bufGroup,
      delGroup
    })
  })

  function updateConnectedEdges(secId) {
    edgeRefs.forEach(edge => {
      if (edge.start.id !== secId && edge.end.id !== secId) return
      const startNodes = getSectionNodePoints(edge.start)
      const endNodes = getSectionNodePoints(edge.end)
      const startMap = new Map(startNodes.map(n => [n.id, n]))
      const endMap = new Map(endNodes.map(n => [n.id, n]))
      const curP1 = startMap.get(edge.fromNodeId) || startNodes[0]
      const curP2 = endMap.get(edge.toNodeId) || endNodes[0]
      if (!curP1 || !curP2) return

      const curve = computeSmoothConnectionPath(curP1, curP2)
      edge.path.setAttribute("d", curve.d)
      edge.hitArea.setAttribute("d", curve.d)

      edge.startHit.setAttribute("cx", curP1.x)
      edge.startHit.setAttribute("cy", curP1.y)
      edge.startDot.setAttribute("cx", curP1.x)
      edge.startDot.setAttribute("cy", curP1.y)

      edge.endHit.setAttribute("cx", curP2.x)
      edge.endHit.setAttribute("cy", curP2.y)
      edge.endDot.setAttribute("cx", curP2.x)
      edge.endDot.setAttribute("cy", curP2.y)

      if (edge.bufGroup) {
        edge.bufGroup.setAttribute("transform", `translate(${curve.midX} ${curve.midY})`)
      }
      if (edge.delGroup) {
        edge.delGroup.setAttribute("transform", `translate(${curve.midX} ${curve.midY})`)
      }
    })
  }

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
    section.nodeElem = group

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

    // Perimeter Snap Nodes (16 points around the section block)
    const snapNodes = getSectionNodePoints(section)
    const snapGroup = svgElement("g", { class: "section-snap-nodes" })
    snapNodes.forEach(sNode => {
      const snapCircle = svgElement("circle", {
        cx: sNode.lx,
        cy: sNode.ly,
        r: 5.5,
        class: "section-snap-node",
        "data-node-id": sNode.id,
        "data-section-id": section.id,
        title: `Snap node (${sNode.edge}) - Drag to start connection or snap incoming arrow here`
      })
      snapCircle.onmousedown = (e) => {
        e.stopPropagation()
        state.hasUserInteracted = true
        const attachedResolved = (selectedResolved && ((selectedResolved.start.id === section.id && selectedResolved.p1.id === sNode.id) || (selectedResolved.end.id === section.id && selectedResolved.p2.id === sNode.id)))
          ? selectedResolved
          : resolvedConns.find(rc => (rc.start.id === section.id && rc.p1.id === sNode.id) || (rc.end.id === section.id && rc.p2.id === sNode.id))
        if (attachedResolved) {
          const isStart = (attachedResolved.start.id === section.id && attachedResolved.p1.id === sNode.id)
          const selHandleType = isStart ? "start" : "end"
          state.reconnectingConnection = {
            handleType: selHandleType,
            connId: attachedResolved.conn.id,
            fromId: attachedResolved.start.id,
            fromName: attachedResolved.start.name,
            oldToId: attachedResolved.end.id,
            fromNode: attachedResolved.p1.id,
            toNode: attachedResolved.p2.id,
            p1: attachedResolved.p1,
            p2: attachedResolved.p2,
            fixedPoint: (selHandleType === "start") ? attachedResolved.p2 : attachedResolved.p1,
            connType: attachedResolved.conn.connection_type || "subassembly",
            originX: e.clientX,
            originY: e.clientY,
            isDrag: false,
            fromHandle: true
          }
          return
        }
        state.pendingConnection = {
          fromId: section.id,
          fromName: section.name,
          fromNode: sNode.id,
          startX: sNode.x,
          startY: sNode.y,
          startNormal: { nx: sNode.nx, ny: sNode.ny }
        }
      }
      snapGroup.appendChild(snapCircle)
    })
    group.appendChild(snapGroup)

    // Connection Port Handle (on right border of header)
    const port = svgElement("circle", {
      cx: secWidth / 2, cy: -secHeight / 2 + 21, r: 8, class: "port-handle",
      title: "Drag to connect this section to another section"
    })
    port.onmousedown = (e) => {
      e.stopPropagation()
      state.hasUserInteracted = true
      const portX = section.sx + secWidth / 2
      const portY = section.sy - secHeight / 2 + 21
      const matchesPort = (rc) => (
        (rc.start.id === section.id && (rc.p1.id === "right_1" || Math.hypot(rc.p1.x - portX, rc.p1.y - portY) <= 28)) ||
        (rc.end.id === section.id && (rc.p2.id === "right_1" || Math.hypot(rc.p2.x - portX, rc.p2.y - portY) <= 28))
      )
      const attachedPortResolved = (selectedResolved && matchesPort(selectedResolved))
        ? selectedResolved
        : resolvedConns.find(matchesPort)
      if (attachedPortResolved) {
        const isStart = (attachedPortResolved.start.id === section.id && (attachedPortResolved.p1.id === "right_1" || Math.hypot(attachedPortResolved.p1.x - portX, attachedPortResolved.p1.y - portY) <= 28))
        const selHandleType = isStart ? "start" : "end"
        state.reconnectingConnection = {
          handleType: selHandleType,
          connId: attachedPortResolved.conn.id,
          fromId: attachedPortResolved.start.id,
          fromName: attachedPortResolved.start.name,
          oldToId: attachedPortResolved.end.id,
          fromNode: attachedPortResolved.p1.id,
          toNode: attachedPortResolved.p2.id,
          p1: attachedPortResolved.p1,
          p2: attachedPortResolved.p2,
          fixedPoint: (selHandleType === "start") ? attachedPortResolved.p2 : attachedPortResolved.p1,
          connType: attachedPortResolved.conn.connection_type || "subassembly",
          originX: e.clientX,
          originY: e.clientY,
          isDrag: false,
          fromHandle: true
        }
        return
      }
      state.pendingConnection = {
        fromId: section.id,
        fromName: section.name,
        fromNode: "right_1",
        startX: section.sx + secWidth / 2,
        startY: section.sy - secHeight / 2 + 21,
        startNormal: { nx: 1, ny: 0 }
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
        cluster.clusterElem = clusterGroup

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
          "data-part-number": activePart.part_number || "",
          "data-assignment-id": activePart.id,
          style: "cursor: grab;"
        })
        cluster.cardElem = card

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

        const pnStr = activePart.part_number || ""
        const pnText = svgElement("text", {
          x: cardX + cardW / 2, y: cardY + 66, "text-anchor": "middle",
          fill: "var(--st-text-color)", "font-size": 8.8, "font-weight": 700,
          class: "part-number-text",
          "data-full-pn": pnStr,
          "data-card-w": cardW
        })
        pnText.textContent = pnStr.length > 10 ? `${pnStr.slice(0, 9)}…` : pnStr
        card.appendChild(pnText)

        // Variant badge (click to edit model variant ties) and suffix counter for cascaded clusters
        if (hasMultiple) {
          const badgeG = svgElement("g", {
            class: "cascade-badge",
            title: `Click to edit ${cluster.parts.length} model variant ties`
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
          badgeG.onclick = (e) => {
            e.stopPropagation()
            openVariantTiesModal(cluster, section)
          }
          card.appendChild(badgeG)

          // Suffix indicator at bottom
          const sufTxt = svgElement("text", {
            x: cardX + cardW / 2, y: cardY + 76, "text-anchor": "middle",
            fill: "#6366f1", "font-size": 7.5, "font-weight": 600
          })
          const distinctPns = new Set(cluster.parts.map(cp => String(cp.part_number || "").trim().toUpperCase()))
          const qtyVal = activePart.quantity !== undefined && activePart.quantity !== null ? activePart.quantity : 1
          const noteRaw = String(activePart.use_description || "").trim()
          if (distinctPns.size < cluster.parts.length) {
            const noteShort = noteRaw ? `·${noteRaw.length > 5 ? noteRaw.slice(0, 4) + "…" : noteRaw}` : ""
            sufTxt.textContent = `[${activeIdx + 1}/${cluster.parts.length}] Qty ${qtyVal}${noteShort}`
          } else {
            let suf = pnStr
            const sufMatch = pnStr.match(/^([A-Z0-9#]+?)[-_\\s]?([PG])[-_\\s]?(\\d{1,5}[A-Z]?|[#X]+)(?:_.*)?$/)
            if (sufMatch && sufMatch[1].length >= 4) {
              suf = `${sufMatch[2]}${sufMatch[3]}`
            } else if (pnStr.length >= 8) {
              suf = pnStr.slice(8)
            }
            sufTxt.textContent = `[${activeIdx + 1}/${cluster.parts.length}] ${suf} (${qtyVal})`
          }
          card.appendChild(sufTxt)
        } else {
          const qtyVal = activePart.quantity !== undefined && activePart.quantity !== null ? activePart.quantity : 1
          const noteRaw = String(activePart.use_description || "").trim()
          const subLabel = noteRaw
            ? `Qty ${qtyVal} · ${noteRaw.length > 7 ? noteRaw.slice(0, 6) + "…" : noteRaw}`
            : `Qty: ${qtyVal}`
          const qtyTxt = svgElement("text", {
            x: cardX + cardW / 2, y: cardY + 75.5, "text-anchor": "middle",
            fill: "var(--st-secondary-text-color)", "font-size": 7.5, "font-weight": 600
          })
          qtyTxt.textContent = subLabel
          card.appendChild(qtyTxt)
        }

        // Multi-use indicator badge (when placed in 2+ sections or split into 2+ cards)
        const partSecMap = partSectionsMap.get(activePart.part_id)
        const totalPlacedSections = partSecMap ? partSecMap.size : 1
        const totalPartUses = partTotalUsesMap.get(activePart.part_id) || 1
        if (totalPartUses > 1) {
          const multiBadge = svgElement("g", {
            class: "part-multiuse-badge",
            title: totalPlacedSections > 1
              ? `Used in ${totalPlacedSections} sections (${totalPartUses} cards) — click to manage uses`
              : `Split into ${totalPartUses} cards in this section — click to manage uses`
          })
          multiBadge.appendChild(svgElement("rect", {
            x: cardX + 3, y: cardY + 41, width: 36, height: 13, rx: 3.5,
            fill: "#0284c7", stroke: "white", "stroke-width": 1
          }))
          const multiTxt = svgElement("text", {
            x: cardX + 21, y: cardY + 50, "text-anchor": "middle",
            fill: "white", "font-size": 7.8, "font-weight": 700
          })
          multiTxt.textContent = `${totalPartUses} uses`
          multiBadge.appendChild(multiTxt)
          multiBadge.onclick = (e) => {
            e.stopPropagation()
            openPartUsesModal(activePart, section)
          }
          card.appendChild(multiBadge)
        }

        // Replicate / Manage Uses (+) Button at bottom-left (where 'uses' badge lives)
        const repCx = totalPartUses > 1 ? (cardX + 47.5) : (cardX + 10.5)
        const repCy = cardY + 47.5
        const replicateBtn = svgElement("g", {
          class: "part-replicate-btn",
          title: `Replicate ${activePart.part_number} to other sections or split quantity into multiple cards`,
          style: "cursor: pointer;"
        })
        replicateBtn.appendChild(svgElement("circle", {
          cx: repCx, cy: repCy, r: 7.5,
          fill: "#0284c7", stroke: "white", "stroke-width": 1.5
        }))
        const repTxt = svgElement("text", {
          x: repCx, y: repCy + 3.2, "text-anchor": "middle",
          fill: "white", "font-size": 10.5, "font-weight": 700
        })
        repTxt.textContent = "+"
        replicateBtn.appendChild(repTxt)
        replicateBtn.onclick = (e) => {
          e.stopPropagation()
          openPartUsesModal(activePart, section)
        }
        card.appendChild(replicateBtn)

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
          if (e.target.closest(".part-remove-btn") || e.target.closest(".part-replicate-btn") || e.target.closest(".part-multiuse-badge") || e.target.closest(".cascade-badge")) return
          e.stopPropagation()
          const startMouseX = e.clientX
          const startMouseY = e.clientY
          let isDragging = false
          state.draggingPart = true
          tooltip.hidden = true
          let ghostEl = null

          const onMouseMove = (moveEvt) => {
            const dist = Math.hypot(moveEvt.clientX - startMouseX, moveEvt.clientY - startMouseY)
            if (dist > 4 && !isDragging) {
              isDragging = true
              state.hasUserInteracted = true
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
              document.querySelectorAll(".part-card").forEach(c => c.classList.remove("part-card-stack-target"))
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

                // Helper to check if a target cluster can be stacked with the dragged cluster as a model variant
                const clusters = hoveredSec.partClusters || []
                const localX = currX - hoveredSec.sx
                const localY = currY - hoveredSec.sy
                const cardTopY = -hoveredSec.secHeight / 2 + 48
                const cardBotY = cardTopY + 78
                const sameSectionSourceIdx = hoveredSec.id === section.id ? clusters.indexOf(cluster) : -1

                let stackTargetCluster = null
                if (localY >= cardTopY + 10 && localY <= cardBotY - 10) {
                  stackTargetCluster = clusters.find(cl => {
                    if (cl === cluster) return false
                    return Math.abs(localX - cl.midX) <= 11
                  }) || null
                }

                if (stackTargetCluster && stackTargetCluster.cardElem) {
                  stackTargetCluster.cardElem.classList.add("part-card-stack-target")
                  ghostEl.textContent = `${activePart.part_number} · Stack as Variant`
                } else {
                  ghostEl.textContent = `${activePart.part_number}${hasMultiple ? ` (+${cluster.parts.length - 1})` : ""}`
                  // Show insertion line between parts if section has clusters
                  if (clusters.length > 0) {
                    const gap = 12
                    let targetIdx = clusters.length
                    if (localX < clusters[0].midX) {
                      targetIdx = 0
                    } else if (localX >= clusters[clusters.length - 1].midX) {
                      targetIdx = clusters.length
                    } else {
                      for (let i = 0; i < clusters.length - 1; i++) {
                        if (localX < clusters[i + 1].midX) {
                          targetIdx = i + 1
                          break
                        }
                      }
                    }
                    if (sameSectionSourceIdx !== -1) {
                      if (
                        targetIdx === sameSectionSourceIdx + 1 &&
                        sameSectionSourceIdx + 1 < clusters.length &&
                        localX >= clusters[sameSectionSourceIdx + 1].cardX
                      ) {
                        targetIdx = sameSectionSourceIdx + 2
                      } else if (
                        targetIdx === sameSectionSourceIdx &&
                        sameSectionSourceIdx - 1 >= 0 &&
                        localX <= clusters[sameSectionSourceIdx - 1].cardX + clusters[sameSectionSourceIdx - 1].cardW
                      ) {
                        targetIdx = sameSectionSourceIdx - 1
                      }
                    }

                    let insertLocalX = 0
                    if (targetIdx <= 0) {
                      insertLocalX = clusters[0].cardX - gap / 2
                    } else if (targetIdx >= clusters.length) {
                      const lastCl = clusters[clusters.length - 1]
                      insertLocalX = lastCl.cardX + lastCl.cardW + gap / 2
                    } else {
                      const clA = clusters[targetIdx - 1]
                      const clB = clusters[targetIdx]
                      insertLocalX = (clA.cardX + clA.cardW + clB.cardX) / 2
                    }

                    const isNoOpSameSlot = sameSectionSourceIdx !== -1 && (targetIdx === sameSectionSourceIdx || targetIdx === sameSectionSourceIdx + 1)
                    if (!isNoOpSameSlot) {
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
            }
          }

          const onMouseUp = (upEvt) => {
            state.draggingPart = false
            window.removeEventListener("mousemove", onMouseMove)
            window.removeEventListener("mouseup", onMouseUp)
            window.removeEventListener("keydown", onKeyDown)
            document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))
            document.querySelectorAll(".part-card").forEach(c => c.classList.remove("part-card-stack-target"))
            const oldIndicator = ghostLayer.querySelector(".part-insert-indicator")
            if (oldIndicator) oldIndicator.remove()
            if (ghostEl) {
              ghostEl.remove()
              ghostEl = null
            }
            if (isDragging) {
              state.hasUserInteracted = true
              saveFishboneView(storageKey, state)
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
                const localX = currX - targetSec.sx
                const localY = currY - targetSec.sy
                const cardTopY = -targetSec.secHeight / 2 + 48
                const cardBotY = cardTopY + 78
                const sameSectionSourceIdx = targetSec.id === section.id ? clusters.indexOf(cluster) : -1

                let stackTargetCluster = null
                if (localY >= cardTopY + 10 && localY <= cardBotY - 10) {
                  stackTargetCluster = clusters.find(cl => {
                    if (cl === cluster) return false
                    return Math.abs(localX - cl.midX) <= 11
                  }) || null
                }

                const stackWithPart = stackTargetCluster && stackTargetCluster.parts && stackTargetCluster.parts.length > 0
                  ? stackTargetCluster.parts[stackTargetCluster.activeIdx || 0] || stackTargetCluster.parts[0]
                  : null
                const stackTargetAssignmentIds = []
                if (stackTargetCluster && Array.isArray(stackTargetCluster.parts)) {
                  stackTargetCluster.parts.forEach(tp => {
                    if (tp.assignment_ids && tp.assignment_ids.length > 0) {
                      tp.assignment_ids.forEach(aid => {
                        if (aid && !stackTargetAssignmentIds.includes(aid)) stackTargetAssignmentIds.push(aid)
                      })
                    } else if (tp.id && !stackTargetAssignmentIds.includes(tp.id)) {
                      stackTargetAssignmentIds.push(tp.id)
                    }
                  })
                }

                let movingParts = cluster.parts
                let remainingSourceParts = []
                let combinedTargetParts = null
                if (stackTargetCluster) {
                  const sourceSharesTargetPart = cluster.parts.some(sp =>
                    stackTargetCluster.parts.some(tp =>
                      (tp.part_id && sp.part_id && String(tp.part_id) === String(sp.part_id)) ||
                      (tp.part_number && sp.part_number && String(tp.part_number).trim().toUpperCase() === String(sp.part_number).trim().toUpperCase())
                    )
                  )
                  if (sourceSharesTargetPart) {
                    movingParts = [activePart]
                    remainingSourceParts = cluster.parts.filter(sp => sp !== activePart)
                  }
                  const partUseCounts = new Map()
                  const countPart = (item) => {
                    const key = String(item.part_id || item.part_number || "").trim().toUpperCase()
                    if (!key) return
                    partUseCounts.set(key, (partUseCounts.get(key) || 0) + 1)
                  }
                  clusters.forEach(cl => {
                    if (cl !== cluster) cl.parts.forEach(countPart)
                  })
                  if (targetSec.id === section.id) {
                    remainingSourceParts.forEach(countPart)
                  }
                  movingParts.forEach(countPart)

                  const rawCombined = [...stackTargetCluster.parts, ...movingParts]
                  combinedTargetParts = rawCombined.slice().sort((a, b) => {
                    const keyA = String(a.part_id || a.part_number || "").trim().toUpperCase()
                    const keyB = String(b.part_id || b.part_number || "").trim().toUpperCase()
                    const countA = partUseCounts.get(keyA) || 1
                    const countB = partUseCounts.get(keyB) || 1
                    return countB - countA
                  })
                }

                let targetIdx = clusters.length
                if (!stackTargetCluster && clusters.length > 0) {
                  if (localX < clusters[0].midX) {
                    targetIdx = 0
                  } else if (localX >= clusters[clusters.length - 1].midX) {
                    targetIdx = clusters.length
                  } else {
                    for (let i = 0; i < clusters.length - 1; i++) {
                      if (localX < clusters[i + 1].midX) {
                        targetIdx = i + 1
                        break
                      }
                    }
                  }
                  if (sameSectionSourceIdx !== -1) {
                    if (
                      targetIdx === sameSectionSourceIdx + 1 &&
                      sameSectionSourceIdx + 1 < clusters.length &&
                      localX >= clusters[sameSectionSourceIdx + 1].cardX
                    ) {
                      targetIdx = sameSectionSourceIdx + 2
                    } else if (
                      targetIdx === sameSectionSourceIdx &&
                      sameSectionSourceIdx - 1 >= 0 &&
                      localX <= clusters[sameSectionSourceIdx - 1].cardX + clusters[sameSectionSourceIdx - 1].cardW
                    ) {
                      targetIdx = sameSectionSourceIdx - 1
                    }
                  }
                }

                const clusterAssignmentIds = []
                movingParts.forEach(p => {
                  if (p.assignment_ids && p.assignment_ids.length > 0) {
                    p.assignment_ids.forEach(aid => {
                      if (aid && !clusterAssignmentIds.includes(aid)) clusterAssignmentIds.push(aid)
                    })
                  } else if (p.id && !clusterAssignmentIds.includes(p.id)) {
                    clusterAssignmentIds.push(p.id)
                  }
                })

                if (targetSec.id === section.id) {
                  // Reorder or stack within the same section
                  if (clusters.length > 1 || stackWithPart) {
                    const sourceIdx = sameSectionSourceIdx
                    if (stackTargetCluster) {
                      const newClusters = []
                      let insertAt = 0
                      clusters.forEach((cl) => {
                        if (cl === cluster) {
                          if (remainingSourceParts.length > 0) {
                            newClusters.push(Object.assign({}, cl, { parts: remainingSourceParts }))
                          }
                        } else if (cl === stackTargetCluster) {
                          insertAt = newClusters.length
                          newClusters.push(Object.assign({}, cl, { parts: combinedTargetParts }))
                        } else {
                          newClusters.push(cl)
                        }
                      })

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
                        assignment_ids: clusterAssignmentIds.length > 0 ? clusterAssignmentIds : (activePart.assignment_ids || [activePart.id]),
                        part_id: activePart.part_id,
                        part_number: activePart.part_number,
                        from_section_id: section.id,
                        to_section_id: section.id,
                        target_index: insertAt,
                        ordered_assignment_ids: orderedAssignmentIds,
                        stack_with_part_number: stackWithPart ? stackWithPart.part_number : null,
                        stack_with_part_id: stackWithPart ? stackWithPart.part_id : null,
                        stack_with_assignment_id: stackWithPart ? stackWithPart.id : null,
                        stack_with_assignment_ids: stackTargetAssignmentIds,
                      })
                    } else if (sourceIdx !== -1 && targetIdx !== sourceIdx && targetIdx !== sourceIdx + 1) {
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
                        assignment_ids: clusterAssignmentIds.length > 0 ? clusterAssignmentIds : (activePart.assignment_ids || [activePart.id]),
                        part_id: activePart.part_id,
                        part_number: activePart.part_number,
                        from_section_id: section.id,
                        to_section_id: section.id,
                        target_index: insertAt,
                        ordered_assignment_ids: orderedAssignmentIds,
                        stack_with_part_number: null,
                        stack_with_part_id: null,
                      })
                    }
                  }
                } else {
                  // Move to another section (and optionally stack onto target card)
                  let targetClusters = []
                  let insertAt = 0
                  if (stackTargetCluster) {
                    clusters.forEach((cl) => {
                      if (cl === stackTargetCluster) {
                        insertAt = targetClusters.length
                        targetClusters.push(Object.assign({}, cl, { parts: combinedTargetParts }))
                      } else {
                        targetClusters.push(cl)
                      }
                    })
                  } else {
                    targetClusters = [...clusters]
                    insertAt = Math.min(Math.max(0, targetIdx), targetClusters.length)
                    targetClusters.splice(insertAt, 0, Object.assign({}, cluster, { parts: movingParts }))
                  }

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
                    assignment_ids: clusterAssignmentIds.length > 0 ? clusterAssignmentIds : (activePart.assignment_ids || [activePart.id]),
                    part_id: activePart.part_id,
                    part_number: activePart.part_number,
                    from_section_id: section.id,
                    to_section_id: targetSec.id,
                    target_index: insertAt,
                    ordered_assignment_ids: orderedTargetAssignmentIds,
                    stack_with_part_number: stackWithPart ? stackWithPart.part_number : null,
                    stack_with_part_id: stackWithPart ? stackWithPart.part_id : null,
                    stack_with_assignment_id: stackWithPart ? stackWithPart.id : null,
                    stack_with_assignment_ids: stackTargetAssignmentIds,
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
              state.draggingPart = false
              window.removeEventListener("mousemove", onMouseMove)
              window.removeEventListener("mouseup", onMouseUp)
              window.removeEventListener("keydown", onKeyDown)
              document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))
              document.querySelectorAll(".part-card").forEach(c => c.classList.remove("part-card-stack-target"))
              const oldIndicator = ghostLayer.querySelector(".part-insert-indicator")
              if (oldIndicator) oldIndicator.remove()
              if (ghostEl) {
                ghostEl.remove()
                ghostEl = null
              }
              state.draggingPart = false
              isDragging = false
            }
          }

          window.addEventListener("mousemove", onMouseMove)
          window.addEventListener("mouseup", onMouseUp)
          window.addEventListener("keydown", onKeyDown)
        }

        // Hover tooltip
        card.onmouseenter = (e) => {
          if (state.draggingPart || state.dragging) return
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
            const lines = cluster.parts.map((p, i) => {
              const noteStr = p.use_description ? ` · ${p.use_description}` : ""
              return `${i === activeIdx ? "▶ " : "• "}${p.part_number}: ${p.description || ""} (Qty: ${p.quantity}${noteStr})`
            }).join("\\n")
            tooltipMeta.textContent = `${lines}\n\n💡 Click ${cluster.parts.length}× badge to edit variant ties · Click card to cycle active variant · Drag to move`
          } else {
            tooltipNumber.textContent = activePart.part_number
            tooltipName.textContent = activePart.description || "—"
            tooltipMeta.textContent = `Qty: ${activePart.quantity} · ${activePart.models || "All models"}${activePart.use_description ? ` · ${activePart.use_description}` : ""}\n\n💡 Drag to re-order or move between sections`
          }
          tooltip.hidden = false
          const rect = viewport.getBoundingClientRect()
          const tipWidth = tooltip.offsetWidth || 360
          const tipHeight = tooltip.offsetHeight || 150
          tooltip.style.left = `${e.clientX - rect.left + 16}px`
          tooltip.style.top = `${e.clientY - rect.top + 16}px`
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
          state.hasUserInteracted = true
          group.classList.add("dragging")
          section.sx = origSx + dx
          section.sy = origSy + dy
          group.setAttribute("transform", `translate(${section.sx} ${section.sy})`)
          updateConnectedEdges(section.id)
        }
      }

      const onMouseUp = () => {
        window.removeEventListener("mousemove", onMouseMove)
        window.removeEventListener("mouseup", onMouseUp)
        group.classList.remove("dragging")
        if (didMove) {
          state.hasUserInteracted = true
          saveFishboneView(storageKey, state)
          section.sx = snap(section.sx, 20)
          section.sy = snap(section.sy, 20)
          updateConnectedEdges(section.id)
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

      // Light up snap nodes on potential target sections
      document.querySelectorAll(".section-snap-node").forEach(el => {
        if (el.getAttribute("data-section-id") !== state.pendingConnection.fromId) {
          el.classList.add("connecting-active")
        }
      })
      document.querySelectorAll(".snap-target-highlight").forEach(el => el.classList.remove("snap-target-highlight"))

      const candidateSections = sections.filter(s => s.id !== state.pendingConnection.fromId)
      const snapRes = findBestSnapTarget(candidateSections, currX, currY, 140)

      if (snapRes) {
        const matchedCircle = document.querySelector(`.section-snap-node[data-section-id="${snapRes.section.id}"][data-node-id="${snapRes.node.id}"]`)
        if (matchedCircle) matchedCircle.classList.add("snap-target-highlight")
      }

      const p1 = {
        x: state.pendingConnection.startX,
        y: state.pendingConnection.startY,
        nx: state.pendingConnection.startNormal ? state.pendingConnection.startNormal.nx : 1,
        ny: state.pendingConnection.startNormal ? state.pendingConnection.startNormal.ny : 0
      }

      let ghostPathD = ""
      if (snapRes) {
        const p2 = { x: snapRes.node.x, y: snapRes.node.y, nx: snapRes.node.nx, ny: snapRes.node.ny }
        const pathData = computeSmoothConnectionPath(p1, p2)
        ghostPathD = pathData.d
      } else {
        const dx = currX - p1.x
        const dy = currY - p1.y
        const dist = Math.hypot(dx, dy)
        const bend = Math.min(Math.max(dist * 0.4, 30), 120)
        const c1x = p1.x + p1.nx * bend
        const c1y = p1.y + p1.ny * bend
        ghostPathD = `M ${p1.x} ${p1.y} Q ${c1x} ${c1y} ${currX} ${currY}`
      }

      const ghost = svgElement("path", {
        d: ghostPathD,
        fill: "none",
        stroke: snapRes ? "#22c55e" : "#3b82f6",
        "stroke-width": 3.5,
        "stroke-dasharray": "6 4",
        "marker-end": snapRes ? "url(#arrow-snap)" : "url(#arrow-flow)"
      })
      ghostLayer.appendChild(ghost)
      const ghostHandle = svgElement("circle", {
        cx: snapRes ? snapRes.node.x : currX,
        cy: snapRes ? snapRes.node.y : currY,
        r: 7.5,
        fill: snapRes ? "#22c55e" : "#3b82f6",
        stroke: "white",
        "stroke-width": 2
      })
      ghostLayer.appendChild(ghostHandle)
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
        const rConn = state.reconnectingConnection

        svg.querySelectorAll(`[data-conn-id="${rConn.connId}"]`).forEach(el => el.classList.add("dragging-dimmed"))
        const currentLine = svg.querySelector("#conn-path-" + rConn.connId)
        if (currentLine) currentLine.classList.add("dragging-dimmed")

        document.querySelectorAll(".snap-target-highlight").forEach(el => el.classList.remove("snap-target-highlight"))
        document.querySelectorAll(".section-snap-node").forEach(el => {
          const sid = el.getAttribute("data-section-id")
          if (!rConn.fromHandle || rConn.handleType !== "start" || sid === rConn.fromId || sid === rConn.oldToId) {
            el.classList.add("connecting-active")
          }
        })

        const resolved = resolveReconnectTarget(rConn, currX, currY)
        if (resolved && resolved.highlights) {
          resolved.highlights.forEach(h => {
            const matchedCircle = document.querySelector(`.section-snap-node[data-section-id="${h.sectionId}"][data-node-id="${h.nodeId}"]`)
            if (matchedCircle) matchedCircle.classList.add("snap-target-highlight")
          })
        }

        if (resolved && resolved.p1 && resolved.p2) {
          const pathData = computeSmoothConnectionPath(resolved.p1, resolved.p2)
          const ghost = svgElement("path", {
            d: pathData.d,
            fill: "none",
            stroke: "#22c55e",
            "stroke-width": 3.5,
            "stroke-dasharray": "6 4",
            "marker-end": "url(#arrow-snap)"
          })
          ghostLayer.appendChild(ghost)
          const hp = resolved.handlePoint || resolved.p2
          const ghostHandle = svgElement("circle", {
            cx: hp.x,
            cy: hp.y,
            r: 7.5,
            fill: "#22c55e",
            stroke: "white",
            "stroke-width": 2
          })
          ghostLayer.appendChild(ghostHandle)
        }
      }
      return
    }
  }

  function resolveReconnectTarget(rConn, currX, currY) {
    const sourceSec = sectionById.get(rConn.fromId) || sections.find(s => s.id === rConn.fromId)
    const endSec = sectionById.get(rConn.oldToId) || sections.find(s => s.id === rConn.oldToId)
    const origP1 = rConn.p1 || (sourceSec ? findNearestNodePoint(sourceSec, currX, currY) : null)
    const origP2 = rConn.p2 || (endSec ? findNearestNodePoint(endSec, currX, currY) : null)

    if (!rConn.fromHandle) {
      const otherSections = sections.filter(s => s.id !== rConn.fromId && s.id !== rConn.oldToId)
      const otherSnap = findBestSnapTarget(otherSections, currX, currY, 110)
      const nearStart = sourceSec ? findNearestNodePoint(sourceSec, currX, currY) : null
      const nearEnd = endSec ? findNearestNodePoint(endSec, currX, currY) : null
      const dStart = nearStart ? Math.hypot(nearStart.x - currX, nearStart.y - currY) : Infinity
      const dEnd = nearEnd ? Math.hypot(nearEnd.x - currX, nearEnd.y - currY) : Infinity

      if (otherSnap && otherSnap.distance < Math.min(dStart, dEnd)) {
        return {
          mode: "move_connection",
          toSectionId: otherSnap.section.id,
          fromNode: rConn.fromNode,
          toNode: otherSnap.node.id,
          p1: origP1,
          p2: otherSnap.node,
          highlights: [{ sectionId: otherSnap.section.id, nodeId: otherSnap.node.id }],
          handlePoint: otherSnap.node
        }
      }

      if (nearStart && dStart <= 75 && dEnd > 110) {
        return {
          mode: "update_nodes",
          toSectionId: rConn.oldToId,
          fromNode: nearStart.id,
          toNode: rConn.toNode,
          p1: nearStart,
          p2: origP2,
          highlights: [{ sectionId: rConn.fromId, nodeId: nearStart.id }],
          handlePoint: nearStart
        }
      }

      if (nearEnd && dEnd <= 75 && dStart > 110) {
        return {
          mode: "update_nodes",
          toSectionId: rConn.oldToId,
          fromNode: rConn.fromNode,
          toNode: nearEnd.id,
          p1: origP1,
          p2: nearEnd,
          highlights: [{ sectionId: rConn.oldToId, nodeId: nearEnd.id }],
          handlePoint: nearEnd
        }
      }

      if (nearStart && nearEnd) {
        return {
          mode: "update_nodes",
          toSectionId: rConn.oldToId,
          fromNode: nearStart.id,
          toNode: nearEnd.id,
          p1: nearStart,
          p2: nearEnd,
          highlights: [
            { sectionId: rConn.fromId, nodeId: nearStart.id },
            { sectionId: rConn.oldToId, nodeId: nearEnd.id }
          ],
          handlePoint: (dStart <= dEnd) ? nearStart : nearEnd
        }
      }
    }

    if (rConn.handleType === "start") {
      const nearStart = sourceSec ? findNearestNodePoint(sourceSec, currX, currY) : null
      const nearEnd = endSec ? findNearestNodePoint(endSec, currX, currY) : null
      const dStart = nearStart ? Math.hypot(nearStart.x - currX, nearStart.y - currY) : Infinity
      const dEnd = nearEnd ? Math.hypot(nearEnd.x - currX, nearEnd.y - currY) : Infinity
      if (nearEnd && dEnd <= 65 && dStart > 140) {
        return {
          mode: "update_nodes",
          toSectionId: rConn.oldToId,
          fromNode: rConn.fromNode,
          toNode: nearEnd.id,
          p1: origP1,
          p2: nearEnd,
          highlights: [{ sectionId: rConn.oldToId, nodeId: nearEnd.id }],
          handlePoint: nearEnd
        }
      }
      if (nearStart) {
        return {
          mode: "update_nodes",
          toSectionId: rConn.oldToId,
          fromNode: nearStart.id,
          toNode: rConn.toNode,
          p1: nearStart,
          p2: origP2,
          highlights: [{ sectionId: rConn.fromId, nodeId: nearStart.id }],
          handlePoint: nearStart
        }
      }
      return null
    }

    const candidateSections = sections.filter(s => s.id !== rConn.fromId)
    let snapRes = findBestSnapTarget(candidateSections, currX, currY, 240)
    if (!snapRes && endSec) {
      const nearEnd = findNearestNodePoint(endSec, currX, currY)
      if (nearEnd) {
        snapRes = { section: endSec, node: nearEnd, distance: Math.hypot(nearEnd.x - currX, nearEnd.y - currY) }
      }
    }
    if (snapRes) {
      if (snapRes.section.id === rConn.oldToId) {
        return {
          mode: "update_nodes",
          toSectionId: rConn.oldToId,
          fromNode: rConn.fromNode,
          toNode: snapRes.node.id,
          p1: origP1,
          p2: snapRes.node,
          highlights: [{ sectionId: rConn.oldToId, nodeId: snapRes.node.id }],
          handlePoint: snapRes.node
        }
      }
      return {
        mode: "move_connection",
        toSectionId: snapRes.section.id,
        fromNode: rConn.fromNode,
        toNode: snapRes.node.id,
        p1: origP1,
        p2: snapRes.node,
        highlights: [{ sectionId: snapRes.section.id, nodeId: snapRes.node.id }],
        handlePoint: snapRes.node
      }
    }
    return null
  }

  window.onmouseup = (e) => {
    document.querySelectorAll(".connecting-active").forEach(el => el.classList.remove("connecting-active"))
    document.querySelectorAll(".snap-target-highlight").forEach(el => el.classList.remove("snap-target-highlight"))
    svg.querySelectorAll(".dragging-dimmed").forEach(el => el.classList.remove("dragging-dimmed"))

    if (state.pendingConnection) {
      state.hasUserInteracted = true
      saveFishboneView(storageKey, state)
      ghostLayer.replaceChildren()
      const fromId = state.pendingConnection.fromId
      const fromNode = state.pendingConnection.fromNode || "right_1"
      state.pendingConnection = null

      const rect = svg.getBoundingClientRect()
      const currX = (e.clientX - rect.left - state.x) / state.scale
      const currY = (e.clientY - rect.top - state.y) / state.scale

      const candidateSections = sections.filter(s => s.id !== fromId)
      const snapRes = findBestSnapTarget(candidateSections, currX, currY, 180)

      if (snapRes) {
        const updatedNodes = { from_node: fromNode, to_node: snapRes.node.id }
        state.connNodeOverrides[`${fromId}->${snapRes.section.id}`] = updatedNodes
        const existingConn = connections.find(c => c.from_section_id === fromId && c.to_section_id === snapRes.section.id)
        if (existingConn && existingConn.id) {
          state.connNodeOverrides[existingConn.id] = updatedNodes
        }
        saveConnNodes(storageKey, state.connNodeOverrides)
        renderWorld()
        component.setTriggerValue("create_connection", {
          from_section_id: fromId,
          to_section_id: snapRes.section.id,
          connection_type: "subassembly",
          from_node: fromNode,
          to_node: snapRes.node.id
        })
      }
      return
    }

    if (state.reconnectingConnection) {
      state.hasUserInteracted = true
      saveFishboneView(storageKey, state)
      ghostLayer.replaceChildren()
      const rConn = state.reconnectingConnection
      state.reconnectingConnection = null

      if (rConn.isDrag) {
        const rect = svg.getBoundingClientRect()
        const currX = (e.clientX - rect.left - state.x) / state.scale
        const currY = (e.clientY - rect.top - state.y) / state.scale
        const resolved = resolveReconnectTarget(rConn, currX, currY)

        if (resolved) {
          if (resolved.mode === "update_nodes") {
            const updatedNodes = { from_node: resolved.fromNode, to_node: resolved.toNode }
            if (rConn.connId) state.connNodeOverrides[rConn.connId] = updatedNodes
            state.connNodeOverrides[`${rConn.fromId}->${rConn.oldToId}`] = updatedNodes
            saveConnNodes(storageKey, state.connNodeOverrides)
            renderWorld()
            if (resolved.fromNode !== rConn.fromNode || resolved.toNode !== rConn.toNode) {
              component.setTriggerValue("update_connection_nodes", {
                connection_id: rConn.connId,
                from_section_id: rConn.fromId,
                to_section_id: rConn.oldToId,
                from_node: resolved.fromNode,
                to_node: resolved.toNode
              })
            }
          } else if (resolved.mode === "move_connection") {
            const updatedNodes = { from_node: resolved.fromNode, to_node: resolved.toNode }
            if (rConn.connId) state.connNodeOverrides[rConn.connId] = updatedNodes
            state.connNodeOverrides[`${rConn.fromId}->${resolved.toSectionId}`] = updatedNodes
            saveConnNodes(storageKey, state.connNodeOverrides)
            state.selectedConnId = null
            renderWorld()
            component.setTriggerValue("move_connection", {
              connection_id: rConn.connId,
              from_section_id: rConn.fromId,
              to_section_id: resolved.toSectionId,
              old_to_section_id: rConn.oldToId,
              connection_type: rConn.connType,
              from_node: resolved.fromNode,
              to_node: resolved.toNode
            })
          }
        }
      } else {
        if (!rConn.fromHandle || state.selectedConnId !== rConn.connId) {
          state.selectedConnId = (state.selectedConnId === rConn.connId) ? null : rConn.connId
        }
        renderWorld()
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
    document.querySelectorAll(".part-card").forEach(c => c.classList.remove("part-card-stack-target"))

    const targetSec = sections.find(s => {
      const w = s.secWidth || 220
      const h = s.secHeight || 64
      return Math.abs(currX - s.sx) < w / 2 && Math.abs(currY - s.sy) < h / 2
    })
    if (targetSec) {
      const nodeElem = parentElement.querySelector(`[data-section-id="${targetSec.id}"]`)
      if (nodeElem) nodeElem.classList.add("section-drop-hover")

      const clusters = targetSec.partClusters || []
      const localX = currX - targetSec.sx
      const localY = currY - targetSec.sy
      const cardTopY = -targetSec.secHeight / 2 + 48
      const cardBotY = cardTopY + 78
      if (localY >= cardTopY - 8 && localY <= cardBotY + 8) {
        const stackTargetCluster = clusters.find(cl => {
          const margin = Math.min(18, cl.cardW * 0.22)
          return localX >= cl.cardX + margin && localX <= cl.cardX + cl.cardW - margin
        })
        if (stackTargetCluster && stackTargetCluster.cardElem) {
          stackTargetCluster.cardElem.classList.add("part-card-stack-target")
        }
      }
    }
  }

  svg.ondragleave = () => {
    document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))
    document.querySelectorAll(".part-card").forEach(c => c.classList.remove("part-card-stack-target"))
  }

  svg.ondrop = (e) => {
    e.preventDefault()
    state.hasUserInteracted = true
    saveFishboneView(storageKey, state)
    document.querySelectorAll(".section-node").forEach(n => n.classList.remove("section-drop-hover"))
    document.querySelectorAll(".part-card").forEach(c => c.classList.remove("part-card-stack-target"))
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

    const clusters = targetSec.partClusters || []
    const localX = currX - targetSec.sx
    const localY = currY - targetSec.sy
    const cardTopY = -targetSec.secHeight / 2 + 48
    const cardBotY = cardTopY + 78
    let stackTargetCluster = null
    if (localY >= cardTopY - 8 && localY <= cardBotY + 8) {
      stackTargetCluster = clusters.find(cl => {
        const margin = Math.min(18, cl.cardW * 0.22)
        return localX >= cl.cardX + margin && localX <= cl.cardX + cl.cardW - margin
      }) || null
    }
    const stackWithPart = stackTargetCluster && stackTargetCluster.parts && stackTargetCluster.parts.length > 0
      ? stackTargetCluster.parts[stackTargetCluster.activeIdx || 0] || stackTargetCluster.parts[0]
      : null

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
      const orderedAssignmentIds = []
      const dropStackTargetAids = []
      if (stackTargetCluster) {
        clusters.forEach(cl => {
          cl.parts.forEach(p => {
            if (p.assignment_ids && p.assignment_ids.length > 0) {
              p.assignment_ids.forEach(aid => {
                if (!orderedAssignmentIds.includes(aid)) orderedAssignmentIds.push(aid)
                if (cl === stackTargetCluster && !dropStackTargetAids.includes(aid)) dropStackTargetAids.push(aid)
              })
            } else if (p.id && !orderedAssignmentIds.includes(p.id)) {
              orderedAssignmentIds.push(p.id)
              if (cl === stackTargetCluster && !dropStackTargetAids.includes(p.id)) dropStackTargetAids.push(p.id)
            }
          })
          if (cl === stackTargetCluster) {
            orderedAssignmentIds.push("__dropped__")
          }
        })
      }
      component.setTriggerValue("drop_part", {
        part_id: item.part_id,
        part_number: item.part_number,
        section_id: targetSec.id,
        quantity: item.quantity || 1,
        use_description: useDesc,
        ordered_assignment_ids: orderedAssignmentIds,
        stack_with_part_number: stackWithPart ? stackWithPart.part_number : null,
        stack_with_part_id: stackWithPart ? stackWithPart.part_id : null,
        stack_with_assignment_id: stackWithPart ? stackWithPart.id : null,
        stack_with_assignment_ids: dropStackTargetAids,
      })
    }
  }

  // Viewport Pan and Zoom
  function updateTransform() {
    world.setAttribute("transform", `translate(${state.x} ${state.y}) scale(${state.scale})`)
    saveFishboneView(storageKey, state)
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
    state.fitted = true
    updateTransform()
    return true
  }

  function applySearchHighlightAndZoom(options = {}) {
    const zoomToMatch = Boolean(options.zoomToMatch)
    const query = (paletteSearch.value || "").trim().toLowerCase()
    const focusedPartId = state.focusedPartId ? String(state.focusedPartId) : null
    const focusedSectionId = state.focusedSectionId ? String(state.focusedSectionId) : null

    if (!query && !focusedPartId) {
      world.classList.remove("search-highlight-active")
      sections.forEach((sec) => {
        if (sec.nodeElem) sec.nodeElem.classList.remove("search-highlight")
        ;(sec.partClusters || []).forEach((cl) => {
          if (cl.clusterElem) cl.clusterElem.classList.remove("search-highlight")
          if (cl.cardElem) cl.cardElem.classList.remove("search-highlight")
        })
      })
      return
    }

    const matchedSections = []
    const matchedClusters = []

    sections.forEach((sec) => {
      const secEligible = !focusedSectionId || String(sec.id) === focusedSectionId
      let secHasMatch = false
      ;(sec.partClusters || []).forEach((cl) => {
        const isMatch = secEligible && (cl.parts || []).some((p) => {
          if (focusedPartId) return String(p.part_id || p.id) === focusedPartId
          return partMatchesQuery(p, query)
        })
        if (cl.clusterElem) cl.clusterElem.classList.toggle("search-highlight", isMatch)
        if (cl.cardElem) cl.cardElem.classList.toggle("search-highlight", isMatch)
        if (isMatch) {
          secHasMatch = true
          matchedClusters.push({ sec, cl })
        }
      })
      if (sec.nodeElem) sec.nodeElem.classList.toggle("search-highlight", secHasMatch)
      if (secHasMatch) matchedSections.push(sec)
    })

    if (matchedSections.length === 0) {
      world.classList.remove("search-highlight-active")
      return
    }

    world.classList.add("search-highlight-active")

    if (!zoomToMatch) return
    const rect = viewport.getBoundingClientRect()
    if (!rect.width || !rect.height || rect.width < 80 || rect.height < 80) return

    let secMinX = Infinity, secMaxX = -Infinity, secMinY = Infinity, secMaxY = -Infinity
    matchedSections.forEach((s) => {
      const hw = (s.secWidth || 220) / 2
      const hh = (s.secHeight || 80) / 2
      secMinX = Math.min(secMinX, s.sx - hw)
      secMaxX = Math.max(secMaxX, s.sx + hw)
      secMinY = Math.min(secMinY, s.sy - hh)
      secMaxY = Math.max(secMaxY, s.sy + hh)
    })

    let cardMinX = Infinity, cardMaxX = -Infinity
    matchedClusters.forEach(({ sec, cl }) => {
      const cx0 = sec.sx + (Number(cl.cardX) || 0)
      const cx1 = cx0 + (Number(cl.cardW) || 68)
      cardMinX = Math.min(cardMinX, cx0)
      cardMaxX = Math.max(cardMaxX, cx1)
    })

    const padX = 64
    const padY = 64
    const availW = Math.max(rect.width - 60, 140)
    const availH = Math.max(rect.height - 60, 140)

    const secSpanW = Math.max(secMaxX - secMinX + padX * 2, 260)
    const secSpanH = Math.max(secMaxY - secMinY + padY * 2, 200)
    let targetScale = clamp(Math.min(availW / secSpanW, availH / secSpanH), 0.45, 1.2)
    let targetMidX = (secMinX + secMaxX) / 2
    let targetMidY = (secMinY + secMaxY) / 2

    if (matchedSections.length === 1 && targetScale < 0.88 && isFinite(cardMinX) && isFinite(cardMaxX)) {
      const focusSpanW = Math.max(cardMaxX - cardMinX + 240, 320)
      targetScale = clamp(Math.min(availW / focusSpanW, availH / secSpanH), 0.88, 1.2)
      targetMidX = (cardMinX + cardMaxX) / 2
    }

    state.scale = targetScale
    state.x = rect.width / 2 - targetMidX * targetScale
    state.y = rect.height / 2 - targetMidY * targetScale
    state.fitted = true
    updateTransform()
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

  const shouldZoomToSearch = Boolean(state.pendingSearchZoom)
  state.pendingSearchZoom = false
  applySearchHighlightAndZoom({ zoomToMatch: shouldZoomToSearch })

  // Setup ResizeObserver and IntersectionObserver so canvas defaults to Fit screen when clicked or revealed
  if (!state.observerAttached && typeof ResizeObserver !== "undefined") {
    state.observerAttached = true
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        if (width > 80 && height > 80) {
          if (!state.fitted) {
            requestAnimationFrame(() => {
              if (!state.fitted) fitView()
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
            if (!state.fitted) {
              requestAnimationFrame(() => {
                if (!state.fitted) fitView()
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
    if (state.focusedPartId && !(paletteSearch.value || "").trim()) {
      state.focusedPartId = null
      state.focusedSectionId = null
      renderPalette()
      applySearchHighlightAndZoom({ zoomToMatch: false })
    }
    state.dragging = true
    state.pointerX = e.clientX
    state.pointerY = e.clientY
    svg.classList.add("dragging")
  }
  if (state._panMoveHandler) window.removeEventListener("mousemove", state._panMoveHandler)
  if (state._panUpHandler) window.removeEventListener("mouseup", state._panUpHandler)
  state._panMoveHandler = (e) => {
    if (!state.dragging) return
    state.hasUserInteracted = true
    state.x += (e.clientX - state.pointerX)
    state.y += (e.clientY - state.pointerY)
    state.pointerX = e.clientX
    state.pointerY = e.clientY
    updateTransform()
  }
  state._panUpHandler = () => {
    if (state.dragging) {
      state.dragging = false
      svg.classList.remove("dragging")
    }
  }
  window.addEventListener("mousemove", state._panMoveHandler)
  window.addEventListener("mouseup", state._panUpHandler)

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
    state.hasUserInteracted = true
    fitView()
  }

  function printFishbone() {
    const MAX_COLS_PER_ROW = 7
    const MAX_ROWS_PER_PAGE = 3
    const MAX_CLUSTERS_PER_PAGE = MAX_COLS_PER_ROW * MAX_ROWS_PER_PAGE
    const CARD_W = 68
    const CARD_H = 78
    const COL_GAP = 12
    const ROW_GAP = 16
    const HEADER_H = 42
    const TOP_PAD = 50
    const BOTTOM_PAD = 18
    const PAGE_ASPECT = 820 / 575

    const orderedSections = [...sections].sort((a, b) => {
      const rowA = Math.round((Number(a.sy) || 0) / 100)
      const rowB = Math.round((Number(b.sy) || 0) / 100)
      if (rowA !== rowB) return rowA - rowB
      return (Number(a.sx) || 0) - (Number(b.sx) || 0)
    })

    const pageSpecs = []
    if (orderedSections.length === 0) {
      pageSpecs.push({
        isEmptyState: true,
        section: null,
        chunk: [],
        chunkIdx: 0,
        totalSectionChunks: 1,
        incomingLabels: [],
        outgoingLabels: []
      })
    } else {
      orderedSections.forEach(sec => {
        const secNode = svg.querySelector(`.section-node[data-section-id="${sec.id}"]`)
        const clusterNodes = secNode ? [...secNode.querySelectorAll(".part-cluster")] : []
        const clusters = sec.partClusters || []
        const pairedClusters = clusters.map((cluster, idx) => ({
          cluster,
          domNode: clusterNodes[idx] || null
        }))

        const incomingLabels = resolvedConns
          .filter(rc => rc.end && rc.end.id === sec.id && rc.start)
          .map(rc => rc.start.type === "Support Operations"
            ? `${rc.start.name} (Buffer / Storage)`
            : rc.start.name
          )
        const outgoingLabels = resolvedConns
          .filter(rc => rc.start && rc.start.id === sec.id && rc.end)
          .map(rc => rc.end.name)

        if (pairedClusters.length === 0) {
          pageSpecs.push({
            isEmptyState: false,
            section: sec,
            chunk: [],
            chunkIdx: 0,
            totalSectionChunks: 1,
            incomingLabels,
            outgoingLabels
          })
        } else {
          const totalSectionChunks = Math.ceil(pairedClusters.length / MAX_CLUSTERS_PER_PAGE)
          for (let cIdx = 0; cIdx < totalSectionChunks; cIdx++) {
            const chunk = pairedClusters.slice(
              cIdx * MAX_CLUSTERS_PER_PAGE,
              (cIdx + 1) * MAX_CLUSTERS_PER_PAGE
            )
            pageSpecs.push({
              isEmptyState: false,
              section: sec,
              chunk,
              chunkIdx: cIdx,
              totalSectionChunks,
              incomingLabels,
              outgoingLabels
            })
          }
        }
      })
    }

    const oldFrame = document.getElementById("paag-fishbone-print-frame")
    if (oldFrame) oldFrame.remove()

    const iframe = document.createElement("iframe")
    iframe.id = "paag-fishbone-print-frame"
    iframe.style.position = "fixed"
    iframe.style.right = "0"
    iframe.style.bottom = "0"
    iframe.style.width = "1100px"
    iframe.style.height = "800px"
    iframe.style.border = "0"
    iframe.style.opacity = "0"
    iframe.style.pointerEvents = "none"
    iframe.style.zIndex = "-1"
    document.body.appendChild(iframe)

    const printDoc = iframe.contentDocument || iframe.contentWindow.document
    printDoc.open()
    printDoc.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>Interactive Fishbone Print</title>
<style>
  :root {
    --st-background-color: #ffffff;
    --st-secondary-background-color: #f8fafc;
    --st-border-color: #94a3b8;
    --st-text-color: #0f172a;
    --st-secondary-text-color: #475569;
    --st-primary-color: #2563eb;
  }
  @page {
    size: landscape;
    margin: 0.18in;
  }
  * {
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }
  html, body {
    margin: 0;
    padding: 0;
    background: #ffffff;
    color: #0f172a;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  .print-sheet {
    width: 100%;
    height: 98.5vh;
    max-height: 98.5vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    page-break-after: always;
    break-after: page;
  }
  .print-sheet:last-child {
    page-break-after: auto;
    break-after: auto;
  }
  .print-page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 4px 10px;
    margin-bottom: 4px;
    border-bottom: 1.5px solid #cbd5e1;
    background: #f8fafc;
    border-radius: 6px;
    flex-shrink: 0;
  }
  .print-page-title {
    display: flex;
    align-items: baseline;
    gap: 10px;
    font-size: 12px;
    color: #0f172a;
  }
  .print-page-title strong {
    font-size: 13px;
    font-weight: 800;
  }
  .print-page-title span {
    font-size: 11px;
    color: #475569;
  }
  .print-page-badge {
    font-size: 11px;
    font-weight: 700;
    color: #1e40af;
    background: #dbeafe;
    border: 1px solid #93c5fd;
    padding: 2px 8px;
    border-radius: 999px;
    white-space: nowrap;
  }
  .print-flow-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 16px;
    padding: 3px 10px;
    margin-bottom: 4px;
    font-size: 11px;
    color: #334155;
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    flex-shrink: 0;
  }
  .print-flow-bar strong {
    color: #0f172a;
    font-weight: 700;
  }
  .print-svg-stage {
    flex: 1 1 auto;
    min-height: 0;
    width: 100%;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #ffffff;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .print-fishbone-svg {
    display: block;
    width: 100%;
    height: 100%;
  }
</style>
</head>
<body><div id="print-root"></div></body>
</html>`)
    printDoc.close()

    const printRoot = printDoc.getElementById("print-root")
    const summaryText = summary ? summary.textContent : ""
    const totalPages = pageSpecs.length
    const NS = "http://www.w3.org/2000/svg"
    const makeSvgEl = (tag, attrs = {}) => {
      const el = printDoc.createElementNS(NS, tag)
      Object.entries(attrs).forEach(([k, v]) => {
        if (v !== undefined && v !== null) el.setAttribute(k, String(v))
      })
      return el
    }

    pageSpecs.forEach((spec, idx) => {
      const sheet = printDoc.createElement("section")
      sheet.className = "print-sheet"

      const header = printDoc.createElement("div")
      header.className = "print-page-header"

      const titleWrap = printDoc.createElement("div")
      titleWrap.className = "print-page-title"
      const strong = printDoc.createElement("strong")
      if (spec.section) {
        const partSuffix = spec.totalSectionChunks > 1
          ? ` (Part ${spec.chunkIdx + 1} of ${spec.totalSectionChunks})`
          : ""
        strong.textContent = `Interactive assembly fishbone · ${spec.section.name}${partSuffix}`
      } else {
        strong.textContent = "Interactive assembly fishbone"
      }
      const span = printDoc.createElement("span")
      span.textContent = summaryText
      titleWrap.appendChild(strong)
      titleWrap.appendChild(span)

      const badge = printDoc.createElement("div")
      badge.className = "print-page-badge"
      if (spec.section) {
        const secLabel = spec.totalSectionChunks > 1
          ? `${spec.section.name} · ${spec.chunkIdx + 1}/${spec.totalSectionChunks}`
          : spec.section.name
        badge.textContent = `Page ${idx + 1} of ${totalPages} (${secLabel})`
      } else {
        badge.textContent = `Page ${idx + 1} of ${totalPages}`
      }

      header.appendChild(titleWrap)
      header.appendChild(badge)
      sheet.appendChild(header)

      if (spec.section && (spec.incomingLabels.length > 0 || spec.outgoingLabels.length > 0)) {
        const flowBar = printDoc.createElement("div")
        flowBar.className = "print-flow-bar"
        if (spec.incomingLabels.length > 0) {
          const inSpan = printDoc.createElement("span")
          const inBold = printDoc.createElement("strong")
          inBold.textContent = "⬅ Feeds from: "
          inSpan.appendChild(inBold)
          inSpan.appendChild(printDoc.createTextNode(spec.incomingLabels.join(", ")))
          flowBar.appendChild(inSpan)
        }
        if (spec.outgoingLabels.length > 0) {
          const outSpan = printDoc.createElement("span")
          const outBold = printDoc.createElement("strong")
          outBold.textContent = "➔ Feeds into: "
          outSpan.appendChild(outBold)
          outSpan.appendChild(printDoc.createTextNode(spec.outgoingLabels.join(", ")))
          flowBar.appendChild(outSpan)
        }
        sheet.appendChild(flowBar)
      }

      const stage = printDoc.createElement("div")
      stage.className = "print-svg-stage"

      const pageSvg = makeSvgEl("svg", {
        class: "print-fishbone-svg",
        preserveAspectRatio: "xMidYMid meet"
      })

      if (spec.isEmptyState || !spec.section) {
        pageSvg.setAttribute("viewBox", "-240 -140 480 280")
        const emptyCard = makeSvgEl("rect", {
          x: -180, y: -50, width: 360, height: 100, rx: 12,
          fill: "#f8fafc", stroke: "#94a3b8", "stroke-width": 1.5
        })
        pageSvg.appendChild(emptyCard)
        const emptyTitle = makeSvgEl("text", {
          x: 0, y: -8, "text-anchor": "middle", fill: "#0f172a", "font-size": 15, "font-weight": 700
        })
        emptyTitle.textContent = "No Fishbone Sections Placed"
        pageSvg.appendChild(emptyTitle)
      } else {
        const section = spec.section
        const isSupport = section.type === "Support Operations"
        const secParts = partsBySection.get(section.id) || []
        const chunk = spec.chunk
        const rowsCount = chunk.length > 0 ? Math.ceil(chunk.length / MAX_COLS_PER_ROW) : 0

        let maxRowCardsW = 0
        const rows = []
        for (let r = 0; r < rowsCount; r++) {
          const rowItems = chunk.slice(r * MAX_COLS_PER_ROW, (r + 1) * MAX_COLS_PER_ROW)
          const rowCardsW = rowItems.reduce(
            (sum, item, cIdx) => sum + (item.cluster.cardW || CARD_W) + (cIdx > 0 ? COL_GAP : 0),
            0
          )
          if (rowCardsW > maxRowCardsW) maxRowCardsW = rowCardsW
          rows.push(rowItems)
        }

        const titleLabel = spec.totalSectionChunks > 1
          ? `${section.name} (${spec.chunkIdx + 1}/${spec.totalSectionChunks})`
          : section.name
        const minHeaderW = Math.max(240, titleLabel.length * 8.5 + 48)
        const boxWidth = Math.max(minHeaderW, maxRowCardsW + 28)
        const boxHeight = rowsCount > 0
          ? (TOP_PAD + rowsCount * CARD_H + (rowsCount - 1) * ROW_GAP + BOTTOM_PAD)
          : 92

        const group = makeSvgEl("g", { class: "section-node" })
        const bgRect = makeSvgEl("rect", {
          x: -boxWidth / 2,
          y: -boxHeight / 2,
          width: boxWidth,
          height: boxHeight,
          rx: 10,
          fill: isSupport ? "#1e293b" : "#f8fafc",
          stroke: isSupport ? "#475569" : "#94a3b8",
          "stroke-width": 2
        })
        group.appendChild(bgRect)

        const headerBg = makeSvgEl("rect", {
          x: -boxWidth / 2,
          y: -boxHeight / 2,
          width: boxWidth,
          height: HEADER_H,
          rx: 10,
          fill: isSupport ? "#334155" : "#1e40af"
        })
        group.appendChild(headerBg)

        const label = makeSvgEl("text", {
          x: -boxWidth / 2 + 12,
          y: -boxHeight / 2 + 18,
          fill: "white",
          "font-size": 13,
          "font-weight": 700
        })
        label.textContent = titleLabel
        group.appendChild(label)

        const count = makeSvgEl("text", {
          x: -boxWidth / 2 + 12,
          y: -boxHeight / 2 + 33,
          fill: "rgba(255, 255, 255, 0.88)",
          "font-size": 10
        })
        const chunkRangeText = spec.totalSectionChunks > 1
          ? ` · Showing cards ${spec.chunkIdx * MAX_CLUSTERS_PER_PAGE + 1}–${spec.chunkIdx * MAX_CLUSTERS_PER_PAGE + chunk.length} of ${(section.partClusters || []).length}`
          : ""
        if (isSupport) {
          const targetName = spec.outgoingLabels.length > 0 ? spec.outgoingLabels.join(", ") : ""
          count.textContent = targetName
            ? `🏭 Built here ➔ Feeds ${targetName} · ${secParts.length} parts${chunkRangeText}`
            : `🏭 Fabrication / Support Ops · ${secParts.length} parts${chunkRangeText}`
        } else {
          count.textContent = `${secParts.length} part${secParts.length === 1 ? "" : "s"} assigned${chunkRangeText}`
        }
        group.appendChild(count)

        if (chunk.length === 0) {
          const placeholder = makeSvgEl("text", {
            x: 0,
            y: -boxHeight / 2 + 66,
            "text-anchor": "middle",
            fill: isSupport ? "#cbd5e1" : "#64748b",
            "font-size": 10.5,
            "font-style": "italic"
          })
          placeholder.textContent = "No parts assigned to this section"
          group.appendChild(placeholder)
        } else {
          rows.forEach((rowItems, rIdx) => {
            let curX = -boxWidth / 2 + 14
            const targetY = -boxHeight / 2 + TOP_PAD + rIdx * (CARD_H + ROW_GAP)
            rowItems.forEach(({ cluster, domNode }) => {
              const clusterW = cluster.cardW || CARD_W
              if (domNode) {
                const clClone = domNode.cloneNode(true)
                clClone.classList.remove("search-highlight")
                clClone.querySelectorAll(".part-remove-btn, .part-replicate-btn").forEach(el => el.remove())
                clClone.querySelectorAll(".part-card").forEach(el => {
                  el.classList.remove("search-highlight")
                  el.style.cursor = "default"
                })
                clClone.querySelectorAll(".part-number-text").forEach(pnEl => {
                  const fullPn = pnEl.getAttribute("data-full-pn") || pnEl.textContent || ""
                  const cardW = Number(pnEl.getAttribute("data-card-w")) || CARD_W
                  pnEl.textContent = fullPn
                  if (fullPn.length > 10) {
                    pnEl.setAttribute("font-size", fullPn.length > 13 ? "7.8" : "8.4")
                    pnEl.setAttribute("textLength", String(cardW - 5))
                    pnEl.setAttribute("lengthAdjust", "spacingAndGlyphs")
                  } else {
                    pnEl.setAttribute("font-size", "9.2")
                  }
                })
                const dx = curX - (Number(cluster.cardX) || 0)
                const dy = targetY - (Number(cluster.cardY) || 0)
                clClone.setAttribute("transform", `translate(${dx.toFixed(1)} ${dy.toFixed(1)})`)
                group.appendChild(clClone)
              }
              curX += clusterW + COL_GAP
            })
          })
        }

        pageSvg.appendChild(group)

        let viewW = Math.max(460, boxWidth + 28)
        let viewH = Math.max(280, boxHeight + 28)
        if (viewW / viewH > PAGE_ASPECT) {
          viewH = viewW / PAGE_ASPECT
        } else {
          viewW = viewH * PAGE_ASPECT
        }
        pageSvg.setAttribute(
          "viewBox",
          `${(-viewW / 2).toFixed(1)} ${(-viewH / 2).toFixed(1)} ${viewW.toFixed(1)} ${viewH.toFixed(1)}`
        )
      }

      stage.appendChild(pageSvg)
      sheet.appendChild(stage)
      printRoot.appendChild(sheet)
    })

    setTimeout(() => {
      const printWin = iframe.contentWindow
      if (printWin) {
        printWin.focus()
        printWin.print()
      }
    }, 180)
  }

  if (printFishboneBtn) {
    printFishboneBtn.onclick = printFishbone
  }

  const fullScreenBtn = parentElement.querySelector("#full-screen")
  function isFishboneFullScreen() {
    const fsElement = document.fullscreenElement || document.webkitFullscreenElement
    return Boolean(fsElement && (fsElement === shell || shell.contains(fsElement)))
  }
  function updateFullScreenControl() {
    if (!fullScreenBtn) return
    const isFullScreen = isFishboneFullScreen()
    fullScreenBtn.textContent = isFullScreen ? "Exit Full Screen" : "Full Screen"
    fullScreenBtn.title = isFullScreen ? "Exit full screen (Esc)" : "Open the fishbone full screen"
    fullScreenBtn.setAttribute("aria-pressed", isFullScreen ? "true" : "false")
  }
  shell._updateFullScreenControl = updateFullScreenControl
  if (!shell._fullscreenListenerAttached) {
    shell._fullscreenListenerAttached = true
    const onFullscreenChange = () => {
      if (typeof shell._updateFullScreenControl === "function") {
        shell._updateFullScreenControl()
      }
    }
    document.addEventListener("fullscreenchange", onFullscreenChange)
    document.addEventListener("webkitfullscreenchange", onFullscreenChange)
  }
  updateFullScreenControl()
  if (fullScreenBtn) {
    fullScreenBtn.onclick = () => {
      if (!isFishboneFullScreen()) {
        if (shell.requestFullscreen) {
          shell.requestFullscreen().then(updateFullScreenControl).catch(() => {})
        }
      } else if (document.exitFullscreen) {
        document.exitFullscreen().then(updateFullScreenControl).catch(() => {})
      }
    }
  }
}
"""

_FISHBONE_VISUAL_HOT_RELOAD_REV = 7

_FISHBONE_COMPONENT = st.components.v2.component(
    "paag_interactive_fishbone_builder_v42",
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
    if not raw:
        return ""
    if raw.startswith(("http://", "https://", "data:")):
        return raw
    return cached_image_data_url(raw, max_dim=240, output_format="JPEG", quality=78)


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
    on_update_connection_nodes: Callable[[], None] | None = None,
    on_delete_connection: Callable[[], None] | None = None,
    on_delete_section_request: Callable[[], None] | None = None,
    on_clear_fishbone_request: Callable[[], None] | None = None,
    on_drop_part: Callable[[], None] | None = None,
    on_drop_assembly: Callable[[], None] | None = None,
    on_remove_part: Callable[[], None] | None = None,
    on_move_part_assignment: Callable[[], None] | None = None,
    on_replicate_part_uses: Callable[[], None] | None = None,
    on_unstack_part_variant: Callable[[], None] | None = None,
) -> Any:
    """Render the simplified interactive Fishbone builder canvas with simple blocks and direct parent/child flow."""
    _noop = lambda: None  # noqa: E731
    kwargs = {
        "key": key,
        "data": {
            "component_key": key,
            "sections": sections,
            "connections": connections,
            "parts": parts,
            "palette_items": palette_items or [],
            "all_sections": all_sections or sections,
        },
        "width": "stretch",
        "height": "content",
        "on_create_section_change": on_create_section or _noop,
        "on_move_node_change": on_move_node or _noop,
        "on_auto_arrange_change": on_auto_arrange or _noop,
        "on_create_connection_change": on_create_connection or _noop,
        "on_move_connection_change": on_move_connection or _noop,
        "on_update_connection_nodes_change": on_update_connection_nodes or _noop,
        "on_delete_connection_change": on_delete_connection or _noop,
        "on_delete_section_request_change": on_delete_section_request or _noop,
        "on_clear_fishbone_request_change": on_clear_fishbone_request or _noop,
        "on_drop_part_change": on_drop_part or _noop,
        "on_drop_assembly_change": on_drop_assembly or _noop,
        "on_remove_part_change": on_remove_part or _noop,
        "on_move_part_assignment_change": on_move_part_assignment or _noop,
        "on_replicate_part_uses_change": on_replicate_part_uses or _noop,
        "on_unstack_part_variant_change": on_unstack_part_variant or _noop,
    }

    return _FISHBONE_COMPONENT(**kwargs)
