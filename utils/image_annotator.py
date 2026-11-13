from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import streamlit as st

_IMAGE_ANNOTATOR_REV_20261103 = 8


_HTML = """
<div class="annotator-shell" id="annotator-shell">
  <div class="annotator-toolbar">
    <div class="toolbar-row toolbar-row-top">
      <div class="tool-group tools-bar">
        <button type="button" class="tool-btn active" data-tool="select" title="Select, Move & Resize (V)">👆 Select</button>
        <button type="button" class="tool-btn" data-tool="pen" title="Freehand Pen (P)">✏️ Pen</button>
        <button type="button" class="tool-btn" data-tool="arrow" title="Arrow (A)">↗️ Arrow</button>
        <button type="button" class="tool-btn" data-tool="rect" title="Rectangle Box (R)">🔲 Box</button>
        <button type="button" class="tool-btn" data-tool="circle" title="Circle (C)">⭕ Circle</button>
        <button type="button" class="tool-btn" data-tool="text" title="Text Callout (T)">💬 Callout</button>
        <button type="button" class="tool-btn" data-tool="badge" title="Step Badge (B)">🔢 Badge</button>
        <span class="toolbar-label" style="margin-left:4px;">Next #:</span>
        <input type="number" id="next-badge-num" class="toolbar-num-input" value="1" min="1" max="99" />
      </div>
      <div class="tool-divider"></div>
      <div class="tool-group insert-photo-bar">
        <button type="button" id="btn-add-part-photo" class="action-btn insert-photo-btn" title="Pull and insert a photo from the Parts Catalog onto this visual aid">📦 Part Photo</button>
        <button type="button" id="btn-paste-photo" class="action-btn insert-photo-btn" title="Paste a photo from your clipboard (or press Ctrl+V)">📋 Paste Photo</button>
      </div>
      <div class="tool-divider"></div>
      <div class="tool-group colors-bar">
        <span class="toolbar-label">Color:</span>
        <div class="color-palette">
          <button type="button" class="color-swatch active" data-color="#ef4444" style="background:#ef4444;" title="Red"></button>
          <button type="button" class="color-swatch" data-color="#facc15" style="background:#facc15;" title="Yellow"></button>
          <button type="button" class="color-swatch" data-color="#0284c7" style="background:#0284c7;" title="Blue"></button>
          <button type="button" class="color-swatch" data-color="#22c55e" style="background:#22c55e;" title="Green"></button>
          <button type="button" class="color-swatch" data-color="#ffffff" style="background:#ffffff; border:1px solid #94a3b8;" title="White"></button>
          <button type="button" class="color-swatch" data-color="#0f172a" style="background:#0f172a;" title="Dark"></button>
        </div>
      </div>
      <div class="tool-group props-bar">
        <span class="toolbar-label" style="margin-left:4px;">Line:</span>
        <select id="stroke-width-select" class="toolbar-select">
          <option value="2">Thin</option>
          <option value="4" selected>Med</option>
          <option value="7">Thick</option>
        </select>
        <span class="toolbar-label" style="margin-left:4px;">Text:</span>
        <select id="font-size-select" class="toolbar-select" title="Callout Text Font Size">
          <option value="12">12px</option>
          <option value="14">14px</option>
          <option value="16">16px</option>
          <option value="18" selected>18px (Default)</option>
          <option value="22">22px</option>
          <option value="26">26px</option>
          <option value="32">32px</option>
          <option value="40">40px</option>
          <option value="48">48px</option>
          <option value="60">60px</option>
        </select>
        <button type="button" id="btn-font-dec" class="action-btn" title="Decrease Callout Text Font Size">A−</button>
        <button type="button" id="btn-font-inc" class="action-btn" title="Increase Callout Text Font Size">A+</button>
      </div>
    </div>
    <div class="toolbar-row toolbar-row-bottom">
      <div class="tool-group transform-bar">
        <button type="button" class="tool-btn" data-tool="crop" title="Crop Image (K)">✂️ Crop</button>
        <button type="button" id="btn-apply-crop" class="crop-action-btn apply" style="display:none;" title="Apply Crop Selection (Enter)">✓ Apply Crop</button>
        <button type="button" id="btn-cancel-crop" class="crop-action-btn cancel" style="display:none;" title="Cancel Crop Selection (Esc)">✕ Cancel</button>
        <button type="button" id="btn-rot-left" class="action-btn" title="Rotate 90° Counter-Clockwise">↺ Rotate 90° Left</button>
        <button type="button" id="btn-rot-right" class="action-btn" title="Rotate 90° Clockwise">↻ Rotate 90° Right</button>
      </div>
      <div class="tool-divider"></div>
      <div class="tool-group actions-bar">
        <button type="button" id="btn-undo" class="action-btn" title="Undo (Ctrl+Z)">↶ Undo</button>
        <button type="button" id="btn-redo" class="action-btn" title="Redo (Ctrl+Y)">↷ Redo</button>
        <button type="button" id="btn-del" class="action-btn danger" title="Delete Selected Shape or Entire Contents">🗑️ Delete</button>
      </div>
      <div class="tool-divider"></div>
      <div class="tool-group zoom-bar">
        <span class="toolbar-label">Zoom:</span>
        <button type="button" id="btn-zoom-out" class="action-btn" title="Zoom Out">−</button>
        <button type="button" id="btn-zoom-fit" class="action-btn" title="Reset Zoom to Fit Window">100% Fit</button>
        <button type="button" id="btn-zoom-in" class="action-btn" title="Zoom In Tighter">+</button>
      </div>
      <div class="tool-group save-bar">
        <button type="button" id="btn-save" class="save-btn" title="Apply annotations, crop, and rotation and save">💾 Apply & Save Markup</button>
      </div>
    </div>
  </div>
  <div class="canvas-viewport" id="canvas-viewport">
    <canvas id="annotation-canvas"></canvas>
    <div id="text-edit-overlay" class="text-edit-overlay" style="display:none;">
      <input type="text" id="text-edit-input" placeholder="Type callout note..." />
      <button type="button" id="text-edit-ok">OK</button>
      <button type="button" id="text-edit-cancel">Cancel</button>
    </div>
    <div id="part-photo-modal" class="confirm-modal-backdrop" style="display:none;">
      <div class="confirm-modal-dialog part-photo-dialog" role="dialog" aria-modal="true" aria-labelledby="part-photo-modal-title">
        <div class="confirm-modal-header">
          <h4 id="part-photo-modal-title">📦 Insert Photo from Parts Catalog</h4>
          <button type="button" id="part-photo-modal-close" class="confirm-modal-close" title="Close">✕</button>
        </div>
        <p class="confirm-modal-subtitle">Click a part photo below to overlay it onto this visual aid. Once inserted, drag to move or drag its corners to resize.</p>
        <div class="part-photo-controls">
          <input type="text" id="part-photo-search" class="part-photo-search" placeholder="Search by part number, description, or view..." />
          <select id="part-photo-scope" class="toolbar-select">
            <option value="all">All catalog photos</option>
            <option value="pitch">On this pitch only</option>
          </select>
          <label class="part-photo-label-opt">
            <input type="checkbox" id="part-photo-show-label" checked />
            <span>Show part # caption on photo</span>
          </label>
        </div>
        <div id="part-photo-grid" class="part-photo-grid"></div>
        <div class="confirm-modal-actions">
          <button type="button" id="part-photo-modal-cancel" class="confirm-btn-cancel">Cancel</button>
        </div>
      </div>
    </div>
    <div id="paste-photo-modal" class="confirm-modal-backdrop" style="display:none;">
      <div class="confirm-modal-dialog paste-photo-dialog" role="dialog" aria-modal="true" aria-labelledby="paste-photo-modal-title">
        <div class="confirm-modal-header">
          <h4 id="paste-photo-modal-title">📋 Paste or Insert Photo</h4>
          <button type="button" id="paste-photo-modal-close" class="confirm-modal-close" title="Close">✕</button>
        </div>
        <p class="confirm-modal-subtitle">Copy an image or screenshot (e.g., <strong>Win+Shift+S</strong>), then press <strong>Ctrl+V</strong> below — or choose an image file from your computer:</p>
        <div id="paste-photo-dropzone" class="paste-photo-dropzone" tabindex="0">
          <div class="paste-photo-icon">📋</div>
          <div class="paste-photo-prompt">Press <strong>Ctrl + V</strong> here to paste from clipboard</div>
          <div class="paste-photo-sub">Or click a button below to read clipboard / browse an image file</div>
          <div class="paste-photo-btn-row">
            <button type="button" id="btn-try-clipboard-read" class="action-btn insert-photo-btn">📋 Read Clipboard Now</button>
            <label for="paste-photo-file-input" class="action-btn">📁 Choose Image File...</label>
            <input type="file" id="paste-photo-file-input" accept="image/*" style="display:none;" />
          </div>
          <div id="paste-photo-feedback" class="paste-photo-feedback"></div>
        </div>
        <div class="part-photo-controls" style="justify-content:flex-start;">
          <span class="toolbar-label">Optional caption on photo:</span>
          <input type="text" id="paste-photo-caption" class="part-photo-search" placeholder="e.g. Detail view or part callout (optional)" />
        </div>
        <div class="confirm-modal-actions">
          <button type="button" id="paste-photo-modal-cancel" class="confirm-btn-cancel">Cancel</button>
        </div>
      </div>
    </div>
    <div id="delete-confirm-modal" class="confirm-modal-backdrop" style="display:none;">
      <div class="confirm-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-modal-title">
        <div class="confirm-modal-header">
          <h4 id="confirm-modal-title">Confirm Delete Markup</h4>
          <button type="button" id="confirm-modal-close" class="confirm-modal-close" title="Close">✕</button>
        </div>
        <p class="confirm-modal-subtitle">Choose what you would like to delete from this annotation window:</p>
        <div class="confirm-modal-options">
          <label class="confirm-option" id="opt-label-selected">
            <input type="radio" name="delete-mode" value="selected" id="radio-del-selected" />
            <div class="confirm-option-text">
              <span class="confirm-option-title" id="opt-title-selected">Delete selected shape</span>
              <span class="confirm-option-desc" id="opt-desc-selected">Removes only the currently selected annotation shape from the canvas.</span>
            </div>
          </label>
          <label class="confirm-option" id="opt-label-all">
            <input type="radio" name="delete-mode" value="all" id="radio-del-all" />
            <div class="confirm-option-text">
              <span class="confirm-option-title">Delete entire contents</span>
              <span class="confirm-option-desc" id="opt-desc-all">Deletes all drawn annotations and resets any crop or rotation back to the original image.</span>
            </div>
          </label>
        </div>
        <div class="confirm-warning-box" id="confirm-downstream-box">
          <strong>⚠️ Downstream effects:</strong>
          <span id="confirm-downstream-text">This change updates the current annotation canvas. You can still Undo before saving, and the saved visual aid is only overwritten when you click 💾 Apply &amp; Save Markup.</span>
        </div>
        <div class="confirm-modal-actions">
          <button type="button" id="confirm-modal-cancel" class="confirm-btn-cancel">Cancel</button>
          <button type="button" id="confirm-modal-confirm" class="confirm-btn-danger">🗑️ Delete</button>
        </div>
      </div>
    </div>
  </div>
  <div class="annotator-statusbar">
    <span id="annotator-status">Select a tool to annotate, crop, or rotate · Click and drag on image</span>
    <span id="annotator-count">0 annotations</span>
  </div>
</div>
"""

_CSS = """
:host {
  color: var(--st-text-color, #1e293b);
  font-family: var(--st-font, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
}
.annotator-shell {
  display: flex;
  flex-direction: column;
  width: 100%;
  border: 1px solid var(--st-border-color, #cbd5e1);
  border-radius: var(--st-base-radius, 8px);
  background: var(--st-background-color, #ffffff);
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}
.annotator-toolbar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  background: var(--st-secondary-background-color, #f8fafc);
  border-bottom: 1px solid var(--st-border-color, #cbd5e1);
  user-select: none;
}
.toolbar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  width: 100%;
}
.toolbar-row-bottom {
  padding-top: 6px;
  border-top: 1px solid #e2e8f0;
}
.tool-group {
  display: flex;
  align-items: center;
  gap: 4px;
}
.tool-divider {
  width: 1px;
  height: 22px;
  background: var(--st-border-color, #cbd5e1);
  margin: 0 4px;
}
.toolbar-label {
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--st-secondary-text-color, #64748b);
}
.tool-btn, .action-btn, .crop-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 8px;
  font-size: 0.78rem;
  font-weight: 600;
  border-radius: 5px;
  border: 1px solid var(--st-border-color, #cbd5e1);
  background: var(--st-background-color, #ffffff);
  color: var(--st-text-color, #1e293b);
  cursor: pointer;
  transition: all 0.12s ease;
  line-height: 1.2;
}
.tool-btn:hover, .action-btn:hover {
  border-color: #0284c7;
  color: #0284c7;
}
.tool-btn.active {
  background: #0284c7;
  color: #ffffff;
  border-color: #0284c7;
  box-shadow: 0 1px 3px rgba(2, 132, 199, 0.4);
}
.crop-action-btn.apply {
  background: #0284c7;
  color: #ffffff;
  border-color: #0369a1;
  font-weight: 700;
}
.crop-action-btn.apply:hover {
  background: #0369a1;
}
.crop-action-btn.cancel {
  background: #f1f5f9;
  color: #475569;
  border-color: #94a3b8;
}
.crop-action-btn.cancel:hover {
  background: #e2e8f0;
  color: #0f172a;
}
.action-btn.danger {
  background: #c62828;
  color: #ffffff;
  border-color: #c62828;
}
.action-btn.danger:hover {
  background: #a71919;
  color: #ffffff;
  border-color: #a71919;
}
.color-palette {
  display: flex;
  align-items: center;
  gap: 4px;
}
.color-swatch {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
  transition: transform 0.12s ease, border-color 0.12s ease;
}
.color-swatch:hover {
  transform: scale(1.15);
}
.color-swatch.active {
  border-color: #0f172a;
  transform: scale(1.18);
  box-shadow: 0 0 0 1px #ffffff, 0 0 4px rgba(0,0,0,0.5);
}
.toolbar-select, .toolbar-num-input {
  font-size: 0.76rem;
  padding: 3px 5px;
  border-radius: 4px;
  border: 1px solid var(--st-border-color, #cbd5e1);
  background: var(--st-background-color, #ffffff);
  color: var(--st-text-color, #1e293b);
}
.toolbar-num-input {
  width: 44px;
}
.save-bar {
  margin-left: auto;
}
.save-btn {
  background: #16a34a;
  color: #ffffff;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 5px 12px;
  border-radius: 6px;
  border: 1px solid #15803d;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(22, 163, 74, 0.3);
  transition: background 0.12s ease, transform 0.12s ease;
}
.save-btn:hover {
  background: #15803d;
  transform: translateY(-1px);
}
.canvas-viewport {
  position: relative;
  width: 100%;
  height: 540px;
  min-height: 420px;
  background: #1e293b;
  display: flex;
  overflow: auto;
  user-select: none;
}
#annotation-canvas {
  display: block;
  cursor: crosshair;
  box-shadow: 0 4px 20px rgba(0,0,0,0.4);
  margin: auto;
}
.text-edit-overlay {
  position: absolute;
  z-index: 20;
  display: flex;
  gap: 4px;
  background: #0f172a;
  padding: 6px;
  border-radius: 6px;
  border: 1px solid #38bdf8;
  box-shadow: 0 8px 24px rgba(0,0,0,0.6);
}
#text-edit-input {
  width: 200px;
  padding: 4px 8px;
  border-radius: 4px;
  border: 1px solid #64748b;
  background: #ffffff;
  color: #0f172a;
  font-size: 0.82rem;
  font-weight: 600;
}
#text-edit-ok, #text-edit-cancel {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
  border: none;
}
#text-edit-ok { background: #0284c7; color: #ffffff; }
#text-edit-cancel { background: #64748b; color: #ffffff; }
.confirm-modal-backdrop {
  position: absolute;
  inset: 0;
  z-index: 50;
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.confirm-modal-dialog {
  width: 100%;
  max-width: 460px;
  background: #ffffff;
  color: #1e293b;
  border-radius: 10px;
  border: 1px solid #cbd5e1;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.35);
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.confirm-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.confirm-modal-header h4 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
}
.confirm-modal-close {
  background: transparent;
  border: none;
  font-size: 1rem;
  color: #64748b;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}
.confirm-modal-close:hover {
  background: #f1f5f9;
  color: #0f172a;
}
.confirm-modal-subtitle {
  margin: 0;
  font-size: 0.84rem;
  color: #475569;
}
.confirm-modal-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.confirm-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  cursor: pointer;
  background: #f8fafc;
  transition: border-color 0.12s ease, background 0.12s ease;
}
.confirm-option:hover:not(.disabled) {
  border-color: #0284c7;
  background: #f0f9ff;
}
.confirm-option.disabled {
  opacity: 0.55;
  cursor: not-allowed;
  background: #f1f5f9;
}
.confirm-option input[type="radio"] {
  margin-top: 3px;
  accent-color: #c62828;
}
.confirm-option-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.confirm-option-title {
  font-size: 0.84rem;
  font-weight: 700;
  color: #0f172a;
}
.confirm-option-desc {
  font-size: 0.76rem;
  color: #64748b;
}
.confirm-warning-box {
  padding: 10px 12px;
  border-radius: 6px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  font-size: 0.78rem;
  line-height: 1.4;
}
.confirm-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
.confirm-btn-cancel {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
}
.confirm-btn-cancel:hover {
  background: #f1f5f9;
}
.confirm-btn-danger {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid #c62828;
  background: #c62828;
  color: #ffffff;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
}
.confirm-btn-danger:hover {
  background: #a71919;
  border-color: #a71919;
}
.insert-photo-btn {
  background: #f0f9ff;
  border-color: #7dd3fc;
  color: #0369a1;
  font-weight: 700;
}
.insert-photo-btn:hover {
  background: #e0f2fe;
  border-color: #0284c7;
  color: #075985;
}
.part-photo-dialog {
  max-width: 680px;
  max-height: 490px;
}
.paste-photo-dialog {
  max-width: 520px;
}
.part-photo-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.part-photo-search {
  flex: 1 1 200px;
  padding: 5px 9px;
  font-size: 0.8rem;
  border-radius: 5px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #0f172a;
}
.part-photo-label-opt {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.78rem;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
}
.part-photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(145px, 1fr));
  gap: 10px;
  max-height: 270px;
  overflow-y: auto;
  padding: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.part-photo-card {
  display: flex;
  flex-direction: column;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: #ffffff;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease;
  text-align: left;
  padding: 0;
}
.part-photo-card:hover {
  border-color: #0284c7;
  box-shadow: 0 4px 12px rgba(2, 132, 199, 0.22);
  transform: translateY(-1px);
}
.part-photo-thumb {
  width: 100%;
  height: 96px;
  object-fit: contain;
  background: #0f172a;
  border-bottom: 1px solid #e2e8f0;
}
.part-photo-meta {
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.part-photo-pnum {
  font-size: 0.78rem;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.part-photo-desc {
  font-size: 0.71rem;
  color: #475569;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.part-photo-view {
  font-size: 0.68rem;
  color: #0284c7;
  font-weight: 600;
}
.part-photo-badge {
  display: inline-block;
  align-self: flex-start;
  font-size: 0.65rem;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  background: #dcfce7;
  color: #166534;
  margin-bottom: 2px;
}
.part-photo-empty {
  grid-column: 1 / -1;
  padding: 24px 12px;
  text-align: center;
  font-size: 0.82rem;
  color: #64748b;
}
.paste-photo-dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 20px 16px;
  border: 2px dashed #38bdf8;
  border-radius: 8px;
  background: #f0f9ff;
  text-align: center;
  outline: none;
}
.paste-photo-dropzone:focus {
  border-color: #0284c7;
  background: #e0f2fe;
  box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.2);
}
.paste-photo-icon {
  font-size: 1.6rem;
}
.paste-photo-prompt {
  font-size: 0.88rem;
  color: #0f172a;
}
.paste-photo-sub {
  font-size: 0.75rem;
  color: #475569;
}
.paste-photo-btn-row {
  display: flex;
  gap: 8px;
  margin-top: 6px;
  flex-wrap: wrap;
  justify-content: center;
}
.paste-photo-feedback {
  font-size: 0.76rem;
  color: #b91c1c;
  min-height: 16px;
  margin-top: 2px;
}
.annotator-statusbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 12px;
  background: var(--st-secondary-background-color, #f8fafc);
  border-top: 1px solid var(--st-border-color, #cbd5e1);
  font-size: 0.76rem;
  color: var(--st-secondary-text-color, #64748b);
}
"""

_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component;
  if (typeof parentElement.__paagAnnotatorCleanup === "function") {
    try { parentElement.__paagAnnotatorCleanup(); } catch (e) {}
  }
  const shell = parentElement.querySelector("#annotator-shell");
  const canvas = parentElement.querySelector("#annotation-canvas");
  const viewport = parentElement.querySelector("#canvas-viewport");
  const ctx = canvas.getContext("2d");
  const statusEl = parentElement.querySelector("#annotator-status");
  const countEl = parentElement.querySelector("#annotator-count");
  const textOverlay = parentElement.querySelector("#text-edit-overlay");
  const textInput = parentElement.querySelector("#text-edit-input");
  const textOkBtn = parentElement.querySelector("#text-edit-ok");
  const textCancelBtn = parentElement.querySelector("#text-edit-cancel");
  const strokeSelect = parentElement.querySelector("#stroke-width-select");
  const fontSizeSelect = parentElement.querySelector("#font-size-select");
  const fontDecBtn = parentElement.querySelector("#btn-font-dec");
  const fontIncBtn = parentElement.querySelector("#btn-font-inc");
  const nextBadgeInput = parentElement.querySelector("#next-badge-num");
  const applyCropBtn = parentElement.querySelector("#btn-apply-crop");
  const cancelCropBtn = parentElement.querySelector("#btn-cancel-crop");
  const rotLeftBtn = parentElement.querySelector("#btn-rot-left");
  const rotRightBtn = parentElement.querySelector("#btn-rot-right");
  const zoomOutBtn = parentElement.querySelector("#btn-zoom-out");
  const zoomFitBtn = parentElement.querySelector("#btn-zoom-fit");
  const zoomInBtn = parentElement.querySelector("#btn-zoom-in");
  const deleteModal = parentElement.querySelector("#delete-confirm-modal");
  const deleteModalClose = parentElement.querySelector("#confirm-modal-close");
  const deleteModalCancel = parentElement.querySelector("#confirm-modal-cancel");
  const deleteModalConfirm = parentElement.querySelector("#confirm-modal-confirm");
  const radioDelSelected = parentElement.querySelector("#radio-del-selected");
  const radioDelAll = parentElement.querySelector("#radio-del-all");
  const optLabelSelected = parentElement.querySelector("#opt-label-selected");
  const optTitleSelected = parentElement.querySelector("#opt-title-selected");
  const optDescSelected = parentElement.querySelector("#opt-desc-selected");
  const optDescAll = parentElement.querySelector("#opt-desc-all");
  const downstreamText = parentElement.querySelector("#confirm-downstream-text");
  const addPartPhotoBtn = parentElement.querySelector("#btn-add-part-photo");
  const pastePhotoBtn = parentElement.querySelector("#btn-paste-photo");
  const partPhotoModal = parentElement.querySelector("#part-photo-modal");
  const partPhotoModalClose = parentElement.querySelector("#part-photo-modal-close");
  const partPhotoModalCancel = parentElement.querySelector("#part-photo-modal-cancel");
  const partPhotoSearch = parentElement.querySelector("#part-photo-search");
  const partPhotoScope = parentElement.querySelector("#part-photo-scope");
  const partPhotoShowLabel = parentElement.querySelector("#part-photo-show-label");
  const partPhotoGrid = parentElement.querySelector("#part-photo-grid");
  const pastePhotoModal = parentElement.querySelector("#paste-photo-modal");
  const pastePhotoModalClose = parentElement.querySelector("#paste-photo-modal-close");
  const pastePhotoModalCancel = parentElement.querySelector("#paste-photo-modal-cancel");
  const pastePhotoDropzone = parentElement.querySelector("#paste-photo-dropzone");
  const tryClipboardReadBtn = parentElement.querySelector("#btn-try-clipboard-read");
  const pastePhotoFileInput = parentElement.querySelector("#paste-photo-file-input");
  const pastePhotoFeedback = parentElement.querySelector("#paste-photo-feedback");
  const pastePhotoCaption = parentElement.querySelector("#paste-photo-caption");

  let currentTool = "select";
  let currentColor = "#ef4444";
  let currentStrokeWidth = 4;
  const FONT_SIZE_STEPS = [12, 14, 16, 18, 22, 26, 32, 40, 48, 60];
  let currentFontSize = 18;
  let editingTextShapeId = null;
  let shapes = [];
  let transformOps = [];
  let undoStack = [];
  let redoStack = [];
  let selectedShapeId = null;
  let isDrawing = false;
  let isDragging = false;
  let isResizing = false;
  let resizeHandle = null;
  let isCropping = false;
  let cropRect = null;
  let dragStartX = 0;
  let dragStartY = 0;
  let activeShape = null;
  let img = new Image();
  let workingCanvas = document.createElement("canvas");
  let imgLoaded = false;
  let scale = 1.0;
  let zoomMultiplier = 1.0;
  let savedPanX = 0.5;
  let savedPanY = 0.5;
  let canvasDispW = 800;
  let canvasDispH = 500;
  const imageShapeCache = new Map();
  const catalogPhotos = Array.isArray(data && data.catalog_photos) ? data.catalog_photos : [];

  function getCachedShapeImage(shapeOrUrl) {
    const dataUrl = (shapeOrUrl && typeof shapeOrUrl === "object")
      ? (shapeOrUrl.dataUrl || shapeOrUrl.data_url || "")
      : shapeOrUrl;
    if (!dataUrl || typeof dataUrl !== "string") return null;
    if (imageShapeCache.has(dataUrl)) {
      return imageShapeCache.get(dataUrl);
    }
    const cachedIm = new Image();
    if (!dataUrl.startsWith("data:")) {
      cachedIm.crossOrigin = "anonymous";
    }
    imageShapeCache.set(dataUrl, cachedIm);
    cachedIm.onload = () => {
      render();
    };
    cachedIm.src = dataUrl;
    return cachedIm;
  }

  function warmShapeImages() {
    shapes.forEach(s => {
      if (s && s.type === "image" && (s.dataUrl || s.data_url)) {
        getCachedShapeImage(s.dataUrl || s.data_url);
      }
    });
  }

  function activateSelectTool() {
    currentTool = "select";
    parentElement.querySelectorAll(".tool-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.tool === "select");
    });
    canvas.style.cursor = "default";
  }

  function insertImageOverlay(rawSrcUrl, labelText, sourceTag, partMeta) {
    if (!imgLoaded || !rawSrcUrl) return;
    statusEl.textContent = "Loading photo into annotation canvas...";
    const loader = new Image();
    if (!String(rawSrcUrl).startsWith("data:")) {
      loader.crossOrigin = "anonymous";
    }
    loader.onload = () => {
      const natW = loader.naturalWidth || 240;
      const natH = loader.naturalHeight || 240;
      const maxStoredDim = 640;
      let storeW = natW;
      let storeH = natH;
      if (Math.max(natW, natH) > maxStoredDim) {
        const r = maxStoredDim / Math.max(natW, natH);
        storeW = Math.max(1, Math.round(natW * r));
        storeH = Math.max(1, Math.round(natH * r));
      }
      let finalDataUrl = rawSrcUrl;
      try {
        const normCanvas = document.createElement("canvas");
        normCanvas.width = storeW;
        normCanvas.height = storeH;
        const nctx = normCanvas.getContext("2d");
        nctx.drawImage(loader, 0, 0, storeW, storeH);
        finalDataUrl = normCanvas.toDataURL("image/png");
      } catch (err) {
        finalDataUrl = rawSrcUrl;
      }
      imageShapeCache.set(finalDataUrl, loader);
      if (rawSrcUrl !== finalDataUrl) {
        imageShapeCache.set(rawSrcUrl, loader);
      }

      const workW = getWorkingWidth();
      const workH = getWorkingHeight();
      const baseRef = Math.min(workW, workH);
      const targetMaxDim = Math.max(96, Math.min(Math.round(baseRef * 0.34), Math.round(workW * 0.45), Math.round(workH * 0.45)));
      const aspect = natW / Math.max(1, natH);
      let boxW = aspect >= 1 ? targetMaxDim : Math.max(64, Math.round(targetMaxDim * aspect));
      let photoH = aspect >= 1 ? Math.max(64, Math.round(targetMaxDim / aspect)) : targetMaxDim;
      const cleanLabel = String(labelText || "").trim();
      const normFactor = getVisualNormFactor();
      const extraFooterH = cleanLabel
        ? Math.max(18, Math.round(Math.min(photoH * 0.28, Math.max(11 * normFactor, Math.min(18 * normFactor, photoH * 0.14)) + 8 * normFactor)))
        : 0;
      let boxH = photoH + extraFooterH;
      boxW = Math.min(workW - 16, boxW);
      boxH = Math.min(workH - 16, boxH);

      const existingImgs = shapes.filter(s => s && s.type === "image").length;
      const cascade = (existingImgs % 5) * 22;
      const startX = Math.max(12, Math.min(workW - boxW - 12, Math.round(workW - boxW - 24 - cascade)));
      const startY = Math.max(12, Math.min(workH - boxH - 12, 24 + cascade));

      pushUndo();
      const newShape = {
        id: `shape_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`,
        type: "image",
        x: startX,
        y: startY,
        w: boxW,
        h: boxH,
        dataUrl: finalDataUrl,
        label: String(labelText || "").trim(),
        color: currentColor,
        strokeWidth: currentStrokeWidth,
      };
      if (partMeta && typeof partMeta === "object") {
        if (partMeta.partId) newShape.partId = String(partMeta.partId);
        if (partMeta.partNumber) newShape.partNumber = String(partMeta.partNumber);
        if (partMeta.viewId) newShape.viewId = String(partMeta.viewId);
      }
      shapes.push(newShape);
      selectedShapeId = newShape.id;
      activateSelectTool();
      statusEl.textContent = `Inserted ${sourceTag || "photo"} · Drag to move or drag corners to resize`;
      render();
    };
    loader.onerror = () => {
      statusEl.textContent = "Could not load the selected photo.";
    };
    loader.src = rawSrcUrl;
  }

  function getWorkingWidth() {
    return workingCanvas.width || img.naturalWidth || 800;
  }

  function getWorkingHeight() {
    return workingCanvas.height || img.naturalHeight || 500;
  }

  function getBaseFitScale() {
    const natW = Math.max(1, getWorkingWidth());
    const natH = Math.max(1, getWorkingHeight());
    const fitW = 784 / natW;
    const fitH = 524 / natH;
    return Math.max(0.02, Math.min(fitW, fitH, 4.0));
  }

  function getVisualNormFactor() {
    return 1.0 / getBaseFitScale();
  }

  function rebuildWorkingImage() {
    if (!imgLoaded) return;
    let srcCanvas = document.createElement("canvas");
    srcCanvas.width = img.naturalWidth || 1;
    srcCanvas.height = img.naturalHeight || 1;
    const sctx = srcCanvas.getContext("2d");
    sctx.drawImage(img, 0, 0);

    for (const op of transformOps) {
      if (!op || typeof op !== "object") continue;
      if (op.kind === "rotate") {
        const angle = Number(op.angle) || 0;
        if (angle === 90 || angle === -90) {
          const nextCanvas = document.createElement("canvas");
          nextCanvas.width = srcCanvas.height;
          nextCanvas.height = srcCanvas.width;
          const nctx = nextCanvas.getContext("2d");
          if (angle === 90) {
            nctx.translate(nextCanvas.width, 0);
            nctx.rotate(Math.PI / 2);
          } else {
            nctx.translate(0, nextCanvas.height);
            nctx.rotate(-Math.PI / 2);
          }
          nctx.drawImage(srcCanvas, 0, 0);
          srcCanvas = nextCanvas;
        }
      } else if (op.kind === "crop") {
        const cx = Math.max(0, Math.min(srcCanvas.width - 1, Math.round(Number(op.x) || 0)));
        const cy = Math.max(0, Math.min(srcCanvas.height - 1, Math.round(Number(op.y) || 0)));
        const cw = Math.max(1, Math.min(srcCanvas.width - cx, Math.round(Number(op.w) || srcCanvas.width)));
        const ch = Math.max(1, Math.min(srcCanvas.height - cy, Math.round(Number(op.h) || srcCanvas.height)));
        const nextCanvas = document.createElement("canvas");
        nextCanvas.width = cw;
        nextCanvas.height = ch;
        const nctx = nextCanvas.getContext("2d");
        nctx.drawImage(srcCanvas, cx, cy, cw, ch, 0, 0, cw, ch);
        srcCanvas = nextCanvas;
      }
    }
    workingCanvas = srcCanvas;
  }

  function syncCropActionButtons() {
    const hasValidCrop = Boolean(cropRect && Math.abs(cropRect.w) >= 12 && Math.abs(cropRect.h) >= 12);
    applyCropBtn.style.display = hasValidCrop ? "inline-flex" : "none";
    cancelCropBtn.style.display = hasValidCrop ? "inline-flex" : "none";
  }

  function applyPendingCrop() {
    if (!cropRect) return false;
    const wMax = getWorkingWidth();
    const hMax = getWorkingHeight();
    const nx = Math.max(0, Math.min(wMax - 1, Math.round(Math.min(cropRect.x, cropRect.x + cropRect.w))));
    const ny = Math.max(0, Math.min(hMax - 1, Math.round(Math.min(cropRect.y, cropRect.y + cropRect.h))));
    const nw = Math.max(1, Math.min(wMax - nx, Math.round(Math.abs(cropRect.w))));
    const nh = Math.max(1, Math.min(hMax - ny, Math.round(Math.abs(cropRect.h))));
    if (nw < 12 || nh < 12) {
      cropRect = null;
      syncCropActionButtons();
      render();
      return false;
    }
    pushUndo();
    transformOps.push({ kind: "crop", x: nx, y: ny, w: nw, h: nh });
    shapes.forEach(s => moveShape(s, -nx, -ny));
    cropRect = null;
    selectedShapeId = null;
    syncCropActionButtons();
    rebuildWorkingImage();
    resizeCanvas();
    statusEl.textContent = `Cropped image to ${nw}×${nh} px`;
    render();
    return true;
  }

  function cancelPendingCrop() {
    cropRect = null;
    isCropping = false;
    syncCropActionButtons();
    statusEl.textContent = `Crop selection cancelled · ${getToolHint(currentTool)}`;
    render();
  }

  applyCropBtn.onclick = () => {
    applyPendingCrop();
  };

  cancelCropBtn.onclick = () => {
    cancelPendingCrop();
  };

  function rotateImage90(deltaAngle) {
    if (!imgLoaded) return;
    const oldW = getWorkingWidth();
    const oldH = getWorkingHeight();
    pushUndo();
    transformOps.push({ kind: "rotate", angle: deltaAngle });

    const rotPt = (px, py) => {
      if (deltaAngle === 90) {
        return [oldH - py, px];
      }
      return [py, oldW - px];
    };

    shapes.forEach(s => {
      if (s.type === "arrow") {
        const [nx1, ny1] = rotPt(s.x1, s.y1);
        const [nx2, ny2] = rotPt(s.x2, s.y2);
        s.x1 = nx1; s.y1 = ny1;
        s.x2 = nx2; s.y2 = ny2;
      } else if (s.type === "rect" || s.type === "circle" || s.type === "image") {
        const [ax, ay] = rotPt(s.x, s.y);
        const [bx, by] = rotPt(s.x + s.w, s.y + s.h);
        s.x = Math.min(ax, bx);
        s.y = Math.min(ay, by);
        s.w = Math.abs(bx - ax);
        s.h = Math.abs(by - ay);
      } else if (s.type === "badge" || s.type === "text") {
        const [nx, ny] = rotPt(s.x, s.y);
        s.x = nx; s.y = ny;
      } else if (s.type === "pen" && Array.isArray(s.points)) {
        s.points = s.points.map(p => {
          const [nx, ny] = rotPt(p.x, p.y);
          return { x: nx, y: ny };
        });
      }
    });

    cropRect = null;
    selectedShapeId = null;
    syncCropActionButtons();
    rebuildWorkingImage();
    resizeCanvas();
    statusEl.textContent = deltaAngle === 90 ? "Rotated image 90° clockwise" : "Rotated image 90° counter-clockwise";
    render();
  }

  rotLeftBtn.onclick = () => rotateImage90(-90);
  rotRightBtn.onclick = () => rotateImage90(90);

  // Zoom controls
  function hasZoomTransform() {
    return Math.abs((Number(zoomMultiplier) || 1.0) - 1.0) > 0.001;
  }

  function getNormalizedViewportPan() {
    const vpW = viewport.clientWidth || 800;
    const vpH = viewport.clientHeight || 540;
    let panX = (typeof savedPanX === "number" && isFinite(savedPanX)) ? savedPanX : 0.5;
    let panY = (typeof savedPanY === "number" && isFinite(savedPanY)) ? savedPanY : 0.5;
    if (canvasDispW > vpW && canvasDispW > 0) {
      panX = (viewport.scrollLeft + vpW / 2) / canvasDispW;
    }
    if (canvasDispH > vpH && canvasDispH > 0) {
      panY = (viewport.scrollTop + vpH / 2) / canvasDispH;
    }
    return {
      panX: Math.max(0, Math.min(1, panX)),
      panY: Math.max(0, Math.min(1, panY)),
    };
  }

  function syncViewportScrollToPan(panX, panY) {
    const vpW = viewport.clientWidth || 800;
    const vpH = viewport.clientHeight || 540;
    if (canvasDispW > vpW) {
      const targetLeft = Math.round(panX * canvasDispW - vpW / 2);
      viewport.scrollLeft = Math.max(0, Math.min(canvasDispW - vpW, targetLeft));
    } else {
      viewport.scrollLeft = 0;
    }
    if (canvasDispH > vpH) {
      const targetTop = Math.round(panY * canvasDispH - vpH / 2);
      viewport.scrollTop = Math.max(0, Math.min(canvasDispH - vpH, targetTop));
    } else {
      viewport.scrollTop = 0;
    }
  }

  viewport.addEventListener("scroll", () => {
    if (!imgLoaded) return;
    const vpW = viewport.clientWidth || 800;
    const vpH = viewport.clientHeight || 540;
    if (canvasDispW > vpW && canvasDispW > 0) {
      savedPanX = Math.max(0, Math.min(1, (viewport.scrollLeft + vpW / 2) / canvasDispW));
    }
    if (canvasDispH > vpH && canvasDispH > 0) {
      savedPanY = Math.max(0, Math.min(1, (viewport.scrollTop + vpH / 2) / canvasDispH));
    }
  }, { passive: true });

  function setZoom(newMultiplier, recordUndo = true) {
    const clamped = Math.max(0.5, Math.min(3.0, Math.round(newMultiplier * 100) / 100));
    if (Math.abs(clamped - zoomMultiplier) < 0.001) {
      zoomFitBtn.textContent = `${Math.round(zoomMultiplier * 100)}% Fit`;
      return;
    }
    const prevPan = getNormalizedViewportPan();
    if (recordUndo && imgLoaded) {
      pushUndo();
    }
    zoomMultiplier = clamped;
    if (!hasZoomTransform()) {
      savedPanX = 0.5;
      savedPanY = 0.5;
    } else {
      savedPanX = prevPan.panX;
      savedPanY = prevPan.panY;
    }
    zoomFitBtn.textContent = `${Math.round(zoomMultiplier * 100)}% Fit`;
    resizeCanvas();
    syncViewportScrollToPan(savedPanX, savedPanY);
    statusEl.textContent = `Zoom set to ${Math.round(zoomMultiplier * 100)}% · Click '💾 Apply & Save Markup' to apply`;
    render();
  }

  zoomOutBtn.onclick = () => setZoom(zoomMultiplier - 0.25);
  zoomFitBtn.onclick = () => setZoom(1.0);
  zoomInBtn.onclick = () => setZoom(zoomMultiplier + 0.25);

  viewport.addEventListener("wheel", (e) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.15 : -0.15;
      setZoom(zoomMultiplier + delta);
    }
  }, { passive: false });

  // Initialize tool buttons
  parentElement.querySelectorAll(".tool-btn").forEach(btn => {
    btn.onclick = () => {
      commitPendingTextOverlay(false);
      parentElement.querySelectorAll(".tool-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentTool = btn.dataset.tool;
      selectedShapeId = null;
      if (currentTool !== "crop" && cropRect) {
        cropRect = null;
        syncCropActionButtons();
      }
      canvas.style.cursor = currentTool === "select" ? "default" : "crosshair";
      statusEl.textContent = `Tool: ${btn.textContent.trim()} · ${getToolHint(currentTool)}`;
      render();
    };
  });

  // Initialize color swatches
  parentElement.querySelectorAll(".color-swatch").forEach(swatch => {
    swatch.onclick = () => {
      if (textOverlay.style.display === "flex" && textInput.value.trim()) {
        commitPendingTextOverlay(true);
      }
      parentElement.querySelectorAll(".color-swatch").forEach(s => s.classList.remove("active"));
      swatch.classList.add("active");
      currentColor = swatch.dataset.color;
      if (selectedShapeId) {
        const sel = shapes.find(s => s.id === selectedShapeId);
        if (sel) {
          pushUndo();
          sel.color = currentColor;
          render();
        }
      }
    };
  });

  function syncFontSizeSelectValue(val) {
    if (!fontSizeSelect) return;
    const numVal = Math.round(Number(val) || 18);
    let closest = FONT_SIZE_STEPS[0];
    for (const step of FONT_SIZE_STEPS) {
      if (Math.abs(step - numVal) < Math.abs(closest - numVal)) {
        closest = step;
      }
    }
    fontSizeSelect.value = String(closest);
  }

  function applyFontSize(newSize) {
    if (textOverlay.style.display === "flex" && textInput.value.trim()) {
      commitPendingTextOverlay(true);
    }
    const clamped = Math.max(10, Math.min(72, Math.round(Number(newSize) || 18)));
    currentFontSize = clamped;
    syncFontSizeSelectValue(clamped);
    if (selectedShapeId) {
      const sel = shapes.find(s => s.id === selectedShapeId);
      if (sel && sel.type === "text") {
        pushUndo();
        sel.fontSize = currentFontSize;
        statusEl.textContent = `Callout text font size set to ${currentFontSize}px`;
        render();
      }
    }
  }

  if (fontSizeSelect) {
    fontSizeSelect.onchange = () => {
      applyFontSize(parseInt(fontSizeSelect.value, 10) || 18);
    };
  }
  if (fontDecBtn) {
    fontDecBtn.onclick = () => {
      let idx = FONT_SIZE_STEPS.findIndex(v => v >= currentFontSize);
      if (idx === -1) idx = FONT_SIZE_STEPS.length - 1;
      const nextIdx = Math.max(0, idx - 1);
      applyFontSize(FONT_SIZE_STEPS[nextIdx]);
    };
  }
  if (fontIncBtn) {
    fontIncBtn.onclick = () => {
      let idx = FONT_SIZE_STEPS.findIndex(v => v > currentFontSize);
      if (idx === -1) idx = FONT_SIZE_STEPS.length - 1;
      applyFontSize(FONT_SIZE_STEPS[idx]);
    };
  }

  strokeSelect.onchange = () => {
    if (textOverlay.style.display === "flex" && textInput.value.trim()) {
      commitPendingTextOverlay(true);
    }
    currentStrokeWidth = parseInt(strokeSelect.value, 10) || 4;
    if (selectedShapeId) {
      const sel = shapes.find(s => s.id === selectedShapeId);
      if (sel) {
        pushUndo();
        sel.strokeWidth = currentStrokeWidth;
        render();
      }
    }
  };

  function getToolHint(t) {
    switch(t) {
      case "select": return "Click shape/photo to select · Drag to move · Drag corners to resize · Del to delete";
      case "crop": return "Click and drag to select crop area, then click ✓ Apply Crop (or Enter)";
      case "arrow": return "Click and drag to point arrow";
      case "rect": return "Click and drag to draw focus box";
      case "circle": return "Click and drag to circle component";
      case "text": return "Click where you want the callout note";
      case "badge": return "Click where you want the step number badge";
      case "pen": return "Click and drag to draw freehand markup";
      default: return "";
    }
  }

  function snapshotState() {
    const pan = getNormalizedViewportPan();
    return JSON.stringify({
      shapes: shapes,
      transformOps: transformOps,
      zoomMultiplier: zoomMultiplier,
      panX: pan.panX,
      panY: pan.panY,
    });
  }

  function restoreState(serialized) {
    try {
      const parsed = JSON.parse(serialized);
      if (Array.isArray(parsed)) {
        shapes = parsed;
        transformOps = [];
        zoomMultiplier = 1.0;
        savedPanX = 0.5;
        savedPanY = 0.5;
      } else if (parsed && typeof parsed === "object") {
        shapes = Array.isArray(parsed.shapes) ? parsed.shapes : [];
        transformOps = Array.isArray(parsed.transformOps) ? parsed.transformOps : [];
        const zVal = Number(parsed.zoomMultiplier);
        zoomMultiplier = (isFinite(zVal) && zVal >= 0.5 && zVal <= 3.0) ? Math.round(zVal * 100) / 100 : 1.0;
        const pxVal = Number(parsed.panX);
        const pyVal = Number(parsed.panY);
        savedPanX = (isFinite(pxVal) && pxVal >= 0 && pxVal <= 1) ? pxVal : 0.5;
        savedPanY = (isFinite(pyVal) && pyVal >= 0 && pyVal <= 1) ? pyVal : 0.5;
      }
    } catch (e) {
      shapes = [];
      transformOps = [];
      zoomMultiplier = 1.0;
      savedPanX = 0.5;
      savedPanY = 0.5;
    }
    zoomFitBtn.textContent = `${Math.round(zoomMultiplier * 100)}% Fit`;
    warmShapeImages();
    selectedShapeId = null;
    cropRect = null;
    syncCropActionButtons();
    rebuildWorkingImage();
    resizeCanvas();
    syncViewportScrollToPan(savedPanX, savedPanY);
    render();
  }

  function pushUndo() {
    undoStack.push(snapshotState());
    if (undoStack.length > 30) undoStack.shift();
    redoStack = [];
    updateStatus();
  }

  parentElement.querySelector("#btn-undo").onclick = () => {
    if (undoStack.length > 0) {
      redoStack.push(snapshotState());
      restoreState(undoStack.pop());
    }
  };

  parentElement.querySelector("#btn-redo").onclick = () => {
    if (redoStack.length > 0) {
      undoStack.push(snapshotState());
      restoreState(redoStack.pop());
    }
  };

  function formatShapeLabel(shape) {
    if (!shape) return "selected shape";
    switch (shape.type) {
      case "arrow": return "Arrow";
      case "rect": return "Box";
      case "circle": return "Circle";
      case "text": return shape.text ? `Callout ("${shape.text}")` : "Callout";
      case "badge": return `Step Badge #${shape.badgeNum || 1}`;
      case "pen": return "Freehand Pen stroke";
      case "image": return shape.label ? `Inset Photo (${shape.label})` : "Inset Photo";
      default: return "shape";
    }
  }

  // Parts Catalog Photo Picker Modal
  function renderPartPhotoGrid() {
    while (partPhotoGrid.firstChild) {
      partPhotoGrid.removeChild(partPhotoGrid.firstChild);
    }
    if (!catalogPhotos || catalogPhotos.length === 0) {
      const emptyEl = document.createElement("div");
      emptyEl.className = "part-photo-empty";
      emptyEl.textContent = "No photos found in the Parts Catalog yet. Upload or paste part photos in the Parts Catalog module to pull them into visual aid annotations.";
      partPhotoGrid.appendChild(emptyEl);
      return;
    }
    const query = (partPhotoSearch.value || "").trim().toLowerCase();
    const scopeVal = partPhotoScope.value || "all";
    const filtered = catalogPhotos.filter(item => {
      if (!item || !item.data_url) return false;
      if (scopeVal === "pitch" && !item.on_pitch) return false;
      if (!query) return true;
      const hay = `${item.part_number || ""} ${item.description || ""} ${item.view_label || ""} ${item.caption || ""}`.toLowerCase();
      return hay.includes(query);
    });
    if (filtered.length === 0) {
      const emptyEl = document.createElement("div");
      emptyEl.className = "part-photo-empty";
      emptyEl.textContent = scopeVal === "pitch"
        ? "No matching Parts Catalog photos assigned to this pitch. Switch filter to 'All catalog photos' to browse the full catalog."
        : "No Parts Catalog photos match your search.";
      partPhotoGrid.appendChild(emptyEl);
      return;
    }
    filtered.forEach(item => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "part-photo-card";
      card.title = `Insert ${item.part_number || "Part"} (${item.view_label || "Photo"})`;

      const thumb = document.createElement("img");
      thumb.className = "part-photo-thumb";
      thumb.src = item.data_url;
      thumb.alt = item.part_number || "Part photo";
      card.appendChild(thumb);

      const meta = document.createElement("div");
      meta.className = "part-photo-meta";
      if (item.on_pitch) {
        const badge = document.createElement("span");
        badge.className = "part-photo-badge";
        badge.textContent = "📌 On this pitch";
        meta.appendChild(badge);
      }
      const pnum = document.createElement("div");
      pnum.className = "part-photo-pnum";
      pnum.textContent = item.part_number || "Part";
      meta.appendChild(pnum);

      if (item.description) {
        const desc = document.createElement("div");
        desc.className = "part-photo-desc";
        desc.textContent = item.description;
        meta.appendChild(desc);
      }
      if (item.view_label) {
        const vlbl = document.createElement("div");
        vlbl.className = "part-photo-view";
        vlbl.textContent = item.view_label;
        meta.appendChild(vlbl);
      }
      card.appendChild(meta);

      card.onclick = () => {
        const labelTxt = partPhotoShowLabel.checked ? (item.part_number || "") : "";
        closePartPhotoModal();
        insertImageOverlay(
          item.data_url,
          labelTxt,
          `part photo (${item.part_number || "Catalog"})`, { partId: item.part_id || "", partNumber: item.part_number || "", viewId: item.view_id || "" }
        );
      };
      partPhotoGrid.appendChild(card);
    });
  }

  function openPartPhotoModal() {
    const hasPitchPhotos = catalogPhotos.some(item => item && item.on_pitch && item.data_url);
    partPhotoScope.value = hasPitchPhotos ? "pitch" : "all";
    partPhotoSearch.value = "";
    renderPartPhotoGrid();
    partPhotoModal.style.display = "flex";
    setTimeout(() => partPhotoSearch.focus(), 50);
  }

  function closePartPhotoModal() {
    partPhotoModal.style.display = "none";
  }

  addPartPhotoBtn.onclick = openPartPhotoModal;
  partPhotoModalClose.onclick = closePartPhotoModal;
  partPhotoModalCancel.onclick = closePartPhotoModal;
  partPhotoSearch.oninput = renderPartPhotoGrid;
  partPhotoScope.onchange = renderPartPhotoGrid;
  partPhotoModal.onclick = (e) => {
    if (e.target === partPhotoModal) closePartPhotoModal();
  };

  // Clipboard & File Photo Paste Modal
  function handleImageBlob(blob, sourceTag) {
    if (!blob) return;
    const captionTxt = (pastePhotoCaption && pastePhotoCaption.value ? pastePhotoCaption.value : "").trim();
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        closePastePhotoModal();
        insertImageOverlay(reader.result, captionTxt, sourceTag || "clipboard photo");
      }
    };
    reader.onerror = () => {
      if (pastePhotoFeedback) {
        pastePhotoFeedback.textContent = "Could not read image data from clipboard.";
      }
    };
    reader.readAsDataURL(blob);
  }

  function openPastePhotoModal(feedbackMsg) {
    if (pastePhotoFeedback) {
      pastePhotoFeedback.textContent = feedbackMsg || "";
    }
    if (pastePhotoCaption) {
      pastePhotoCaption.value = "";
    }
    if (pastePhotoFileInput) {
      pastePhotoFileInput.value = "";
    }
    pastePhotoModal.style.display = "flex";
    setTimeout(() => {
      if (pastePhotoDropzone) pastePhotoDropzone.focus();
    }, 50);
  }

  function closePastePhotoModal() {
    pastePhotoModal.style.display = "none";
  }

  async function tryReadClipboardImage(openModalOnFail) {
    if (navigator.clipboard && typeof navigator.clipboard.read === "function") {
      try {
        const items = await navigator.clipboard.read();
        for (const item of items) {
          const imgType = (item.types || []).find(t => t.startsWith("image/"));
          if (imgType) {
            const blob = await item.getType(imgType);
            handleImageBlob(blob, "clipboard photo");
            return true;
          }
        }
        if (openModalOnFail) {
          openPastePhotoModal("No image found in clipboard. Copy an image (Win+Shift+S) and press Ctrl+V below, or choose a file.");
        } else if (pastePhotoFeedback) {
          pastePhotoFeedback.textContent = "No image found in clipboard. Copy an image first, then press Ctrl+V.";
        }
        return false;
      } catch (err) {
        if (openModalOnFail) {
          openPastePhotoModal();
        } else if (pastePhotoFeedback) {
          pastePhotoFeedback.textContent = "Browser blocked direct clipboard access — press Ctrl+V on your keyboard instead.";
        }
        return false;
      }
    }
    if (openModalOnFail) {
      openPastePhotoModal();
    }
    return false;
  }

  pastePhotoBtn.onclick = () => {
    openPastePhotoModal("");
  };
  tryClipboardReadBtn.onclick = () => {
    tryReadClipboardImage(false);
  };
  pastePhotoModalClose.onclick = closePastePhotoModal;
  pastePhotoModalCancel.onclick = closePastePhotoModal;
  pastePhotoModal.onclick = (e) => {
    if (e.target === pastePhotoModal) closePastePhotoModal();
  };
  pastePhotoFileInput.onchange = (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) {
      handleImageBlob(file, `photo (${file.name})`);
    }
  };

  const onWindowPaste = (e) => {
    if (!imgLoaded) return;
    const activeEl = document.activeElement;
    if (activeEl === textInput || activeEl === partPhotoSearch) return;
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.type && item.type.startsWith("image/")) {
        const blob = item.getAsFile();
        if (blob) {
          e.preventDefault();
          handleImageBlob(blob, "clipboard photo");
          return;
        }
      }
    }
    if (pastePhotoModal.style.display === "flex" && pastePhotoFeedback) {
      pastePhotoFeedback.textContent = "Clipboard does not contain an image. Copy a screenshot or image first, then press Ctrl+V.";
    }
  };
  window.addEventListener("paste", onWindowPaste);

  function syncDeleteModalDownstream() {
    if (radioDelSelected.checked && !radioDelSelected.disabled) {
      const sel = shapes.find(s => s.id === selectedShapeId);
      downstreamText.textContent =
        `Removes the selected ${formatShapeLabel(sel)} from this canvas while keeping all other annotations and crop/rotation/zoom intact. ` +
        `You can still Undo before saving, and the saved visual aid is only updated when you click "💾 Apply & Save Markup".`;
    } else {
      const countNote = `${shapes.length} annotation${shapes.length === 1 ? "" : "s"}`;
      const hasAnyTransform = transformOps.length > 0 || hasZoomTransform();
      const transformNote = hasAnyTransform ? " and resets crop/rotation/zoom back to the original base image" : "";
      downstreamText.textContent =
        `Deletes all ${countNote} on this canvas${transformNote}. ` +
        `You can still Undo before saving, and the saved visual aid is only updated when you click "💾 Apply & Save Markup".`;
    }
  }

  function openDeleteConfirmModal() {
    if (shapes.length === 0 && transformOps.length === 0 && !hasZoomTransform() && !cropRect) {
      statusEl.textContent = "Nothing to delete — canvas has no annotations or crop/rotation/zoom applied.";
      return;
    }
    const sel = selectedShapeId ? shapes.find(s => s.id === selectedShapeId) : null;
    if (sel) {
      radioDelSelected.disabled = false;
      optLabelSelected.classList.remove("disabled");
      optTitleSelected.textContent = `Delete selected shape (${formatShapeLabel(sel)})`;
      optDescSelected.textContent = "Removes only the currently highlighted shape from the canvas.";
      radioDelSelected.checked = true;
    } else {
      radioDelSelected.disabled = true;
      optLabelSelected.classList.add("disabled");
      optTitleSelected.textContent = "Delete selected shape (no shape selected)";
      optDescSelected.textContent = "Use 👆 Select and click a shape on the canvas first to delete a single shape.";
      radioDelAll.checked = true;
    }
    const hasTransform = transformOps.length > 0 || hasZoomTransform();
    optDescAll.textContent = hasTransform
      ? `Deletes all ${shapes.length} annotation${shapes.length === 1 ? "" : "s"} and resets crop/rotation/zoom back to the original image.`
      : `Deletes all ${shapes.length} annotation${shapes.length === 1 ? "" : "s"} from this canvas.`;
    syncDeleteModalDownstream();
    deleteModal.style.display = "flex";
  }

  function closeDeleteConfirmModal() {
    deleteModal.style.display = "none";
  }

  radioDelSelected.onchange = syncDeleteModalDownstream;
  radioDelAll.onchange = syncDeleteModalDownstream;
  deleteModalClose.onclick = closeDeleteConfirmModal;
  deleteModalCancel.onclick = closeDeleteConfirmModal;
  deleteModal.onclick = (e) => {
    if (e.target === deleteModal) closeDeleteConfirmModal();
  };

  deleteModalConfirm.onclick = () => {
    if (radioDelSelected.checked && !radioDelSelected.disabled && selectedShapeId) {
      pushUndo();
      shapes = shapes.filter(s => s.id !== selectedShapeId);
      selectedShapeId = null;
      closeDeleteConfirmModal();
      statusEl.textContent = "Deleted selected annotation shape.";
      render();
    } else {
      pushUndo();
      shapes = [];
      transformOps = [];
      zoomMultiplier = 1.0;
      savedPanX = 0.5;
      savedPanY = 0.5;
      zoomFitBtn.textContent = "100% Fit";
      selectedShapeId = null;
      cropRect = null;
      syncCropActionButtons();
      rebuildWorkingImage();
      resizeCanvas();
      syncViewportScrollToPan(0.5, 0.5);
      closeDeleteConfirmModal();
      statusEl.textContent = "Deleted entire canvas contents and restored original image.";
      render();
    }
  };

  parentElement.querySelector("#btn-del").onclick = () => {
    openDeleteConfirmModal();
  };

  // Keyboard shortcuts for Crop Apply/Cancel & Delete
  const onWindowKeydown = (e) => {
    if (textOverlay.style.display === "flex") return;
    if (partPhotoModal.style.display === "flex") {
      if (e.key === "Escape") {
        e.preventDefault();
        closePartPhotoModal();
      }
      return;
    }
    if (pastePhotoModal.style.display === "flex") {
      if (e.key === "Escape") {
        e.preventDefault();
        closePastePhotoModal();
      }
      return;
    }
    if (deleteModal.style.display === "flex") {
      if (e.key === "Escape") {
        e.preventDefault();
        closeDeleteConfirmModal();
      } else if (e.key === "Enter") {
        e.preventDefault();
        deleteModalConfirm.click();
      }
      return;
    }
    if (cropRect && e.key === "Enter") {
      e.preventDefault();
      applyPendingCrop();
    } else if (cropRect && e.key === "Escape") {
      e.preventDefault();
      cancelPendingCrop();
    } else if (
      (e.key === "Delete" || e.key === "Backspace") &&
      selectedShapeId &&
      document.activeElement !== nextBadgeInput &&
      document.activeElement !== partPhotoSearch
    ) {
      e.preventDefault();
      openDeleteConfirmModal();
    }
  };
  window.addEventListener("keydown", onWindowKeydown);

  // Save composite button
  parentElement.querySelector("#btn-save").onclick = () => {
    if (!imgLoaded) return;
    commitPendingTextOverlay(false);
    if (cropRect && Math.abs(cropRect.w) >= 12 && Math.abs(cropRect.h) >= 12) {
      applyPendingCrop();
    }
    statusEl.textContent = "Generating high-resolution composite...";
    const workW = getWorkingWidth();
    const workH = getWorkingHeight();
    const MAX_EXPORT_DIM = 1920;
    const exportScale = Math.min(1.0, MAX_EXPORT_DIM / Math.max(1, workW, workH));
    const exportW = Math.max(1, Math.round(workW * exportScale));
    const exportH = Math.max(1, Math.round(workH * exportScale));
    const baseCanvas = document.createElement("canvas");
    baseCanvas.width = exportW;
    baseCanvas.height = exportH;
    const baseCtx = baseCanvas.getContext("2d");
    baseCtx.imageSmoothingEnabled = true;
    baseCtx.imageSmoothingQuality = "high";
    baseCtx.drawImage(workingCanvas, 0, 0, exportW, exportH);

    const pan = getNormalizedViewportPan();
    savedPanX = pan.panX;
    savedPanY = pan.panY;

    const zRect = (hasZoomTransform() && zoomMultiplier > 1.0)
      ? computeZoomCropRect(exportW, exportH, zoomMultiplier, pan.panX, pan.panY, shapes, baseCtx, exportScale)
      : null;
    const exportBounds = zRect
      ? { left: zRect.sx, top: zRect.sy, right: zRect.sx + zRect.cropW, bottom: zRect.sy + zRect.cropH }
      : { left: 0, top: 0, right: exportW, bottom: exportH };

    // Draw all shapes at exportScale so proportions match the working canvas, clamped to visible bounds
    shapes.forEach(shape => drawShape(baseCtx, shape, exportScale, false, exportBounds));

    let offscreen = baseCanvas;
    if (hasZoomTransform()) {
      const zoomedCanvas = document.createElement("canvas");
      zoomedCanvas.width = exportW;
      zoomedCanvas.height = exportH;
      const zCtx = zoomedCanvas.getContext("2d");
      zCtx.imageSmoothingEnabled = true;
      zCtx.imageSmoothingQuality = "high";
      if (zoomMultiplier > 1.0 && zRect) {
        zCtx.drawImage(baseCanvas, zRect.sx, zRect.sy, zRect.cropW, zRect.cropH, 0, 0, exportW, exportH);
      } else {
        zCtx.fillStyle = "#ffffff";
        zCtx.fillRect(0, 0, exportW, exportH);
        const drawW = Math.max(1, Math.round(exportW * zoomMultiplier));
        const drawH = Math.max(1, Math.round(exportH * zoomMultiplier));
        const dx = Math.round((exportW - drawW) / 2);
        const dy = Math.round((exportH - drawH) / 2);
        zCtx.drawImage(baseCanvas, 0, 0, exportW, exportH, dx, dy, drawW, drawH);
      }
      offscreen = zoomedCanvas;
    }

    const srcUrl = String((data && data.image_data_url) || "");
    const preferJpeg = srcUrl.startsWith("data:image/jpeg") || srcUrl.startsWith("data:image/jpg");
    let dataUrl = "";
    if (preferJpeg) {
      dataUrl = offscreen.toDataURL("image/jpeg", 0.92);
    } else {
      dataUrl = offscreen.toDataURL("image/png");
      if (dataUrl.length > 4000000) {
        const jpgCanvas = document.createElement("canvas");
        jpgCanvas.width = exportW;
        jpgCanvas.height = exportH;
        const jCtx = jpgCanvas.getContext("2d");
        jCtx.fillStyle = "#ffffff";
        jCtx.fillRect(0, 0, exportW, exportH);
        jCtx.drawImage(offscreen, 0, 0);
        dataUrl = jpgCanvas.toDataURL("image/jpeg", 0.92);
      }
    }
    const hasTransformOrZoom = transformOps.length > 0 || hasZoomTransform();
    const transformEntry = {
      id: "__transform__",
      type: "__transform__",
      ops: transformOps,
    };
    if (hasZoomTransform()) {
      transformEntry.zoom = Math.round(zoomMultiplier * 100) / 100;
      transformEntry.panX = Math.round(pan.panX * 10000) / 10000;
      transformEntry.panY = Math.round(pan.panY * 10000) / 10000;
      transformEntry.zoomCropRev = 2;
    }
    const serializedList = hasTransformOrZoom
      ? [transformEntry, ...shapes]
      : shapes;
    setTriggerValue("save", {
      annotations_json: serializedList.length > 0 ? JSON.stringify(serializedList) : "",
      data_url: dataUrl,
      count: shapes.length,
    });
    const extraNotes = [];
    if (transformOps.length > 0) extraNotes.push("crop/rotation");
    if (hasZoomTransform()) extraNotes.push(`zoom (${Math.round(zoomMultiplier * 100)}%)`);
    const transformNote = extraNotes.length > 0 ? ` + ${extraNotes.join(" & ")}` : "";
    statusEl.textContent = `Applied ${shapes.length} annotation${shapes.length === 1 ? '' : 's'}${transformNote}! Saving...`;
  };

  function updateStatus() {
    const badges = [];
    if (transformOps.length > 0) badges.push("Cropped/Rotated");
    if (hasZoomTransform()) badges.push(`Zoom ${Math.round(zoomMultiplier * 100)}%`);
    const transformBadge = badges.length > 0 ? ` · ${badges.join(" · ")}` : "";
    countEl.textContent = `${shapes.length} annotation${shapes.length === 1 ? '' : 's'}${transformBadge}`;
  }

  // Load image
  if (data && data.image_data_url) {
    img.crossOrigin = "anonymous";
    img.onload = () => {
      imgLoaded = true;
      shapes = [];
      transformOps = [];
      zoomMultiplier = 1.0;
      savedPanX = 0.5;
      savedPanY = 0.5;
      if (data.annotations_json) {
        try {
          const parsed = JSON.parse(data.annotations_json) || [];
          if (Array.isArray(parsed)) {
            parsed.forEach(item => {
              if (item && item.type === "__transform__") {
                if (Array.isArray(item.ops)) {
                  transformOps = item.ops;
                }
                const zVal = Number(item.zoom);
                if (isFinite(zVal) && zVal >= 0.5 && zVal <= 3.0) {
                  zoomMultiplier = Math.round(zVal * 100) / 100;
                }
                const pxVal = Number(item.panX);
                const pyVal = Number(item.panY);
                if (isFinite(pxVal) && pxVal >= 0 && pxVal <= 1) savedPanX = pxVal;
                if (isFinite(pyVal) && pyVal >= 0 && pyVal <= 1) savedPanY = pyVal;
              } else if (item && item.type) {
                shapes.push(item);
              }
            });
          }
        } catch(e) {
          shapes = [];
          transformOps = [];
          zoomMultiplier = 1.0;
          savedPanX = 0.5;
          savedPanY = 0.5;
        }
      }
      zoomFitBtn.textContent = `${Math.round(zoomMultiplier * 100)}% Fit`;
      if (data.initial_badge_number) {
        nextBadgeInput.value = data.initial_badge_number;
      }
      if (Array.isArray(catalogPhotos) && catalogPhotos.length > 0) {
        shapes.forEach(s => {
          if (!s || s.type !== "image") return;
          let matched = null;
          if (s.partId && s.viewId) {
            matched = catalogPhotos.find(cp => cp && cp.part_id === s.partId && cp.view_id === s.viewId);
          }
          if (!matched && s.partId) {
            matched = catalogPhotos.find(cp => cp && cp.part_id === s.partId);
          }
          if (!matched) {
            const pKey = String(s.partNumber || s.label || "").trim().toLowerCase();
            if (pKey) {
              matched = catalogPhotos.find(cp => cp && String(cp.part_number || "").trim().toLowerCase() === pKey);
            }
          }
          if (matched && matched.data_url) {
            s.dataUrl = matched.data_url;
            if (!s.partId && matched.part_id) s.partId = matched.part_id;
            if (!s.partNumber && matched.part_number) s.partNumber = matched.part_number;
            if (!s.viewId && matched.view_id) s.viewId = matched.view_id;
          }
        });
      }
      warmShapeImages();
      rebuildWorkingImage();
      resizeCanvas();
      syncViewportScrollToPan(savedPanX, savedPanY);
      render();
    };
    img.src = data.image_data_url;
  }

  function resizeCanvas() {
    if (!imgLoaded) return;
    const vpW = viewport.clientWidth || 800;
    const vpH = viewport.clientHeight || 540;
    const natW = getWorkingWidth();
    const natH = getWorkingHeight();

    const rW = Math.max(0.02, (vpW - 16) / natW);
    const rH = Math.max(0.02, (vpH - 16) / natH);
    const fitScale = Math.min(rW, rH, 4.0);
    scale = fitScale * zoomMultiplier;
    canvasDispW = Math.max(1, Math.round(natW * scale));
    canvasDispH = Math.max(1, Math.round(natH * scale));

    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvasDispW * dpr;
    canvas.height = canvasDispH * dpr;
    canvas.style.width = `${canvasDispW}px`;
    canvas.style.height = `${canvasDispH}px`;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
  }

  const onWindowResize = () => {
    resizeCanvas();
    render();
  };
  window.addEventListener("resize", onWindowResize);

  // Coordinate transforms
  function getCanvasPos(e) {
    const rect = canvas.getBoundingClientRect();
    const clientX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
    const clientY = e.clientY || (e.touches && e.touches[0].clientY) || 0;
    const dispX = clientX - rect.left;
    const dispY = clientY - rect.top;
    return {
      natX: Math.round(dispX / scale),
      natY: Math.round(dispY / scale),
      dispX,
      dispY,
    };
  }

  function findResizeHandle(s, nx, ny) {
    if (!s || s.type !== "image") return null;
    const tol = Math.max(12, Math.round(14 / Math.max(0.25, scale)));
    const xMin = Math.min(s.x, s.x + s.w);
    const xMax = Math.max(s.x, s.x + s.w);
    const yMin = Math.min(s.y, s.y + s.h);
    const yMax = Math.max(s.y, s.y + s.h);
    const corners = [
      { id: "nw", x: xMin, y: yMin },
      { id: "ne", x: xMax, y: yMin },
      { id: "sw", x: xMin, y: yMax },
      { id: "se", x: xMax, y: yMax },
    ];
    for (const c of corners) {
      if (Math.hypot(nx - c.x, ny - c.y) <= tol) {
        return c.id;
      }
    }
    return null;
  }

  // Pointer interactions
  canvas.onpointerdown = (e) => {
    if (!imgLoaded) return;
    canvas.setPointerCapture(e.pointerId);
    const pos = getCanvasPos(e);

    if (currentTool === "crop") {
      const clampedX = Math.max(0, Math.min(getWorkingWidth(), pos.natX));
      const clampedY = Math.max(0, Math.min(getWorkingHeight(), pos.natY));
      isCropping = true;
      cropRect = { x: clampedX, y: clampedY, w: 0, h: 0 };
      syncCropActionButtons();
      render();
      return;
    }

    if (currentTool === "select") {
      if (selectedShapeId) {
        const currentSel = shapes.find(s => s.id === selectedShapeId);
        const hId = findResizeHandle(currentSel, pos.natX, pos.natY);
        if (hId) {
          pushUndo();
          isResizing = true;
          resizeHandle = hId;
          dragStartX = pos.natX;
          dragStartY = pos.natY;
          canvas.style.cursor = (hId === "nw" || hId === "se") ? "nwse-resize" : "nesw-resize";
          render();
          return;
        }
      }
      const hit = findHitShape(pos.natX, pos.natY);
      if (hit) {
        pushUndo();
        selectedShapeId = hit.id;
        if (hit.type === "text") {
          currentFontSize = Number(hit.fontSize) || 18;
          syncFontSizeSelectValue(currentFontSize);
        }
        isDragging = true;
        dragStartX = pos.natX;
        dragStartY = pos.natY;
        canvas.style.cursor = "move";
      } else {
        selectedShapeId = null;
      }
      render();
      return;
    }

    if (currentTool === "text") {
      const existingTextHit = findHitShape(pos.natX, pos.natY);
      if (existingTextHit && existingTextHit.type === "text") {
        pushUndo();
        selectedShapeId = existingTextHit.id;
        currentFontSize = Number(existingTextHit.fontSize) || 18;
        syncFontSizeSelectValue(currentFontSize);
        isDragging = true;
        dragStartX = pos.natX;
        dragStartY = pos.natY;
        canvas.style.cursor = "move";
        render();
        return;
      }
      openTextOverlay(pos.dispX, pos.dispY, pos.natX, pos.natY);
      return;
    }

    if (currentTool === "badge") {
      pushUndo();
      const bNum = parseInt(nextBadgeInput.value, 10) || 1;
      shapes.push({
        id: `shape_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`,
        type: "badge",
        x: pos.natX,
        y: pos.natY,
        badgeNum: bNum,
        color: currentColor,
        strokeWidth: currentStrokeWidth,
      });
      nextBadgeInput.value = bNum + 1;
      render();
      return;
    }

    // Tools requiring drag
    isDrawing = true;
    const newId = `shape_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`;
    if (currentTool === "arrow") {
      activeShape = {
        id: newId,
        type: "arrow",
        x1: pos.natX, y1: pos.natY,
        x2: pos.natX, y2: pos.natY,
        color: currentColor,
        strokeWidth: currentStrokeWidth,
      };
    } else if (currentTool === "rect") {
      activeShape = {
        id: newId,
        type: "rect",
        x: pos.natX, y: pos.natY,
        w: 0, h: 0,
        color: currentColor,
        strokeWidth: currentStrokeWidth,
      };
    } else if (currentTool === "circle") {
      activeShape = {
        id: newId,
        type: "circle",
        x: pos.natX, y: pos.natY,
        w: 0, h: 0,
        color: currentColor,
        strokeWidth: currentStrokeWidth,
      };
    } else if (currentTool === "pen") {
      activeShape = {
        id: newId,
        type: "pen",
        points: [{ x: pos.natX, y: pos.natY }],
        color: currentColor,
        strokeWidth: currentStrokeWidth,
      };
    }
  };

  canvas.onpointermove = (e) => {
    if (!imgLoaded) return;
    const pos = getCanvasPos(e);

    if (isCropping && cropRect) {
      const clampedX = Math.max(0, Math.min(getWorkingWidth(), pos.natX));
      const clampedY = Math.max(0, Math.min(getWorkingHeight(), pos.natY));
      cropRect.w = clampedX - cropRect.x;
      cropRect.h = clampedY - cropRect.y;
      render();
      return;
    }

    if (isResizing && selectedShapeId) {
      const dx = pos.natX - dragStartX;
      const dy = pos.natY - dragStartY;
      const sel = shapes.find(s => s.id === selectedShapeId);
      if (sel && sel.type === "image") {
        const minSize = 28;
        if (resizeHandle === "se") {
          sel.w = Math.max(minSize, sel.w + dx);
          sel.h = Math.max(minSize, sel.h + dy);
        } else if (resizeHandle === "sw") {
          const newW = Math.max(minSize, sel.w - dx);
          sel.x += (sel.w - newW);
          sel.w = newW;
          sel.h = Math.max(minSize, sel.h + dy);
        } else if (resizeHandle === "ne") {
          sel.w = Math.max(minSize, sel.w + dx);
          const newH = Math.max(minSize, sel.h - dy);
          sel.y += (sel.h - newH);
          sel.h = newH;
        } else if (resizeHandle === "nw") {
          const newW = Math.max(minSize, sel.w - dx);
          const newH = Math.max(minSize, sel.h - dy);
          sel.x += (sel.w - newW);
          sel.y += (sel.h - newH);
          sel.w = newW;
          sel.h = newH;
        }
        dragStartX = pos.natX;
        dragStartY = pos.natY;
        render();
      }
      return;
    }

    if (isDragging && selectedShapeId) {
      const dx = pos.natX - dragStartX;
      const dy = pos.natY - dragStartY;
      const sel = shapes.find(s => s.id === selectedShapeId);
      if (sel) {
        moveShape(sel, dx, dy);
        dragStartX = pos.natX;
        dragStartY = pos.natY;
        render();
      }
      return;
    }

    if (currentTool === "select" && !isDragging && !isResizing) {
      if (selectedShapeId) {
        const currentSel = shapes.find(s => s.id === selectedShapeId);
        const hId = findResizeHandle(currentSel, pos.natX, pos.natY);
        if (hId) {
          canvas.style.cursor = (hId === "nw" || hId === "se") ? "nwse-resize" : "nesw-resize";
          return;
        }
      }
      const hoverHit = findHitShape(pos.natX, pos.natY);
      canvas.style.cursor = hoverHit ? "move" : "default";
      return;
    }

    if (currentTool === "text" && !isDragging && !isResizing) {
      const hoverText = findHitShape(pos.natX, pos.natY);
      canvas.style.cursor = (hoverText && hoverText.type === "text") ? "move" : "crosshair";
      return;
    }

    if (isDrawing && activeShape) {
      if (activeShape.type === "arrow") {
        activeShape.x2 = pos.natX;
        activeShape.y2 = pos.natY;
      } else if (activeShape.type === "rect" || activeShape.type === "circle") {
        activeShape.w = pos.natX - activeShape.x;
        activeShape.h = pos.natY - activeShape.y;
      } else if (activeShape.type === "pen") {
        activeShape.points.push({ x: pos.natX, y: pos.natY });
      }
      render();
    }
  };

  canvas.onpointerup = (e) => {
    if (isCropping) {
      isCropping = false;
      if (cropRect) {
        const wMax = getWorkingWidth();
        const hMax = getWorkingHeight();
        const nx = Math.max(0, Math.min(wMax - 1, Math.round(Math.min(cropRect.x, cropRect.x + cropRect.w))));
        const ny = Math.max(0, Math.min(hMax - 1, Math.round(Math.min(cropRect.y, cropRect.y + cropRect.h))));
        const nw = Math.min(wMax - nx, Math.round(Math.abs(cropRect.w)));
        const nh = Math.min(hMax - ny, Math.round(Math.abs(cropRect.h)));
        if (nw < 12 || nh < 12) {
          cropRect = null;
        } else {
          cropRect = { x: nx, y: ny, w: nw, h: nh };
          statusEl.textContent = `Crop area: ${nw}×${nh} px · Click '✓ Apply Crop' in toolbar (or press Enter)`;
        }
      }
      syncCropActionButtons();
      render();
      return;
    }
    if (isResizing) {
      isResizing = false;
      resizeHandle = null;
      canvas.style.cursor = currentTool === "select" ? "default" : "crosshair";
      render();
      return;
    }
    if (isDragging) {
      isDragging = false;
      canvas.style.cursor = currentTool === "select" ? "default" : "crosshair";
      return;
    }
    if (isDrawing && activeShape) {
      isDrawing = false;
      pushUndo();
      shapes.push(activeShape);
      selectedShapeId = activeShape.id;
      activeShape = null;
      render();
    }
  };

  function moveShape(s, dx, dy) {
    if (s.type === "arrow") {
      s.x1 += dx; s.y1 += dy;
      s.x2 += dx; s.y2 += dy;
    } else if (s.type === "rect" || s.type === "circle" || s.type === "badge" || s.type === "text" || s.type === "image") {
      s.x += dx; s.y += dy;
    } else if (s.type === "pen") {
      s.points.forEach(p => { p.x += dx; p.y += dy; });
    }
  }

  function findHitShape(nx, ny) {
    const normFactor = getVisualNormFactor();
    for (let i = shapes.length - 1; i >= 0; i--) {
      const s = shapes[i];
      const sw = (Number(s.strokeWidth) || 4) * normFactor;
      if (s.type === "arrow") {
        const d = distToSegment(nx, ny, s.x1, s.y1, s.x2, s.y2);
        if (d < Math.max(18 * normFactor, sw * 3)) return s;
      } else if (s.type === "rect" || s.type === "image") {
        const tol = 10 * normFactor;
        const xMin = Math.min(s.x, s.x + s.w);
        const xMax = Math.max(s.x, s.x + s.w);
        const yMin = Math.min(s.y, s.y + s.h);
        const yMax = Math.max(s.y, s.y + s.h);
        if (nx >= xMin - tol && nx <= xMax + tol && ny >= yMin - tol && ny >= yMin - tol && ny <= yMax + tol) return s;
      } else if (s.type === "circle") {
        const tol = 10 * normFactor;
        const cx = s.x + s.w / 2;
        const cy = s.y + s.h / 2;
        const rx = Math.abs(s.w / 2) + tol;
        const ry = Math.abs(s.h / 2) + tol;
        const norm = Math.pow((nx - cx)/rx, 2) + Math.pow((ny - cy)/ry, 2);
        if (norm <= 1.0) return s;
      } else if (s.type === "badge") {
        const d = Math.hypot(nx - s.x, ny - s.y);
        if (d <= Math.max(20 * normFactor, sw * 4.5)) return s;
      } else if (s.type === "text") {
        const tx = isFinite(s._drawX) ? s._drawX : s.x;
        const ty = isFinite(s._drawY) ? s._drawY : s.y;
        const tw = s.boxW || (120 * normFactor);
        const th = s.boxH || (30 * normFactor);
        const tol = Math.max(10 * normFactor, Math.round(10 / Math.max(0.05, scale)));
        if (nx >= tx - tol && nx <= tx + tw + tol && ny >= ty - tol && ny <= ty + th + tol) return s;
      } else if (s.type === "pen") {
        for (let j = 0; j < s.points.length - 1; j++) {
          const d = distToSegment(nx, ny, s.points[j].x, s.points[j].y, s.points[j+1].x, s.points[j+1].y);
          if (d < Math.max(16 * normFactor, sw * 3)) return s;
        }
      }
    }
    return null;
  }

  function distToSegment(px, py, x1, y1, x2, y2) {
    const l2 = Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2);
    if (l2 === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
  }

  // Text overlay
  let pendingTextNatPos = null;
  function commitPendingTextOverlay(keepTool) {
    if (textOverlay.style.display !== "flex") return false;
    const txt = (textInput.value || "").trim();
    let created = false;
    if (txt && pendingTextNatPos) {
      pushUndo();
      shapes.push({
        id: `shape_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`,
        type: "text",
        x: pendingTextNatPos.nx,
        y: pendingTextNatPos.ny,
        text: txt,
        color: currentColor,
        strokeWidth: currentStrokeWidth,
        fontSize: currentFontSize,
      });
      const createdCallout = shapes[shapes.length - 1];
      if (createdCallout) {
        selectedShapeId = createdCallout.id;
      }
      if (!keepTool) {
        activateSelectTool();
      }
      statusEl.textContent = "Callout added · Drag callout to move it";
      created = true;
    }
    textOverlay.style.display = "none";
    pendingTextNatPos = null;
    if (created) {
      render();
    }
    return created;
  }

  function openTextOverlay(dx, dy, nx, ny) {
    if (textOverlay.style.display === "flex" && (textInput.value || "").trim()) {
      commitPendingTextOverlay(true);
    }
    pendingTextNatPos = { nx, ny };
    textOverlay.style.left = `${Math.min(viewport.clientWidth - 260, Math.max(10, dx))}px`;
    textOverlay.style.top = `${Math.min(viewport.clientHeight - 60, Math.max(10, dy))}px`;
    textOverlay.style.display = "flex";
    textInput.value = "";
    setTimeout(() => textInput.focus(), 50);
  }

  textOkBtn.onclick = () => {
    commitPendingTextOverlay(false);
  };

  textCancelBtn.onclick = () => {
    textOverlay.style.display = "none";
    pendingTextNatPos = null;
  };

  textInput.onkeydown = (e) => {
    if (e.key === "Enter") textOkBtn.click();
    if (e.key === "Escape") textCancelBtn.click();
  };

  function drawCropOverlay(targetCtx, rect, sc) {
    const rx = Math.min(rect.x, rect.x + rect.w) * sc;
    const ry = Math.min(rect.y, rect.y + rect.h) * sc;
    const rw = Math.abs(rect.w) * sc;
    const rh = Math.abs(rect.h) * sc;
    if (rw < 2 || rh < 2) return;

    targetCtx.save();
    // Dim outside area
    targetCtx.fillStyle = "rgba(15, 23, 42, 0.58)";
    targetCtx.fillRect(0, 0, canvasDispW, ry);
    targetCtx.fillRect(0, ry + rh, canvasDispW, Math.max(0, canvasDispH - (ry + rh)));
    targetCtx.fillRect(0, ry, rx, rh);
    targetCtx.fillRect(rx + rw, ry, Math.max(0, canvasDispW - (rx + rw)), rh);

    // Outer solid border + inner dashed white border
    targetCtx.strokeStyle = "#38bdf8";
    targetCtx.lineWidth = 2;
    targetCtx.strokeRect(rx, ry, rw, rh);

    targetCtx.strokeStyle = "#ffffff";
    targetCtx.lineWidth = 1.5;
    targetCtx.setLineDash([5, 5]);
    targetCtx.strokeRect(rx, ry, rw, rh);
    targetCtx.setLineDash([]);

    // Corner handles
    const hSize = 7;
    targetCtx.fillStyle = "#38bdf8";
    [
      [rx, ry],
      [rx + rw, ry],
      [rx, ry + rh],
      [rx + rw, ry + rh],
    ].forEach(([ hx, hy ]) => {
      targetCtx.fillRect(hx - hSize / 2, hy - hSize / 2, hSize, hSize);
    });

    // Dimensions pill
    const natW = Math.round(Math.abs(rect.w));
    const natH = Math.round(Math.abs(rect.h));
    const label = `${natW} × ${natH} px`;
    targetCtx.font = "700 11px sans-serif";
    const tw = targetCtx.measureText(label).width + 12;
    const th = 20;
    const pillX = Math.max(4, Math.min(canvasDispW - tw - 4, rx));
    const pillY = ry > 24 ? ry - 24 : Math.min(canvasDispH - th - 4, ry + rh + 4);
    targetCtx.fillStyle = "#0f172a";
    targetCtx.fillRect(pillX, pillY, tw, th);
    targetCtx.strokeStyle = "#38bdf8";
    targetCtx.lineWidth = 1;
    targetCtx.strokeRect(pillX, pillY, tw, th);
    targetCtx.fillStyle = "#ffffff";
    targetCtx.textAlign = "left";
    targetCtx.textBaseline = "middle";
    targetCtx.fillText(label, pillX + 6, pillY + th / 2);
    targetCtx.restore();
  }

  // Main render loop
  function render() {
    if (!imgLoaded) return;
    ctx.clearRect(0, 0, canvasDispW, canvasDispH);
    ctx.drawImage(workingCanvas, 0, 0, canvasDispW, canvasDispH);

    // Render saved shapes
    shapes.forEach(shape => {
      const isSelected = shape.id === selectedShapeId;
      drawShape(ctx, shape, scale, isSelected);
    });

    // Render active drawing shape
    if (activeShape) {
      drawShape(ctx, activeShape, scale, false);
    }

    // Render active crop selection
    if (cropRect) {
      drawCropOverlay(ctx, cropRect, scale);
    }
    updateStatus();
  }

  function getShapeBounds(targetCtx, s, sc) {
    if (!s || !s.type) return null;
    const normFactor = getVisualNormFactor();
    const visScale = sc * normFactor;
    const sw = Number(s.strokeWidth) || 4;
    if (s.type === "arrow") {
      const pad = Math.max(14 * visScale, sw * 4 * visScale);
      return {
        minX: Math.min(s.x1, s.x2) * sc - pad,
        minY: Math.min(s.y1, s.y2) * sc - pad,
        maxX: Math.max(s.x1, s.x2) * sc + pad,
        maxY: Math.max(s.y1, s.y2) * sc + pad,
      };
    }
    if (s.type === "rect" || s.type === "circle" || s.type === "image") {
      const rx = Math.min(s.x, s.x + s.w) * sc;
      const ry = Math.min(s.y, s.y + s.h) * sc;
      const rw = Math.abs(s.w) * sc;
      const rh = Math.abs(s.h) * sc;
      const pad = 4 * visScale;
      return {
        minX: rx - pad,
        minY: ry - pad,
        maxX: rx + rw + pad,
        maxY: ry + rh + pad,
      };
    }
    if (s.type === "badge") {
      const r = Math.max(13 * visScale, sw * 3.6 * visScale) + 3 * visScale;
      return {
        minX: s.x * sc - r,
        minY: s.y * sc - r,
        maxX: s.x * sc + r,
        maxY: s.y * sc + r,
      };
    }
    if (s.type === "text") {
      const tx = s.x * sc;
      const ty = s.y * sc;
      const baseFontPx = Number(s.fontSize) || 18;
      const fontSize = Math.max(10 * visScale, baseFontPx * visScale);
      targetCtx.save();
      targetCtx.font = `700 ${Math.round(fontSize * 10) / 10}px sans-serif`;
      const txt = s.text || "";
      const metrics = targetCtx.measureText(txt);
      targetCtx.restore();
      const padX = Math.max(6, Math.round(baseFontPx * 0.45)) * visScale;
      const padY = Math.max(4, Math.round(baseFontPx * 0.28)) * visScale;
      const boxW = metrics.width + padX * 2;
      const boxH = fontSize + padY * 2;
      const pad = Math.max(8, 10 * visScale);
      return {
        minX: tx - pad,
        minY: ty - pad,
        maxX: tx + boxW + pad,
        maxY: ty + boxH + pad,
      };
    }
    if (s.type === "pen" && Array.isArray(s.points) && s.points.length > 0) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      s.points.forEach(p => {
        const px = p.x * sc, py = p.y * sc;
        if (px < minX) minX = px;
        if (py < minY) minY = py;
        if (px > maxX) maxX = px;
        if (py > maxY) maxY = py;
      });
      const pad = Math.max(4, sw * visScale);
      return { minX: minX - pad, minY: minY - pad, maxX: maxX + pad, maxY: maxY + pad };
    }
    return null;
  }

  function computeZoomCropRect(exportW, exportH, zoomVal, panX, panY, shapesList, targetCtx, sc) {
    const cropW = Math.max(1, exportW / zoomVal);
    const cropH = Math.max(1, exportH / zoomVal);
    const centerX = panX * exportW;
    const centerY = panY * exportH;
    let sx = Math.max(0, Math.min(exportW - cropW, centerX - cropW / 2));
    let sy = Math.max(0, Math.min(exportH - cropH, centerY - cropH / 2));

    if (Array.isArray(shapesList) && shapesList.length > 0) {
      let uMinX = Infinity, uMinY = Infinity, uMaxX = -Infinity, uMaxY = -Infinity;
      let tMinX = Infinity, tMinY = Infinity, tMaxX = -Infinity, tMaxY = -Infinity;
      shapesList.forEach(s => {
        const b = getShapeBounds(targetCtx, s, sc);
        if (!b) return;
        const bx1 = Math.max(0, Math.min(exportW, b.minX));
        const by1 = Math.max(0, Math.min(exportH, b.minY));
        const bx2 = Math.max(0, Math.min(exportW, b.maxX));
        const by2 = Math.max(0, Math.min(exportH, b.maxY));
        if (bx1 < uMinX) uMinX = bx1;
        if (by1 < uMinY) uMinY = by1;
        if (bx2 > uMaxX) uMaxX = bx2;
        if (by2 > uMaxY) uMaxY = by2;
        if (s.type === "text" || s.type === "badge") {
          if (bx1 < tMinX) tMinX = bx1;
          if (by1 < tMinY) tMinY = by1;
          if (bx2 > tMaxX) tMaxX = bx2;
          if (by2 > tMaxY) tMaxY = by2;
        }
      });
      if (isFinite(uMinX) && isFinite(uMaxX) && uMaxX > uMinX) {
        if ((uMaxX - uMinX) <= cropW) {
          if (sx > uMinX) sx = Math.max(0, uMinX);
          if (sx + cropW < uMaxX) sx = Math.min(exportW - cropW, uMaxX - cropW);
        } else if (isFinite(tMinX) && isFinite(tMaxX) && (tMaxX - tMinX) <= cropW) {
          if (sx > tMinX) sx = Math.max(0, tMinX);
          if (sx + cropW < tMaxX) sx = Math.min(exportW - cropW, tMaxX - cropW);
        } else {
          sx = Math.max(0, Math.min(exportW - cropW, (uMinX + uMaxX) / 2 - cropW / 2));
        }
      }
      if (isFinite(uMinY) && isFinite(uMaxY) && uMaxY > uMinY) {
        if ((uMaxY - uMinY) <= cropH) {
          if (sy > uMinY) sy = Math.max(0, uMinY);
          if (sy + cropH < uMaxY) sy = Math.min(exportH - cropH, uMaxY - cropH);
        } else if (isFinite(tMinY) && isFinite(tMaxY) && (tMaxY - tMinY) <= cropH) {
          if (sy > tMinY) sy = Math.max(0, tMinY);
          if (sy + cropH < tMaxY) sy = Math.min(exportH - cropH, tMaxY - cropH);
        } else {
          sy = Math.max(0, Math.min(exportH - cropH, (uMinY + uMaxY) / 2 - cropH / 2));
        }
      }
    }
    return { sx, sy, cropW, cropH };
  }

  function drawShape(targetCtx, s, sc, isSelected, boundsRect) {
    targetCtx.save();
    const normFactor = getVisualNormFactor();
    const visScale = sc * normFactor;
    const sw = Number(s.strokeWidth) || 4;
    const bLeft = boundsRect && isFinite(boundsRect.left) ? boundsRect.left : 0;
    const bTop = boundsRect && isFinite(boundsRect.top) ? boundsRect.top : 0;
    const bRight = boundsRect && isFinite(boundsRect.right) ? boundsRect.right : (getWorkingWidth() * sc);
    const bBottom = boundsRect && isFinite(boundsRect.bottom) ? boundsRect.bottom : (getWorkingHeight() * sc);
    targetCtx.strokeStyle = s.color;
    targetCtx.fillStyle = s.color;
    targetCtx.lineWidth = Math.max(1.5, sw * visScale);
    targetCtx.lineCap = "round";
    targetCtx.lineJoin = "round";

    if (s.type === "arrow") {
      const x1 = s.x1 * sc, y1 = s.y1 * sc;
      const x2 = s.x2 * sc, y2 = s.y2 * sc;
      targetCtx.beginPath();
      targetCtx.moveTo(x1, y1);
      targetCtx.lineTo(x2, y2);
      targetCtx.stroke();

      // Arrowhead
      const angle = Math.atan2(y2 - y1, x2 - x1);
      const headLen = Math.max(14 * visScale, targetCtx.lineWidth * 3.8);
      targetCtx.beginPath();
      targetCtx.moveTo(x2, y2);
      targetCtx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6));
      targetCtx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6));
      targetCtx.closePath();
      targetCtx.fill();

    } else if (s.type === "rect") {
      const rx = s.x * sc, ry = s.y * sc;
      const rw = s.w * sc, rh = s.h * sc;
      targetCtx.strokeRect(rx, ry, rw, rh);
      targetCtx.fillStyle = s.color + "22"; // 13% opacity tint
      targetCtx.fillRect(rx, ry, rw, rh);

    } else if (s.type === "circle") {
      const cx = (s.x + s.w / 2) * sc;
      const cy = (s.y + s.h / 2) * sc;
      const rx = Math.abs((s.w / 2) * sc);
      const ry = Math.abs((s.h / 2) * sc);
      targetCtx.beginPath();
      targetCtx.ellipse(cx, cy, Math.max(1, rx), Math.max(1, ry), 0, 0, Math.PI * 2);
      targetCtx.stroke();
      targetCtx.fillStyle = s.color + "22";
      targetCtx.fill();

    } else if (s.type === "badge") {
      const bx = s.x * sc, by = s.y * sc;
      const r = Math.max(13 * visScale, sw * 3.6 * visScale);
      // Outer high-contrast dark disc with border
      targetCtx.beginPath();
      targetCtx.arc(bx, by, r, 0, Math.PI * 2);
      targetCtx.fillStyle = "#0f172a";
      targetCtx.fill();
      targetCtx.strokeStyle = s.color;
      targetCtx.lineWidth = Math.max(2, 2.5 * visScale);
      targetCtx.stroke();

      // Number text inside
      targetCtx.fillStyle = "#ffffff";
      targetCtx.font = `800 ${Math.round(r * 1.15)}px sans-serif`;
      targetCtx.textAlign = "center";
      targetCtx.textBaseline = "middle";
      targetCtx.fillText(String(s.badgeNum || 1), bx, by + 1);

    } else if (s.type === "text") {
      const baseFontPx = Number(s.fontSize) || 18;
      let fontSize = Math.max(10 * visScale, baseFontPx * visScale);
      const txt = s.text || "";
      let padX = Math.max(6, Math.round(baseFontPx * 0.45)) * visScale;
      let padY = Math.max(4, Math.round(baseFontPx * 0.28)) * visScale;
      const edgeMargin = Math.max(3, Math.round(4 * visScale));
      const availW = Math.max(36, (bRight - bLeft) - edgeMargin * 2);

      targetCtx.font = `700 ${Math.round(fontSize * 10) / 10}px sans-serif`;
      let metrics = targetCtx.measureText(txt);
      let boxW = metrics.width + padX * 2;
      if (boxW > availW && boxW > 1) {
        const shrinkRatio = Math.max(0.45, availW / boxW);
        fontSize = Math.max(8 * visScale, fontSize * shrinkRatio);
        padX = Math.max(4 * visScale, padX * shrinkRatio);
        padY = Math.max(3 * visScale, padY * shrinkRatio);
        targetCtx.font = `700 ${Math.round(fontSize * 10) / 10}px sans-serif`;
        metrics = targetCtx.measureText(txt);
        boxW = metrics.width + padX * 2;
      }
      const boxH = fontSize + padY * 2;
      const tx = Math.max(bLeft + edgeMargin, Math.min(Math.max(bLeft + edgeMargin, bRight - boxW - edgeMargin), s.x * sc));
      const ty = Math.max(bTop + edgeMargin, Math.min(Math.max(bTop + edgeMargin, bBottom - boxH - edgeMargin), s.y * sc));
      s.boxW = boxW / sc;
      s.boxH = boxH / sc;
      s._drawX = tx / sc;
      s._drawY = ty / sc;

      // Callout box with subtle shadow
      targetCtx.shadowColor = "rgba(0,0,0,0.5)";
      targetCtx.shadowBlur = 6 * visScale;
      targetCtx.fillStyle = "#0f172a";
      targetCtx.fillRect(tx, ty, boxW, boxH);
      targetCtx.shadowBlur = 0;

      targetCtx.strokeStyle = s.color;
      targetCtx.lineWidth = Math.max(1.5, 2 * visScale);
      targetCtx.strokeRect(tx, ty, boxW, boxH);

      // Callout text
      targetCtx.fillStyle = "#ffffff";
      targetCtx.textAlign = "left";
      targetCtx.textBaseline = "top";
      targetCtx.fillText(txt, tx + padX, ty + padY);

    } else if (s.type === "pen") {
      if (s.points && s.points.length > 1) {
        targetCtx.beginPath();
        targetCtx.moveTo(s.points[0].x * sc, s.points[0].y * sc);
        for (let i = 1; i < s.points.length; i++) {
          targetCtx.lineTo(s.points[i].x * sc, s.points[i].y * sc);
        }
        targetCtx.stroke();
      }
    } else if (s.type === "image") {
      const rx = Math.min(s.x, s.x + s.w) * sc;
      const ry = Math.min(s.y, s.y + s.h) * sc;
      const rw = Math.max(1, Math.abs(s.w) * sc);
      const rh = Math.max(1, Math.abs(s.h) * sc);
      const cachedImg = getCachedShapeImage(s.dataUrl || s.data_url || s);

      targetCtx.save();
      targetCtx.shadowColor = "rgba(0, 0, 0, 0.55)";
      targetCtx.shadowBlur = 8 * visScale;
      targetCtx.fillStyle = "#ffffff";
      targetCtx.fillRect(rx, ry, rw, rh);
      targetCtx.shadowBlur = 0;

      if (cachedImg && cachedImg.complete && cachedImg.naturalWidth > 0) {
        const labelTxtForPhoto = String(s.label || "").trim();
        const lblFontForPhoto = Math.max(11 * visScale, Math.min(18 * visScale, Math.round(rh * 0.14)));
        const bannerHForPhoto = labelTxtForPhoto ? Math.min(rh * 0.36, lblFontForPhoto + 8 * visScale) : 0;
        const photoH = Math.max(1, rh - bannerHForPhoto);
        const iw = cachedImg.naturalWidth;
        const ih = cachedImg.naturalHeight;
        const scaleFit = Math.min(rw / Math.max(1, iw), photoH / Math.max(1, ih));
        const dw = Math.max(1, iw * scaleFit);
        const dh = Math.max(1, ih * scaleFit);
        const dx = rx + (rw - dw) / 2;
        const dy = ry + (photoH - dh) / 2;
        targetCtx.drawImage(cachedImg, dx, dy, dw, dh);
      } else {
        targetCtx.fillStyle = "#f8fafc";
        targetCtx.fillRect(rx, ry, rw, rh);
      }

      if (s.label) {
        const lblFontSize = Math.max(11 * visScale, Math.min(18 * visScale, Math.round(rh * 0.14)));
        const bannerH = Math.min(rh * 0.36, lblFontSize + 8 * visScale);
        const by = ry + rh - bannerH;
        targetCtx.fillStyle = "#0f172a";
        targetCtx.fillRect(rx, by, rw, bannerH);
        targetCtx.fillStyle = "#ffffff";
        targetCtx.font = `700 ${Math.round(lblFontSize)}px sans-serif`;
        targetCtx.textAlign = "center";
        targetCtx.textBaseline = "middle";
        targetCtx.fillText(String(s.label), rx + rw / 2, by + bannerH / 2, Math.max(8, rw - 8 * visScale));
      }

      targetCtx.strokeStyle = s.color || "#38bdf8";
      targetCtx.lineWidth = Math.max(2, (s.strokeWidth || 3) * 0.75 * visScale);
      targetCtx.strokeRect(rx, ry, rw, rh);
      targetCtx.restore();
    }

    // Selection highlight
    if (isSelected) {
      targetCtx.strokeStyle = "#38bdf8";
      targetCtx.lineWidth = 1.5;
      targetCtx.setLineDash([4, 4]);
      if (s.type === "badge") {
        const r = Math.max(13 * visScale, sw * 3.6 * visScale) + 5;
        targetCtx.beginPath();
        targetCtx.arc(s.x * sc, s.y * sc, r, 0, Math.PI * 2);
        targetCtx.stroke();
      } else if (s.type === "arrow") {
        targetCtx.strokeRect(
          Math.min(s.x1, s.x2) * sc - 6,
          Math.min(s.y1, s.y2) * sc - 6,
          Math.abs(s.x2 - s.x1) * sc + 12,
          Math.abs(s.y2 - s.y1) * sc + 12
        );
      } else if (s.type === "rect" || s.type === "circle") {
        targetCtx.strokeRect(
          Math.min(s.x, s.x + s.w) * sc - 6,
          Math.min(s.y, s.y + s.h) * sc - 6,
          Math.abs(s.w) * sc + 12,
          Math.abs(s.h) * sc + 12
        );
      } else if (s.type === "image") {
        const rx = Math.min(s.x, s.x + s.w) * sc;
        const ry = Math.min(s.y, s.y + s.h) * sc;
        const rw = Math.abs(s.w) * sc;
        const rh = Math.abs(s.h) * sc;
        targetCtx.strokeRect(rx - 4, ry - 4, rw + 8, rh + 8);
        targetCtx.setLineDash([]);
        const hSize = 8;
        [
          [rx, ry],
          [rx + rw, ry],
          [rx, ry + rh],
          [rx + rw, ry + rh],
        ].forEach(([hx, hy]) => {
          targetCtx.fillStyle = "#38bdf8";
          targetCtx.fillRect(hx - hSize / 2, hy - hSize / 2, hSize, hSize);
          targetCtx.strokeStyle = "#ffffff";
          targetCtx.lineWidth = 1.5;
          targetCtx.strokeRect(hx - hSize / 2, hy - hSize / 2, hSize, hSize);
        });
      } else if (s.type === "text") {
        const tx = isFinite(s._drawX) ? s._drawX : s.x;
        const ty = isFinite(s._drawY) ? s._drawY : s.y;
        targetCtx.strokeRect(tx * sc - 4, ty * sc - 4, (s.boxW || 100) * sc + 8, (s.boxH || 30) * sc + 8);
      }
    }
    targetCtx.restore();
  }

  const cleanup = () => {
    window.removeEventListener("paste", onWindowPaste);
    window.removeEventListener("keydown", onWindowKeydown);
    window.removeEventListener("resize", onWindowResize);
  };
  parentElement.__paagAnnotatorCleanup = cleanup;
  return cleanup;
}
"""

_IMAGE_ANNOTATOR = st.components.v2.component(
    "paag_image_annotator_v15",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def image_annotator(
    image_data_url: str,
    annotations_json: str = "",
    *,
    key: str,
    initial_badge_number: int = 1,
    catalog_photos: list[dict[str, Any]] | None = None,
) -> Any:
    """Render the in-app interactive image annotation and markup tool."""
    safe_key = str(key or "annotator").replace("__", "_")
    pending_save_key = f"_annotator_pending_save_{safe_key}"

    def _on_save() -> None:
        state_obj = st.session_state.get(safe_key)
        save_payload = getattr(state_obj, "save", None)
        if save_payload is None and isinstance(state_obj, dict):
            save_payload = state_obj.get("save")
        if isinstance(save_payload, dict) and save_payload.get("data_url"):
            st.session_state[pending_save_key] = dict(save_payload)

    try:
        res = _IMAGE_ANNOTATOR(
            key=safe_key,
            data={
                "image_data_url": image_data_url,
                "annotations_json": annotations_json,
                "initial_badge_number": initial_badge_number,
                "catalog_photos": catalog_photos or [],
            },
            on_save_change=_on_save,
            width="stretch",
            height="content",
        )
        save_val = getattr(res, "save", None)
        if isinstance(save_val, dict) and save_val.get("data_url"):
            st.session_state.pop(pending_save_key, None)
            return res
        pending = st.session_state.pop(pending_save_key, None)
        if isinstance(pending, dict) and pending.get("data_url"):
            return type("_AnnotatorSaveResult", (), {"save": pending})()
        return res
    except Exception:
        return None


def decode_data_url(data_url: str) -> bytes:
    """Decode a Base64 data URL string into raw image bytes."""
    if not data_url or not isinstance(data_url, str):
        raise ValueError("No data URL provided.")
    if ";base64," not in data_url:
        raise ValueError("Invalid data URL format.")
    _, encoded = data_url.split(";base64,", 1)
    return base64.b64decode(encoded)


def _parse_hex_color(
    color_str: str, default: tuple[int, int, int] = (239, 68, 68)
) -> tuple[int, int, int]:
    cleaned = str(color_str or "").strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) >= 6:
        try:
            return (
                int(cleaned[0:2], 16),
                int(cleaned[2:4], 16),
                int(cleaned[4:6], 16),
            )
        except ValueError:
            pass
    return default


def _load_annotator_font(size_px: int, bold: bool = True):
    from PIL import ImageFont

    px = max(8, int(round(size_px)))
    candidates = (
        ("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf", "arial.ttf", "segoeui.ttf")
        if bold
        else ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf")
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, px)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=px)
    except Exception:
        return ImageFont.load_default()


def _compute_working_canvas_image(base_img, transform_ops: list[dict]):
    from PIL import Image

    work = base_img.convert("RGBA")
    for op in transform_ops:
        if not isinstance(op, dict):
            continue
        kind = str(op.get("kind") or "")
        if kind == "rotate":
            angle = int(round(float(op.get("angle") or 0)))
            if angle == 90:
                work = work.transpose(Image.Transpose.ROTATE_270)
            elif angle == -90:
                work = work.transpose(Image.Transpose.ROTATE_90)
        elif kind == "crop":
            cx = max(0, min(work.width - 1, int(round(float(op.get("x") or 0)))))
            cy = max(0, min(work.height - 1, int(round(float(op.get("y") or 0)))))
            cw = max(1, min(work.width - cx, int(round(float(op.get("w") or work.width)))))
            ch = max(1, min(work.height - cy, int(round(float(op.get("h") or work.height)))))
            work = work.crop((cx, cy, cx + cw, cy + ch))
    return work


def _get_annotator_shape_bounds_pil(
    draw,
    shape: dict[str, Any],
    sc: float,
    vis_scale: float,
) -> tuple[float, float, float, float] | None:
    s_type = str(shape.get("type") or "").strip()
    if not s_type or s_type == "__transform__":
        return None
    sw = float(shape.get("strokeWidth") or 4.0)
    if s_type == "arrow":
        x1 = float(shape.get("x1") or 0.0) * sc
        y1 = float(shape.get("y1") or 0.0) * sc
        x2 = float(shape.get("x2") or 0.0) * sc
        y2 = float(shape.get("y2") or 0.0) * sc
        pad = max(14.0 * vis_scale, sw * 4.0 * vis_scale)
        return (min(x1, x2) - pad, min(y1, y2) - pad, max(x1, x2) + pad, max(y1, y2) + pad)
    if s_type in ("rect", "circle", "image"):
        x_val = float(shape.get("x") or 0.0)
        y_val = float(shape.get("y") or 0.0)
        w_val = float(shape.get("w") or 0.0)
        h_val = float(shape.get("h") or 0.0)
        rx = min(x_val, x_val + w_val) * sc
        ry = min(y_val, y_val + h_val) * sc
        rw = abs(w_val) * sc
        rh = abs(h_val) * sc
        pad = 4.0 * vis_scale
        return (rx - pad, ry - pad, rx + rw + pad, ry + rh + pad)
    if s_type == "badge":
        bx = float(shape.get("x") or 0.0) * sc
        by = float(shape.get("y") or 0.0) * sc
        r = max(13.0 * vis_scale, sw * 3.6 * vis_scale) + 3.0 * vis_scale
        return (bx - r, by - r, bx + r, by + r)
    if s_type == "text":
        tx = float(shape.get("x") or 0.0) * sc
        ty = float(shape.get("y") or 0.0) * sc
        base_font_px = float(shape.get("fontSize") or 18.0)
        font_size = max(10.0 * vis_scale, base_font_px * vis_scale)
        font = _load_annotator_font(int(round(font_size)), bold=True)
        txt = str(shape.get("text") or "")
        pad_x = max(6.0, round(base_font_px * 0.45)) * vis_scale
        pad_y = max(4.0, round(base_font_px * 0.28)) * vis_scale
        try:
            bbox = draw.textbbox((0, 0), txt, font=font)
            text_w = float(bbox[2] - bbox[0])
        except Exception:
            text_w = float(len(txt)) * font_size * 0.58
        box_w = text_w + pad_x * 2.0
        box_h = font_size + pad_y * 2.0
        pad = max(8.0, 10.0 * vis_scale)
        return (tx - pad, ty - pad, tx + box_w + pad, ty + box_h + pad)
    if s_type == "pen":
        pts = shape.get("points") or []
        coords = [
            (float(p.get("x") or 0.0) * sc, float(p.get("y") or 0.0) * sc)
            for p in pts
            if isinstance(p, dict)
        ]
        if coords:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            pad = max(4.0, sw * vis_scale)
            return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    return None


def _compute_zoom_crop_rect_pil(
    export_w: int,
    export_h: int,
    zoom_multiplier: float,
    pan_x: float,
    pan_y: float,
    shapes: list[dict[str, Any]],
    sc: float,
    vis_scale: float,
) -> tuple[float, float, float, float]:
    from PIL import Image, ImageDraw

    crop_w = max(1.0, export_w / float(zoom_multiplier))
    crop_h = max(1.0, export_h / float(zoom_multiplier))
    px = max(0.0, min(1.0, float(pan_x if pan_x is not None else 0.5)))
    py = max(0.0, min(1.0, float(pan_y if pan_y is not None else 0.5)))
    sx = max(0.0, min(export_w - crop_w, px * export_w - crop_w / 2.0))
    sy = max(0.0, min(export_h - crop_h, py * export_h - crop_h / 2.0))

    if shapes:
        scratch = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(scratch, "RGBA")
        u_min_x, u_min_y, u_max_x, u_max_y = float("inf"), float("inf"), float("-inf"), float("-inf")
        t_min_x, t_min_y, t_max_x, t_max_y = float("inf"), float("inf"), float("-inf"), float("-inf")
        for s in shapes:
            if not isinstance(s, dict):
                continue
            b = _get_annotator_shape_bounds_pil(draw, s, sc, vis_scale)
            if not b:
                continue
            bx1 = max(0.0, min(float(export_w), b[0]))
            by1 = max(0.0, min(float(export_h), b[1]))
            bx2 = max(0.0, min(float(export_w), b[2]))
            by2 = max(0.0, min(float(export_h), b[3]))
            u_min_x = min(u_min_x, bx1)
            u_min_y = min(u_min_y, by1)
            u_max_x = max(u_max_x, bx2)
            u_max_y = max(u_max_y, by2)
            if s.get("type") in ("text", "badge"):
                t_min_x = min(t_min_x, bx1)
                t_min_y = min(t_min_y, by1)
                t_max_x = max(t_max_x, bx2)
                t_max_y = max(t_max_y, by2)

        if u_min_x < u_max_x:
            if (u_max_x - u_min_x) <= crop_w:
                if sx > u_min_x:
                    sx = max(0.0, u_min_x)
                if sx + crop_w < u_max_x:
                    sx = min(export_w - crop_w, u_max_x - crop_w)
            elif t_min_x < t_max_x and (t_max_x - t_min_x) <= crop_w:
                if sx > t_min_x:
                    sx = max(0.0, t_min_x)
                if sx + crop_w < t_max_x:
                    sx = min(export_w - crop_w, t_max_x - crop_w)
            else:
                sx = max(0.0, min(export_w - crop_w, (u_min_x + u_max_x) / 2.0 - crop_w / 2.0))

        if u_min_y < u_max_y:
            if (u_max_y - u_min_y) <= crop_h:
                if sy > u_min_y:
                    sy = max(0.0, u_min_y)
                if sy + crop_h < u_max_y:
                    sy = min(export_h - crop_h, u_max_y - crop_h)
            elif t_min_y < t_max_y and (t_max_y - t_min_y) <= crop_h:
                if sy > t_min_y:
                    sy = max(0.0, t_min_y)
                if sy + crop_h < t_max_y:
                    sy = min(export_h - crop_h, t_max_y - crop_h)
            else:
                sy = max(0.0, min(export_h - crop_h, (u_min_y + u_max_y) / 2.0 - crop_h / 2.0))

    return (sx, sy, sx + crop_w, sy + crop_h)


def _draw_annotator_shape_pil(
    canvas,
    shape: dict[str, Any],
    sc: float,
    vis_scale: float,
    bounds_rect: tuple[float, float, float, float] | None = None,
) -> None:
    import math
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageOps

    s_type = str(shape.get("type") or "").strip()
    if not s_type or s_type == "__transform__":
        return
    sw = float(shape.get("strokeWidth") or 4.0)
    rgb = _parse_hex_color(str(shape.get("color") or "#ef4444"))
    line_w = max(2, int(round(max(1.5, sw * vis_scale))))
    b_left, b_top, b_right, b_bottom = (
        bounds_rect
        if bounds_rect is not None
        else (0.0, 0.0, float(canvas.width), float(canvas.height))
    )
    draw = ImageDraw.Draw(canvas, "RGBA")

    if s_type == "arrow":
        x1 = float(shape.get("x1") or 0.0) * sc
        y1 = float(shape.get("y1") or 0.0) * sc
        x2 = float(shape.get("x2") or 0.0) * sc
        y2 = float(shape.get("y2") or 0.0) * sc
        draw.line([(x1, y1), (x2, y2)], fill=(*rgb, 255), width=line_w)
        angle = math.atan2(y2 - y1, x2 - x1)
        head_len = max(14.0 * vis_scale, line_w * 3.8)
        p1 = (x2, y2)
        p2 = (
            x2 - head_len * math.cos(angle - math.pi / 6.0),
            y2 - head_len * math.sin(angle - math.pi / 6.0),
        )
        p3 = (
            x2 - head_len * math.cos(angle + math.pi / 6.0),
            y2 - head_len * math.sin(angle + math.pi / 6.0),
        )
        draw.polygon([p1, p2, p3], fill=(*rgb, 255))

    elif s_type == "rect":
        rx = min(float(shape.get("x") or 0.0), float(shape.get("x") or 0.0) + float(shape.get("w") or 0.0)) * sc
        ry = min(float(shape.get("y") or 0.0), float(shape.get("y") or 0.0) + float(shape.get("h") or 0.0)) * sc
        rw = abs(float(shape.get("w") or 0.0)) * sc
        rh = abs(float(shape.get("h") or 0.0)) * sc
        draw.rectangle(
            [rx, ry, rx + rw, ry + rh],
            fill=(*rgb, 34),
            outline=(*rgb, 255),
            width=line_w,
        )

    elif s_type == "circle":
        rx = min(float(shape.get("x") or 0.0), float(shape.get("x") or 0.0) + float(shape.get("w") or 0.0)) * sc
        ry = min(float(shape.get("y") or 0.0), float(shape.get("y") or 0.0) + float(shape.get("h") or 0.0)) * sc
        rw = max(2.0, abs(float(shape.get("w") or 0.0)) * sc)
        rh = max(2.0, abs(float(shape.get("h") or 0.0)) * sc)
        draw.ellipse(
            [rx, ry, rx + rw, ry + rh],
            fill=(*rgb, 34),
            outline=(*rgb, 255),
            width=line_w,
        )

    elif s_type == "badge":
        bx = float(shape.get("x") or 0.0) * sc
        by = float(shape.get("y") or 0.0) * sc
        r = max(13.0 * vis_scale, sw * 3.6 * vis_scale)
        border_w = max(2, int(round(2.5 * vis_scale)))
        draw.ellipse(
            [bx - r, by - r, bx + r, by + r],
            fill=(15, 23, 42, 255),
            outline=(*rgb, 255),
            width=border_w,
        )
        font = _load_annotator_font(int(round(r * 1.15)), bold=True)
        draw.text(
            (bx, by + 1),
            str(shape.get("badgeNum") or 1),
            fill=(255, 255, 255, 255),
            font=font,
            anchor="mm",
        )

    elif s_type == "text":
        base_font_px = float(shape.get("fontSize") or 18.0)
        font_size = max(10.0 * vis_scale, base_font_px * vis_scale)
        txt = str(shape.get("text") or "")
        pad_x = max(6.0, round(base_font_px * 0.45)) * vis_scale
        pad_y = max(4.0, round(base_font_px * 0.28)) * vis_scale
        edge_margin = max(3.0, round(4.0 * vis_scale))
        avail_w = max(36.0, (b_right - b_left) - edge_margin * 2.0)

        font = _load_annotator_font(int(round(font_size)), bold=True)
        try:
            bbox = draw.textbbox((0, 0), txt, font=font)
            text_w = float(bbox[2] - bbox[0])
        except Exception:
            text_w = float(len(txt)) * font_size * 0.58
        box_w = text_w + pad_x * 2.0
        if box_w > avail_w and box_w > 1.0:
            shrink_ratio = max(0.45, avail_w / box_w)
            font_size = max(8.0 * vis_scale, font_size * shrink_ratio)
            pad_x = max(4.0 * vis_scale, pad_x * shrink_ratio)
            pad_y = max(3.0 * vis_scale, pad_y * shrink_ratio)
            font = _load_annotator_font(int(round(font_size)), bold=True)
            try:
                bbox = draw.textbbox((0, 0), txt, font=font)
                text_w = float(bbox[2] - bbox[0])
            except Exception:
                text_w = float(len(txt)) * font_size * 0.58
            box_w = text_w + pad_x * 2.0
        box_h = font_size + pad_y * 2.0
        tx = max(
            b_left + edge_margin,
            min(max(b_left + edge_margin, b_right - box_w - edge_margin), float(shape.get("x") or 0.0) * sc),
        )
        ty = max(
            b_top + edge_margin,
            min(max(b_top + edge_margin, b_bottom - box_h - edge_margin), float(shape.get("y") or 0.0) * sc),
        )
        border_w = max(2, int(round(2.0 * vis_scale)))
        draw.rectangle(
            [tx, ty, tx + box_w, ty + box_h],
            fill=(15, 23, 42, 255),
            outline=(*rgb, 255),
            width=border_w,
        )
        draw.text(
            (tx + pad_x, ty + pad_y),
            txt,
            fill=(255, 255, 255, 255),
            font=font,
        )

    elif s_type == "pen":
        pts = shape.get("points") or []
        if isinstance(pts, list) and len(pts) > 1:
            coords = [
                (float(p.get("x") or 0.0) * sc, float(p.get("y") or 0.0) * sc)
                for p in pts
                if isinstance(p, dict)
            ]
            if len(coords) > 1:
                draw.line(coords, fill=(*rgb, 255), width=line_w, joint="curve")

    elif s_type == "image":
        x_val = float(shape.get("x") or 0.0)
        y_val = float(shape.get("y") or 0.0)
        w_val = float(shape.get("w") or 1.0)
        h_val = float(shape.get("h") or 1.0)
        rx = int(round(min(x_val, x_val + w_val) * sc))
        ry = int(round(min(y_val, y_val + h_val) * sc))
        rw = max(1, int(round(abs(w_val) * sc)))
        rh = max(1, int(round(abs(h_val) * sc)))

        tile = Image.new("RGBA", (rw, rh), (255, 255, 255, 255))
        part_img_bytes: bytes | None = None
        local_img_path = str(shape.get("_resolved_image_path") or "").strip()
        if local_img_path:
            try:
                p_obj = Path(local_img_path)
                if p_obj.exists() and p_obj.is_file():
                    part_img_bytes = p_obj.read_bytes()
            except Exception:
                part_img_bytes = None
        if part_img_bytes is None:
            d_url = str(shape.get("dataUrl") or shape.get("data_url") or "").strip()
            if d_url.startswith("data:") and ";base64," in d_url:
                try:
                    part_img_bytes = decode_data_url(d_url)
                except Exception:
                    part_img_bytes = None
        if part_img_bytes:
            try:
                with Image.open(BytesIO(part_img_bytes)) as pim:
                    pim_rgba = ImageOps.exif_transpose(pim).convert("RGBA")
                    label_txt_pre = str(shape.get("label") or "").strip()
                    lbl_fs_pre = max(11.0 * vis_scale, min(18.0 * vis_scale, round(rh * 0.14)))
                    banner_h_pre = max(1, int(round(min(rh * 0.36, lbl_fs_pre + 8.0 * vis_scale)))) if label_txt_pre else 0
                    photo_h = max(1, rh - banner_h_pre)
                    iw, ih = max(1, pim_rgba.width), max(1, pim_rgba.height)
                    scale_fit = min(rw / float(iw), photo_h / float(ih))
                    dw = max(1, int(round(iw * scale_fit)))
                    dh = max(1, int(round(ih * scale_fit)))
                    dx = max(0, int(round((rw - dw) / 2.0)))
                    dy = max(0, int(round((photo_h - dh) / 2.0)))
                    pim_resized = pim_rgba.resize((dw, dh), Image.Resampling.LANCZOS)
                    tile.alpha_composite(pim_resized, (dx, dy))
                    pim_resized = None
                    if pim_resized is not None:
                        tile.alpha_composite(pim_resized, (0, 0))
            except Exception:
                pass

        label_txt = str(shape.get("label") or "").strip()
        if label_txt:
            lbl_font_size = max(11.0 * vis_scale, min(18.0 * vis_scale, round(rh * 0.14)))
            banner_h = max(1, int(round(min(rh * 0.36, lbl_font_size + 8.0 * vis_scale))))
            by_local = max(0, rh - banner_h)
            banner_overlay = Image.new("RGBA", (rw, rh - by_local), (15, 23, 42, 219))
            tile.alpha_composite(banner_overlay, (0, by_local))
            tile_draw = ImageDraw.Draw(tile, "RGBA")
            border_w_approx = max(2, int(round(float(shape.get("strokeWidth") or 3.0) * 0.75 * vis_scale)))
            max_txt_w = max(8.0, float(rw - border_w_approx * 2 - max(6.0, 8.0 * vis_scale)))
            cur_font_px = max(8, int(round(lbl_font_size)))
            lbl_font = _load_annotator_font(cur_font_px, bold=True)
            while cur_font_px > 7:
                bbox = tile_draw.textbbox((0, 0), label_txt, font=lbl_font)
                if float(bbox[2] - bbox[0]) <= max_txt_w:
                    break
                cur_font_px -= 1
                lbl_font = _load_annotator_font(cur_font_px, bold=True)
            tile_draw.text(
                (rw / 2.0, by_local + (rh - by_local) / 2.0),
                label_txt,
                fill=(255, 255, 255, 255),
                font=lbl_font,
                anchor="mm",
            )

        canvas.alpha_composite(tile, (max(0, rx), max(0, ry)))
        border_rgb = _parse_hex_color(str(shape.get("color") or "#38bdf8"), (56, 189, 248))
        border_w = max(2, int(round(float(shape.get("strokeWidth") or 3.0) * 0.75 * vis_scale)))
        draw.rectangle(
            [rx, ry, rx + rw, ry + rh],
            outline=(*border_rgb, 255),
            width=border_w,
        )


def _apply_zoom_to_composite_pil(
    comp_rgba,
    zoom_multiplier: float,
    pan_x: float = 0.5,
    pan_y: float = 0.5,
    crop_box: tuple[float, float, float, float] | None = None,
):
    from PIL import Image

    try:
        z_val = float(zoom_multiplier or 1.0)
    except Exception:
        z_val = 1.0
    if not (0.5 <= z_val <= 3.0) or abs(z_val - 1.0) <= 0.001:
        return comp_rgba

    export_w, export_h = max(1, comp_rgba.width), max(1, comp_rgba.height)
    px = max(0.0, min(1.0, float(pan_x if pan_x is not None else 0.5)))
    py = max(0.0, min(1.0, float(pan_y if pan_y is not None else 0.5)))

    if z_val > 1.0:
        if crop_box is not None:
            sx, sy, sx2, sy2 = crop_box
            left = max(0, int(round(sx)))
            top = max(0, int(round(sy)))
            right = min(export_w, max(left + 1, int(round(sx2))))
            bottom = min(export_h, max(top + 1, int(round(sy2))))
        else:
            crop_w = max(1.0, export_w / z_val)
            crop_h = max(1.0, export_h / z_val)
            center_x = px * export_w
            center_y = py * export_h
            sx = max(0.0, min(export_w - crop_w, center_x - crop_w / 2.0))
            sy = max(0.0, min(export_h - crop_h, center_y - crop_h / 2.0))
            left = max(0, int(round(sx)))
            top = max(0, int(round(sy)))
            right = min(export_w, max(left + 1, int(round(sx + crop_w))))
            bottom = min(export_h, max(top + 1, int(round(sy + crop_h))))
        cropped = comp_rgba.crop((left, top, right, bottom))
        return cropped.resize((export_w, export_h), Image.Resampling.LANCZOS)

    out = Image.new("RGBA", (export_w, export_h), (255, 255, 255, 255))
    draw_w = max(1, int(round(export_w * z_val)))
    draw_h = max(1, int(round(export_h * z_val)))
    dx = max(0, int(round((export_w - draw_w) / 2.0)))
    dy = max(0, int(round((export_h - draw_h) / 2.0)))
    scaled = comp_rgba.resize((draw_w, draw_h), Image.Resampling.LANCZOS)
    out.alpha_composite(scaled, (dx, dy))
    return out


def patch_visual_media_composite_image_shapes(
    original_file_path: str | Any,
    composite_file_path: str | Any,
    annotations_json: str,
    updated_shape_ids: set[str] | None = None,
    resolved_paths_by_shape_id: dict[str, str] | None = None,
) -> bool:
    """Update or re-render a visual aid composite file when catalog part photos change."""
    import json
    from pathlib import Path
    from PIL import Image, ImageOps

    comp_path = Path(str(composite_file_path or ""))
    orig_path = Path(str(original_file_path or "")) if original_file_path else comp_path
    if not orig_path.exists() or not orig_path.is_file():
        orig_path = comp_path
    if not orig_path.exists() or not orig_path.is_file():
        return False

    try:
        raw_list = json.loads(annotations_json or "[]")
        if not isinstance(raw_list, list):
            raw_list = []
    except Exception:
        raw_list = []

    transform_ops: list[dict] = []
    zoom_multiplier = 1.0
    pan_x = 0.5
    pan_y = 0.5
    shapes: list[dict] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "__transform__":
            if isinstance(item.get("ops"), list):
                transform_ops = item["ops"]
            try:
                z_raw = float(item.get("zoom") or 1.0)
                if 0.5 <= z_raw <= 3.0:
                    zoom_multiplier = z_raw
            except Exception:
                pass
            try:
                if item.get("panX") is not None:
                    pan_x = max(0.0, min(1.0, float(item.get("panX"))))
                if item.get("panY") is not None:
                    pan_y = max(0.0, min(1.0, float(item.get("panY"))))
            except Exception:
                pass
        elif item.get("type"):
            s_copy = dict(item)
            sid = str(s_copy.get("id") or "")
            if resolved_paths_by_shape_id and sid in resolved_paths_by_shape_id:
                s_copy["_resolved_image_path"] = resolved_paths_by_shape_id[sid]
            shapes.append(s_copy)

    try:
        with Image.open(orig_path) as raw_orig:
            orig_transposed = ImageOps.exif_transpose(raw_orig)
            work_img = _compute_working_canvas_image(orig_transposed, transform_ops)
            work_w, work_h = max(1, work_img.width), max(1, work_img.height)
    except Exception:
        return False

    base_fit_scale = max(0.02, min(784.0 / work_w, 524.0 / work_h, 4.0))
    norm_factor = 1.0 / base_fit_scale
    has_zoom = abs(zoom_multiplier - 1.0) > 0.001

    can_patch = (
        not has_zoom
        and updated_shape_ids is not None
        and len(updated_shape_ids) > 0
        and comp_path.exists()
        and comp_path.is_file()
    )
    if can_patch:
        try:
            with Image.open(comp_path) as existing_comp:
                comp_rgba = ImageOps.exif_transpose(existing_comp).convert("RGBA")
            export_w, export_h = comp_rgba.width, comp_rgba.height
            export_scale = export_w / float(work_w)
            vis_scale = export_scale * norm_factor

            for idx, s in enumerate(shapes):
                sid = str(s.get("id") or "")
                if s.get("type") != "image" or sid not in updated_shape_ids:
                    continue
                _draw_annotator_shape_pil(comp_rgba, s, export_scale, vis_scale)
                subsequent = shapes[idx + 1 :]
                if subsequent:
                    x_val = float(s.get("x") or 0.0)
                    y_val = float(s.get("y") or 0.0)
                    w_val = float(s.get("w") or 1.0)
                    h_val = float(s.get("h") or 1.0)
                    rx = max(0, int(round(min(x_val, x_val + w_val) * export_scale)))
                    ry = max(0, int(round(min(y_val, y_val + h_val) * export_scale)))
                    rw = max(1, int(round(abs(w_val) * export_scale)))
                    rh = max(1, int(round(abs(h_val) * export_scale)))
                    cx2 = min(export_w, rx + rw)
                    cy2 = min(export_h, ry + rh)
                    if cx2 > rx and cy2 > ry:
                        over = Image.new("RGBA", (export_w, export_h), (0, 0, 0, 0))
                        for sub_s in subsequent:
                            _draw_annotator_shape_pil(over, sub_s, export_scale, vis_scale)
                        cropped_over = over.crop((rx, ry, cx2, cy2))
                        comp_rgba.alpha_composite(cropped_over, (rx, ry))

            _save_composite_pil_image(comp_rgba, comp_path)
            return True
        except Exception:
            pass

    try:
        export_scale = min(1.0, 1920.0 / max(1, work_w, work_h))
        export_w = max(1, int(round(work_w * export_scale)))
        export_h = max(1, int(round(work_h * export_scale)))
        vis_scale = export_scale * norm_factor
        comp_rgba = work_img.resize((export_w, export_h), Image.Resampling.LANCZOS).convert("RGBA")
        zoom_bounds = (
            _compute_zoom_crop_rect_pil(
                export_w,
                export_h,
                zoom_multiplier,
                pan_x,
                pan_y,
                shapes,
                export_scale,
                vis_scale,
            )
            if (has_zoom and zoom_multiplier > 1.0)
            else (0.0, 0.0, float(export_w), float(export_h))
        )
        for s in shapes:
            _draw_annotator_shape_pil(comp_rgba, s, export_scale, vis_scale, bounds_rect=zoom_bounds)
        if has_zoom:
            comp_rgba = _apply_zoom_to_composite_pil(
                comp_rgba,
                zoom_multiplier,
                pan_x,
                pan_y,
                crop_box=zoom_bounds if zoom_multiplier > 1.0 else None,
            )
        _save_composite_pil_image(comp_rgba, comp_path)
        return True
    except Exception:
        return False


def _save_composite_pil_image(comp_rgba, target_path) -> None:
    from pathlib import Path

    p = Path(target_path)
    suffix = p.suffix.lower()
    buf = BytesIO()
    if suffix in (".jpg", ".jpeg"):
        comp_rgba.convert("RGB").save(buf, format="JPEG", quality=92)
    elif suffix == ".webp":
        comp_rgba.save(buf, format="WEBP", quality=90)
    else:
        comp_rgba.save(buf, format="PNG")
    p.write_bytes(buf.getvalue())
