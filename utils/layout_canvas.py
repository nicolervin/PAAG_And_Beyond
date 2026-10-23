"""High-performance HTML5 2D Canvas Lucidchart-style Pin Map & Layout Engine.

Engineered to handle 20,000+ shapes at 60 FPS with a clean, uncluttered Lucidchart UI:
- Single 44px Top Bar: Page Title, Scale/Units, Contextual Selection Formatting Bar, Overlay & Save
- Floating 42px Left Tool Rail + Collapsible 236px SVG Outline Shape Library Drawer
- Top & Left Physical Scale Rulers (ft, in, m, yd) + Crisp Vector Scaled Grid Canvas
- Slim 34px Bottom Bar: Page Tabs, Floating Layers Popover, Grid/Snap Popover, Undo/Redo, Zoom & Fullscreen
- Uniform Spatial Hash Grid (O(1) hit-testing, port snapping, marquee selection, alignment guides)
- Live PAAG & Yamazumi Data Overlays (Cycle Time vs. Takt Heatmap, Operator & Step Badges, Pitch Inspector)
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Callable

import streamlit as st

_HTML = """
<div id="lc-root" class="lc-root" tabindex="0">
  <!-- Hidden File Input for Optional CAD / Floorplan Image Upload -->
  <input type="file" id="lc-bg-file-input" accept="image/png,image/jpeg,image/webp" style="display:none;" />

  <!-- Single Sleek 44px Lucidchart Top Header & Contextual Formatting Bar -->
  <div class="lc-topbar">
    <!-- Left: Panel Toggle, Editable Page Title, Save Pill, Physical Scale & Unit Controls -->
    <div class="lc-topbar-left">
      <button id="lc-btn-drawer-toggle" class="lc-icon-btn" title="Toggle Shape Library Panel">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="1.5" y="2" width="13" height="12" rx="1.5"/>
          <line x1="6" y1="2" x2="6" y2="14"/>
        </svg>
      </button>
      <input type="text" id="lc-page-title" class="lc-title-input" value="Page 1" title="Click to rename page" />
      <span id="lc-save-pill" class="lc-save-pill saved" title="Save status">● Saved</span>
      <div class="lc-sep"></div>
      <div class="lc-scale-group" title="Physical Canvas Scale (Width × Height)">
        <span class="lc-top-lbl">Scale:</span>
        <input type="number" id="lc-scale-w" class="lc-top-num" value="200" min="1" step="5" title="Canvas physical width" />
        <span class="lc-top-lbl">×</span>
        <input type="number" id="lc-scale-h" class="lc-top-num" value="100" min="1" step="5" title="Canvas physical height" />
        <select id="lc-scale-unit" class="lc-top-select" title="Physical measurement unit">
          <option value="feet">ft</option>
          <option value="inches">in</option>
          <option value="yards">yd</option>
        </select>
        <button id="lc-btn-calibrate" class="lc-top-btn" title="2-Point Scale Calibration on Floorplan (K)">🎯 Calibrate</button>
      </div>
    </div>

    <!-- Center: Contextual Formatting Toolbar (Visible ONLY when 1+ shapes/connectors selected) -->
    <div id="lc-ctx-bar" class="lc-ctx-bar" style="display:none;">
      <button id="lc-ctx-props" class="lc-top-btn" style="font-weight:600; color:#1d4ed8; border-color:#93c5fd; background:#eff6ff;" title="Open Exact Size, Label & Opacity Properties (Double-Click Shape)">⚙ Size &amp; Style</button>
      <input type="text" id="lc-ctx-label" class="lc-top-input" placeholder="Label text..." title="Shape or connector label" />
      <div class="lc-sep"></div>

      <label class="lc-color-wrap" title="Fill Color">
        <span class="lc-color-lbl">Fill</span>
        <input type="color" id="lc-ctx-fill" class="lc-color-pick" value="#ffffff" />
      </label>
      <input type="number" id="lc-ctx-opacity" class="lc-top-num lc-num-xs" min="0" max="100" step="5" value="85" title="Fill Opacity (% — fades fill only, keeps border & text crisp)" />
      <span class="lc-top-lbl">%</span>

      <label class="lc-color-wrap" title="Line / Border Color">
        <span class="lc-color-lbl">Line</span>
        <input type="color" id="lc-ctx-stroke" class="lc-color-pick" value="#1e293b" />
      </label>
      <input type="number" id="lc-ctx-sw" class="lc-top-num lc-num-xs" min="1" max="14" value="2" title="Line Width (px)" />
      <select id="lc-ctx-lstyle" class="lc-top-select" title="Line Style">
        <option value="solid">Solid</option>
        <option value="dashed">Dashed</option>
        <option value="dotted">Dotted</option>
      </select>

      <!-- Connector Routing Controls (Only when connector selected) -->
      <div id="lc-ctx-conn-group" class="lc-ctx-sub" style="display:none;">
        <div class="lc-sep"></div>
        <select id="lc-ctx-routing" class="lc-top-select" title="Connector Routing">
          <option value="orthogonal">↱ Orthogonal</option>
          <option value="curved">↝ Curved</option>
          <option value="straight">↗ Straight</option>
        </select>
        <select id="lc-ctx-arrow" class="lc-top-select" title="Arrowheads">
          <option value="end">→ End</option>
          <option value="both">↔ Both</option>
          <option value="none">— None</option>
        </select>
      </div>

      <!-- Box Geometry Controls (Only when non-connector shape selected) -->
      <div id="lc-ctx-geom-group" class="lc-ctx-sub">
        <div class="lc-sep"></div>
        <span class="lc-top-lbl">W:</span>
        <input type="number" id="lc-ctx-w" class="lc-top-num" step="0.5" min="0.2" title="Physical Width" />
        <span class="lc-top-lbl">H:</span>
        <input type="number" id="lc-ctx-h" class="lc-top-num" step="0.5" min="0.2" title="Physical Height" />
        <span class="lc-top-lbl">∠:</span>
        <input type="number" id="lc-ctx-rot" class="lc-top-num lc-num-xs" step="15" min="0" max="360" title="Rotation Degrees" />
        <button id="lc-ctx-rot90" class="lc-icon-btn lc-btn-xs" title="Rotate 90° Clockwise (R)">↻</button>
      </div>

      <div class="lc-sep"></div>
      <input type="number" id="lc-ctx-fsize" class="lc-top-num lc-num-xs" min="6" max="72" value="12" title="Font Size (pt)" />
      <label class="lc-color-wrap" title="Text Color">
        <span class="lc-color-lbl">Txt</span>
        <input type="color" id="lc-ctx-tcolor" class="lc-color-pick" value="#0f172a" />
      </label>
      <select id="lc-ctx-txt-rot" class="lc-top-select" title="Text Orientation inside Shape (e.g. -90° for vertical pitch numbers)">
        <option value="0">Txt 0°</option>
        <option value="-90">Txt -90°↑</option>
        <option value="90">Txt 90°↓</option>
        <option value="180">Txt 180°</option>
      </select>
      <select id="lc-ctx-pitch" class="lc-top-select" style="max-width:110px;" title="Link shape to Scenario Yamazumi Pitch">
        <option value="">No Pitch Link</option>
      </select>
      <select id="lc-ctx-layer" class="lc-top-select" style="max-width:100px;" title="Assign shape to Layer"></select>

      <div class="lc-sep"></div>
      <button id="lc-ctx-weld" class="lc-top-btn" title="Merge / Weld 2+ overlapping shapes into one unified perimeter polygon (removes interior seams)">⬟ Weld</button>
      <button id="lc-ctx-save-custom" class="lc-top-btn" title="Save selected shape(s) as a reusable Custom Shape in the drawer">★ Save Shape</button>
      <div class="lc-sep"></div>
      <button id="lc-ctx-align-l" class="lc-icon-btn lc-btn-xs" title="Align Left">⫷</button>
      <button id="lc-ctx-align-c" class="lc-icon-btn lc-btn-xs" title="Align Center">⫿</button>
      <button id="lc-ctx-align-t" class="lc-icon-btn lc-btn-xs" title="Align Top">⊤</button>
      <button id="lc-ctx-align-m" class="lc-icon-btn lc-btn-xs" title="Align Middle">⊶</button>
      <button id="lc-ctx-front" class="lc-icon-btn lc-btn-xs" title="Bring to Front">⬆</button>
      <button id="lc-ctx-back" class="lc-icon-btn lc-btn-xs" title="Send to Back">⬇</button>
      <button id="lc-ctx-group" class="lc-icon-btn lc-btn-xs" title="Group / Ungroup (Ctrl+G)">🔗</button>
      <button id="lc-ctx-lock" class="lc-icon-btn lc-btn-xs" title="Lock / Unlock Shape">🔓</button>
      <button id="lc-ctx-dup" class="lc-icon-btn lc-btn-xs" title="Duplicate (Ctrl+D)">⧉</button>
      <button id="lc-ctx-del" class="lc-icon-btn lc-btn-xs lc-danger-icon" title="Delete (Del)">🗑</button>
    </div>

    <!-- Right: Data Overlay Mode, Pitch Sequence Flow Toggle, Export PNG, Save -->
    <div class="lc-topbar-right">
      <select id="lc-overlay-mode" class="lc-top-select" title="PAAG & Yamazumi Data Overlay Mode">
        <option value="clean">Clean Diagram</option>
        <option value="heatmap">CT vs. Takt Heatmap</option>
        <option value="badges">Operators & Steps</option>
        <option value="status">Pitch Status</option>
      </select>
      <button id="lc-btn-flow-chain" class="lc-top-btn active" title="Toggle automatic pitch sequence flow arrows">⛓ Flow</button>
      <button id="lc-btn-export-png" class="lc-top-btn" title="Download high-resolution PNG snapshot of canvas">⬇ PNG</button>
      <button id="lc-btn-save" class="lc-btn-primary" title="Save all changes to database (Ctrl+S)">Save</button>
    </div>
  </div>

  <!-- Main Workspace Stage -->
  <div class="lc-workspace">
    <!-- Top & Left Physical Scale Rulers + Infinite/Scaled 2D Canvas -->
    <div id="lc-center-wrap" class="lc-center-wrap">
      <div id="lc-ruler-corner" class="lc-ruler-corner">ft</div>
      <canvas id="lc-ruler-top" class="lc-ruler-top"></canvas>
      <canvas id="lc-ruler-left" class="lc-ruler-left"></canvas>

      <div id="lc-canvas-stage" class="lc-canvas-stage">
        <canvas id="lc-main-canvas" class="lc-main-canvas"></canvas>

        <!-- Floating Left Vertical Icon Rail (Lucidchart Screenshot 2 style) -->
        <div class="lc-left-rail">
          <button id="lc-rail-search" class="lc-rail-btn" title="Search Shapes & Pitches">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
              <circle cx="7" cy="7" r="4.5"/><line x1="10.5" y1="10.5" x2="14" y2="14"/>
            </svg>
          </button>
          <button id="lc-rail-select" class="lc-rail-btn active" title="Select / Move / Marquee (V)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M3 2l9 6.5-4.2 1.1 2.2 4.2-1.8.9-2.2-4.2L3 13V2z"/>
            </svg>
          </button>
          <button id="lc-rail-shapes" class="lc-rail-btn" title="Shape Library Drawer (S)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="2" y="2" width="6.5" height="6.5" rx="1"/>
              <circle cx="10.5" cy="10.5" r="3.5"/>
            </svg>
          </button>
          <button id="lc-rail-polygon" class="lc-rail-btn" title="Draw Custom Polygon / Machine Footprint Point-by-Point (P)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <polygon points="2.5,3 10,3 10,7.5 13.5,7.5 13.5,13.5 2.5,13.5"/>
              <circle cx="2.5" cy="3" r="1.2" fill="currentColor"/>
              <circle cx="10" cy="7.5" r="1.2" fill="currentColor"/>
              <circle cx="13.5" cy="13.5" r="1.2" fill="currentColor"/>
            </svg>
          </button>
          <button id="lc-rail-note" class="lc-rail-btn" title="Place Sticky Note / Callout (N)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M2.5 2.5h11v8.5l-2.5 2.5h-8.5v-11z"/>
              <path d="M10.5 13.5v-2.5h3"/>
            </svg>
          </button>
          <button id="lc-rail-text" class="lc-rail-btn" title="Place Text Label (T)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7">
              <path d="M3 3.5h10M8 3.5v9.5M5.5 13h5"/>
            </svg>
          </button>
          <button id="lc-rail-connector" class="lc-rail-btn" title="Draw Smart Connector / Flow Arrow (L or C)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M3 13L13 3M9 3h4v4"/>
            </svg>
          </button>
          <button id="lc-rail-frame" class="lc-rail-btn" title="Place Area Header / Swimlane Container (F)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="2" y="2.5" width="12" height="11" rx="1"/>
              <line x1="2" y1="6" x2="14" y2="6"/>
            </svg>
          </button>
          <div class="lc-rail-sep"></div>
          <button id="lc-rail-image" class="lc-rail-btn" title="Upload or Clear Floorplan / CAD Background Image (I)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="2" y="2.5" width="12" height="11" rx="1.5"/>
              <circle cx="5.5" cy="6" r="1.2"/>
              <path d="M2.5 12l3.5-3.5 2.5 2.5 2.5-3 2.5 4"/>
            </svg>
          </button>
          <button id="lc-rail-measure" class="lc-rail-btn" title="Tape Measure Tool (M)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M2 11.5L11.5 2l2.5 2.5L4.5 14 2 11.5z"/>
              <path d="M5 8.5l1.5 1.5M7.5 6l1.5 1.5M10 3.5l1.5 1.5"/>
            </svg>
          </button>
          <button id="lc-rail-array" class="lc-rail-btn" title="Grid / Array Stamp & 20K Generator (G)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="2" y="2" width="3.2" height="3.2"/><rect x="6.4" y="2" width="3.2" height="3.2"/><rect x="10.8" y="2" width="3.2" height="3.2"/>
              <rect x="2" y="6.4" width="3.2" height="3.2"/><rect x="6.4" y="6.4" width="3.2" height="3.2"/><rect x="10.8" y="6.4" width="3.2" height="3.2"/>
              <rect x="2" y="10.8" width="3.2" height="3.2"/><rect x="6.4" y="10.8" width="3.2" height="3.2"/><rect x="10.8" y="10.8" width="3.2" height="3.2"/>
            </svg>
          </button>
          <div class="lc-rail-sep"></div>
          <button id="lc-rail-center-grid" class="lc-rail-btn" title="Center & Fit Grid to Screen (Home or Ctrl+0)">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
              <circle cx="8" cy="8" r="4.5"/>
              <circle cx="8" cy="8" r="1.2" fill="currentColor"/>
              <line x1="8" y1="1.5" x2="8" y2="3.5"/><line x1="8" y1="12.5" x2="8" y2="14.5"/>
              <line x1="1.5" y1="8" x2="3.5" y2="8"/><line x1="12.5" y1="8" x2="14.5" y2="8"/>
            </svg>
          </button>
        </div>

        <!-- Floating Auto-Appearing Return-to-Grid Pill when Scrolled Off-Grid -->
        <button type="button" id="lc-return-grid-btn" class="lc-return-grid-btn" style="display:none;" title="Snap camera back to the center of your grid (Home)">
          ⌖ Return to Grid
        </button>

        <!-- Collapsible Left Shape Library Drawer (Lucidchart Screenshot 1 style) -->
        <div id="lc-shape-drawer" class="lc-shape-drawer" style="display:none;">
          <div class="lc-drawer-hdr">
            <span class="lc-drawer-title">Shapes</span>
            <button id="lc-drawer-close" class="lc-btn-close" title="Close Shape Drawer">✕</button>
          </div>
          <div class="lc-drawer-search">
            <input type="text" id="lc-shape-search" class="lc-input" placeholder="Search shapes & pitches..." />
          </div>
          <div id="lc-drawer-body" class="lc-drawer-body">
            <!-- Populated dynamically with crisp black-and-white outline SVG stencils + Scenario Pitches -->
          </div>
        </div>

        <!-- Centered "Get started faster" Onboarding Card (Shown when canvas is empty & not dismissed) -->
        <div id="lc-empty-card" class="lc-empty-card" style="display:none;">
          <div class="lc-empty-hdr">
            <span>Get started faster</span>
            <button id="lc-empty-close" class="lc-btn-close" title="Dismiss">✕</button>
          </div>
          <div class="lc-empty-actions">
            <button id="lc-empty-shapes" class="lc-empty-btn">
              <span class="lc-empty-ico">□○</span>
              <span>Browse shape libraries</span>
            </button>
            <button id="lc-empty-pitches" class="lc-empty-btn">
              <span class="lc-empty-ico">🏭</span>
              <span>Place scenario pitches</span>
            </button>
            <button id="lc-empty-upload" class="lc-empty-btn">
              <span class="lc-empty-ico">🖼</span>
              <span>Upload CAD / floorplan</span>
            </button>
          </div>
        </div>

        <!-- Floating Live Physical Dimension & Coordinate Pill -->
        <div id="lc-float-hud" class="lc-float-hud" style="display:none;"></div>

        <!-- Inline Double-Click Text Editor Overlay -->
        <div id="lc-inline-editor" class="lc-inline-editor" style="display:none;">
          <input type="text" id="lc-inline-input" class="lc-input" placeholder="Enter text..." />
          <button id="lc-inline-ok" class="lc-btn-primary lc-btn-sm">OK</button>
        </div>

        <!-- Compact Floating PAAG Pitch Inspector Card (Bottom-Right when a linked Pitch is selected) -->
        <div id="lc-pitch-card" class="lc-pitch-card" style="display:none;">
          <div class="lc-pitch-card-hdr">
            <strong id="lc-pc-title">Pitch P01</strong>
            <button id="lc-pc-close" class="lc-btn-close">✕</button>
          </div>
          <div id="lc-pc-body" class="lc-pitch-card-body"></div>
        </div>

        <!-- Floating Layers Popover (Anchored above Bottom Bar) -->
        <div id="lc-layers-popover" class="lc-popover" style="display:none; left:180px; bottom:10px;">
          <div class="lc-popover-hdr">
            <span>❖ Layers (<span id="lc-layer-count">0</span>)</span>
            <div style="display:flex; gap:6px; align-items:center;">
              <button id="lc-btn-add-layer" class="lc-top-btn">+ New Layer</button>
              <button id="lc-layers-close" class="lc-btn-close">✕</button>
            </div>
          </div>
          <div class="lc-popover-sub">
            <label class="lc-chk">
              <input type="checkbox" id="lc-chk-autolayer" checked /> Auto-route shapes to matching layer
            </label>
          </div>
          <div id="lc-layer-list" class="lc-layer-list"></div>
        </div>

        <!-- Floating Grid, Rulers & Background Popover (Anchored above Bottom Bar) -->
        <div id="lc-grid-popover" class="lc-popover" style="display:none; left:275px; bottom:10px; width:250px;">
          <div class="lc-popover-hdr">
            <span>⊞ Grid, Rulers & Floorplan</span>
            <button id="lc-grid-close" class="lc-btn-close">✕</button>
          </div>
          <div style="padding:10px; display:flex; flex-direction:column; gap:8px; font-size:12px;">
            <label class="lc-chk"><input type="checkbox" id="lc-chk-rulers" checked /> Show Physical Scale Rulers</label>
            <label class="lc-chk"><input type="checkbox" id="lc-chk-grid" checked /> Show Scaled Vector Gridlines</label>
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span>Grid Snap Interval:</span>
              <select id="lc-snap-step" class="lc-top-select">
                <option value="auto">Auto</option>
                <option value="0.5">0.5 units</option>
                <option value="1" selected>1.0 unit</option>
                <option value="2">2.0 units</option>
                <option value="5">5.0 units</option>
                <option value="0">Off</option>
              </select>
            </div>
            <div style="border-top:1px solid #e2e8f0; padding-top:8px; display:flex; gap:6px;">
              <button id="lc-btn-upload-bg" class="lc-top-btn" style="flex:1;">🖼 Upload Floorplan</button>
              <button id="lc-btn-clear-bg" class="lc-top-btn" style="flex:1; background:#c62828; color:#ffffff; border-color:#c62828;">Clear Image</button>
            </div>
          </div>
        </div>

        <!-- Modal Dialog for 2-Point Scale Calibration -->
        <div id="lc-calib-modal" class="lc-modal" style="display:none;">
          <div class="lc-modal-box">
            <div class="lc-modal-hdr">🎯 Calibrate Canvas Scale</div>
            <div class="lc-modal-body">
              <p id="lc-calib-px-info" style="margin:4px 0 10px 0; font-size:12px; color:#475569;"></p>
              <label class="lc-field-lbl">Known Real-World Distance Between Points:</label>
              <div style="display:flex; gap:8px; margin-top:6px;">
                <input type="number" id="lc-calib-dist" class="lc-input" value="20" min="0.1" step="0.5" style="flex:1;" />
                <select id="lc-calib-unit" class="lc-top-select" style="width:100px;">
                  <option value="feet">feet</option>
                  <option value="inches">inches</option>
                  <option value="yards">yards</option>
                </select>
              </div>
            </div>
            <div class="lc-modal-ftr">
              <button id="lc-calib-cancel" class="lc-top-btn">Cancel</button>
              <button id="lc-calib-apply" class="lc-btn-primary">Apply Scale</button>
            </div>
          </div>
        </div>

        <!-- Modal Dialog for Grid / Array Stamp & 20K Benchmark -->
        <div id="lc-array-modal" class="lc-modal" style="display:none;">
          <div class="lc-modal-box">
            <div class="lc-modal-hdr">⠿ Grid / Array Stamp (Up to 20,000 Shapes)</div>
            <div class="lc-modal-body">
              <p style="margin:0 0 8px 0; font-size:12px; color:#475569;">
                Stamp the selected shape (or standard workstation footprint) into a scaled grid of rows and columns.
              </p>
              <div class="lc-form-grid">
                <div>
                  <label class="lc-field-lbl">Columns (X):</label>
                  <input type="number" id="lc-arr-cols" class="lc-input" value="10" min="1" max="250" />
                </div>
                <div>
                  <label class="lc-field-lbl">Rows (Y):</label>
                  <input type="number" id="lc-arr-rows" class="lc-input" value="2" min="1" max="250" />
                </div>
                <div>
                  <label class="lc-field-lbl">Gap X (<span class="lc-unit-txt">ft</span>):</label>
                  <input type="number" id="lc-arr-gapx" class="lc-input" value="1.0" step="0.5" />
                </div>
                <div>
                  <label class="lc-field-lbl">Gap Y (<span class="lc-unit-txt">ft</span>):</label>
                  <input type="number" id="lc-arr-gapy" class="lc-input" value="4.0" step="0.5" />
                </div>
              </div>
              <div style="margin-top:10px; padding-top:8px; border-top:1px solid #e2e8f0; display:flex; gap:6px; flex-wrap:wrap;">
                <button id="lc-arr-preset-500" class="lc-top-btn">Preset: 500 (25×20)</button>
                <button id="lc-arr-preset-2500" class="lc-top-btn">Preset: 2,500 (50×50)</button>
                <button id="lc-arr-preset-20k" class="lc-top-btn">Stress Test: 20,000 (200×100)</button>
              </div>
            </div>
            <div class="lc-modal-ftr">
              <button id="lc-arr-cancel" class="lc-top-btn">Cancel</button>
              <button id="lc-arr-apply" class="lc-btn-primary">Stamp Grid</button>
            </div>
          </div>
        </div>

        <!-- Double-Click Shape Exact Size, Text & Opacity Properties Modal -->
        <div id="lc-shape-props-modal" class="lc-modal" style="display:none;">
          <div class="lc-modal-box" style="width:460px; max-width:95vw;">
            <div class="lc-modal-hdr" style="display:flex; justify-content:space-between; align-items:center;">
              <span id="lc-prop-modal-title">⚙ Shape Size, Text &amp; Appearance</span>
              <button id="lc-prop-close-x" class="lc-btn-close">✕</button>
            </div>
            <div class="lc-modal-body" style="max-height:76vh; overflow-y:auto; display:flex; flex-direction:column; gap:10px;">
              <!-- Section 1: Label & Text Inside Shape -->
              <div class="lc-prop-section">
                <div class="lc-prop-sec-title">Label &amp; Inside Text</div>
                <textarea id="lc-prop-label" class="lc-input" rows="2" placeholder="Enter shape label (supports multiple lines)..." style="resize:vertical; font-family:inherit;"></textarea>
                <div style="display:grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap:6px; margin-top:6px;">
                  <div>
                    <label class="lc-field-lbl">Font Size (pt)</label>
                    <input type="number" id="lc-prop-fsize" class="lc-input" min="6" max="96" value="12" />
                  </div>
                  <div>
                    <label class="lc-field-lbl">Weight</label>
                    <select id="lc-prop-fweight" class="lc-top-select" style="width:100%; height:28px;">
                      <option value="bold">Bold</option>
                      <option value="normal">Normal</option>
                    </select>
                  </div>
                  <div>
                    <label class="lc-field-lbl">Align</label>
                    <select id="lc-prop-talign" class="lc-top-select" style="width:100%; height:28px;">
                      <option value="center">Center</option>
                      <option value="left">Left</option>
                      <option value="right">Right</option>
                    </select>
                  </div>
                  <div>
                    <label class="lc-field-lbl">Text Angle</label>
                    <select id="lc-prop-trot" class="lc-top-select" style="width:100%; height:28px;">
                      <option value="0">0° Horiz</option>
                      <option value="-90">-90° Vert ↑</option>
                      <option value="90">90° Vert ↓</option>
                      <option value="180">180° Flip</option>
                    </select>
                  </div>
                </div>
                <div style="display:flex; align-items:center; gap:8px; margin-top:6px;">
                  <label class="lc-field-lbl" style="margin:0;">Text Color:</label>
                  <input type="color" id="lc-prop-tcolor" class="lc-color-pick" value="#0f172a" />
                  <div class="lc-swatch-row" id="lc-prop-tcolor-swatches">
                    <button type="button" class="lc-swatch" data-color="#0f172a" style="background:#0f172a;" title="Dark Slate"></button>
                    <button type="button" class="lc-swatch" data-color="#ffffff" style="background:#ffffff;" title="White"></button>
                    <button type="button" class="lc-swatch" data-color="#b91c1c" style="background:#b91c1c;" title="Red"></button>
                    <button type="button" class="lc-swatch" data-color="#15803d" style="background:#15803d;" title="Green"></button>
                    <button type="button" class="lc-swatch" data-color="#1d4ed8" style="background:#1d4ed8;" title="Blue"></button>
                  </div>
                </div>
              </div>

              <!-- Optional Area Header Extra Fields (Only when area_header selected) -->
              <div id="lc-prop-area-hdr-sec" class="lc-prop-section" style="display:none;">
                <div class="lc-prop-sec-title">Area Header Badge Details</div>
                <div class="lc-form-grid">
                  <div>
                    <label class="lc-field-lbl">Area / Dept Number (e.g. 374)</label>
                    <input type="text" id="lc-prop-area-code" class="lc-input" placeholder="374" />
                  </div>
                  <div>
                    <label class="lc-field-lbl">Sub-Pills (comma-separated)</label>
                    <input type="text" id="lc-prop-area-pills" class="lc-input" placeholder="STANDARD WORK, YAMAZUMI" />
                  </div>
                </div>
              </div>

              <!-- Section 2: Exact Physical Size & Position -->
              <div class="lc-prop-section">
                <div class="lc-prop-sec-title">Exact Physical Size &amp; Orientation (<span class="lc-unit-txt">ft</span>)</div>
                <div style="display:grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap:6px;">
                  <div>
                    <label class="lc-field-lbl">Width (<span class="lc-unit-txt">ft</span>)</label>
                    <input type="number" id="lc-prop-w" class="lc-input" min="0.1" step="0.25" />
                  </div>
                  <div>
                    <label class="lc-field-lbl">Height (<span class="lc-unit-txt">ft</span>)</label>
                    <input type="number" id="lc-prop-h" class="lc-input" min="0.1" step="0.25" />
                  </div>
                  <div>
                    <label class="lc-field-lbl">X Pos (<span class="lc-unit-txt">ft</span>)</label>
                    <input type="number" id="lc-prop-x" class="lc-input" step="0.5" />
                  </div>
                  <div>
                    <label class="lc-field-lbl">Y Pos (<span class="lc-unit-txt">ft</span>)</label>
                    <input type="number" id="lc-prop-y" class="lc-input" step="0.5" />
                  </div>
                </div>
                <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:6px;">
                  <div style="display:flex; align-items:center; gap:6px;">
                    <label class="lc-field-lbl" style="margin:0;">Shape Rotation (°):</label>
                    <input type="number" id="lc-prop-rot" class="lc-input" style="width:70px;" min="0" max="360" step="15" />
                  </div>
                  <div style="display:flex; gap:4px;">
                    <button type="button" class="lc-top-btn lc-rot-preset" data-rot="0">0°</button>
                    <button type="button" class="lc-top-btn lc-rot-preset" data-rot="90">90°</button>
                    <button type="button" class="lc-top-btn lc-rot-preset" data-rot="180">180°</button>
                    <button type="button" class="lc-top-btn lc-rot-preset" data-rot="270">270°</button>
                  </div>
                </div>
              </div>

              <!-- Section 3: Fill Color, Fill Opacity & Border Style -->
              <div class="lc-prop-section">
                <div class="lc-prop-sec-title">Fill Color, Opacity &amp; Border</div>
                <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
                  <div style="display:flex; align-items:center; gap:6px;">
                    <label class="lc-field-lbl" style="margin:0;">Fill:</label>
                    <input type="color" id="lc-prop-fill" class="lc-color-pick" value="#ffffff" />
                  </div>
                  <div class="lc-swatch-row" id="lc-prop-fill-swatches">
                    <button type="button" class="lc-swatch" data-color="#ffffff" style="background:#ffffff;" title="White"></button>
                    <button type="button" class="lc-swatch" data-color="#fdba74" style="background:#fdba74;" title="Machine Orange (Pedestal Bend)"></button>
                    <button type="button" class="lc-swatch" data-color="#bbf7d0" style="background:#bbf7d0;" title="Active Green"></button>
                    <button type="button" class="lc-swatch" data-color="#fef08a" style="background:#fef08a;" title="Staging Yellow"></button>
                    <button type="button" class="lc-swatch" data-color="#fecaca" style="background:#fecaca;" title="Alert / Defect Red"></button>
                    <button type="button" class="lc-swatch" data-color="#dbeafe" style="background:#dbeafe;" title="Pitch Blue"></button>
                    <button type="button" class="lc-swatch" data-color="#e9d5ff" style="background:#e9d5ff;" title="Subassembly Purple"></button>
                    <button type="button" class="lc-swatch" data-color="#cbd5e1" style="background:#cbd5e1;" title="Conveyor Slate"></button>
                  </div>
                </div>
                <div style="display:flex; align-items:center; gap:8px; margin-top:8px;">
                  <label class="lc-field-lbl" style="margin:0; min-width:105px;">Fill Opacity (%):</label>
                  <input type="range" id="lc-prop-opacity-range" min="0" max="100" step="5" value="85" style="flex:1;" />
                  <input type="number" id="lc-prop-opacity-num" class="lc-input" style="width:58px;" min="0" max="100" step="5" value="85" />
                  <button type="button" id="lc-prop-op-zero" class="lc-top-btn" title="Transparent Fill (Outline Only)">0%</button>
                </div>
                <div style="font-size:10px; color:#64748b; margin-top:2px;">
                  Fades only the interior fill so gridlines/CAD remain visible underneath while borders &amp; text stay 100% crisp.
                </div>

                <div style="display:grid; grid-template-columns: auto 1fr 75px 100px; gap:8px; align-items:center; margin-top:8px; padding-top:8px; border-top:1px solid #e2e8f0;">
                  <div style="display:flex; align-items:center; gap:5px;">
                    <label class="lc-field-lbl" style="margin:0;">Border:</label>
                    <input type="color" id="lc-prop-stroke" class="lc-color-pick" value="#1e293b" />
                  </div>
                  <div class="lc-swatch-row" id="lc-prop-stroke-swatches">
                    <button type="button" class="lc-swatch" data-color="#1e293b" style="background:#1e293b;" title="Dark Slate"></button>
                    <button type="button" class="lc-swatch" data-color="#16a34a" style="background:#16a34a;" title="Green Border"></button>
                    <button type="button" class="lc-swatch" data-color="#eab308" style="background:#eab308;" title="Yellow Border"></button>
                    <button type="button" class="lc-swatch" data-color="#dc2626" style="background:#dc2626;" title="Red Border"></button>
                    <button type="button" class="lc-swatch" data-color="#2563eb" style="background:#2563eb;" title="Blue Border"></button>
                    <button type="button" class="lc-swatch" data-color="#ea580c" style="background:#ea580c;" title="Orange Border"></button>
                  </div>
                  <div>
                    <input type="number" id="lc-prop-sw" class="lc-input" min="1" max="16" value="2" title="Border Width (px)" />
                  </div>
                  <div>
                    <select id="lc-prop-lstyle" class="lc-top-select" style="width:100%; height:28px;">
                      <option value="solid">Solid</option>
                      <option value="dashed">Dashed</option>
                      <option value="dotted">Dotted</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
            <div class="lc-modal-ftr" style="justify-content:space-between;">
              <button type="button" id="lc-prop-save-custom" class="lc-top-btn" title="Save this shape into your Custom Shapes library">★ Save as Custom Shape</button>
              <div style="display:flex; gap:8px;">
                <button type="button" id="lc-prop-cancel" class="lc-top-btn">Cancel</button>
                <button type="button" id="lc-prop-apply" class="lc-btn-primary">Apply Changes</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Modal Dialog to Save Selected Shapes as a Reusable Custom Shape -->
        <div id="lc-custom-stencil-modal" class="lc-modal" style="display:none;">
          <div class="lc-modal-box">
            <div class="lc-modal-hdr">★ Save to Custom Shapes Library</div>
            <div class="lc-modal-body">
              <p id="lc-custom-stencil-info" style="margin:0 0 8px 0; font-size:12px; color:#475569;">
                Save the currently selected shape(s) as a reusable stencil in your project's <strong>Saved Shapes</strong> drawer.
              </p>
              <label class="lc-field-lbl">Custom Shape Name:</label>
              <input type="text" id="lc-custom-stencil-name" class="lc-input" placeholder="e.g. Pedestal Bend Machine, Quality Pin, Worktable..." style="margin-bottom:8px;" />
              <label class="lc-field-lbl">Category Label:</label>
              <input type="text" id="lc-custom-stencil-cat" class="lc-input" value="Saved Shapes" />
            </div>
            <div class="lc-modal-ftr">
              <button type="button" id="lc-custom-stencil-cancel" class="lc-top-btn">Cancel</button>
              <button type="button" id="lc-custom-stencil-save" class="lc-btn-primary">Save Custom Shape</button>
            </div>
          </div>
        </div>

        <!-- Right-Click Context Menu on Canvas / Shapes -->
        <div id="lc-context-menu" class="lc-context-menu" style="display:none;">
          <button type="button" class="lc-ctx-item" id="lc-cm-props">⚙ Edit Exact Size, Text &amp; Opacity...</button>
          <div class="lc-ctx-divider"></div>
          <button type="button" class="lc-ctx-item" id="lc-cm-rot90">↻ Rotate Shape 90° CW (R)</button>
          <button type="button" class="lc-ctx-item" id="lc-cm-rot-ccw">↺ Rotate Shape 90° CCW (Shift+R)</button>
          <button type="button" class="lc-ctx-item" id="lc-cm-txt-rot">↕ Toggle Vertical Text (-90° / 0°)</button>
          <button type="button" class="lc-ctx-item" id="lc-cm-weld">⬟ Merge / Weld Overlapping Shapes</button>
          <button type="button" class="lc-ctx-item" id="lc-cm-save-custom">★ Save as Custom Shape...</button>
          <button type="button" class="lc-ctx-item" id="lc-cm-group">🔗 Group / Ungroup (Ctrl+G)</button>
          <button type="button" class="lc-ctx-item" id="lc-cm-lock">🔒 Lock / Unlock Shape</button>
          <div class="lc-ctx-divider"></div>
          <button type="button" class="lc-ctx-item" id="lc-cm-front">⬆ Bring to Front</button>
          <button type="button" class="lc-ctx-item" id="lc-cm-back">⬇ Send to Back</button>
          <button type="button" class="lc-ctx-item" id="lc-cm-dup">⧉ Duplicate (Ctrl+D)</button>
          <button type="button" class="lc-ctx-item lc-ctx-danger" id="lc-cm-del">🗑 Delete (Del)</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Slim 34px Lucidchart Bottom Bar (Page Tabs, Layers, Grid, Print Scale, Undo/Redo, Zoom, Fullscreen) -->
  <div class="lc-bottombar">
    <div class="lc-bottom-left">
      <div id="lc-page-tabs" class="lc-page-tabs"></div>
      <button id="lc-btn-add-page" class="lc-bottom-btn" title="Add New Page">+</button>
      <div class="lc-sep"></div>
      <button id="lc-btn-layers-pop" class="lc-bottom-btn" title="Open Layers Manager">❖ Layers</button>
      <button id="lc-btn-grid-pop" class="lc-bottom-btn" title="Grid, Rulers & Floorplan Settings">⊞ Grid &amp; Snap</button>
      <button id="lc-btn-sec-std" class="lc-bottom-btn" title="Configure Section Pitch Dimensions &amp; Standards">📐 Pitch Standards</button>
      <button id="lc-btn-cad-rev" class="lc-bottom-btn" title="Manage PDF / CAD Floorplan Revisions &amp; Multi-Page PDF Imports">📄 PDF/CAD Rev</button>
      <div class="lc-sep"></div>
      <span id="lc-print-scale" class="lc-status-txt" style="font-weight:600; color:#334155;" title="Physical Print / Grid Scale Equivalency">Print scale: 3 in = 16 ft</span>
    </div>

    <div class="lc-bottom-right">
      <span id="lc-status-cursor" class="lc-status-txt">0.0, 0.0 ft</span>
      <span class="lc-status-dot">·</span>
      <span id="lc-status-counts" class="lc-status-txt">0 shapes</span>
      <div class="lc-sep"></div>
      <button id="lc-btn-undo" class="lc-bottom-btn" title="Undo (Ctrl+Z)" disabled>↶</button>
      <button id="lc-btn-redo" class="lc-bottom-btn" title="Redo (Ctrl+Y)" disabled>↷</button>
      <div class="lc-sep"></div>
      <button id="lc-btn-center-grid" class="lc-bottom-btn" title="Center &amp; Fit Grid to Screen (Home or Ctrl+0)" style="font-weight:600; color:#1d4ed8;">⌖ Center Grid</button>
      <button id="lc-zoom-out" class="lc-bottom-btn" title="Zoom Out">−</button>
      <button id="lc-zoom-fit" class="lc-bottom-btn lc-zoom-pct" title="Click to Center &amp; Fit Grid to Screen (Home)"><span id="lc-zoom-readout">100%</span></button>
      <button id="lc-zoom-in" class="lc-bottom-btn" title="Zoom In">+</button>
      <button id="lc-fullscreen" class="lc-bottom-btn" title="Toggle Fullscreen">⛶</button>
    </div>
  </div>
</div>
"""

_CSS = """
* { box-sizing: border-box; }
.lc-root {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 740px;
  min-height: 680px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #f3f4f6;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: #1f2937;
  overflow: hidden;
  user-select: none;
  outline: none;
}
.lc-root:fullscreen {
  height: 100vh !important;
  border-radius: 0;
  border: none;
}

/* Single 44px Top Header Bar */
.lc-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  flex-shrink: 0;
  overflow: hidden;
  padding: 0 10px;
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
  gap: 8px;
  z-index: 30;
}
.lc-topbar-left, .lc-topbar-right, .lc-ctx-bar, .lc-ctx-sub, .lc-scale-group {
  display: flex;
  align-items: center;
  gap: 5px;
}
.lc-ctx-bar {
  background: #f8fafc;
  padding: 3px 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  overflow-x: auto;
  scrollbar-width: none;
  max-width: 58vw;
}
.lc-ctx-bar::-webkit-scrollbar {
  display: none;
}
.lc-title-input {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  border: 1px solid transparent;
  border-radius: 4px;
  padding: 3px 6px;
  width: 130px;
  background: transparent;
}
.lc-title-input:hover, .lc-title-input:focus {
  border-color: #cbd5e1;
  background: #ffffff;
  outline: none;
}
.lc-save-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 999px;
  white-space: nowrap;
}
.lc-save-pill.saved {
  color: #15803d;
  background: #dcfce7;
}
.lc-save-pill.unsaved {
  color: #b45309;
  background: #fef3c7;
}
.lc-sep {
  width: 1px;
  height: 18px;
  background: #e5e7eb;
  margin: 0 2px;
  flex-shrink: 0;
}
.lc-top-lbl {
  font-size: 11px;
  font-weight: 600;
  color: #6b7280;
}
.lc-top-num {
  width: 54px;
  padding: 3px 5px;
  font-size: 12px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  color: #111827;
  background: #ffffff;
}
.lc-num-xs {
  width: 44px;
}
.lc-top-input {
  width: 110px;
  padding: 3px 6px;
  font-size: 12px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  color: #111827;
  background: #ffffff;
}
.lc-top-select {
  padding: 3px 6px;
  font-size: 12px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  color: #111827;
  background: #ffffff;
  cursor: pointer;
}
.lc-top-btn, .lc-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 500;
  color: #374151;
  background: #ffffff;
  border: 1px solid #d1d5db;
  border-radius: 5px;
  cursor: pointer;
  white-space: nowrap;
}
.lc-icon-btn {
  padding: 4px 6px;
}
.lc-btn-xs {
  padding: 2px 5px;
  font-size: 11px;
}
.lc-top-btn:hover, .lc-icon-btn:hover {
  background: #f3f4f6;
  border-color: #9ca3af;
}
.lc-top-btn.active, .lc-icon-btn.active {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #93c5fd;
}
.lc-danger-icon:hover {
  background: #fef2f2;
  color: #dc2626;
  border-color: #fca5a5;
}
.lc-btn-primary {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #ffffff;
  background: #2563eb;
  border: 1px solid #1d4ed8;
  border-radius: 5px;
  cursor: pointer;
  white-space: nowrap;
}
.lc-btn-primary:hover {
  background: #1d4ed8;
}
.lc-btn-primary.unsaved {
  background: #ea580c;
  border-color: #c2410c;
}
.lc-color-wrap {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  cursor: pointer;
}
.lc-color-lbl {
  font-size: 11px;
  color: #4b5563;
  font-weight: 500;
}
.lc-color-pick {
  width: 22px;
  height: 22px;
  padding: 0;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  background: none;
  cursor: pointer;
}

/* Workspace & Rulers */
.lc-workspace {
  display: flex;
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: hidden;
}
.lc-center-wrap {
  flex: 1;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  grid-template-rows: 22px minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  position: relative;
  overflow: hidden;
}
.lc-center-wrap.no-rulers {
  grid-template-columns: 0px minmax(0, 1fr);
  grid-template-rows: 0px minmax(0, 1fr);
}
.lc-ruler-corner {
  background: #f9fafb;
  border-right: 1px solid #e5e7eb;
  border-bottom: 1px solid #e5e7eb;
  font-size: 9px;
  font-weight: 700;
  color: #6b7280;
  display: flex;
  align-items: center;
  justify-content: center;
}
.lc-ruler-top {
  width: 100%;
  height: 22px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #f9fafb;
  border-bottom: 1px solid #e5e7eb;
  display: block;
}
.lc-ruler-left {
  width: 24px;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #f9fafb;
  border-right: 1px solid #e5e7eb;
  display: block;
}
.lc-canvas-stage {
  position: relative;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #e5e7eb;
}
.lc-main-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  cursor: default;
  touch-action: none;
}

/* Floating Left Vertical Icon Rail (Screenshot 2) */
.lc-left-rail {
  position: absolute;
  left: 10px;
  top: 12px;
  width: 40px;
  background: #ffffff;
  border: 1px solid #d1d5db;
  border-radius: 7px;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 5px 0;
  gap: 3px;
  z-index: 20;
}
.lc-rail-btn {
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  border-radius: 5px;
  color: #374151;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.lc-rail-btn:hover {
  background: #f3f4f6;
  color: #111827;
}
.lc-rail-btn.active {
  background: #dbeafe;
  color: #2563eb;
}
.lc-rail-sep {
  width: 22px;
  height: 1px;
  background: #e5e7eb;
  margin: 2px 0;
}

/* Collapsible Left Shape Library Drawer (Screenshot 1) */
.lc-shape-drawer {
  position: absolute;
  left: 58px;
  top: 12px;
  bottom: 12px;
  width: 242px;
  background: #ffffff;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 22;
}
.lc-drawer-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid #e5e7eb;
}
.lc-drawer-title {
  font-size: 13px;
  font-weight: 700;
  color: #111827;
}
.lc-drawer-search {
  padding: 8px 10px;
  border-bottom: 1px solid #f3f4f6;
}
.lc-input {
  width: 100%;
  padding: 5px 8px;
  font-size: 12px;
  border: 1px solid #d1d5db;
  border-radius: 5px;
  color: #111827;
  background: #f9fafb;
}
.lc-input:focus {
  background: #ffffff;
  border-color: #2563eb;
  outline: none;
}
.lc-drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px 10px 14px 10px;
}
.lc-cat-sec {
  margin-bottom: 10px;
}
.lc-cat-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  font-weight: 700;
  color: #374151;
  padding: 4px 2px;
  cursor: pointer;
  border-bottom: 1px solid #f3f4f6;
  margin-bottom: 6px;
}
.lc-cat-hdr:hover {
  color: #111827;
}
/* Lucidchart 5-column minimal SVG icon grid */
.lc-svg-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 4px;
}
.lc-svg-tile {
  height: 36px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: #334155;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 3px;
  transition: all 0.1s;
}
.lc-svg-tile:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
  color: #0f172a;
}

/* Scenario Pitches in Drawer */
.lc-pitch-item {
  padding: 5px 7px;
  border: 1px solid #e5e7eb;
  border-radius: 5px;
  background: #f9fafb;
  font-size: 11px;
  cursor: pointer;
  margin-bottom: 4px;
}
.lc-pitch-item:hover {
  background: #eff6ff;
  border-color: #93c5fd;
}
.lc-pitch-item.placed {
  border-left: 3px solid #16a34a;
}
.lc-pitch-item.unplaced {
  border-left: 3px solid #f59e0b;
}

/* Centered "Get started faster" Onboarding Card (Screenshot 1 & 2) */
.lc-empty-card {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 240px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.08);
  padding: 12px 14px;
  z-index: 15;
}
.lc-empty-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 8px;
}
.lc-empty-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.lc-empty-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  font-size: 12px;
  color: #334155;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 5px;
  cursor: pointer;
  text-align: left;
}
.lc-empty-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1d4ed8;
}
.lc-empty-ico {
  width: 18px;
  text-align: center;
  font-size: 13px;
}

/* Popovers (Layers & Grid) */
.lc-popover {
  position: absolute;
  width: 280px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  box-shadow: 0 10px 25px rgba(15, 23, 42, 0.16);
  z-index: 28;
  overflow: hidden;
}
.lc-popover-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
}
.lc-popover-sub {
  padding: 5px 10px;
  border-bottom: 1px solid #f1f5f9;
  background: #ffffff;
}
.lc-layer-list {
  max-height: 210px;
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.lc-layer-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 6px;
  border-radius: 5px;
  border: 1px solid transparent;
  font-size: 11px;
  cursor: pointer;
}
.lc-layer-row:hover {
  background: #f8fafc;
}
.lc-layer-row.active {
  background: #eff6ff;
  border-color: #93c5fd;
  font-weight: 600;
}
.lc-layer-swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}
.lc-layer-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lc-layer-cnt {
  font-size: 10px;
  color: #64748b;
  background: #e2e8f0;
  padding: 0 5px;
  border-radius: 8px;
}
.lc-layer-icon-btn {
  background: none;
  border: none;
  padding: 1px 3px;
  font-size: 12px;
  cursor: pointer;
  opacity: 0.75;
}
.lc-layer-icon-btn:hover {
  opacity: 1;
}

/* Slim 34px Lucidchart Bottom Bar */
.lc-bottombar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 34px;
  flex-shrink: 0;
  overflow: hidden;
  padding: 0 10px;
  background: #ffffff;
  border-top: 1px solid #e5e7eb;
  font-size: 11px;
  z-index: 30;
}
.lc-bottom-left, .lc-bottom-right, .lc-page-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
}
.lc-page-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 500;
  color: #4b5563;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
}
.lc-page-tab:hover {
  background: #f3f4f6;
}
.lc-page-tab.active {
  color: #1d4ed8;
  background: #eff6ff;
  border-color: #bfdbfe;
  font-weight: 600;
}
.lc-page-del {
  font-size: 10px;
  color: #9ca3af;
  margin-left: 2px;
}
.lc-page-del:hover {
  color: #dc2626;
}
.lc-bottom-btn {
  padding: 3px 7px;
  font-size: 11px;
  font-weight: 600;
  color: #374151;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
}
.lc-bottom-btn:hover:not(:disabled) {
  background: #f3f4f6;
  border-color: #d1d5db;
}
.lc-bottom-btn.active {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #93c5fd;
}
.lc-bottom-btn:disabled {
  opacity: 0.35;
  cursor: default;
}
.lc-zoom-pct {
  min-width: 46px;
  text-align: center;
}
.lc-status-txt {
  color: #6b7280;
  font-weight: 500;
}
.lc-status-dot {
  color: #cbd5e1;
}

/* Floating HUD, Inline Editor, Pitch Card & Modals */
.lc-float-hud {
  position: absolute;
  pointer-events: none;
  background: rgba(15, 23, 42, 0.88);
  color: #f8fafc;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  z-index: 25;
}
.lc-inline-editor {
  position: absolute;
  display: flex;
  gap: 4px;
  background: #ffffff;
  padding: 4px;
  border: 2px solid #2563eb;
  border-radius: 6px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.2);
  z-index: 30;
}
.lc-pitch-card {
  position: absolute;
  right: 12px;
  bottom: 12px;
  width: 280px;
  max-height: 220px;
  background: rgba(255, 255, 255, 0.97);
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.14);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 20;
}
.lc-pitch-card-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: #eff6ff;
  border-bottom: 1px solid #bfdbfe;
  font-size: 12px;
  color: #1e3a8a;
}
.lc-pitch-card-body {
  padding: 8px 10px;
  font-size: 11px;
  overflow-y: auto;
}
.lc-btn-close {
  background: none;
  border: none;
  font-size: 13px;
  color: #64748b;
  cursor: pointer;
}
.lc-btn-close:hover {
  color: #0f172a;
}
.lc-chk {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #374151;
  cursor: pointer;
}
.lc-field-lbl {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: #4b5563;
  margin-bottom: 2px;
}
.lc-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.lc-modal {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 40;
}
.lc-modal-box {
  width: 360px;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.25);
  overflow: hidden;
}
.lc-modal-hdr {
  padding: 10px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  font-size: 13px;
  font-weight: 700;
}
.lc-modal-body {
  padding: 12px 14px;
}
.lc-modal-ftr {
  padding: 8px 14px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.lc-prop-section {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 10px;
}
.lc-prop-sec-title {
  font-size: 11px;
  font-weight: 700;
  color: #1e293b;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 6px;
}
.lc-swatch-row {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.lc-swatch {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  border: 1px solid rgba(15, 23, 42, 0.28);
  cursor: pointer;
  padding: 0;
  transition: transform 0.1s;
}
.lc-swatch:hover {
  transform: scale(1.15);
  border-color: #2563eb;
}
.lc-context-menu {
  position: absolute;
  z-index: 45;
  min-width: 220px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  box-shadow: 0 10px 25px rgba(15, 23, 42, 0.18);
  padding: 4px;
  display: flex;
  flex-direction: column;
}
.lc-ctx-item {
  border: none;
  background: transparent;
  text-align: left;
  padding: 6px 10px;
  font-size: 12px;
  color: #1e293b;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.lc-ctx-item:hover {
  background: #eff6ff;
  color: #1d4ed8;
}
.lc-ctx-danger {
  color: #dc2626;
}
.lc-ctx-danger:hover {
  background: #fef2f2;
  color: #b91c1c;
}
.lc-ctx-divider {
  height: 1px;
  background: #e2e8f0;
  margin: 3px 0;
}
.lc-custom-stencil-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 5px 7px;
  margin-bottom: 4px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 5px;
  font-size: 11px;
  cursor: pointer;
}
.lc-custom-stencil-row:hover {
  border-color: #2563eb;
  background: #eff6ff;
}
.lc-return-grid-btn {
  position: absolute;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 42;
  background: #1d4ed8;
  color: #ffffff;
  border: 1px solid #1e40af;
  border-radius: 999px;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.22);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: background 0.15s, transform 0.15s;
}
.lc-return-grid-btn:hover {
  background: #1e40af;
  transform: translateX(-50%) scale(1.03);
}
"""

_JS = r"""
export default function(component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector("#lc-root")
  const centerWrap = parentElement.querySelector("#lc-center-wrap")
  const stage = parentElement.querySelector("#lc-canvas-stage")
  const mainCanvas = parentElement.querySelector("#lc-main-canvas")
  const rulerTop = parentElement.querySelector("#lc-ruler-top")
  const rulerLeft = parentElement.querySelector("#lc-ruler-left")
  const rulerCorner = parentElement.querySelector("#lc-ruler-corner")
  const floatHud = parentElement.querySelector("#lc-float-hud")
  const inlineEditor = parentElement.querySelector("#lc-inline-editor")
  const inlineInput = parentElement.querySelector("#lc-inline-input")
  const inlineOk = parentElement.querySelector("#lc-inline-ok")
  const pitchCard = parentElement.querySelector("#lc-pitch-card")
  const pcTitle = parentElement.querySelector("#lc-pc-title")
  const pcBody = parentElement.querySelector("#lc-pc-body")
  const pcClose = parentElement.querySelector("#lc-pc-close")
  const emptyCard = parentElement.querySelector("#lc-empty-card")
  const shapeDrawer = parentElement.querySelector("#lc-shape-drawer")
  const layersPopover = parentElement.querySelector("#lc-layers-popover")
  const gridPopover = parentElement.querySelector("#lc-grid-popover")
  const bgFileInput = parentElement.querySelector("#lc-bg-file-input")
  const contextMenu = parentElement.querySelector("#lc-context-menu")
  const shapePropsModal = parentElement.querySelector("#lc-shape-props-modal")
  const customStencilModal = parentElement.querySelector("#lc-custom-stencil-modal")

  if (!root || !mainCanvas || !stage) return

  const UNIT_TO_IN = { inches: 1.0, feet: 12.0, yards: 36.0, miles: 63360.0, meters: 39.37007874 }
  const UNIT_ABBR = { inches: "in", feet: "ft", yards: "yd", miles: "mi", meters: "m" }

  const DEFAULT_LAYERS = [
    { id: "layer_facility", name: "Facility & Grid", visible: true, locked: false, opacity: 1.0, z_index: 10, color: "#64748b" },
    { id: "layer_pitches", name: "Pitches & Line", visible: true, locked: false, opacity: 1.0, z_index: 20, color: "#1976d2" },
    { id: "layer_workers", name: "Workers & Ergonomics", visible: true, locked: false, opacity: 1.0, z_index: 30, color: "#00897b" },
    { id: "layer_screens", name: "Screens, HMI & Andon", visible: true, locked: false, opacity: 1.0, z_index: 40, color: "#f57c00" },
    { id: "layer_info", name: "Information Flow", visible: true, locked: false, opacity: 1.0, z_index: 50, color: "#7b1fa2" },
    { id: "layer_material", name: "Material Flow & Racks", visible: true, locked: false, opacity: 1.0, z_index: 60, color: "#e64a19" },
    { id: "layer_notes", name: "Dimensions & Callouts", visible: true, locked: false, opacity: 1.0, z_index: 70, color: "#455a64" }
  ]

  // Crisp black-and-white outline SVG icons for the Lucidchart Shape Library Drawer
  const STENCIL_CATEGORIES = [
    {
      id: "primitives",
      title: "Simple Primitives & Lines",
      items: [
        { stype: "rectangle", title: "Rectangle", svg: `<rect x="3" y="5" width="18" height="14" rx="1"/>` },
        { stype: "square", title: "Square", svg: `<rect x="4" y="4" width="16" height="16" rx="1"/>` },
        { stype: "rounded_rect", title: "Rounded Rectangle", svg: `<rect x="3" y="5" width="18" height="14" rx="4"/>` },
        { stype: "pill", title: "Pill / Capsule", svg: `<rect x="2" y="6" width="20" height="12" rx="6"/>` },
        { stype: "circle", title: "Circle / Oval", svg: `<circle cx="12" cy="12" r="8"/>` },
        { stype: "semicircle", title: "Half-Circle / Semicircle", svg: `<path d="M4 16a8 8 0 0 1 16 0Z"/>` },
        { stype: "quarter_circle", title: "Quarter-Circle / Sector", svg: `<path d="M5 19V5a14 14 0 0 1 14 14Z"/>` },
        { stype: "arc_line", title: "Half-Circle Arc Line (Combine with Circle for Pins)", svg: `<path d="M4 15a8 8 0 0 1 16 0" fill="none"/>` },
        { stype: "line", title: "Straight Line Segment", svg: `<line x1="3" y1="12" x2="21" y2="12"/><circle cx="4" cy="12" r="1.5"/><circle cx="20" cy="12" r="1.5"/>` },
        { stype: "triangle", title: "Triangle", svg: `<polygon points="12,4 21,19 3,19"/>` },
        { stype: "right_triangle", title: "Right Triangle", svg: `<polygon points="4,4 20,19 4,19"/>` },
        { stype: "diamond", title: "Diamond", svg: `<polygon points="12,3 21,12 12,21 3,12"/>` },
        { stype: "pentagon", title: "Pentagon", svg: `<polygon points="12,3 21,9.5 17.5,20 6.5,20 3,9.5"/>` },
        { stype: "hexagon", title: "Hexagon", svg: `<polygon points="7,4 17,4 22,12 17,20 7,20 2,12"/>` },
        { stype: "octagon", title: "Octagon", svg: `<polygon points="8,3 16,3 21,8 21,16 16,21 8,21 3,16 3,8"/>` },
        { stype: "trapezoid", title: "Trapezoid", svg: `<polygon points="6,5 18,5 21,19 3,19"/>` },
        { stype: "parallelogram", title: "Parallelogram", svg: `<polygon points="7,5 21,5 17,19 3,19"/>` },
        { stype: "l_shape", title: "L-Shape Footprint", svg: `<polygon points="4,4 11,4 11,13 20,13 20,20 4,20"/>` },
        { stype: "t_shape", title: "T-Shape Footprint", svg: `<polygon points="3,4 21,4 21,10 15,10 15,20 9,20 9,10 3,10"/>` },
        { stype: "u_shape", title: "U-Shape Cell Footprint", svg: `<polygon points="3,4 8,4 8,14 16,14 16,4 21,4 21,20 3,20"/>` },
        { stype: "cross", title: "Cross / Plus", svg: `<polygon points="9,3 15,3 15,9 21,9 21,15 15,15 15,21 9,21 9,15 3,15 3,9 9,9"/>` },
        { stype: "star", title: "Star / Kaizen Burst", svg: `<polygon points="12,2 14.8,8.5 22,9.2 16.5,14 18.2,21 12,17.3 5.8,21 7.5,14 2,9.2 9.2,8.5"/>` },
        { stype: "arrow_block", title: "Block Arrow / Chevron", svg: `<polygon points="3,7 14,7 14,4 21,12 14,20 14,17 3,17"/>` },
        { stype: "cylinder", title: "Cylinder / Tank", svg: `<ellipse cx="12" cy="6" rx="7" ry="2.5"/><path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6"/>` },
        { stype: "document", title: "Document", svg: `<path d="M4 4h16v13c-4 3-8-2-16 1V4z"/>` },
        { stype: "callout", title: "Sticky Note / Callout", svg: `<path d="M4 4h16v12H9l-5 4V4z"/>` },
        { stype: "text", title: "Text Label", svg: `<path d="M5 6h14M12 6v13M8 19h8"/>` },
        { stype: "dimension", title: "Dimension Line", svg: `<path d="M3 7v10M21 7v10M3 12h18M6 9l-3 3 3 3M18 9l3 3-3 3"/>` }
      ]
    },
    {
      id: "manufacturing",
      title: "Pin Map & Line Stencils",
      items: [
        { stype: "area_header", title: "Area Header Badge (e.g. 374 | PEDESTAL + Pills)", svg: `<rect x="2" y="4" width="20" height="10" rx="1"/><line x1="8" y1="4" x2="8" y2="14"/><rect x="3" y="16" width="8" height="4" rx="1"/><rect x="13" y="16" width="8" height="4" rx="1"/>` },
        { stype: "pitch_box", title: "Pitch Slot / Station (001–013)", svg: `<rect x="4" y="3" width="16" height="18" rx="1"/><line x1="4" y1="17" x2="20" y2="17"/>` },
        { stype: "conveyor", title: "Straight Roller Conveyor", svg: `<rect x="2" y="7" width="20" height="10"/><line x1="7" y1="7" x2="7" y2="17"/><line x1="12" y1="7" x2="12" y2="17"/><line x1="17" y1="7" x2="17" y2="17"/>` },
        { stype: "conveyor_curve", title: "90° Curved Roller Turn", svg: `<path d="M4 20V14A10 10 0 0 1 14 4h6v6h-6a4 4 0 0 0-4 4v6Z"/><line x1="7" y1="14" x2="11" y2="14"/><line x1="14" y1="7" x2="14" y2="11"/>` },
        { stype: "x_box", title: "Crossed Box (X-Box / Pallet / Rack)", svg: `<rect x="3" y="4" width="18" height="16"/><line x1="3" y1="4" x2="21" y2="20"/><line x1="21" y1="4" x2="3" y2="20"/>` },
        { stype: "worker", title: "Operator / Worker (Top-Down)", svg: `<ellipse cx="12" cy="12" rx="7" ry="5"/><circle cx="12" cy="12" r="3"/><polygon points="22,12 18,9.5 18,14.5"/>` },
        { stype: "turntable", title: "Turntable / Indexer", svg: `<circle cx="12" cy="12" r="8"/><path d="M12 7a5 5 0 1 1-4.3 2.5"/>` },
        { stype: "quality_gate", title: "Quality Buyoff Gate", svg: `<polygon points="12,3 21,12 12,21 3,12"/><path d="M8.5 12l2.5 2.5 4.5-5"/>` },
        { stype: "screen", title: "HMI / Andon Display Screen", svg: `<rect x="3" y="6" width="18" height="10" rx="1"/><line x1="8" y1="19" x2="16" y2="19"/><line x1="12" y1="16" x2="12" y2="19"/>` },
        { stype: "scanner", title: "Barcode / Vision Scanner", svg: `<rect x="4" y="6" width="16" height="12" rx="2"/><circle cx="12" cy="12" r="3"/>` },
        { stype: "computer_kiosk", title: "MES / Torque Controller", svg: `<rect x="5" y="4" width="14" height="16" rx="1"/><line x1="8" y1="8" x2="16" y2="8"/><circle cx="12" cy="14" r="2"/>` },
        { stype: "rack", title: "Lineside Flow Rack", svg: `<rect x="3" y="6" width="18" height="12"/><line x1="9" y1="6" x2="9" y2="18"/><line x1="15" y1="6" x2="15" y2="18"/><line x1="3" y1="12" x2="21" y2="12"/>` },
        { stype: "supermarket", title: "Supermarket Staging Bay", svg: `<rect x="2" y="5" width="20" height="14"/><line x1="7" y1="5" x2="7" y2="19"/><line x1="12" y1="5" x2="12" y2="19"/><line x1="17" y1="5" x2="17" y2="19"/><line x1="2" y1="12" x2="22" y2="12"/>` },
        { stype: "pallet", title: "Pallet / Skid", svg: `<rect x="4" y="4" width="16" height="16"/><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/>` },
        { stype: "agv", title: "AGV / Tugger Vehicle", svg: `<rect x="3" y="6" width="18" height="12" rx="3"/><circle cx="7" cy="6" r="1.5"/><circle cx="17" cy="6" r="1.5"/><circle cx="7" cy="18" r="1.5"/><circle cx="17" cy="18" r="1.5"/>` },
        { stype: "mat_flow", title: "Material Route Arrow", svg: `<path d="M3 12h16"/><polyline points="14,7 19,12 14,17"/>` },
        { stype: "info_flow", title: "Information Signal Arrow", svg: `<path d="M3 16l7-7 4 4 7-7" stroke-dasharray="2,2"/><polyline points="16,6 21,6 21,11"/>` },
        { stype: "frame", title: "Area Frame / Container", svg: `<rect x="2" y="4" width="20" height="16" rx="1"/><line x1="2" y1="8" x2="22" y2="8"/>` },
        { stype: "swimlane_h", title: "Horizontal Swimlane", svg: `<rect x="2" y="4" width="20" height="16"/><line x1="6" y1="4" x2="6" y2="20"/><line x1="2" y1="12" x2="22" y2="12"/>` },
        { stype: "swimlane_v", title: "Vertical Swimlane", svg: `<rect x="2" y="4" width="20" height="16"/><line x1="2" y1="8" x2="22" y2="8"/><line x1="12" y1="4" x2="12" y2="20"/>` },
        { stype: "safety_zone", title: "Safety / Keep-Out Zone", svg: `<rect x="3" y="5" width="18" height="14" stroke-dasharray="3,2"/><line x1="5" y1="19" x2="19" y2="5"/>` }
      ]
    }
  ]

  // Persistent Interactive State across Streamlit reruns
  if (!root.__lcState) {
    root.__lcState = {
      initialized: false,
      lastDataSig: "",
      shapes: [],
      shapeMap: new Map(),
      layers: [],
      activeLayerId: "",
      pitches: [],
      pitchMetrics: {},
      sectionStandards: {},
      customStencils: [],
      pages: [],
      activePageId: "",
      pageTitle: "Page 1",
      selectedIds: new Set(),
      hoveredId: null,
      hoveredPort: null,
      tool: "select",
      polygonDraft: [],
      drawerOpen: false,
      emptyDismissed: false,
      collapsedCats: {},
      overlayMode: "clean",
      showPitchChain: true,
      showRulers: true,
      showGrid: true,
      autoLayer: true,
      snapStepUnits: "1",
      camX: 48,
      camY: 36,
      zoom: 1.0,
      imageWidth: 2400,
      imageHeight: 1200,
      scalePxPerInX: 1.0,
      scalePxPerInY: 1.0,
      unit: "feet",
      isBlankCanvas: true,
      bgImageUrl: "",
      bgImage: null,
      spatialGrid: new Map(),
      gridCellSize: 160,
      undoStack: [],
      redoStack: [],
      clipboard: [],
      unsaved: false,
      interaction: null,
      mouseWorldX: 0,
      mouseWorldY: 0,
      mouseScreenX: 0,
      mouseScreenY: 0,
      spaceDown: false,
      guideLines: [],
      measureLine: null,
      calibLine: null,
      needsRender: false,
      rafId: 0,
      hasFittedStage: false,
      autoSaveTimer: null,
      activeModalShapeId: null,
      lastTapTime: 0,
      lastTapShapeId: null,
      lastTapScreenX: 0,
      lastTapScreenY: 0
    }
  }
  const st = root.__lcState
  if (st.rafId) {
    cancelAnimationFrame(st.rafId)
    st.rafId = 0
  }
  st.needsRender = false

  function uid() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID()
    return "s_" + Math.random().toString(36).slice(2, 11) + "_" + Date.now().toString(36)
  }

  function unitAbbr() { return UNIT_ABBR[st.unit] || "ft" }
  function unitIn() { return UNIT_TO_IN[st.unit] || 12.0 }
  function pxToUnitsX(px) { return px / (st.scalePxPerInX * unitIn()) }
  function pxToUnitsY(py) { return py / (st.scalePxPerInY * unitIn()) }
  function unitsToPxX(u) { return u * st.scalePxPerInX * unitIn() }
  function unitsToPxY(u) { return u * st.scalePxPerInY * unitIn() }

  function parseStyle(shape) {
    if (!shape) return {}
    if (shape._styleObj) return shape._styleObj
    let raw = shape.style_json
    if (!raw) { shape._styleObj = {}; return shape._styleObj }
    if (typeof raw === "object") { shape._styleObj = { ...raw }; return shape._styleObj }
    try { shape._styleObj = JSON.parse(raw) || {} } catch (_) { shape._styleObj = {} }
    return shape._styleObj
  }

  function syncStyleJson(shape) {
    if (!shape) return
    const obj = parseStyle(shape)
    shape.style_json = JSON.stringify(obj)
  }

  function normalizeLayer(l, idx = 0) {
    return {
      id: String(l.id || ("layer_" + idx)),
      name: String(l.name || ("Layer " + (idx + 1))),
      visible: l.visible === undefined ? true : Boolean(l.visible),
      locked: Boolean(l.locked),
      opacity: Number(l.opacity !== undefined ? l.opacity : 1.0),
      z_index: Number(l.z_index !== undefined ? l.z_index : (idx + 1) * 10),
      color: String(l.color || "#1976d2")
    }
  }

  function normalizeShape(raw, idx = 0) {
    const s = {
      id: String(raw.id || uid()),
      revision_id: String(raw.revision_id || ""),
      layer_id: raw.layer_id ? String(raw.layer_id) : "",
      shape_type: String(raw.shape_type || "rectangle"),
      x: Number(raw.x || 0),
      y: Number(raw.y || 0),
      width: Math.max(4, Number(raw.width || 60)),
      height: Math.max(4, Number(raw.height || 40)),
      rotation: Number(raw.rotation || 0),
      z_index: Number(raw.z_index !== undefined ? raw.z_index : (idx + 1) * 10),
      group_id: String(raw.group_id || ""),
      locked: Boolean(raw.locked),
      source_shape_id: raw.source_shape_id ? String(raw.source_shape_id) : null,
      target_shape_id: raw.target_shape_id ? String(raw.target_shape_id) : null,
      color: String(raw.color || "#1e293b"),
      label: String(raw.label || ""),
      pitch_id: raw.pitch_id ? String(raw.pitch_id) : null,
      equipment_id: raw.equipment_id ? String(raw.equipment_id) : null,
      style_json: raw.style_json || "{}"
    }
    parseStyle(s)
    if (!s.layer_id && st.layers.length > 0) {
      s.layer_id = inferLayerForShape(s.shape_type, Boolean(s.pitch_id))
    }
    updateShapeBounds(s)
    return s
  }

  function inferLayerForShape(shapeType, hasPitch) {
    if (!st.autoLayer && st.activeLayerId) return st.activeLayerId
    const byKeyword = (kw) => {
      const found = st.layers.find(l => l.name.toLowerCase().includes(kw))
      return found ? found.id : (st.activeLayerId || (st.layers[0]?.id || ""))
    }
    if (hasPitch || ["pitch_box", "conveyor", "turntable", "quality_gate"].includes(shapeType)) return byKeyword("pitch")
    if (shapeType === "worker") return byKeyword("worker")
    if (["screen", "scanner", "computer_kiosk"].includes(shapeType)) return byKeyword("screen")
    if (shapeType === "connector" || shapeType === "info_flow") return byKeyword("info")
    if (["rack", "supermarket", "pallet", "agv", "mat_flow"].includes(shapeType)) return byKeyword("material")
    if (["callout", "text", "dimension"].includes(shapeType)) return byKeyword("dimension")
    return st.activeLayerId || (st.layers[0]?.id || "")
  }

  function rotatePointAround(px, py, cx, cy, deg) {
    if (!deg) return { x: px, y: py }
    const rad = (deg * Math.PI) / 180
    const cos = Math.cos(rad), sin = Math.sin(rad)
    const dx = px - cx, dy = py - cy
    return { x: cx + dx * cos - dy * sin, y: cy + dx * sin + dy * cos }
  }

  function getShapePorts(s) {
    if (!s || s.shape_type === "connector") return []
    const x = s.x, y = s.y, w = s.width, h = s.height
    const cx = x + w / 2, cy = y + h / 2
    const rot = Number(s.rotation || 0)
    const raw = [
      { port: "N", x: cx, y: y },
      { port: "E", x: x + w, y: cy },
      { port: "S", x: cx, y: y + h },
      { port: "W", x: x, y: cy }
    ]
    if (!rot) return raw
    return raw.map(p => {
      const rp = rotatePointAround(p.x, p.y, cx, cy, rot)
      return { port: p.port, x: rp.x, y: rp.y }
    })
  }

  function getConnectorEndpoints(s) {
    const style = parseStyle(s)
    let x1 = Number(style.x1 !== undefined ? style.x1 : s.x)
    let y1 = Number(style.y1 !== undefined ? style.y1 : s.y + s.height / 2)
    let x2 = Number(style.x2 !== undefined ? style.x2 : s.x + s.width)
    let y2 = Number(style.y2 !== undefined ? style.y2 : s.y + s.height / 2)

    if (s.source_shape_id && st.shapeMap.has(s.source_shape_id)) {
      const src = st.shapeMap.get(s.source_shape_id)
      const ports = getShapePorts(src)
      const sp = ports.find(p => p.port === (style.source_port || "E")) || ports[1]
      if (sp) { x1 = sp.x; y1 = sp.y }
    }
    if (s.target_shape_id && st.shapeMap.has(s.target_shape_id)) {
      const tgt = st.shapeMap.get(s.target_shape_id)
      const ports = getShapePorts(tgt)
      const tp = ports.find(p => p.port === (style.target_port || "W")) || ports[3]
      if (tp) { x2 = tp.x; y2 = tp.y }
    }
    return { x1, y1, x2, y2 }
  }

  function saveConnectorEndpoints(s, x1, y1, x2, y2) {
    const style = parseStyle(s)
    style.x1 = Number(x1.toFixed(2))
    style.y1 = Number(y1.toFixed(2))
    style.x2 = Number(x2.toFixed(2))
    style.y2 = Number(y2.toFixed(2))
    s.x = Math.min(style.x1, style.x2)
    s.y = Math.min(style.y1, style.y2)
    s.width = Math.max(8, Math.abs(style.x2 - style.x1))
    s.height = Math.max(8, Math.abs(style.y2 - style.y1))
    syncStyleJson(s)
    updateShapeBounds(s)
  }

  function updateShapeBounds(s) {
    if (s.shape_type === "connector") {
      const pts = getConnectorEndpoints(s)
      s._minX = Math.min(pts.x1, pts.x2) - 8
      s._minY = Math.min(pts.y1, pts.y2) - 8
      s._maxX = Math.max(pts.x1, pts.x2) + 8
      s._maxY = Math.max(pts.y1, pts.y2) + 8
    } else if (s.rotation) {
      const cx = s.x + s.width / 2, cy = s.y + s.height / 2
      const corners = [
        rotatePointAround(s.x, s.y, cx, cy, s.rotation),
        rotatePointAround(s.x + s.width, s.y, cx, cy, s.rotation),
        rotatePointAround(s.x + s.width, s.y + s.height, cx, cy, s.rotation),
        rotatePointAround(s.x, s.y + s.height, cx, cy, s.rotation)
      ]
      s._minX = Math.min(...corners.map(c => c.x))
      s._minY = Math.min(...corners.map(c => c.y))
      s._maxX = Math.max(...corners.map(c => c.x))
      s._maxY = Math.max(...corners.map(c => c.y))
    } else {
      s._minX = s.x
      s._minY = s.y
      s._maxX = s.x + s.width
      s._maxY = s.y + s.height
    }
  }

  // Uniform Spatial Hash Grid for 20,000+ shapes
  function rebuildSpatialIndex() {
    st.spatialGrid.clear()
    st.shapeMap.clear()
    const cs = st.gridCellSize
    for (let i = 0; i < st.shapes.length; i++) {
      const s = st.shapes[i]
      st.shapeMap.set(s.id, s)
    }
    for (let i = 0; i < st.shapes.length; i++) {
      const s = st.shapes[i]
      updateShapeBounds(s)
      const c0 = Math.floor(s._minX / cs)
      const c1 = Math.floor(s._maxX / cs)
      const r0 = Math.floor(s._minY / cs)
      const r1 = Math.floor(s._maxY / cs)
      for (let r = r0; r <= r1; r++) {
        for (let c = c0; c <= c1; c++) {
          const key = c + "," + r
          let bucket = st.spatialGrid.get(key)
          if (!bucket) {
            bucket = []
            st.spatialGrid.set(key, bucket)
          }
          bucket.push(s)
        }
      }
    }
  }

  function querySpatialBox(minX, minY, maxX, maxY) {
    const cs = st.gridCellSize
    const c0 = Math.floor(minX / cs)
    const c1 = Math.floor(maxX / cs)
    const r0 = Math.floor(minY / cs)
    const r1 = Math.floor(maxY / cs)
    if ((c1 - c0 + 1) * (r1 - r0 + 1) > 900) return st.shapes
    const seen = new Set()
    const out = []
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        const bucket = st.spatialGrid.get(c + "," + r)
        if (!bucket) continue
        for (let i = 0; i < bucket.length; i++) {
          const s = bucket[i]
          if (!seen.has(s.id)) {
            seen.add(s.id)
            if (s._maxX >= minX && s._minX <= maxX && s._maxY >= minY && s._minY <= maxY) {
              out.push(s)
            }
          }
        }
      }
    }
    return out
  }

  function getLayerMap() {
    const m = new Map()
    for (let i = 0; i < st.layers.length; i++) m.set(st.layers[i].id, st.layers[i])
    return m
  }

  function isShapeVisible(s, layerMap) {
    const l = layerMap.get(s.layer_id)
    return l ? Boolean(l.visible) : true
  }

  function isLayerLocked(s, layerMap) {
    if (!s) return false
    const l = layerMap ? layerMap.get(s.layer_id) : st.layers.find(ly => ly.id === s.layer_id)
    return l ? Boolean(l.locked) : false
  }

  function isShapeLocked(s, layerMap) {
    if (!s) return false
    if (s.locked) return true
    return isLayerLocked(s, layerMap)
  }

  function isAnyModalOpen() {
    const modals = ["#lc-shape-props-modal", "#lc-custom-stencil-modal", "#lc-calib-modal", "#lc-array-modal"]
    return modals.some(sel => {
      const el = parentElement.querySelector(sel)
      return el && el.style.display === "flex"
    })
  }

  function scheduleAutoSave() {
    if (st.autoSaveTimer) clearTimeout(st.autoSaveTimer)
    if (st.shapes.length > 5000) return
    st.autoSaveTimer = setTimeout(() => {
      st.autoSaveTimer = null
      if (!st.unsaved || st.interaction || isAnyModalOpen()) {
        if (st.unsaved) scheduleAutoSave()
        return
      }
      const ae = document.activeElement
      if (ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.tagName === "SELECT")) {
        scheduleAutoSave()
        return
      }
      commitCanvasToPython({ action: "save" })
    }, 3500)
  }

  function markUnsaved() {
    st.unsaved = true
    const pill = parentElement.querySelector("#lc-save-pill")
    const btn = parentElement.querySelector("#lc-btn-save")
    if (pill) { pill.textContent = "● Unsaved"; pill.className = "lc-save-pill unsaved" }
    if (btn) { btn.classList.add("unsaved") }
    updateEmptyCardVisibility()
    scheduleAutoSave()
  }

  function markSynced() {
    st.unsaved = false
    if (st.autoSaveTimer) {
      clearTimeout(st.autoSaveTimer)
      st.autoSaveTimer = null
    }
    const pill = parentElement.querySelector("#lc-save-pill")
    const btn = parentElement.querySelector("#lc-btn-save")
    if (pill) { pill.textContent = "● Saved"; pill.className = "lc-save-pill saved" }
    if (btn) { btn.classList.remove("unsaved") }
  }

  function updateEmptyCardVisibility() {
    if (!emptyCard) return
    const hasBg = !st.isBlankCanvas && Boolean(st.bgImageUrl || st.bgImage)
    emptyCard.style.display = (st.shapes.length === 0 && !hasBg && !st.emptyDismissed) ? "block" : "none"
  }

  function buildUndoSnapshot() {
    const shapesSnap = st.shapes.map(s => {
      syncStyleJson(s)
      return { ...s, _styleObj: undefined }
    })
    const layersSnap = (st.layers || []).map(l => ({ ...l }))
    return JSON.stringify({
      shapes: shapesSnap,
      layers: layersSnap,
      activeLayerId: st.activeLayerId || ""
    })
  }

  function applyUndoSnapshot(rawSnap) {
    const parsed = JSON.parse(rawSnap)
    const shapeArr = Array.isArray(parsed) ? parsed : (parsed.shapes || [])
    if (!Array.isArray(parsed) && Array.isArray(parsed.layers) && parsed.layers.length > 0) {
      st.layers = parsed.layers.map((l, i) => normalizeLayer(l, i))
      if (parsed.activeLayerId && st.layers.some(l => l.id === parsed.activeLayerId)) {
        st.activeLayerId = parsed.activeLayerId
      } else {
        st.activeLayerId = st.layers[0].id
      }
    }
    st.shapes = shapeArr.map((r, i) => normalizeShape(r, i))
    const validIds = new Set(st.shapes.map(s => s.id))
    st.selectedIds.forEach(id => {
      if (!validIds.has(id)) st.selectedIds.delete(id)
    })
  }

  function pushUndo() {
    if (st.shapes.length > 6000) return
    st.undoStack.push(buildUndoSnapshot())
    if (st.undoStack.length > 35) st.undoStack.shift()
    st.redoStack = []
    updateUndoRedoButtons()
  }

  function updateUndoRedoButtons() {
    const uBtn = parentElement.querySelector("#lc-btn-undo")
    const rBtn = parentElement.querySelector("#lc-btn-redo")
    if (uBtn) uBtn.disabled = st.undoStack.length === 0
    if (rBtn) rBtn.disabled = st.redoStack.length === 0
  }

  function performUndo() {
    if (!st.undoStack.length) return
    st.redoStack.push(buildUndoSnapshot())
    applyUndoSnapshot(st.undoStack.pop())
    rebuildSpatialIndex()
    renderShapeDrawer()
    renderLayerList()
    updateContextualToolbar()
    markUnsaved()
    updateUndoRedoButtons()
    requestRender()
  }

  function performRedo() {
    if (!st.redoStack.length) return
    st.undoStack.push(buildUndoSnapshot())
    applyUndoSnapshot(st.redoStack.pop())
    rebuildSpatialIndex()
    renderShapeDrawer()
    renderLayerList()
    updateContextualToolbar()
    markUnsaved()
    updateUndoRedoButtons()
    requestRender()
  }

  function buildShapesDigest(arr) {
    return (arr || [])
      .map(s => `${s.id}:${Math.round(Number(s.x || 0))}:${Math.round(Number(s.y || 0))}:${Math.round(Number(s.width || 0))}:${Math.round(Number(s.height || 0))}:${Math.round(Number(s.rotation || 0))}:${s.label || ""}:${s.color || ""}:${typeof s.style_json === "string" ? s.style_json : JSON.stringify(s.style_json || {})}`)
      .sort()
      .join("|")
  }

  // Ingest incoming props from Streamlit
  const rawImgUrl = String(data?.imageUrl || "")
  const incomingSig = JSON.stringify({
    pageId: data?.activePageId || "",
    blank: Boolean(data?.isBlankCanvas),
    urlLen: rawImgUrl.length,
    urlTail: rawImgUrl.length > 64 ? rawImgUrl.slice(-64) : rawImgUrl,
    w: data?.imageWidth || 2400,
    h: data?.imageHeight || 1200,
    sx: data?.scalePxPerInX || data?.scalePxPerIn || 1.0,
    sy: data?.scalePxPerInY || data?.scalePxPerIn || 1.0,
    u: data?.unit || "feet",
    scLen: (data?.shapes || []).length,
    shapesDigest: buildShapesDigest(data?.shapes),
    layersSig: (data?.layers || []).map(l => `${l.id}:${l.name}:${l.visible ? 1 : 0}:${l.locked ? 1 : 0}:${l.z_index || 0}`).join("|"),
    pagesLen: (data?.pages || []).length,
    customLen: (data?.customStencils || []).length
  })

  if (!st.initialized || (incomingSig !== st.lastDataSig && !st.unsaved && !isAnyModalOpen())) {
    const pageSwitched = st.activePageId !== String(data?.activePageId || "")
    st.lastDataSig = incomingSig
    st.activePageId = String(data?.activePageId || "")
    st.pageTitle = String(data?.pageTitle || "Page 1")
    st.pages = Array.isArray(data?.pages) ? data.pages : []
    st.imageWidth = Math.max(100, Number(data?.imageWidth || 2400))
    st.imageHeight = Math.max(100, Number(data?.imageHeight || 1200))
    st.scalePxPerInX = Math.max(0.001, Number(data?.scalePxPerInX || data?.scalePxPerIn || 1.0))
    st.scalePxPerInY = Math.max(0.001, Number(data?.scalePxPerInY || data?.scalePxPerIn || 1.0))
    st.unit = String(data?.unit || "feet")
    st.isBlankCanvas = Boolean(data?.isBlankCanvas)
    st.pitches = Array.isArray(data?.pitches) ? data.pitches : []
    st.pitchMetrics = data?.pitch_metrics || {}
    st.sectionStandards = data?.section_standards || {}
    st.customStencils = Array.isArray(data?.customStencils) ? data.customStencils : []

    const titleEl = parentElement.querySelector("#lc-page-title")
    if (titleEl) titleEl.value = st.pageTitle
    const swEl = parentElement.querySelector("#lc-scale-w")
    const shEl = parentElement.querySelector("#lc-scale-h")
    const suEl = parentElement.querySelector("#lc-scale-unit")
    if (swEl) swEl.value = Number(pxToUnitsX(st.imageWidth).toFixed(1))
    if (shEl) shEl.value = Number(pxToUnitsY(st.imageHeight).toFixed(1))
    if (suEl) suEl.value = st.unit

    const rawLayers = Array.isArray(data?.layers) && data.layers.length > 0 ? data.layers : DEFAULT_LAYERS
    st.layers = rawLayers.map((l, idx) => normalizeLayer(l, idx))
    if (!st.activeLayerId || !st.layers.some(l => l.id === st.activeLayerId)) {
      const pitchLayer = st.layers.find(l => l.name.toLowerCase().includes("pitch")) || st.layers[0]
      st.activeLayerId = pitchLayer ? pitchLayer.id : ""
    }

    const rawShapes = Array.isArray(data?.shapes) ? data.shapes : []
    st.shapes = rawShapes.map((r, i) => normalizeShape(r, i))
    rebuildSpatialIndex()

    if (data?.selectedShapeId) {
      st.selectedIds.clear()
      st.selectedIds.add(String(data.selectedShapeId))
    } else if (pageSwitched) {
      st.selectedIds.clear()
    }

    const newUrl = st.isBlankCanvas ? "" : String(data?.imageUrl || "")
    if (newUrl !== st.bgImageUrl || (newUrl && !st.bgImage)) {
      st.bgImageUrl = newUrl
      if (newUrl) {
        st.emptyDismissed = true
        window.__paagBgImageCache = window.__paagBgImageCache || new Map()
        if (window.__paagBgImageCache.has(newUrl)) {
          st.bgImage = window.__paagBgImageCache.get(newUrl)
        } else {
          const img = new Image()
          img.onload = () => {
            window.__paagBgImageCache.set(newUrl, img)
            st.bgImage = img
            updateEmptyCardVisibility()
            renderFrame()
            requestRender()
          }
          img.src = newUrl
        }
      } else {
        st.bgImage = null
      }
    }

    if (!st.initialized || pageSwitched) {
      st.initialized = true
      st.hasFittedStage = false
      setTimeout(() => fitCanvasToStage(), 40)
    }
  } else {
    if (Array.isArray(data?.pitches)) st.pitches = data.pitches
    if (data?.pitch_metrics) st.pitchMetrics = data.pitch_metrics
    if (data?.section_standards) st.sectionStandards = data.section_standards
    if (Array.isArray(data?.pages)) st.pages = data.pages
    if (Array.isArray(data?.customStencils)) st.customStencils = data.customStencils
  }

  rulerCorner.textContent = unitAbbr()
  parentElement.querySelectorAll(".lc-unit-txt").forEach(el => { el.textContent = unitAbbr() })
  updateEmptyCardVisibility()

  function screenToWorld(sx, sy) {
    return { x: (sx - st.camX) / st.zoom, y: (sy - st.camY) / st.zoom }
  }

  function getSnapStepWorldPx() {
    if (st.snapStepUnits === "0") return { x: 0, y: 0 }
    let stepU = 1.0
    if (st.snapStepUnits === "auto") {
      const pxPerUnit = unitsToPxX(1) * st.zoom
      if (pxPerUnit > 80) stepU = 0.5
      else if (pxPerUnit > 25) stepU = 1.0
      else if (pxPerUnit > 8) stepU = 5.0
      else stepU = 10.0
    } else {
      stepU = Math.max(0.1, Number(st.snapStepUnits) || 1.0)
    }
    return { x: unitsToPxX(stepU), y: unitsToPxY(stepU), stepU }
  }

  function snapWorldCoord(wx, wy) {
    const step = getSnapStepWorldPx()
    if (!step.x || !step.y) return { x: wx, y: wy }
    return {
      x: Math.round(wx / step.x) * step.x,
      y: Math.round(wy / step.y) * step.y
    }
  }

  function fitCanvasToStage() {
    const rect = stage.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    st.hasFittedStage = true
    const leftPad = st.drawerOpen ? 310 : 64
    const availW = Math.max(200, rect.width - leftPad - 28)
    const availH = Math.max(150, rect.height - 48)
    const zx = availW / Math.max(100, st.imageWidth)
    const zy = availH / Math.max(100, st.imageHeight)
    st.zoom = Math.max(0.05, Math.min(4.0, Math.min(zx, zy)))
    st.camX = leftPad + (availW - st.imageWidth * st.zoom) / 2
    st.camY = (rect.height - st.imageHeight * st.zoom) / 2
    renderFrame()
    requestRender()
  }

  function zoomAroundPoint(factor, sx, sy) {
    const rect = mainCanvas.getBoundingClientRect()
    const cx = sx !== undefined ? sx : (rect.width || 800) / 2
    const cy = sy !== undefined ? sy : (rect.height || 600) / 2
    const nextZoom = Math.max(0.04, Math.min(10.0, st.zoom * factor))
    st.camX = cx - ((cx - st.camX) / st.zoom) * nextZoom
    st.camY = cy - ((cy - st.camY) / st.zoom) * nextZoom
    st.zoom = nextZoom
    requestRender()
  }

  function requestRender() {
    if (!st.needsRender) {
      st.needsRender = true
      st.rafId = requestAnimationFrame(() => {
        st.needsRender = false
        st.rafId = 0
        renderFrame()
      })
    }
  }

  // Hit-testing from top Z to bottom Z using spatial grid
  function hitTestWorld(wx, wy) {
    const candidates = querySpatialBox(wx - 8, wy - 8, wx + 8, wy + 8)
    if (!candidates.length) return null
    const layerMap = getLayerMap()
    const layerOrder = new Map()
    st.layers.forEach((l, idx) => layerOrder.set(l.id, Number(l.z_index || idx * 10)))

    candidates.sort((a, b) => {
      const la = layerOrder.get(a.layer_id) || 0
      const lb = layerOrder.get(b.layer_id) || 0
      if (la !== lb) return lb - la
      return (b.z_index || 0) - (a.z_index || 0)
    })

    for (let i = 0; i < candidates.length; i++) {
      const s = candidates[i]
      if (!isShapeVisible(s, layerMap)) continue
      if (isLayerLocked(s, layerMap)) continue
      if (s.shape_type === "connector") {
        const pts = getConnectorEndpoints(s)
        const dist = pointToSegmentDist(wx, wy, pts.x1, pts.y1, pts.x2, pts.y2)
        if (dist <= 10 / st.zoom) return s
      } else {
        if (isWorldPointInsideShape(s, wx, wy, true)) {
          return s
        }
      }
    }
    return null
  }

  function findNearestPort(wx, wy, excludeShapeId) {
    const radius = 18 / st.zoom
    const candidates = querySpatialBox(wx - radius, wy - radius, wx + radius, wy + radius)
    const layerMap = getLayerMap()
    let best = null
    let bestD = radius
    for (let i = 0; i < candidates.length; i++) {
      const s = candidates[i]
      if (s.id === excludeShapeId || s.shape_type === "connector") continue
      if (!isShapeVisible(s, layerMap)) continue
      const ports = getShapePorts(s)
      for (let p of ports) {
        const d = Math.hypot(wx - p.x, wy - p.y)
        if (d < bestD) {
          bestD = d
          best = { shapeId: s.id, port: p.port, x: p.x, y: p.y }
        }
      }
    }
    return best
  }

  function pointToSegmentDist(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1, dy = y2 - y1
    const lenSq = dx * dx + dy * dy
    if (lenSq < 0.0001) return Math.hypot(px - x1, py - y1)
    const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lenSq))
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
  }

  function getSelectionHandles(s) {
    if (!s || isShapeLocked(s, getLayerMap())) return []
    if (s.shape_type === "connector") {
      const pts = getConnectorEndpoints(s)
      return [
        { id: "p1", x: pts.x1, y: pts.y1 },
        { id: "p2", x: pts.x2, y: pts.y2 }
      ]
    }
    const x = s.x, y = s.y, w = s.width, h = s.height
    const cx = x + w / 2, cy = y + h / 2
    const rot = Number(s.rotation || 0)
    const rotOffset = 20 / st.zoom
    const raw = [
      { id: "nw",  x: x, y: y },
      { id: "n",   x: cx, y: y },
      { id: "ne",  x: x + w, y: y },
      { id: "e",   x: x + w, y: cy },
      { id: "se",  x: x + w, y: y + h },
      { id: "s",   x: cx, y: y + h },
      { id: "sw",  x: x, y: y + h },
      { id: "w",   x: x, y: cy },
      { id: "rot", x: cx, y: y - rotOffset }
    ]
    if (!rot) return raw
    return raw.map(h => {
      const rp = rotatePointAround(h.x, h.y, cx, cy, rot)
      return { id: h.id, x: rp.x, y: rp.y }
    })
  }

  function hitTestHandle(wx, wy) {
    if (st.selectedIds.size !== 1) return null
    const selId = Array.from(st.selectedIds)[0]
    const s = st.shapeMap.get(selId)
    if (!s || isShapeLocked(s, getLayerMap())) return null
    const tol = 9 / st.zoom
    const handles = getSelectionHandles(s)
    for (let h of handles) {
      if (Math.abs(wx - h.x) <= tol && Math.abs(wy - h.y) <= tol) {
        return { shape: s, handle: h.id }
      }
    }
    return null
  }

  // Rulers Renderer (Lucidchart Clean Light Gray Rulers)
  function renderRulers(stageW, stageH, dpr) {
    if (!st.showRulers) return

    const tw = stageW, th = 22
    if (rulerTop.width !== Math.floor(tw * dpr) || rulerTop.height !== Math.floor(th * dpr)) {
      rulerTop.width = Math.floor(tw * dpr)
      rulerTop.height = Math.floor(th * dpr)
    }
    const tctx = rulerTop.getContext("2d")
    tctx.save()
    tctx.scale(dpr, dpr)
    tctx.fillStyle = "#f9fafb"
    tctx.fillRect(0, 0, tw, th)

    const pxPerUnitX = unitsToPxX(1) * st.zoom
    let majorStepU = 1
    if (pxPerUnitX < 2) majorStepU = 100
    else if (pxPerUnitX < 5) majorStepU = 50
    else if (pxPerUnitX < 12) majorStepU = 20
    else if (pxPerUnitX < 25) majorStepU = 10
    else if (pxPerUnitX < 60) majorStepU = 5
    else if (pxPerUnitX < 140) majorStepU = 1
    else majorStepU = 0.5

    const minorStepU = majorStepU / 5
    const startU = Math.floor(pxToUnitsX(-st.camX / st.zoom) / minorStepU) * minorStepU
    const endU = Math.ceil(pxToUnitsX((tw - st.camX) / st.zoom) / minorStepU) * minorStepU

    tctx.strokeStyle = "#cbd5e1"
    tctx.fillStyle = "#64748b"
    tctx.font = "500 9px sans-serif"
    tctx.beginPath()
    for (let u = startU; u <= endU; u += minorStepU) {
      const wx = unitsToPxX(u)
      const sx = wx * st.zoom + st.camX
      if (sx < 0 || sx > tw) continue
      const isMajor = Math.abs(Math.round(u / majorStepU) * majorStepU - u) < 0.001
      tctx.moveTo(sx, isMajor ? 3 : 14)
      tctx.lineTo(sx, th)
      if (isMajor) {
        tctx.fillText(Number(u.toFixed(1)) + " " + unitAbbr(), sx + 3, 11)
      }
    }
    tctx.stroke()

    const curSx = st.mouseWorldX * st.zoom + st.camX
    tctx.strokeStyle = "#2563eb"
    tctx.lineWidth = 1.2
    tctx.beginPath()
    tctx.moveTo(curSx, 0); tctx.lineTo(curSx, th)
    tctx.stroke()
    tctx.restore()

    // Left Vertical Ruler
    const lw = 24, lh = stageH
    if (rulerLeft.width !== Math.floor(lw * dpr) || rulerLeft.height !== Math.floor(lh * dpr)) {
      rulerLeft.width = Math.floor(lw * dpr)
      rulerLeft.height = Math.floor(lh * dpr)
    }
    const lctx = rulerLeft.getContext("2d")
    lctx.save()
    lctx.scale(dpr, dpr)
    lctx.fillStyle = "#f9fafb"
    lctx.fillRect(0, 0, lw, lh)

    const startUY = Math.floor(pxToUnitsY(-st.camY / st.zoom) / minorStepU) * minorStepU
    const endUY = Math.ceil(pxToUnitsY((lh - st.camY) / st.zoom) / minorStepU) * minorStepU

    lctx.strokeStyle = "#cbd5e1"
    lctx.fillStyle = "#64748b"
    lctx.font = "500 9px sans-serif"
    lctx.beginPath()
    for (let u = startUY; u <= endUY; u += minorStepU) {
      const wy = unitsToPxY(u)
      const sy = wy * st.zoom + st.camY
      if (sy < 0 || sy > lh) continue
      const isMajor = Math.abs(Math.round(u / majorStepU) * majorStepU - u) < 0.001
      lctx.moveTo(isMajor ? 3 : 15, sy)
      lctx.lineTo(lw, sy)
      if (isMajor) {
        lctx.save()
        lctx.translate(10, sy - 3)
        lctx.rotate(-Math.PI / 2)
        lctx.fillText(Number(u.toFixed(1)), 0, 0)
        lctx.restore()
      }
    }
    lctx.stroke()

    const curSy = st.mouseWorldY * st.zoom + st.camY
    lctx.strokeStyle = "#2563eb"
    lctx.lineWidth = 1.2
    lctx.beginPath()
    lctx.moveTo(0, curSy); lctx.lineTo(lw, curSy)
    lctx.stroke()
    lctx.restore()
  }

  // Main 2D Canvas Frame Renderer
  function renderFrame() {
    st.needsRender = false
    const rect = stage.getBoundingClientRect()
    const w = Math.max(100, rect.width)
    const h = Math.max(100, rect.height)
    const dpr = window.devicePixelRatio || 1

    if (mainCanvas.width !== Math.floor(w * dpr) || mainCanvas.height !== Math.floor(h * dpr)) {
      mainCanvas.width = Math.floor(w * dpr)
      mainCanvas.height = Math.floor(h * dpr)
    }

    renderRulers(w, h, dpr)

    const ctx = mainCanvas.getContext("2d")
    ctx.save()
    ctx.scale(dpr, dpr)

    // Lucidchart soft gray surround
    ctx.fillStyle = "#e5e7eb"
    ctx.fillRect(0, 0, w, h)

    ctx.save()
    ctx.translate(st.camX, st.camY)
    ctx.scale(st.zoom, st.zoom)

    // Subtle page drop shadow + crisp white canvas sheet
    ctx.save()
    ctx.shadowColor = "rgba(15, 23, 42, 0.10)"
    ctx.shadowBlur = 16 / st.zoom
    ctx.shadowOffsetY = 4 / st.zoom
    ctx.fillStyle = "#ffffff"
    ctx.fillRect(0, 0, st.imageWidth, st.imageHeight)
    ctx.restore()

    // Draw uploaded CAD / Floorplan image if present
    const layerMap = getLayerMap()
    const facLayer = st.layers.find(l => l.name.toLowerCase().includes("facility"))
    const facVisible = facLayer ? facLayer.visible : true
    const facOpacity = facLayer ? Number(facLayer.opacity ?? 1.0) : 1.0

    if (st.bgImage && facVisible && !st.isBlankCanvas) {
      ctx.save()
      ctx.globalAlpha = facOpacity
      ctx.drawImage(st.bgImage, 0, 0, st.imageWidth, st.imageHeight)
      ctx.restore()
    }

    // Crisp Lucidchart Vector Scaled Gridlines
    if (st.showGrid && facVisible) {
      const pxPerUnitX = unitsToPxX(1) * st.zoom
      let majorU = 1
      if (pxPerUnitX < 2) majorU = 100
      else if (pxPerUnitX < 5) majorU = 50
      else if (pxPerUnitX < 12) majorU = 20
      else if (pxPerUnitX < 25) majorU = 10
      else if (pxPerUnitX < 60) majorU = 5
      else majorU = 1
      const minorU = majorU / 5

      const stepMinorX = unitsToPxX(minorU)
      const stepMinorY = unitsToPxY(minorU)
      const stepMajorX = unitsToPxX(majorU)
      const stepMajorY = unitsToPxY(majorU)

      if (stepMinorX * st.zoom >= 7) {
        ctx.strokeStyle = "rgba(203, 213, 225, 0.45)"
        ctx.lineWidth = 1 / st.zoom
        ctx.beginPath()
        for (let x = 0; x <= st.imageWidth; x += stepMinorX) {
          ctx.moveTo(x, 0); ctx.lineTo(x, st.imageHeight)
        }
        for (let y = 0; y <= st.imageHeight; y += stepMinorY) {
          ctx.moveTo(0, y); ctx.lineTo(st.imageWidth, y)
        }
        ctx.stroke()
      }

      ctx.strokeStyle = "rgba(148, 163, 184, 0.55)"
      ctx.lineWidth = 1 / st.zoom
      ctx.beginPath()
      for (let x = 0; x <= st.imageWidth; x += stepMajorX) {
        ctx.moveTo(x, 0); ctx.lineTo(x, st.imageHeight)
      }
      for (let y = 0; y <= st.imageHeight; y += stepMajorY) {
        ctx.moveTo(0, y); ctx.lineTo(st.imageWidth, y)
      }
      ctx.stroke()
    }

    // Crisp page border
    ctx.strokeStyle = "#cbd5e1"
    ctx.lineWidth = 1 / st.zoom
    ctx.strokeRect(0, 0, st.imageWidth, st.imageHeight)

    // Frustum culling bounds in world coordinates
    const viewMinX = -st.camX / st.zoom - 60
    const viewMinY = -st.camY / st.zoom - 60
    const viewMaxX = (w - st.camX) / st.zoom + 60
    const viewMaxY = (h - st.camY) / st.zoom + 60

    const visibleShapes = querySpatialBox(viewMinX, viewMinY, viewMaxX, viewMaxY)
    const layerOrder = new Map()
    st.layers.forEach((l, idx) => layerOrder.set(l.id, Number(l.z_index || idx * 10)))

    visibleShapes.sort((a, b) => {
      const la = layerOrder.get(a.layer_id) || 0
      const lb = layerOrder.get(b.layer_id) || 0
      if (la !== lb) return la - lb
      return (a.z_index || 0) - (b.z_index || 0)
    })

    const fastLod = st.zoom < 0.22 || visibleShapes.length > 3500

    if (st.showPitchChain && !fastLod) {
      drawPitchSequenceChain(ctx, layerMap)
    }

    let renderedCount = 0
    for (let i = 0; i < visibleShapes.length; i++) {
      const s = visibleShapes[i]
      const layer = layerMap.get(s.layer_id)
      if (layer && !layer.visible) continue
      const layerAlpha = layer ? Number(layer.opacity ?? 1.0) : 1.0
      drawShapeOnCanvas(ctx, s, layerAlpha, fastLod)
      renderedCount++
    }

    // Hover ports for smart connector attachment
    if (st.hoveredId && st.shapeMap.has(st.hoveredId) && !fastLod) {
      const hs = st.shapeMap.get(st.hoveredId)
      const ports = getShapePorts(hs)
      for (let p of ports) {
        const isTarget = st.hoveredPort && st.hoveredPort.shapeId === hs.id && st.hoveredPort.port === p.port
        ctx.fillStyle = isTarget ? "#16a34a" : "#ffffff"
        ctx.strokeStyle = isTarget ? "#15803d" : "#2563eb"
        ctx.lineWidth = 2 / st.zoom
        ctx.beginPath()
        ctx.arc(p.x, p.y, (isTarget ? 6 : 4.5) / st.zoom, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()
      }
    }

    // Selection handles + Rotation handle for single selected shape
    if (st.selectedIds.size === 1) {
      const selId = Array.from(st.selectedIds)[0]
      const sel = st.shapeMap.get(selId)
      if (sel) {
        const handles = getSelectionHandles(sel)
        const hs = 7 / st.zoom
        ctx.strokeStyle = "#2563eb"
        ctx.lineWidth = 1.5 / st.zoom
        const rotH = handles.find(h => h.id === "rot")
        const nH = handles.find(h => h.id === "n")
        if (rotH && nH) {
          ctx.beginPath()
          ctx.moveTo(nH.x, nH.y)
          ctx.lineTo(rotH.x, rotH.y)
          ctx.stroke()
        }
        for (let hdl of handles) {
          if (hdl.id === "rot" || hdl.id === "p1" || hdl.id === "p2") {
            ctx.fillStyle = hdl.id === "rot" ? "#dcfce7" : "#dbeafe"
            ctx.strokeStyle = hdl.id === "rot" ? "#16a34a" : "#2563eb"
            ctx.beginPath()
            ctx.arc(hdl.x, hdl.y, 5 / st.zoom, 0, Math.PI * 2)
            ctx.fill()
            ctx.stroke()
          } else {
            ctx.fillStyle = "#ffffff"
            ctx.strokeStyle = "#2563eb"
            ctx.fillRect(hdl.x - hs / 2, hdl.y - hs / 2, hs, hs)
            ctx.strokeRect(hdl.x - hs / 2, hdl.y - hs / 2, hs, hs)
          }
        }
      }
    }

    // Active Point-by-Point Polygon Draft Preview
    if (st.tool === "polygon" && st.polygonDraft.length > 0) {
      ctx.save()
      ctx.strokeStyle = "#ea580c"
      ctx.fillStyle = "rgba(254, 215, 170, 0.35)"
      ctx.lineWidth = 2 / st.zoom
      ctx.beginPath()
      st.polygonDraft.forEach((pt, idx) => {
        const px = Array.isArray(pt) ? pt[0] : pt.x
        const py = Array.isArray(pt) ? pt[1] : pt.y
        if (idx === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      })
      const snapCur = snapWorldCoord(st.mouseWorldX, st.mouseWorldY)
      ctx.lineTo(snapCur.x, snapCur.y)
      if (st.polygonDraft.length >= 2) {
        ctx.fill()
      }
      ctx.stroke()
      for (let pt of st.polygonDraft) {
        const px = Array.isArray(pt) ? pt[0] : pt.x
        const py = Array.isArray(pt) ? pt[1] : pt.y
        ctx.fillStyle = "#ffffff"
        ctx.strokeStyle = "#ea580c"
        ctx.beginPath()
        ctx.arc(px, py, 4.5 / st.zoom, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()
      }
      ctx.restore()
    }

    // Smart alignment guides during drag
    if (st.guideLines.length > 0) {
      ctx.save()
      ctx.strokeStyle = "#ec4899"
      ctx.lineWidth = 1.2 / st.zoom
      ctx.setLineDash([5 / st.zoom, 4 / st.zoom])
      ctx.beginPath()
      for (let g of st.guideLines) {
        if (g.type === "v") { ctx.moveTo(g.pos, viewMinY); ctx.lineTo(g.pos, viewMaxY) }
        else { ctx.moveTo(viewMinX, g.pos); ctx.lineTo(viewMaxX, g.pos) }
      }
      ctx.stroke()
      ctx.restore()
    }

    // Marquee selection box
    if (st.interaction && st.interaction.mode === "marquee") {
      const ix = Math.min(st.interaction.startWorldX, st.mouseWorldX)
      const iy = Math.min(st.interaction.startWorldY, st.mouseWorldY)
      const iw = Math.abs(st.mouseWorldX - st.interaction.startWorldX)
      const ih = Math.abs(st.mouseWorldY - st.interaction.startWorldY)
      ctx.fillStyle = "rgba(37, 99, 235, 0.10)"
      ctx.strokeStyle = "#2563eb"
      ctx.lineWidth = 1.5 / st.zoom
      ctx.fillRect(ix, iy, iw, ih)
      ctx.strokeRect(ix, iy, iw, ih)
    }

    // Active connector preview
    if (st.interaction && st.interaction.mode === "draw_connector") {
      ctx.save()
      ctx.strokeStyle = "#2563eb"
      ctx.lineWidth = 2 / st.zoom
      ctx.setLineDash([6 / st.zoom, 4 / st.zoom])
      ctx.beginPath()
      ctx.moveTo(st.interaction.startWorldX, st.interaction.startWorldY)
      ctx.lineTo(st.mouseWorldX, st.mouseWorldY)
      ctx.stroke()
      ctx.restore()
    }

    // Tape Measure or Scale Calibration Line
    const activeLine = st.measureLine || st.calibLine
    if (activeLine) {
      const isCalib = Boolean(st.calibLine)
      ctx.save()
      ctx.strokeStyle = isCalib ? "#dc2626" : "#0284c7"
      ctx.lineWidth = 2.2 / st.zoom
      ctx.beginPath()
      ctx.moveTo(activeLine.x1, activeLine.y1)
      ctx.lineTo(activeLine.x2, activeLine.y2)
      ctx.stroke()

      const dxU = pxToUnitsX(activeLine.x2 - activeLine.x1)
      const dyU = pxToUnitsY(activeLine.y2 - activeLine.y1)
      const distU = Math.hypot(dxU, dyU)
      const midX = (activeLine.x1 + activeLine.x2) / 2
      const midY = (activeLine.y1 + activeLine.y2) / 2
      const lbl = (isCalib ? "Calibrate: " : "Measure: ") + distU.toFixed(2) + " " + unitAbbr()
      ctx.font = `bold ${Math.max(10, 12 / st.zoom)}px sans-serif`
      const tw = ctx.measureText(lbl).width + 12 / st.zoom
      const th = 20 / st.zoom
      ctx.fillStyle = isCalib ? "#fef2f2" : "#f0f9ff"
      ctx.fillRect(midX - tw / 2, midY - th / 2, tw, th)
      ctx.strokeRect(midX - tw / 2, midY - th / 2, tw, th)
      ctx.fillStyle = isCalib ? "#991b1b" : "#0369a1"
      ctx.textAlign = "center"
      ctx.textBaseline = "middle"
      ctx.fillText(lbl, midX, midY)
      ctx.restore()
    }

    ctx.restore()
    ctx.restore()

    // Bottom bar readouts (Print Scale + Shape Count + Zoom)
    const psEl = parentElement.querySelector("#lc-print-scale")
    if (psEl) {
      const pxPerU = Math.max(0.001, unitsToPxX(1) * st.zoom)
      const unitsPerThreeIn = (288 / pxPerU)
      psEl.textContent = `Print scale: 3 in = ${unitsPerThreeIn >= 10 ? Math.round(unitsPerThreeIn) : unitsPerThreeIn.toFixed(1)} ${unitAbbr()}`
    }
    const cntEl = parentElement.querySelector("#lc-status-counts")
    if (cntEl) {
      cntEl.textContent = st.shapes.length > 500
        ? `${st.shapes.length.toLocaleString()} shapes (${renderedCount.toLocaleString()} in view)`
        : `${st.shapes.length.toLocaleString()} shape${st.shapes.length === 1 ? "" : "s"}`
    }
    const zoomEl = parentElement.querySelector("#lc-zoom-readout")
    if (zoomEl) zoomEl.textContent = Math.round(st.zoom * 100) + "%"

    // Auto-appearing "Return to Grid" floating button when scrolled off or nearly off the grid
    const retBtn = parentElement.querySelector("#lc-return-grid-btn")
    if (retBtn) {
      const leftPad = st.drawerOpen ? 310 : 54
      const sheetLeft = st.camX
      const sheetTop = st.camY
      const sheetRight = st.camX + st.imageWidth * st.zoom
      const sheetBottom = st.camY + st.imageHeight * st.zoom
      const visLeft = Math.max(leftPad, sheetLeft)
      const visTop = Math.max(0, sheetTop)
      const visRight = Math.min(w, sheetRight)
      const visBottom = Math.min(h, sheetBottom)
      const overlapW = Math.max(0, visRight - visLeft)
      const overlapH = Math.max(0, visBottom - visTop)
      const isOffGrid = overlapW < 90 || overlapH < 90
      if (isOffGrid) {
        const gridCx = (sheetLeft + sheetRight) / 2
        const gridCy = (sheetTop + sheetBottom) / 2
        const viewCx = (leftPad + w) / 2
        const viewCy = h / 2
        const dx = gridCx - viewCx
        const dy = gridCy - viewCy
        const angle = Math.atan2(dy, dx) * (180 / Math.PI)
        let arrow = "⌖"
        if (angle >= -22.5 && angle < 22.5) arrow = "→"
        else if (angle >= 22.5 && angle < 67.5) arrow = "↘"
        else if (angle >= 67.5 && angle < 112.5) arrow = "↓"
        else if (angle >= 112.5 && angle < 157.5) arrow = "↙"
        else if (angle >= 157.5 || angle < -157.5) arrow = "←"
        else if (angle >= -157.5 && angle < -112.5) arrow = "↖"
        else if (angle >= -112.5 && angle < -67.5) arrow = "↑"
        else if (angle >= -67.5 && angle < -22.5) arrow = "↗"
        retBtn.textContent = `${arrow} Return to Grid (Home)`
        retBtn.style.display = "inline-flex"
      } else {
        retBtn.style.display = "none"
      }
    }
  }

  function drawPitchSequenceChain(ctx, layerMap) {
    const pitchShapeByPitchId = new Map()
    for (let i = 0; i < st.shapes.length; i++) {
      const s = st.shapes[i]
      if (s.pitch_id && isShapeVisible(s, layerMap)) {
        pitchShapeByPitchId.set(s.pitch_id, s)
        const aliasPid = st.pitchMetrics[s.pitch_id]?.pitch_id
        if (aliasPid && !pitchShapeByPitchId.has(String(aliasPid))) {
          pitchShapeByPitchId.set(String(aliasPid), s)
        }
      }
    }
    if (pitchShapeByPitchId.size < 2) return

    ctx.save()
    ctx.strokeStyle = "rgba(37, 99, 235, 0.5)"
    ctx.fillStyle = "rgba(37, 99, 235, 0.7)"
    ctx.lineWidth = 2 / st.zoom
    ctx.setLineDash([6 / st.zoom, 4 / st.zoom])

    const drawnSrcIds = new Set()
    pitchShapeByPitchId.forEach((srcShape, pid) => {
      if (drawnSrcIds.has(srcShape.id)) return
      drawnSrcIds.add(srcShape.id)
      const m = st.pitchMetrics[pid]
      const nextPid = m ? m.feeds_into_pitch_id : null
      if (!nextPid || !pitchShapeByPitchId.has(nextPid)) return
      const tgtShape = pitchShapeByPitchId.get(nextPid)
      const x1 = srcShape.x + srcShape.width / 2
      const y1 = srcShape.y + srcShape.height / 2
      const x2 = tgtShape.x + tgtShape.width / 2
      const y2 = tgtShape.y + tgtShape.height / 2
      ctx.beginPath()
      ctx.moveTo(x1, y1); ctx.lineTo(x2, y2)
      ctx.stroke()

      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2
      const ang = Math.atan2(y2 - y1, x2 - x1)
      const ah = 7 / st.zoom
      ctx.save()
      ctx.setLineDash([])
      ctx.translate(mx, my)
      ctx.rotate(ang)
      ctx.beginPath()
      ctx.moveTo(ah, 0); ctx.lineTo(-ah, -ah * 0.65); ctx.lineTo(-ah, ah * 0.65)
      ctx.closePath()
      ctx.fill()
      ctx.restore()
    })
    ctx.restore()
  }

  function drawShapeOnCanvas(ctx, s, layerAlpha, fastLod) {
    const style = parseStyle(s)
    const isSelected = st.selectedIds.has(s.id)
    let strokeColor = style.stroke_color || s.color || "#1e293b"
    let fillColor = style.fill_color || "#ffffff"
    let fillOpacity = Number(style.fill_opacity !== undefined ? style.fill_opacity : 0.90)
    const strokeWidth = Number(style.stroke_width || 2)
    const strokeStyle = style.stroke_style || "solid"

    const pMetric = s.pitch_id ? st.pitchMetrics[s.pitch_id] : null
    if (pMetric && st.overlayMode === "heatmap") {
      const util = Number(pMetric.utilization_pct || 0)
      if (pMetric.pitch_status === "Open" || pMetric.pitch_status === "Blocked") {
        strokeColor = "#64748b"; fillColor = "#e2e8f0"; fillOpacity = 0.7
      } else if (util > 100.0) {
        strokeColor = "#b91c1c"; fillColor = "#fecaca"; fillOpacity = 0.8
      } else if (util >= 85.0) {
        strokeColor = "#d97706"; fillColor = "#fde68a"; fillOpacity = 0.8
      } else if (util > 0) {
        strokeColor = "#15803d"; fillColor = "#bbf7d0"; fillOpacity = 0.8
      }
    } else if (pMetric && st.overlayMode === "status") {
      if (pMetric.pitch_status === "Blocked") {
        strokeColor = "#b91c1c"; fillColor = "#fee2e2"
      } else if (pMetric.pitch_status === "Open") {
        strokeColor = "#64748b"; fillColor = "#f1f5f9"
      }
    }

    ctx.save()
    ctx.globalAlpha = layerAlpha

    if (s.shape_type === "connector") {
      drawConnectorShape(ctx, s, style, strokeColor, strokeWidth, strokeStyle, isSelected, fastLod)
      ctx.restore()
      return
    }

    const cx = s.x + s.width / 2
    const cy = s.y + s.height / 2
    if (s.rotation) {
      ctx.translate(cx, cy)
      ctx.rotate((s.rotation * Math.PI) / 180)
      ctx.translate(-cx, -cy)
    }

    if (strokeStyle === "dashed") ctx.setLineDash([6, 4])
    else if (strokeStyle === "dotted") ctx.setLineDash([2, 3])

    const stype = s.shape_type

    // Fast LOD path for zoomed-out 20K shape view
    if (fastLod) {
      ctx.fillStyle = fillColor
      ctx.globalAlpha = layerAlpha * Math.max(0.5, fillOpacity)
      ctx.fillRect(s.x, s.y, s.width, s.height)
      ctx.globalAlpha = layerAlpha
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = 1 / st.zoom
      ctx.strokeRect(s.x, s.y, s.width, s.height)
      ctx.restore()
      return
    }

    const fillAndStroke = () => {
      if (fillOpacity > 0.005) {
        ctx.fillStyle = fillColor
        ctx.globalAlpha = layerAlpha * fillOpacity
        ctx.fill()
      }
      ctx.globalAlpha = layerAlpha
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = strokeWidth
      ctx.stroke()
    }

    if (stype === "circle" || stype === "turntable") {
      ctx.beginPath()
      ctx.ellipse(cx, cy, s.width / 2, s.height / 2, 0, 0, Math.PI * 2)
      fillAndStroke()
      if (stype === "turntable") {
        ctx.beginPath()
        ctx.arc(cx, cy, Math.min(s.width, s.height) * 0.28, 0, Math.PI * 1.5)
        ctx.stroke()
      }
    } else if (stype === "semicircle") {
      ctx.beginPath()
      ctx.ellipse(cx, s.y + s.height, s.width / 2, s.height, 0, Math.PI, 0, false)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "quarter_circle") {
      ctx.beginPath()
      ctx.moveTo(s.x, s.y + s.height)
      ctx.lineTo(s.x, s.y)
      ctx.ellipse(s.x, s.y + s.height, s.width, s.height, 0, -Math.PI / 2, 0, false)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "arc_line") {
      ctx.beginPath()
      ctx.ellipse(cx, s.y + s.height * 0.85, s.width / 2, s.height * 0.75, 0, Math.PI, 0, false)
      ctx.globalAlpha = layerAlpha
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = strokeWidth
      ctx.stroke()
    } else if (stype === "line") {
      ctx.beginPath()
      ctx.moveTo(s.x, cy)
      ctx.lineTo(s.x + s.width, cy)
      ctx.globalAlpha = layerAlpha
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = strokeWidth
      ctx.stroke()
    } else if (stype === "rounded_rect" || stype === "pill") {
      const r = stype === "pill"
        ? Math.min(s.width, s.height) / 2
        : Math.min(12, s.width * 0.2, s.height * 0.2)
      ctx.beginPath()
      if (ctx.roundRect) ctx.roundRect(s.x, s.y, s.width, s.height, r)
      else ctx.rect(s.x, s.y, s.width, s.height)
      fillAndStroke()
    } else if (stype === "diamond" || stype === "quality_gate") {
      ctx.beginPath()
      ctx.moveTo(cx, s.y); ctx.lineTo(s.x + s.width, cy); ctx.lineTo(cx, s.y + s.height); ctx.lineTo(s.x, cy)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "triangle") {
      ctx.beginPath()
      ctx.moveTo(cx, s.y); ctx.lineTo(s.x + s.width, s.y + s.height); ctx.lineTo(s.x, s.y + s.height)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "right_triangle") {
      ctx.beginPath()
      ctx.moveTo(s.x, s.y); ctx.lineTo(s.x + s.width, s.y + s.height); ctx.lineTo(s.x, s.y + s.height)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "pentagon") {
      ctx.beginPath()
      ctx.moveTo(cx, s.y)
      ctx.lineTo(s.x + s.width, s.y + s.height * 0.38)
      ctx.lineTo(s.x + s.width * 0.81, s.y + s.height)
      ctx.lineTo(s.x + s.width * 0.19, s.y + s.height)
      ctx.lineTo(s.x, s.y + s.height * 0.38)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "hexagon") {
      const dx = s.width * 0.2
      ctx.beginPath()
      ctx.moveTo(s.x + dx, s.y); ctx.lineTo(s.x + s.width - dx, s.y); ctx.lineTo(s.x + s.width, cy)
      ctx.lineTo(s.x + s.width - dx, s.y + s.height); ctx.lineTo(s.x + dx, s.y + s.height); ctx.lineTo(s.x, cy)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "octagon") {
      const dx = s.width * 0.28, dy = s.height * 0.28
      ctx.beginPath()
      ctx.moveTo(s.x + dx, s.y)
      ctx.lineTo(s.x + s.width - dx, s.y)
      ctx.lineTo(s.x + s.width, s.y + dy)
      ctx.lineTo(s.x + s.width, s.y + s.height - dy)
      ctx.lineTo(s.x + s.width - dx, s.y + s.height)
      ctx.lineTo(s.x + dx, s.y + s.height)
      ctx.lineTo(s.x, s.y + s.height - dy)
      ctx.lineTo(s.x, s.y + dy)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "trapezoid") {
      const dx = s.width * 0.18
      ctx.beginPath()
      ctx.moveTo(s.x + dx, s.y); ctx.lineTo(s.x + s.width - dx, s.y)
      ctx.lineTo(s.x + s.width, s.y + s.height); ctx.lineTo(s.x, s.y + s.height)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "parallelogram") {
      const dx = s.width * 0.18
      ctx.beginPath()
      ctx.moveTo(s.x + dx, s.y); ctx.lineTo(s.x + s.width, s.y)
      ctx.lineTo(s.x + s.width - dx, s.y + s.height); ctx.lineTo(s.x, s.y + s.height)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "l_shape") {
      const aw = s.width * 0.42, ah = s.height * 0.42
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(s.x + aw, s.y)
      ctx.lineTo(s.x + aw, s.y + s.height - ah)
      ctx.lineTo(s.x + s.width, s.y + s.height - ah)
      ctx.lineTo(s.x + s.width, s.y + s.height)
      ctx.lineTo(s.x, s.y + s.height)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "t_shape") {
      const stemW = s.width * 0.36, barH = s.height * 0.36
      const sx1 = cx - stemW / 2, sx2 = cx + stemW / 2
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(s.x + s.width, s.y)
      ctx.lineTo(s.x + s.width, s.y + barH)
      ctx.lineTo(sx2, s.y + barH)
      ctx.lineTo(sx2, s.y + s.height)
      ctx.lineTo(sx1, s.y + s.height)
      ctx.lineTo(sx1, s.y + barH)
      ctx.lineTo(s.x, s.y + barH)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "u_shape") {
      const wallW = s.width * 0.28, baseH = s.height * 0.32
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(s.x + wallW, s.y)
      ctx.lineTo(s.x + wallW, s.y + s.height - baseH)
      ctx.lineTo(s.x + s.width - wallW, s.y + s.height - baseH)
      ctx.lineTo(s.x + s.width - wallW, s.y)
      ctx.lineTo(s.x + s.width, s.y)
      ctx.lineTo(s.x + s.width, s.y + s.height)
      ctx.lineTo(s.x, s.y + s.height)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "x_box") {
      ctx.beginPath()
      ctx.rect(s.x, s.y, s.width, s.height)
      fillAndStroke()
      ctx.beginPath()
      ctx.moveTo(s.x, s.y); ctx.lineTo(s.x + s.width, s.y + s.height)
      ctx.moveTo(s.x + s.width, s.y); ctx.lineTo(s.x, s.y + s.height)
      ctx.stroke()
    } else if (stype === "conveyor_curve") {
      ctx.beginPath()
      ctx.moveTo(s.x, s.y + s.height)
      ctx.lineTo(s.x, s.y)
      ctx.ellipse(s.x, s.y + s.height, s.width, s.height, 0, -Math.PI / 2, 0, false)
      ctx.closePath()
      fillAndStroke()
      ctx.save()
      ctx.strokeStyle = "rgba(71, 85, 105, 0.45)"
      ctx.lineWidth = 1
      ctx.beginPath()
      for (let a = 0.25; a < 1.4; a += 0.32) {
        const ang = -a
        ctx.moveTo(s.x + Math.cos(ang) * (s.width * 0.25), s.y + s.height + Math.sin(ang) * (s.height * 0.25))
        ctx.lineTo(s.x + Math.cos(ang) * (s.width * 0.95), s.y + s.height + Math.sin(ang) * (s.height * 0.95))
      }
      ctx.stroke()
      ctx.restore()
    } else if (stype === "area_header") {
      // Industrial Pin Map Area Header Banner (e.g. "374 | PEDESTAL" + "STANDARD WORK" / "YAMAZUMI" pills)
      const r = Math.min(8, s.height * 0.18)
      ctx.beginPath()
      if (ctx.roundRect) ctx.roundRect(s.x, s.y, s.width, s.height, r)
      else ctx.rect(s.x, s.y, s.width, s.height)
      fillAndStroke()

      const codeBoxW = Math.min(s.width * 0.24, s.height * 1.45)
      ctx.beginPath()
      ctx.moveTo(s.x + codeBoxW, s.y)
      ctx.lineTo(s.x + codeBoxW, s.y + s.height)
      ctx.stroke()

      const areaCode = String(style.area_code || "374")
      const pillsRaw = String(style.area_pills !== undefined ? style.area_pills : "STANDARD WORK, YAMAZUMI")
      const pills = pillsRaw.split(",").map(p => p.trim()).filter(Boolean)

      ctx.fillStyle = style.font_color || "#0f172a"
      ctx.textAlign = "center"
      ctx.textBaseline = "middle"
      const codeFont = Math.max(9, Math.min(20, s.height * 0.42))
      ctx.font = `700 ${codeFont}px sans-serif`
      ctx.fillText(areaCode, s.x + codeBoxW / 2, cy, Math.max(12, codeBoxW - 6))

      const rightColW = pills.length > 0 ? Math.min(s.width * 0.34, 130) : 0
      const titleCenterX = s.x + codeBoxW + (s.width - codeBoxW - rightColW) / 2
      const titleFont = Math.max(10, Math.min(22, s.height * 0.44))
      ctx.font = `700 ${titleFont}px sans-serif`
      ctx.fillText(s.label || "PEDESTAL", titleCenterX, cy, Math.max(20, s.width - codeBoxW - rightColW - 10))

      if (pills.length > 0 && rightColW >= 40) {
        const pillH = Math.min(18, (s.height - 8) / Math.max(1, pills.length) - 2)
        const pillW = rightColW - 10
        const pillX = s.x + s.width - rightColW + 5
        pills.forEach((pText, idx) => {
          const py = s.y + 4 + idx * (pillH + 3)
          ctx.fillStyle = "#e2e8f0"
          ctx.strokeStyle = strokeColor
          ctx.lineWidth = 1.2
          ctx.beginPath()
          if (ctx.roundRect) ctx.roundRect(pillX, py, pillW, pillH, pillH / 2)
          else ctx.rect(pillX, py, pillW, pillH)
          ctx.fill()
          ctx.stroke()
          ctx.fillStyle = "#0f172a"
          ctx.font = `700 ${Math.max(6.5, Math.min(9.5, pillH * 0.58))}px sans-serif`
          ctx.fillText(pText, pillX + pillW / 2, py + pillH / 2, pillW - 6)
        })
      }
    } else if (stype === "custom_polygon" && Array.isArray(style.points) && style.points.length >= 3) {
      ctx.beginPath()
      style.points.forEach((pt, idx) => {
        const px = s.x + Number(pt[0] || 0) * s.width
        const py = s.y + Number(pt[1] || 0) * s.height
        if (idx === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      })
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "cylinder") {
      const ry = Math.min(14, s.height * 0.18)
      ctx.beginPath()
      ctx.moveTo(s.x, s.y + ry)
      ctx.lineTo(s.x, s.y + s.height - ry)
      ctx.ellipse(cx, s.y + s.height - ry, s.width / 2, ry, 0, Math.PI, 0, true)
      ctx.lineTo(s.x + s.width, s.y + ry)
      ctx.ellipse(cx, s.y + ry, s.width / 2, ry, 0, 0, Math.PI * 2)
      fillAndStroke()
    } else if (stype === "callout" || stype === "document") {
      const fold = Math.min(14, s.width * 0.22, s.height * 0.22)
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(s.x + s.width - fold, s.y)
      ctx.lineTo(s.x + s.width, s.y + fold)
      ctx.lineTo(s.x + s.width, s.y + s.height)
      ctx.lineTo(s.x, s.y + s.height)
      ctx.closePath()
      fillAndStroke()
      ctx.beginPath()
      ctx.moveTo(s.x + s.width - fold, s.y)
      ctx.lineTo(s.x + s.width - fold, s.y + fold)
      ctx.lineTo(s.x + s.width, s.y + fold)
      ctx.stroke()
    } else if (stype === "star") {
      const rx = s.width / 2, ry = s.height / 2
      ctx.beginPath()
      for (let i = 0; i < 10; i++) {
        const rad = i % 2 === 0 ? 1.0 : 0.45
        const ang = (i * Math.PI) / 5 - Math.PI / 2
        const px = cx + Math.cos(ang) * rx * rad
        const py = cy + Math.sin(ang) * ry * rad
        if (i === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      }
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "cross") {
      const armX = s.width * 0.32, armY = s.height * 0.32
      ctx.beginPath()
      ctx.moveTo(s.x + armX, s.y)
      ctx.lineTo(s.x + s.width - armX, s.y)
      ctx.lineTo(s.x + s.width - armX, s.y + armY)
      ctx.lineTo(s.x + s.width, s.y + armY)
      ctx.lineTo(s.x + s.width, s.y + s.height - armY)
      ctx.lineTo(s.x + s.width - armX, s.y + s.height - armY)
      ctx.lineTo(s.x + s.width - armX, s.y + s.height)
      ctx.lineTo(s.x + armX, s.y + s.height)
      ctx.lineTo(s.x + armX, s.y + s.height - armY)
      ctx.lineTo(s.x, s.y + s.height - armY)
      ctx.lineTo(s.x, s.y + armY)
      ctx.lineTo(s.x + armX, s.y + armY)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "arrow_block") {
      const headW = Math.min(s.width * 0.35, s.height * 0.9)
      const shaftDY = s.height * 0.22
      ctx.beginPath()
      ctx.moveTo(s.x, s.y + shaftDY)
      ctx.lineTo(s.x + s.width - headW, s.y + shaftDY)
      ctx.lineTo(s.x + s.width - headW, s.y)
      ctx.lineTo(s.x + s.width, cy)
      ctx.lineTo(s.x + s.width - headW, s.y + s.height)
      ctx.lineTo(s.x + s.width - headW, s.y + s.height - shaftDY)
      ctx.lineTo(s.x, s.y + s.height - shaftDY)
      ctx.closePath()
      fillAndStroke()
    } else if (stype === "worker") {
      const r = Math.min(s.width, s.height) / 2
      ctx.beginPath()
      ctx.ellipse(cx, cy, r * 0.9, r * 0.62, 0, 0, Math.PI * 2)
      fillAndStroke()
      ctx.beginPath()
      ctx.arc(cx, cy, r * 0.4, 0, Math.PI * 2)
      ctx.fillStyle = strokeColor
      ctx.fill()
      ctx.beginPath()
      ctx.moveTo(s.x + s.width + 3, cy)
      ctx.lineTo(s.x + s.width - r * 0.35, cy - r * 0.28)
      ctx.lineTo(s.x + s.width - r * 0.35, cy + r * 0.28)
      ctx.closePath()
      ctx.fill()
    } else if (stype === "screen" || stype === "scanner" || stype === "computer_kiosk") {
      ctx.fillStyle = "#1e293b"
      ctx.fillRect(s.x, s.y, s.width, s.height)
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = strokeWidth
      ctx.strokeRect(s.x, s.y, s.width, s.height)
      ctx.fillStyle = "#38bdf8"
      ctx.fillRect(s.x + 2, s.y + s.height - Math.max(3, s.height * 0.25), Math.max(2, s.width - 4), Math.max(2, s.height * 0.2))
    } else if (stype === "conveyor") {
      ctx.beginPath()
      ctx.rect(s.x, s.y, s.width, s.height)
      fillAndStroke()
      ctx.strokeStyle = "rgba(71, 85, 105, 0.45)"
      ctx.lineWidth = 1
      const step = Math.max(8, s.height * 0.35)
      ctx.beginPath()
      for (let rx = s.x + step; rx < s.x + s.width - 2; rx += step) {
        ctx.moveTo(rx, s.y + 2); ctx.lineTo(rx, s.y + s.height - 2)
      }
      ctx.stroke()
    } else if (stype === "rack" || stype === "supermarket") {
      ctx.beginPath()
      ctx.rect(s.x, s.y, s.width, s.height)
      fillAndStroke()
      const cols = stype === "supermarket" ? 4 : 3
      const cw = s.width / cols
      ctx.beginPath()
      for (let i = 1; i < cols; i++) {
        ctx.moveTo(s.x + i * cw, s.y); ctx.lineTo(s.x + i * cw, s.y + s.height)
      }
      ctx.moveTo(s.x, cy); ctx.lineTo(s.x + s.width, cy)
      ctx.stroke()
    } else if (stype === "frame" || stype === "swimlane_h" || stype === "swimlane_v") {
      ctx.beginPath()
      ctx.rect(s.x, s.y, s.width, s.height)
      fillAndStroke()
      const hdrH = Math.min(26, s.height * 0.2)
      ctx.fillStyle = "rgba(226, 232, 240, 0.7)"
      ctx.fillRect(s.x, s.y, s.width, hdrH)
      ctx.strokeRect(s.x, s.y, s.width, hdrH)
    } else if (stype === "dimension") {
      const ay = cy
      ctx.strokeStyle = strokeColor
      ctx.fillStyle = strokeColor
      ctx.lineWidth = strokeWidth
      ctx.beginPath()
      ctx.moveTo(s.x, s.y); ctx.lineTo(s.x, s.y + s.height)
      ctx.moveTo(s.x + s.width, s.y); ctx.lineTo(s.x + s.width, s.y + s.height)
      ctx.moveTo(s.x, ay); ctx.lineTo(s.x + s.width, ay)
      ctx.stroke()
    } else if (stype !== "text") {
      ctx.beginPath()
      ctx.rect(s.x, s.y, s.width, s.height)
      fillAndStroke()
    }

    if (pMetric && s.width >= 28 && s.height >= 18 && st.overlayMode !== "clean") {
      drawPitchOverlayBadges(ctx, s, pMetric)
    }

    let dispLabel = stype === "area_header" ? "" : (s.label || (pMetric ? pMetric.pitch_number : ""))
    if (stype === "dimension" && !style.custom_label) {
      const rad = ((s.rotation || 0) * Math.PI) / 180
      dispLabel = Math.hypot(Math.cos(rad) * pxToUnitsX(s.width), Math.sin(rad) * pxToUnitsY(s.width)).toFixed(2) + " " + unitAbbr()
    }
    if (dispLabel && s.width >= 10 && s.height >= 8) {
      const reqSize = Number(style.font_size || 12)
      const txtRot = Number(style.text_rotation || 0)
      const isVertTxt = Math.abs(txtRot) === 90
      const availSpan = isVertTxt ? s.width : s.height
      const maxLineSpan = isVertTxt ? s.height : s.width
      const lines = String(dispLabel).split("\n")
      const effSize = Math.max(6.5, Math.min(reqSize, (availSpan * 0.78) / Math.max(1, lines.length)))
      const weight = style.font_weight === "normal" ? "400" : "700"
      const align = style.text_align || "center"

      const isFrame = stype === "frame" || stype === "swimlane_h" || stype === "swimlane_v"
      const textY = isFrame
        ? s.y + Math.min(13, s.height * 0.1)
        : (pMetric && st.overlayMode !== "clean" && s.height >= 34 ? s.y + effSize * 0.85 + 2 : cy)

      ctx.save()
      ctx.translate(cx, textY)
      if (txtRot) {
        ctx.rotate((txtRot * Math.PI) / 180)
      }
      ctx.font = `${weight} ${effSize}px sans-serif`
      ctx.textAlign = align
      ctx.textBaseline = "middle"
      ctx.fillStyle = stype === "screen" ? "#f8fafc" : (style.font_color || "#0f172a")

      const lineH = effSize * 1.18
      const startOffsetY = -((lines.length - 1) * lineH) / 2
      const alignX = align === "left" ? -(maxLineSpan / 2 - 4) : (align === "right" ? (maxLineSpan / 2 - 4) : 0)
      for (let li = 0; li < lines.length; li++) {
        ctx.fillText(lines[li], alignX, startOffsetY + li * lineH, Math.max(8, maxLineSpan - 4))
      }
      ctx.restore()
    }

    if (isSelected) {
      ctx.setLineDash([])
      ctx.strokeStyle = "#2563eb"
      ctx.lineWidth = 2 / st.zoom
      ctx.strokeRect(s.x - 2 / st.zoom, s.y - 2 / st.zoom, s.width + 4 / st.zoom, s.height + 4 / st.zoom)
    }

    ctx.restore()
  }

  function drawPitchOverlayBadges(ctx, s, pm) {
    const util = Number(pm.utilization_pct || 0)
    const ct = Number(pm.cycle_time_sec || 0)
    const takt = Number(pm.target_takt_sec || 60)
    const ops = Number(pm.operator_count || 0)
    const steps = Number(pm.step_count || 0)

    if (s.height >= 26) {
      const barH = Math.min(6, Math.max(3, s.height * 0.14))
      const barY = s.y + s.height - barH - 2
      const barW = Math.max(8, s.width - 6)
      ctx.fillStyle = "rgba(15, 23, 42, 0.12)"
      ctx.fillRect(s.x + 3, barY, barW, barH)
      const fillRatio = Math.min(1.0, util / 100.0)
      ctx.fillStyle = util > 100 ? "#dc2626" : (util >= 85 ? "#d97706" : "#16a34a")
      ctx.fillRect(s.x + 3, barY, barW * fillRatio, barH)
    }

    if (s.height >= 38 && s.width >= 44) {
      const subFont = Math.max(6.5, Math.min(9.5, s.height * 0.2))
      ctx.font = `600 ${subFont}px sans-serif`
      ctx.fillStyle = "#334155"
      ctx.textAlign = "center"
      ctx.textBaseline = "middle"
      const infoTxt = st.overlayMode === "badges"
        ? `👷${ops} · 📋${steps} steps`
        : `${ct.toFixed(0)}s / ${takt.toFixed(0)}s (${util.toFixed(0)}%)`
      ctx.fillText(infoTxt, s.x + s.width / 2, s.y + s.height * 0.66, s.width - 6)
    }
  }

  function drawConnectorShape(ctx, s, style, strokeColor, strokeWidth, strokeStyle, isSelected, fastLod) {
    const pts = getConnectorEndpoints(s)
    const routing = style.routing || "orthogonal"
    const arrow = style.arrow || "end"

    ctx.strokeStyle = isSelected ? "#2563eb" : strokeColor
    ctx.fillStyle = isSelected ? "#2563eb" : strokeColor
    ctx.lineWidth = isSelected ? strokeWidth + 1 : strokeWidth

    if (strokeStyle === "dashed") ctx.setLineDash([7, 5])
    else if (strokeStyle === "dotted") ctx.setLineDash([2, 4])

    let midX = (pts.x1 + pts.x2) / 2
    let midY = (pts.y1 + pts.y2) / 2
    let endAngle = Math.atan2(pts.y2 - pts.y1, pts.x2 - pts.x1)

    ctx.beginPath()
    ctx.moveTo(pts.x1, pts.y1)
    if (routing === "orthogonal" && !fastLod) {
      if (Math.abs(pts.x2 - pts.x1) >= Math.abs(pts.y2 - pts.y1)) {
        ctx.lineTo(midX, pts.y1); ctx.lineTo(midX, pts.y2); ctx.lineTo(pts.x2, pts.y2)
        endAngle = pts.x2 >= midX ? 0 : Math.PI
      } else {
        ctx.lineTo(pts.x1, midY); ctx.lineTo(pts.x2, midY); ctx.lineTo(pts.x2, pts.y2)
        endAngle = pts.y2 >= midY ? Math.PI / 2 : -Math.PI / 2
      }
    } else if (routing === "curved" && !fastLod) {
      const cx1 = pts.x1 + (pts.x2 - pts.x1) * 0.5, cy1 = pts.y1
      const cx2 = pts.x1 + (pts.x2 - pts.x1) * 0.5, cy2 = pts.y2
      ctx.bezierCurveTo(cx1, cy1, cx2, cy2, pts.x2, pts.y2)
    } else {
      ctx.lineTo(pts.x2, pts.y2)
    }
    ctx.stroke()
    ctx.setLineDash([])

    if (!fastLod && (arrow === "end" || arrow === "both")) {
      const ah = Math.max(7, strokeWidth * 3)
      ctx.save()
      ctx.translate(pts.x2, pts.y2)
      ctx.rotate(endAngle)
      ctx.beginPath()
      ctx.moveTo(0, 0); ctx.lineTo(-ah, -ah * 0.55); ctx.lineTo(-ah, ah * 0.55)
      ctx.closePath()
      ctx.fill()
      ctx.restore()
    }
    if (!fastLod && arrow === "both") {
      const ah = Math.max(7, strokeWidth * 3)
      const startAngle = Math.atan2(pts.y1 - pts.y2, pts.x1 - pts.x2)
      ctx.save()
      ctx.translate(pts.x1, pts.y1)
      ctx.rotate(startAngle)
      ctx.beginPath()
      ctx.moveTo(0, 0); ctx.lineTo(-ah, -ah * 0.55); ctx.lineTo(-ah, ah * 0.55)
      ctx.closePath()
      ctx.fill()
      ctx.restore()
    }

    if (!fastLod && s.label) {
      const fsize = Number(style.font_size || 11)
      ctx.font = `600 ${fsize}px sans-serif`
      const tw = ctx.measureText(s.label).width + 10
      const th = fsize + 6
      ctx.fillStyle = "#ffffff"
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = 1
      ctx.fillRect(midX - tw / 2, midY - th / 2, tw, th)
      ctx.strokeRect(midX - tw / 2, midY - th / 2, tw, th)
      ctx.fillStyle = "#0f172a"
      ctx.textAlign = "center"
      ctx.textBaseline = "middle"
      ctx.fillText(s.label, midX, midY)
    }
  }

  // Render Collapsible Left Shape Library Drawer (Saved Shapes + Primitives + Pin Map Stencils + Scenario Pitches)
  function renderShapeDrawer() {
    const body = parentElement.querySelector("#lc-drawer-body")
    if (!body) return
    const q = (parentElement.querySelector("#lc-shape-search")?.value || "").trim().toLowerCase()
    body.innerHTML = ""

    // 1. User-Created Saved Custom Shapes Section
    const customSec = document.createElement("div")
    customSec.className = "lc-cat-sec"
    const isCustomCol = Boolean(st.collapsedCats["custom_saved"]) && !q
    const cHdr = document.createElement("div")
    cHdr.className = "lc-cat-hdr"
    cHdr.innerHTML = `<span>${isCustomCol ? "▸" : "▾"} ★ Saved Shapes (${st.customStencils.length})</span>`
    cHdr.onclick = () => {
      st.collapsedCats["custom_saved"] = !st.collapsedCats["custom_saved"]
      renderShapeDrawer()
    }
    customSec.appendChild(cHdr)

    if (!isCustomCol) {
      const saveBtn = document.createElement("button")
      saveBtn.className = "lc-top-btn"
      saveBtn.style.cssText = "width:100%; margin-bottom:6px; justify-content:center; font-size:11px;"
      saveBtn.textContent = "★ Save Selected as Custom Shape…"
      saveBtn.onclick = () => openSaveCustomStencilModal()
      customSec.appendChild(saveBtn)

      const matchedCustom = st.customStencils.filter(cs =>
        !q || String(cs.name || "").toLowerCase().includes(q) || String(cs.category || "").toLowerCase().includes(q)
      )
      if (matchedCustom.length === 0) {
        const emp = document.createElement("div")
        emp.style.cssText = "font-size:10px; color:#6b7280; padding:2px 2px 4px 2px;"
        emp.textContent = st.customStencils.length === 0
          ? "Combine primitives on canvas, select them, and click ★ Save Shape."
          : "No matching saved shapes."
        customSec.appendChild(emp)
      } else {
        matchedCustom.forEach(cs => {
          const row = document.createElement("div")
          row.className = "lc-custom-stencil-row"
          row.draggable = true
          row.title = `${cs.name} (${cs.category || "Custom"}) — Click or drag onto canvas`

          const titleSpan = document.createElement("span")
          titleSpan.style.cssText = "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
          titleSpan.textContent = `★ ${cs.name}`
          row.appendChild(titleSpan)

          const delBtn = document.createElement("button")
          delBtn.className = "lc-custom-del"
          delBtn.textContent = "✕"
          delBtn.title = "Delete saved shape"
          delBtn.onclick = (ev) => {
            ev.stopPropagation()
            if (!window.confirm(`Delete saved shape "${cs.name || "Custom Shape"}"?`)) return
            st.customStencils = st.customStencils.filter(item => String(item.id) !== String(cs.id))
            renderShapeDrawer()
            commitCanvasToPython({ action: "delete_custom_stencil", stencil_id: cs.id })
          }
          row.appendChild(delBtn)

          row.onclick = () => placeCustomStencil(cs)
          row.ondragstart = (ev) => {
            ev.dataTransfer?.setData("text/plain", "custom_stencil:" + cs.id)
          }
          customSec.appendChild(row)
        })
      }
    }
    body.appendChild(customSec)

    // 2. Standard Stencil Categories (Simple Primitives + Pin Map & Line Stencils)
    STENCIL_CATEGORIES.forEach(cat => {
      const matched = cat.items.filter(it => !q || it.title.toLowerCase().includes(q) || it.stype.toLowerCase().includes(q))
      if (!matched.length) return

      const sec = document.createElement("div")
      sec.className = "lc-cat-sec"
      const isCol = Boolean(st.collapsedCats[cat.id]) && !q

      const hdr = document.createElement("div")
      hdr.className = "lc-cat-hdr"
      hdr.innerHTML = `<span>${isCol ? "▸" : "▾"} ${cat.title}</span>`
      hdr.onclick = () => {
        st.collapsedCats[cat.id] = !st.collapsedCats[cat.id]
        renderShapeDrawer()
      }
      sec.appendChild(hdr)

      if (!isCol) {
        const grid = document.createElement("div")
        grid.className = "lc-svg-grid"
        matched.forEach(it => {
          const btn = document.createElement("button")
          btn.className = "lc-svg-tile"
          btn.title = `${it.title} (Click or drag onto canvas)`
          btn.draggable = true
          btn.innerHTML = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${it.svg}</svg>`
          btn.onclick = () => createStencilShape(it.stype)
          btn.ondragstart = (ev) => {
            ev.dataTransfer?.setData("text/plain", "stencil:" + it.stype)
          }
          grid.appendChild(btn)
        })
        sec.appendChild(grid)
      }
      body.appendChild(sec)
    })

    // 3. Scenario Yamazumi Pitches Section
    const pitchSec = document.createElement("div")
    pitchSec.className = "lc-cat-sec"
    const isPitchCol = Boolean(st.collapsedCats["pitches"]) && !q
    const pHdr = document.createElement("div")
    pHdr.className = "lc-cat-hdr"
    pHdr.innerHTML = `<span>${isPitchCol ? "▸" : "▾"} Scenario Pitches (${st.pitches.length})</span>`
    pHdr.onclick = () => {
      st.collapsedCats["pitches"] = !st.collapsedCats["pitches"]
      renderShapeDrawer()
    }
    pitchSec.appendChild(pHdr)

    if (!isPitchCol) {
      if (st.pitches.length === 0) {
        const emp = document.createElement("div")
        emp.style.cssText = "font-size:11px; color:#6b7280; padding:4px 2px;"
        emp.textContent = "No pitches configured in Yamazumi for this scenario yet."
        pitchSec.appendChild(emp)
      } else {
        const autoBtn = document.createElement("button")
        autoBtn.className = "lc-top-btn"
        autoBtn.style.cssText = "width:100%; margin-bottom:6px; justify-content:center;"
        autoBtn.textContent = "⚡ Auto-Place Unplaced Pitches"
        autoBtn.onclick = () => autoPlaceUnplacedPitches()
        pitchSec.appendChild(autoBtn)

        const placedSet = new Set()
        st.shapes.forEach(s => {
          if (s.pitch_id) {
            placedSet.add(s.pitch_id)
            const aliasPid = st.pitchMetrics[s.pitch_id]?.pitch_id
            if (aliasPid) placedSet.add(String(aliasPid))
          }
        })

        st.pitches.forEach(p => {
          const pid = String(p.pitch_id)
          const pNum = String(p.pitch_number || "")
          const pName = String(p.pitch_name || "")
          const areaName = String(p.area_name || "")
          if (q && !pNum.toLowerCase().includes(q) && !pName.toLowerCase().includes(q) && !areaName.toLowerCase().includes(q)) return

          const escHtml = (v) => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
          const isPlaced = placedSet.has(pid)
          const pm = st.pitchMetrics[pid] || {}
          const item = document.createElement("div")
          item.className = "lc-pitch-item " + (isPlaced ? "placed" : "unplaced")
          item.draggable = !isPlaced
          item.innerHTML = `
            <div style="display:flex; justify-content:space-between; font-weight:600;">
              <span>${escHtml(pNum)} ${pName ? "— " + escHtml(pName) : ""}</span>
              <span style="color:${isPlaced ? "#15803d" : "#d97706"};">${isPlaced ? "✓" : "+ Place"}</span>
            </div>
            <div style="font-size:10px; color:#6b7280; margin-top:1px;">
              ${escHtml(areaName)} · CT: ${Number(pm.cycle_time_sec || 0).toFixed(0)}s · 👷${Number(pm.operator_count || 0)}
            </div>
          `
          item.ondragstart = (ev) => {
            ev.dataTransfer?.setData("text/plain", "pitch:" + pid)
          }
          item.onclick = () => {
            if (isPlaced) {
              const found = st.shapes.find(s => s.pitch_id === pid || String(st.pitchMetrics[s.pitch_id]?.pitch_id || "") === pid)
              if (found) {
                st.selectedIds.clear()
                st.selectedIds.add(found.id)
                showPitchInspectorCard(found)
                updateContextualToolbar()
                renderFrame()
                requestRender()
              }
            } else {
              placeScenarioPitchOnCanvas(p)
            }
          }
          pitchSec.appendChild(item)
        })
      }
    }
    body.appendChild(pitchSec)
  }

  // Render Bottom Page Tabs (Page 1, Page 2, +)
  function renderPageTabs() {
    const tabsEl = parentElement.querySelector("#lc-page-tabs")
    if (!tabsEl) return
    tabsEl.innerHTML = ""
    const pages = st.pages.length > 0 ? st.pages : [{ id: st.activePageId || "page_1", name: st.pageTitle || "Page 1" }]
    pages.forEach(pg => {
      const isAct = String(pg.id) === String(st.activePageId)
      const btn = document.createElement("button")
      btn.className = "lc-page-tab" + (isAct ? " active" : "")
      btn.title = "Click to switch page, double-click to rename"
      const span = document.createElement("span")
      span.textContent = pg.name || "Page"
      btn.appendChild(span)

      if (pages.length > 1) {
        const del = document.createElement("span")
        del.className = "lc-page-del"
        del.textContent = "✕"
        del.title = "Delete page"
        del.onclick = (ev) => {
          ev.stopPropagation()
          if (!window.confirm(`Delete page "${pg.name || "Page"}" and all shapes on it?`)) return
          commitCanvasToPython({ action: "delete_page", target_page_id: pg.id })
        }
        btn.appendChild(del)
      }

      btn.onclick = () => {
        if (!isAct) commitCanvasToPython({ action: "switch_page", target_page_id: pg.id })
      }
      btn.ondblclick = (ev) => {
        ev.stopPropagation()
        const nextName = window.prompt("Rename Page:", pg.name || "Page")
        if (nextName && nextName.trim() && nextName.trim() !== pg.name) {
          const trimmed = nextName.trim()
          pg.name = trimmed
          if (isAct) {
            st.pageTitle = trimmed
            const titleEl = parentElement.querySelector("#lc-page-title")
            if (titleEl) titleEl.value = st.pageTitle
          }
          renderPageTabs()
          commitCanvasToPython({ action: "rename_page", target_page_id: pg.id, page_title: trimmed })
        }
      }
      tabsEl.appendChild(btn)
    })
  }

  // Render Layer Manager Popover List
  function renderLayerList() {
    const listEl = parentElement.querySelector("#lc-layer-list")
    const cntEl = parentElement.querySelector("#lc-layer-count")
    if (!listEl) return
    if (cntEl) cntEl.textContent = String(st.layers.length)

    const counts = new Map()
    for (let i = 0; i < st.shapes.length; i++) {
      const lid = st.shapes[i].layer_id || ""
      counts.set(lid, (counts.get(lid) || 0) + 1)
    }

    listEl.innerHTML = ""
    const sorted = [...st.layers].sort((a, b) => (b.z_index || 0) - (a.z_index || 0))
    sorted.forEach(layer => {
      const row = document.createElement("div")
      row.className = "lc-layer-row" + (layer.id === st.activeLayerId ? " active" : "")
      row.onclick = () => {
        st.activeLayerId = layer.id
        renderLayerList()
      }

      const swatch = document.createElement("span")
      swatch.className = "lc-layer-swatch"
      swatch.style.background = layer.color || "#2563eb"
      row.appendChild(swatch)

      const nameSpan = document.createElement("span")
      nameSpan.className = "lc-layer-name"
      nameSpan.textContent = layer.name
      nameSpan.ondblclick = (ev) => {
        ev.stopPropagation()
        const nextName = window.prompt("Rename layer:", layer.name)
        if (nextName && nextName.trim()) {
          layer.name = nextName.trim()
          markUnsaved()
          renderLayerList()
          updateContextualToolbar()
        }
      }
      row.appendChild(nameSpan)

      const cntBadge = document.createElement("span")
      cntBadge.className = "lc-layer-cnt"
      cntBadge.textContent = String(counts.get(layer.id) || 0)
      row.appendChild(cntBadge)

      const visBtn = document.createElement("button")
      visBtn.className = "lc-layer-icon-btn"
      visBtn.title = layer.visible ? "Hide Layer" : "Show Layer"
      visBtn.textContent = layer.visible ? "👁" : "🚫"
      visBtn.onclick = (ev) => {
        ev.stopPropagation()
        layer.visible = !layer.visible
        markUnsaved()
        renderLayerList()
        renderFrame()
        requestRender()
      }
      row.appendChild(visBtn)

      const lockBtn = document.createElement("button")
      lockBtn.className = "lc-layer-icon-btn"
      lockBtn.title = layer.locked ? "Unlock Layer" : "Lock Layer"
      lockBtn.textContent = layer.locked ? "🔒" : "🔓"
      lockBtn.onclick = (ev) => {
        ev.stopPropagation()
        layer.locked = !layer.locked
        markUnsaved()
        renderLayerList()
        renderFrame()
        requestRender()
      }
      row.appendChild(lockBtn)

      if (st.layers.length > 1) {
        const delBtn = document.createElement("button")
        delBtn.className = "lc-layer-icon-btn"
        delBtn.title = "Delete Layer"
        delBtn.textContent = "✕"
        delBtn.onclick = (ev) => {
          ev.stopPropagation()
          const fallback = st.layers.find(l => l.id !== layer.id)
          if (!fallback) return
          const lCount = counts.get(layer.id) || 0
          const confirmMsg = lCount > 0
            ? `Delete layer "${layer.name}" and move its ${lCount} shape(s) to "${fallback.name}"?`
            : `Delete empty layer "${layer.name}"?`
          if (!window.confirm(confirmMsg)) return
          pushUndo()
          st.shapes.forEach(s => { if (s.layer_id === layer.id) s.layer_id = fallback.id })
          st.layers = st.layers.filter(l => l.id !== layer.id)
          if (st.activeLayerId === layer.id) st.activeLayerId = fallback.id
          markUnsaved()
          renderLayerList()
          updateContextualToolbar()
          renderFrame()
          requestRender()
        }
        row.appendChild(delBtn)
      }
      listEl.appendChild(row)
    })
  }

  function getPitchStandardSizePx(sectionId) {
    const std = (sectionId && st.sectionStandards[sectionId]) || {}
    const wU = Number(std.pitch_width || 12.0)
    const hU = Number(std.pitch_height || 8.0)
    return { wPx: Math.max(12, unitsToPxX(wU)), hPx: Math.max(10, unitsToPxY(hU)) }
  }

  function ensureLayerVisible(layerId) {
    if (!layerId) return
    const l = st.layers.find(it => it.id === layerId)
    if (l && !l.visible) l.visible = true
  }

  function placeScenarioPitchOnCanvas(pitch, customX, customY) {
    pushUndo()
    st.emptyDismissed = true
    updateEmptyCardVisibility()
    const pid = String(pitch.pitch_id || pitch.id || "")
    const sz = getPitchStandardSizePx(String(pitch.section_id || ""))

    let x = customX, y = customY
    if (x === undefined || y === undefined) {
      const sameAreaShapes = st.shapes.filter(s => {
        if (!s.pitch_id) return false
        const pm = st.pitchMetrics[s.pitch_id]
        return pm && pm.area_id === pitch.area_id
      })
      if (sameAreaShapes.length > 0) {
        const last = sameAreaShapes[sameAreaShapes.length - 1]
        x = last.x + last.width
        y = last.y
      } else {
        const rect = stage.getBoundingClientRect()
        const centerW = screenToWorld(rect.width / 2, rect.height / 2)
        x = centerW.x - sz.wPx / 2
        y = centerW.y - sz.hPx / 2
      }
    }

    const targetLayerId = inferLayerForShape("pitch_box", true)
    ensureLayerVisible(targetLayerId)

    const newShape = normalizeShape({
      id: uid(),
      layer_id: targetLayerId,
      shape_type: "pitch_box",
      x: Number(x.toFixed(2)),
      y: Number(y.toFixed(2)),
      width: Number(sz.wPx.toFixed(2)),
      height: Number(sz.hPx.toFixed(2)),
      rotation: 0,
      z_index: (st.shapes.length + 1) * 10,
      color: "#1e293b",
      label: String(pitch.pitch_number || "Pitch"),
      pitch_id: pid,
      style_json: {
        stroke_color: "#1e293b",
        stroke_width: 2,
        stroke_style: "solid",
        fill_color: "#dbeafe",
        fill_opacity: 0.75,
        font_size: 12,
        font_color: "#0f172a"
      }
    }, st.shapes.length)

    st.shapes.push(newShape)
    rebuildSpatialIndex()
    st.selectedIds.clear()
    st.selectedIds.add(newShape.id)
    renderShapeDrawer()
    renderLayerList()
    updateContextualToolbar()
    showPitchInspectorCard(newShape)
    markUnsaved()
    renderFrame()
    requestRender()
  }

  function autoPlaceUnplacedPitches() {
    const placedSet = new Set()
    st.shapes.forEach(s => {
      if (s.pitch_id) {
        placedSet.add(s.pitch_id)
        const aliasPid = st.pitchMetrics[s.pitch_id]?.pitch_id
        if (aliasPid) placedSet.add(String(aliasPid))
      }
    })
    const unplaced = st.pitches.filter(p => !placedSet.has(String(p.pitch_id)))
    if (!unplaced.length) return
    pushUndo()
    st.emptyDismissed = true
    updateEmptyCardVisibility()
    const targetLayerId = inferLayerForShape("pitch_box", true)
    ensureLayerVisible(targetLayerId)
    let curX = unitsToPxX(6)
    let curY = unitsToPxY(8)
    let lastArea = ""
    unplaced.forEach(p => {
      if (lastArea && p.area_name !== lastArea) {
        curX = unitsToPxX(6)
        curY += unitsToPxY(14)
      }
      lastArea = p.area_name
      const sz = getPitchStandardSizePx(String(p.section_id || ""))
      if (curX + sz.wPx > st.imageWidth - unitsToPxX(4)) {
        curX = unitsToPxX(6)
        curY += sz.hPx + unitsToPxY(4)
      }
      const ns = normalizeShape({
        id: uid(),
        layer_id: targetLayerId,
        shape_type: "pitch_box",
        x: Number(curX.toFixed(2)),
        y: Number(curY.toFixed(2)),
        width: Number(sz.wPx.toFixed(2)),
        height: Number(sz.hPx.toFixed(2)),
        color: "#1e293b",
        label: String(p.pitch_number),
        pitch_id: String(p.pitch_id),
        style_json: {
          stroke_color: "#1e293b",
          stroke_width: 2,
          fill_color: "#dbeafe",
          fill_opacity: 0.75,
          font_size: 12
        }
      }, st.shapes.length)
      st.shapes.push(ns)
      curX += sz.wPx
    })
    rebuildSpatialIndex()
    renderShapeDrawer()
    renderLayerList()
    markUnsaved()
    renderFrame()
    requestRender()
  }

  function createStencilShape(stype, customWorldX, customWorldY) {
    pushUndo()
    st.emptyDismissed = true
    updateEmptyCardVisibility()
    const rect = stage.getBoundingClientRect()
    let targetCenter = { x: st.imageWidth / 2, y: st.imageHeight / 2 }
    if (customWorldX !== undefined && customWorldY !== undefined) {
      targetCenter = { x: customWorldX, y: customWorldY }
    } else if (rect.width > 0 && rect.height > 0) {
      targetCenter = screenToWorld(rect.width / 2, rect.height / 2)
    }
    const snapped = snapWorldCoord(targetCenter.x, targetCenter.y)

    const defaults = {
      rectangle:      { wU: 10, hU: 6,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      square:         { wU: 6,  hU: 6,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      rounded_rect:   { wU: 10, hU: 6,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      pill:           { wU: 10, hU: 4,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      circle:         { wU: 4,  hU: 4,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      semicircle:     { wU: 6,  hU: 3,   stroke: "#1e293b", fill: "#ffffff", op: 0.85, label: "" },
      quarter_circle: { wU: 5,  hU: 5,   stroke: "#1e293b", fill: "#ffffff", op: 0.85, label: "" },
      arc_line:       { wU: 4,  hU: 2,   stroke: "#ea580c", fill: "#ffffff", op: 0.0,  label: "" },
      line:           { wU: 10, hU: 1.5, stroke: "#1e293b", fill: "#ffffff", op: 0.0,  label: "" },
      triangle:       { wU: 6,  hU: 5,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      right_triangle: { wU: 6,  hU: 5,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      diamond:        { wU: 7,  hU: 7,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      pentagon:       { wU: 6,  hU: 6,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      hexagon:        { wU: 7,  hU: 6,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      octagon:        { wU: 6,  hU: 6,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      trapezoid:      { wU: 9,  hU: 5,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      parallelogram:  { wU: 9,  hU: 5,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      l_shape:        { wU: 10, hU: 8,   stroke: "#c2410c", fill: "#fed7aa", op: 0.85, label: "Machine" },
      t_shape:        { wU: 10, hU: 8,   stroke: "#1e293b", fill: "#e2e8f0", op: 0.85, label: "" },
      u_shape:        { wU: 12, hU: 8,   stroke: "#c2410c", fill: "#fed7aa", op: 0.85, label: "Cell" },
      cross:          { wU: 5,  hU: 5,   stroke: "#16a34a", fill: "#dcfce7", op: 0.90, label: "+" },
      star:           { wU: 6,  hU: 6,   stroke: "#dc2626", fill: "#fef2f2", op: 0.90, label: "" },
      arrow_block:    { wU: 8,  hU: 3.5, stroke: "#2563eb", fill: "#dbeafe", op: 0.85, label: "Flow" },
      cylinder:       { wU: 6,  hU: 8,   stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      document:       { wU: 8,  hU: 5.5, stroke: "#1e293b", fill: "#ffffff", op: 0.90, label: "" },
      callout:        { wU: 9,  hU: 5,   stroke: "#ca8a04", fill: "#fef9c3", op: 0.95, label: "Note" },
      text:           { wU: 8,  hU: 2.5, stroke: "#0f172a", fill: "#ffffff", op: 0.0,  label: "Label" },
      dimension:      { wU: 14, hU: 2,   stroke: "#0f172a", fill: "#ffffff", op: 0.0,  label: "" },
      area_header:    { wU: 26, hU: 5.5, stroke: "#1e293b", fill: "#f8fafc", op: 0.95, label: "PEDESTAL" },
      frame:          { wU: 32, hU: 20,  stroke: "#64748b", fill: "#f8fafc", op: 0.25, label: "Area Frame" },
      swimlane_h:     { wU: 40, hU: 18,  stroke: "#64748b", fill: "#f8fafc", op: 0.20, label: "Swimlane" },
      swimlane_v:     { wU: 20, hU: 36,  stroke: "#64748b", fill: "#f8fafc", op: 0.20, label: "Bay" },
      safety_zone:    { wU: 12, hU: 7,   stroke: "#dc2626", fill: "#fee2e2", op: 0.45, label: "Keep Out" },
      pitch_box:      { wU: 3.5,hU: 6,   stroke: "#1e293b", fill: "#93c5fd", op: 0.80, label: "001" },
      conveyor:       { wU: 20, hU: 4,   stroke: "#334155", fill: "#cbd5e1", op: 0.80, label: "" },
      conveyor_curve: { wU: 8,  hU: 8,   stroke: "#334155", fill: "#cbd5e1", op: 0.80, label: "" },
      x_box:          { wU: 4.5,hU: 4.5, stroke: "#1e293b", fill: "#e2e8f0", op: 0.85, label: "" },
      turntable:      { wU: 7,  hU: 7,   stroke: "#0284c7", fill: "#e0f2fe", op: 0.80, label: "Turntable" },
      quality_gate:   { wU: 7,  hU: 7,   stroke: "#16a34a", fill: "#dcfce7", op: 0.85, label: "Q-Gate" },
      worker:         { wU: 3,  hU: 3,   stroke: "#0f766e", fill: "#99f6e4", op: 0.90, label: "Op" },
      screen:         { wU: 4,  hU: 1.5, stroke: "#0284c7", fill: "#1e293b", op: 0.95, label: "HMI" },
      scanner:        { wU: 2.5,hU: 2.5, stroke: "#7c3aed", fill: "#ede9fe", op: 0.85, label: "Scan" },
      computer_kiosk: { wU: 3.5,hU: 2.5, stroke: "#0369a1", fill: "#e0f2fe", op: 0.85, label: "MES" },
      rack:           { wU: 8,  hU: 4,   stroke: "#ea580c", fill: "#fdba74", op: 0.85, label: "Rack" },
      supermarket:    { wU: 14, hU: 5,   stroke: "#d97706", fill: "#fef3c7", op: 0.80, label: "Supermarket" },
      pallet:         { wU: 4,  hU: 4,   stroke: "#b45309", fill: "#fde68a", op: 0.85, label: "" },
      agv:            { wU: 5.5,hU: 3.5, stroke: "#c2410c", fill: "#fed7aa", op: 0.85, label: "AGV" },
      custom_polygon: { wU: 10, hU: 8,   stroke: "#c2410c", fill: "#fed7aa", op: 0.85, label: "Custom" }
    }

    const targetLayerId = inferLayerForShape(stype, false)
    ensureLayerVisible(targetLayerId)

    if (stype === "info_flow" || stype === "mat_flow") {
      const isInfo = stype === "info_flow"
      const lenPx = unitsToPxX(14)
      const x1 = snapped.x - lenPx / 2, y1 = snapped.y
      const x2 = snapped.x + lenPx / 2, y2 = snapped.y
      const conn = normalizeShape({
        id: uid(),
        layer_id: targetLayerId,
        shape_type: "connector",
        x: x1, y: y1 - 10, width: lenPx, height: 20,
        color: isInfo ? "#7b1fa2" : "#ea580c",
        label: isInfo ? "Info Flow" : "Material Flow",
        style_json: {
          x1, y1, x2, y2,
          routing: "orthogonal",
          arrow: "end",
          stroke_color: isInfo ? "#7b1fa2" : "#ea580c",
          stroke_width: 2,
          stroke_style: isInfo ? "dashed" : "solid",
          font_size: 11
        }
      }, st.shapes.length)
      st.shapes.push(conn)
      rebuildSpatialIndex()
      st.selectedIds.clear()
      st.selectedIds.add(conn.id)
      renderLayerList()
      updateContextualToolbar()
      markUnsaved()
      renderFrame()
      requestRender()
      return
    }

    const cfg = defaults[stype] || defaults.rectangle
    const wPx = Math.max(8, unitsToPxX(cfg.wU))
    const hPx = Math.max(6, unitsToPxY(cfg.hU))

    let posX = snapped.x - wPx / 2
    let posY = snapped.y - hPx / 2
    if (customWorldX === undefined && customWorldY === undefined) {
      const stepOffset = Math.max(8, unitsToPxX(1.5))
      let bumpCount = 0
      while (bumpCount < 15 && st.shapes.some(ex => Math.abs(ex.x - posX) < 3 && Math.abs(ex.y - posY) < 3)) {
        posX += stepOffset
        posY += stepOffset
        bumpCount++
      }
    }

    const stylePayload = {
      stroke_color: cfg.stroke,
      stroke_width: 2,
      stroke_style: stype === "safety_zone" ? "dashed" : "solid",
      fill_color: cfg.fill,
      fill_opacity: cfg.op,
      font_size: 12,
      font_color: "#0f172a",
      font_weight: "bold",
      text_align: "center",
      text_rotation: stype === "pitch_box" ? -90 : 0
    }
    if (stype === "area_header") {
      stylePayload.area_code = "374"
      stylePayload.area_pills = "STANDARD WORK, YAMAZUMI"
    }

    const newS = normalizeShape({
      id: uid(),
      layer_id: targetLayerId,
      shape_type: stype,
      x: Number(posX.toFixed(2)),
      y: Number(posY.toFixed(2)),
      width: Number(wPx.toFixed(2)),
      height: Number(hPx.toFixed(2)),
      rotation: 0,
      z_index: (st.shapes.length + 1) * 10,
      color: cfg.stroke,
      label: cfg.label,
      style_json: stylePayload
    }, st.shapes.length)

    st.shapes.push(newS)
    rebuildSpatialIndex()
    st.selectedIds.clear()
    st.selectedIds.add(newS.id)
    renderLayerList()
    updateContextualToolbar()
    markUnsaved()
    renderFrame()
    requestRender()
  }

  // Place a User-Saved Custom Stencil from the Shape Drawer onto the Canvas
  function placeCustomStencil(stencilRec, customWorldX, customWorldY) {
    if (!stencilRec) return
    let items = []
    try {
      items = typeof stencilRec.stencil_json === "string"
        ? JSON.parse(stencilRec.stencil_json)
        : (Array.isArray(stencilRec.stencil_json) ? stencilRec.stencil_json : (stencilRec.stencil_json?.shapes || []))
    } catch (_) {
      items = []
    }
    if (!Array.isArray(items) || items.length === 0) return

    pushUndo()
    st.emptyDismissed = true
    updateEmptyCardVisibility()

    const rect = stage.getBoundingClientRect()
    let targetCenter = { x: st.imageWidth / 2, y: st.imageHeight / 2 }
    if (customWorldX !== undefined && customWorldY !== undefined) {
      targetCenter = { x: customWorldX, y: customWorldY }
    } else if (rect.width > 0 && rect.height > 0) {
      targetCenter = screenToWorld(rect.width / 2, rect.height / 2)
    }
    const snapped = snapWorldCoord(targetCenter.x, targetCenter.y)

    const totalW = Math.max(10, unitsToPxX(Number(stencilRec.total_w_units || 8)))
    const totalH = Math.max(10, unitsToPxY(Number(stencilRec.total_h_units || 6)))
    const originX = snapped.x - totalW / 2
    const originY = snapped.y - totalH / 2
    const newGroupId = items.length > 1 ? ("grp_" + uid()) : ""
    const newIds = new Set()

    items.forEach(item => {
      const targetLayerId = inferLayerForShape(item.shape_type || "rectangle", false)
      ensureLayerVisible(targetLayerId)
      const wPx = Math.max(6, unitsToPxX(Number(item.w_units || 4)))
      const hPx = Math.max(6, unitsToPxY(Number(item.h_units || 4)))
      const dxPx = unitsToPxX(Number(item.dx_units || 0))
      const dyPx = unitsToPxY(Number(item.dy_units || 0))

      const created = normalizeShape({
        id: uid(),
        layer_id: targetLayerId,
        shape_type: item.shape_type || "rectangle",
        x: Number((originX + dxPx).toFixed(2)),
        y: Number((originY + dyPx).toFixed(2)),
        width: Number(wPx.toFixed(2)),
        height: Number(hPx.toFixed(2)),
        rotation: Number(item.rotation || 0),
        z_index: (st.shapes.length + 1) * 10,
        group_id: newGroupId,
        color: item.color || "#1e293b",
        label: item.label || "",
        style_json: item.style_json || {}
      }, st.shapes.length)
      st.shapes.push(created)
      newIds.add(created.id)
    })

    st.selectedIds = newIds
    rebuildSpatialIndex()
    renderLayerList()
    updateContextualToolbar()
    markUnsaved()
    renderFrame()
    requestRender()
  }

  // Open Modal to Save Selected Shape(s) as Reusable Custom Stencil
  function openSaveCustomStencilModal() {
    if (st.selectedIds.size === 0) {
      window.alert("Select one or more shapes on the canvas first, then click ★ Save Shape.")
      return
    }
    const modal = parentElement.querySelector("#lc-custom-stencil-modal")
    const nameIn = parentElement.querySelector("#lc-custom-stencil-name")
    const infoEl = parentElement.querySelector("#lc-custom-stencil-info")
    const firstShape = st.shapeMap.get(Array.from(st.selectedIds)[0])
    if (nameIn) nameIn.value = (firstShape?.label || "Custom Pin Shape").replace(/\s+/g, " ").trim()
    if (infoEl) {
      infoEl.textContent = `Saving ${st.selectedIds.size} selected shape${st.selectedIds.size > 1 ? "s" : ""} as a reusable stencil in your project Shape Drawer.`
    }
    if (modal) modal.style.display = "flex"
    setTimeout(() => nameIn?.focus(), 30)
  }

  function saveSelectedAsCustomStencil() {
    const selectedArr = Array.from(st.selectedIds).map(id => st.shapeMap.get(id)).filter(s => s && s.shape_type !== "connector")
    if (selectedArr.length === 0) return
    const nameVal = (parentElement.querySelector("#lc-custom-stencil-name")?.value || "Custom Shape").trim()
    const catVal = (parentElement.querySelector("#lc-custom-stencil-cat")?.value || "Saved Shapes").trim() || "Saved Shapes"

    const minX = Math.min(...selectedArr.map(s => s.x))
    const minY = Math.min(...selectedArr.map(s => s.y))
    const maxX = Math.max(...selectedArr.map(s => s.x + s.width))
    const maxY = Math.max(...selectedArr.map(s => s.y + s.height))
    const totalWU = Math.max(0.5, Number(pxToUnitsX(maxX - minX).toFixed(2)))
    const totalHU = Math.max(0.5, Number(pxToUnitsY(maxY - minY).toFixed(2)))

    const serializedShapes = selectedArr.map(s => {
      syncStyleJson(s)
      return {
        shape_type: s.shape_type,
        dx_units: Number(pxToUnitsX(s.x - minX).toFixed(3)),
        dy_units: Number(pxToUnitsY(s.y - minY).toFixed(3)),
        w_units: Number(pxToUnitsX(s.width).toFixed(3)),
        h_units: Number(pxToUnitsY(s.height).toFixed(3)),
        rotation: Number(s.rotation || 0),
        color: s.color || "#1e293b",
        label: s.label || "",
        style_json: JSON.parse(s.style_json || "{}")
      }
    })

    const newStencil = {
      id: "cst_" + uid(),
      name: nameVal,
      category: catVal,
      total_w_units: totalWU,
      total_h_units: totalHU,
      stencil_json: JSON.stringify(serializedShapes)
    }

    st.customStencils.unshift(newStencil)
    st.collapsedCats["custom_saved"] = false
    const modal = parentElement.querySelector("#lc-custom-stencil-modal")
    if (modal) modal.style.display = "none"
    renderShapeDrawer()
    commitCanvasToPython({
      action: "save_custom_stencil",
      custom_stencil: newStencil
    })
  }

  // Test if a world point (wx, wy) is inside a shape's filled geometry (used by Hit-Testing & Weld/Merge)
  function isWorldPointInsideShape(s, wx, wy, forHitTest = false) {
    if (!s) return false
    const cx = s.x + s.width / 2
    const cy = s.y + s.height / 2
    let lx = wx - cx
    let ly = wy - cy
    if (s.rotation) {
      const rad = (-s.rotation * Math.PI) / 180
      const cosA = Math.cos(rad), sinA = Math.sin(rad)
      const rx = lx * cosA - ly * sinA
      const ry = lx * sinA + ly * cosA
      lx = rx; ly = ry
    }
    const hw = s.width / 2, hh = s.height / 2
    if (lx < -hw || lx > hw || ly < -hh || ly > hh) return false
    const nx = (lx + hw) / Math.max(1, s.width)
    const ny = (ly + hh) / Math.max(1, s.height)
    const stype = s.shape_type

    // When hit-testing a shape that renders a centered text label (e.g. L-shape "Machine" or U-shape "Cell"),
    // allow clicking the central label box so users can click the visible text directly.
    if (forHitTest && s.label && String(s.label).trim()) {
      if (Math.abs(nx - 0.5) <= 0.28 && Math.abs(ny - 0.5) <= 0.22) return true
    }

    if (stype === "circle" || stype === "turntable" || stype === "worker") {
      return Math.hypot(nx - 0.5, ny - 0.5) <= 0.5
    }
    if (stype === "semicircle") {
      return ny <= 1.0 && Math.hypot(nx - 0.5, ny - 1.0) <= 0.5
    }
    if (stype === "quarter_circle") {
      return Math.hypot(nx, ny - 1.0) <= 1.0
    }
    if (stype === "diamond") {
      return Math.abs(nx - 0.5) + Math.abs(ny - 0.5) <= 0.5
    }
    if (stype === "l_shape") {
      return nx <= 0.42 || ny >= 0.58
    }
    if (stype === "t_shape") {
      return ny <= 0.36 || (nx >= 0.32 && nx <= 0.68)
    }
    if (stype === "u_shape") {
      return nx <= 0.32 || nx >= 0.68 || ny >= 0.58
    }
    if (stype === "custom_polygon") {
      const pts = parseStyle(s).points
      if (Array.isArray(pts) && pts.length >= 3) {
        let inside = false
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
          const xi = Number(pts[i][0]), yi = Number(pts[i][1])
          const xj = Number(pts[j][0]), yj = Number(pts[j][1])
          const intersect = ((yi > ny) !== (yj > ny)) && (nx < (xj - xi) * (ny - yi) / ((yj - yi) || 1e-9) + xi)
          if (intersect) inside = !inside
        }
        return inside
      }
    }
    return true
  }

  // Merge / Weld 2+ Selected Shapes into One Unified Outer Perimeter Polygon (Seamless Border)
  function weldSelectedShapes() {
    const layerMap = getLayerMap()
    const selectedArr = Array.from(st.selectedIds)
      .map(id => st.shapeMap.get(id))
      .filter(s => s && s.shape_type !== "connector" && !isShapeLocked(s, layerMap))
    if (selectedArr.length < 2) {
      window.alert("Select 2 or more unlocked overlapping or touching shapes to Weld/Merge their borders into a single custom shape.")
      return
    }

    pushUndo()
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    selectedArr.forEach(s => {
      updateShapeBounds(s)
      minX = Math.min(minX, s._minX)
      minY = Math.min(minY, s._minY)
      maxX = Math.max(maxX, s._maxX)
      maxY = Math.max(maxY, s._maxY)
    })

    const unionW = Math.max(12, maxX - minX)
    const unionH = Math.max(12, maxY - minY)

    // High-resolution occupancy grid to trace the unified outer contour
    const GRID_N = 120
    const cols = GRID_N + 2
    const rows = GRID_N + 2
    const grid = Array.from({ length: rows }, () => new Uint8Array(cols))

    for (let r = 1; r <= GRID_N; r++) {
      const wy = minY + ((r - 0.5) / GRID_N) * unionH
      for (let c = 1; c <= GRID_N; c++) {
        const wx = minX + ((c - 0.5) / GRID_N) * unionW
        for (let k = 0; k < selectedArr.length; k++) {
          if (isWorldPointInsideShape(selectedArr[k], wx, wy)) {
            grid[r][c] = 1
            break
          }
        }
      }
    }

    // Collect directed outer boundary edges (clockwise around filled cells)
    const outEdges = new Map()
    const addEdge = (x1, y1, x2, y2) => {
      const k = `${x1},${y1}`
      if (!outEdges.has(k)) outEdges.set(k, [])
      outEdges.get(k).push({ x1, y1, x2, y2, used: false })
    }

    for (let r = 1; r <= GRID_N; r++) {
      for (let c = 1; c <= GRID_N; c++) {
        if (!grid[r][c]) continue
        if (!grid[r - 1][c]) addEdge(c - 1, r - 1, c, r - 1) // Top
        if (!grid[r][c + 1]) addEdge(c, r - 1, c, r)         // Right
        if (!grid[r + 1][c]) addEdge(c, r, c - 1, r)         // Bottom
        if (!grid[r][c - 1]) addEdge(c - 1, r, c - 1, r - 1) // Left
      }
    }

    // Find largest closed boundary loop
    let bestLoop = []
    for (const edgeList of outEdges.values()) {
      for (const startEdge of edgeList) {
        if (startEdge.used) continue
        const loop = []
        let cur = startEdge
        while (cur && !cur.used) {
          cur.used = true
          loop.push([cur.x1 / GRID_N, cur.y1 / GRID_N])
          const nextKey = `${cur.x2},${cur.y2}`
          const candidates = (outEdges.get(nextKey) || []).filter(e => !e.used)
          cur = candidates.length > 0 ? candidates[0] : null
        }
        if (loop.length > bestLoop.length) bestLoop = loop
      }
    }

    // Simplify collinear segments along the loop
    let simplified = bestLoop
    if (simplified.length >= 4) {
      const filtered = []
      const n = simplified.length
      for (let i = 0; i < n; i++) {
        const prev = simplified[(i - 1 + n) % n]
        const curr = simplified[i]
        const next = simplified[(i + 1) % n]
        const dx1 = curr[0] - prev[0], dy1 = curr[1] - prev[1]
        const dx2 = next[0] - curr[0], dy2 = next[1] - curr[1]
        const cross = Math.abs(dx1 * dy2 - dy1 * dx2)
        if (cross > 1e-5) filtered.push([Number(curr[0].toFixed(4)), Number(curr[1].toFixed(4))])
      }
      if (filtered.length >= 3) simplified = filtered
    }

    if (simplified.length < 3) {
      simplified = [[0, 0], [1, 0], [1, 1], [0, 1]]
    }

    const primary = selectedArr[0]
    const pStyle = parseStyle(primary)
    const combinedLabel = selectedArr.map(s => s.label).filter(Boolean).join(" ")

    const weldedShape = normalizeShape({
      id: uid(),
      layer_id: primary.layer_id,
      shape_type: "custom_polygon",
      x: Number(minX.toFixed(2)),
      y: Number(minY.toFixed(2)),
      width: Number(unionW.toFixed(2)),
      height: Number(unionH.toFixed(2)),
      rotation: 0,
      z_index: Math.max(...selectedArr.map(s => s.z_index || 10)),
      color: primary.color || "#c2410c",
      label: combinedLabel || primary.label || "Welded Shape",
      pitch_id: primary.pitch_id || null,
      style_json: {
        ...pStyle,
        points: simplified
      }
    }, st.shapes.length)

    const removeSet = new Set(selectedArr.map(s => s.id))
    st.shapes.forEach(s => {
      if (s.shape_type === "connector" && !removeSet.has(s.id)) {
        const dropSrc = s.source_shape_id && removeSet.has(s.source_shape_id)
        const dropTgt = s.target_shape_id && removeSet.has(s.target_shape_id)
        if (dropSrc || dropTgt) {
          const pts = getConnectorEndpoints(s)
          if (dropSrc) s.source_shape_id = null
          if (dropTgt) s.target_shape_id = null
          saveConnectorEndpoints(s, pts.x1, pts.y1, pts.x2, pts.y2)
        }
      }
    })
    st.shapes = st.shapes.filter(s => !removeSet.has(s.id))
    st.shapes.push(weldedShape)
    st.selectedIds.clear()
    st.selectedIds.add(weldedShape.id)

    rebuildSpatialIndex()
    renderLayerList()
    updateContextualToolbar()
    markUnsaved()
    renderFrame()
    requestRender()
  }

  // Finish Point-by-Point Polygon Drawing
  function finishPolygonDraft() {
    const pts = st.polygonDraft || []
    st.polygonDraft = []
    if (pts.length < 3) {
      setTool("select")
      requestRender()
      return
    }
    pushUndo()
    st.emptyDismissed = true
    updateEmptyCardVisibility()

    const minX = Math.min(...pts.map(p => p[0]))
    const minY = Math.min(...pts.map(p => p[1]))
    const maxX = Math.max(...pts.map(p => p[0]))
    const maxY = Math.max(...pts.map(p => p[1]))
    const wPx = Math.max(12, maxX - minX)
    const hPx = Math.max(12, maxY - minY)

    const normPts = pts.map(p => [
      Number(((p[0] - minX) / wPx).toFixed(4)),
      Number(((p[1] - minY) / hPx).toFixed(4))
    ])

    const targetLayerId = inferLayerForShape("custom_polygon", false)
    ensureLayerVisible(targetLayerId)

    const polyShape = normalizeShape({
      id: uid(),
      layer_id: targetLayerId,
      shape_type: "custom_polygon",
      x: Number(minX.toFixed(2)),
      y: Number(minY.toFixed(2)),
      width: Number(wPx.toFixed(2)),
      height: Number(hPx.toFixed(2)),
      rotation: 0,
      z_index: (st.shapes.length + 1) * 10,
      color: "#c2410c",
      label: "Custom Zone",
      style_json: {
        stroke_color: "#c2410c",
        stroke_width: 2,
        stroke_style: "solid",
        fill_color: "#fed7aa",
        fill_opacity: 0.80,
        font_size: 12,
        font_color: "#0f172a",
        font_weight: "bold",
        points: normPts
      }
    }, st.shapes.length)

    st.shapes.push(polyShape)
    rebuildSpatialIndex()
    st.selectedIds.clear()
    st.selectedIds.add(polyShape.id)
    setTool("select")
    renderLayerList()
    updateContextualToolbar()
    markUnsaved()
    renderFrame()
    requestRender()
  }

  // Rotate Selected Shape(s) by Delta Degrees
  function rotateSelectedBy(deltaDeg) {
    if (!st.selectedIds.size) return
    const layerMap = getLayerMap()
    const targets = Array.from(st.selectedIds)
      .map(id => st.shapeMap.get(id))
      .filter(s => s && s.shape_type !== "connector" && !isShapeLocked(s, layerMap))
    if (!targets.length) return
    pushUndo()
    targets.forEach(s => {
      s.rotation = (((Number(s.rotation || 0) + deltaDeg) % 360) + 360) % 360
    })
    rebuildSpatialIndex()
    updateContextualToolbar()
    markUnsaved()
    requestRender()
  }

  // Open Double-Click Shape Properties & Exact Size Modal
  function openShapePropsModal(targetShape) {
    const s = targetShape || (st.selectedIds.size > 0 ? st.shapeMap.get(Array.from(st.selectedIds)[0]) : null)
    if (!s) return
    if (st.autoSaveTimer) {
      clearTimeout(st.autoSaveTimer)
      st.autoSaveTimer = null
    }
    st.activeModalShapeId = s.id
    if (!st.selectedIds.has(s.id)) {
      st.selectedIds.clear()
      st.selectedIds.add(s.id)
    }
    const style = parseStyle(s)
    const setVal = (sel, val) => { const el = parentElement.querySelector(sel); if (el) el.value = val }

    const titleEl = parentElement.querySelector("#lc-prop-modal-title")
    if (titleEl) {
      const countTxt = st.selectedIds.size > 1 ? ` (${st.selectedIds.size} selected)` : ""
      titleEl.textContent = `⚙ Shape Size, Text & Appearance${countTxt}`
    }

    setVal("#lc-prop-label", s.label || "")
    setVal("#lc-prop-fsize", Number(style.font_size || 12))
    setVal("#lc-prop-tcolor", style.font_color || "#0f172a")
    setVal("#lc-prop-fweight", style.font_weight || "bold")
    setVal("#lc-prop-talign", style.text_align || "center")
    setVal("#lc-prop-trot", String(style.text_rotation || 0))

    setVal("#lc-prop-w", Number(pxToUnitsX(s.width).toFixed(2)))
    setVal("#lc-prop-h", Number(pxToUnitsY(s.height).toFixed(2)))
    setVal("#lc-prop-x", Number(pxToUnitsX(s.x).toFixed(2)))
    setVal("#lc-prop-y", Number(pxToUnitsY(s.y).toFixed(2)))
    setVal("#lc-prop-rot", Math.round(s.rotation || 0))

    setVal("#lc-prop-fill", style.fill_color || "#ffffff")
    const opPct = Math.round(Number(style.fill_opacity ?? 0.90) * 100)
    setVal("#lc-prop-opacity-range", opPct)
    setVal("#lc-prop-opacity-num", opPct)
    setVal("#lc-prop-stroke", style.stroke_color || s.color || "#1e293b")
    setVal("#lc-prop-sw", Number(style.stroke_width ?? 2))
    setVal("#lc-prop-lstyle", style.stroke_style || "solid")

    const areaSec = parentElement.querySelector("#lc-prop-area-hdr-sec")
    if (areaSec) {
      if (s.shape_type === "area_header") {
        areaSec.style.display = "block"
        setVal("#lc-prop-area-code", style.area_code || "374")
        setVal("#lc-prop-area-pills", style.area_pills || "STANDARD WORK, YAMAZUMI")
      } else {
        areaSec.style.display = "none"
      }
    }

    parentElement.querySelectorAll(".lc-unit-txt").forEach(el => { el.textContent = unitAbbr() })
    st.modalOpenedAt = performance.now()
    const modal = parentElement.querySelector("#lc-shape-props-modal")
    if (modal) modal.style.display = "flex"
    setTimeout(() => {
      const wInput = parentElement.querySelector("#lc-prop-w")
      if (wInput) {
        wInput.focus({ preventScroll: true })
        if (typeof wInput.select === "function") wInput.select()
      }
    }, 20)
  }

  function applyShapePropsModal() {
    const targetId = st.activeModalShapeId || (st.selectedIds.size > 0 ? Array.from(st.selectedIds)[0] : null)
    const s = targetId ? st.shapeMap.get(targetId) : null
    const modal = parentElement.querySelector("#lc-shape-props-modal")
    if (!s) {
      if (modal) modal.style.display = "none"
      st.activeModalShapeId = null
      return
    }
    pushUndo()
    const getVal = (sel) => {
      const el = parentElement.querySelector(sel)
      return el ? String(el.value ?? "") : ""
    }

    const labelStr = getVal("#lc-prop-label")
    const rawFSize = parseFloat(getVal("#lc-prop-fsize").trim())
    const tColorVal = getVal("#lc-prop-tcolor").trim()
    const fWeightVal = getVal("#lc-prop-fweight").trim()
    const tAlignVal = getVal("#lc-prop-talign").trim()
    const rawTxtRot = parseFloat(getVal("#lc-prop-trot").trim())

    const rawW = parseFloat(getVal("#lc-prop-w").trim())
    const rawH = parseFloat(getVal("#lc-prop-h").trim())
    const rawX = parseFloat(getVal("#lc-prop-x").trim())
    const rawY = parseFloat(getVal("#lc-prop-y").trim())
    const rawRot = parseFloat(getVal("#lc-prop-rot").trim())

    const fillVal = getVal("#lc-prop-fill").trim()
    const rawOp = parseFloat(getVal("#lc-prop-opacity-num").trim())
    const strokeVal = getVal("#lc-prop-stroke").trim()
    const rawSW = parseFloat(getVal("#lc-prop-sw").trim())
    const lStyleVal = getVal("#lc-prop-lstyle").trim()

    // Apply position & label to the primary shape when provided (preserving existing if blank)
    const labelEl = parentElement.querySelector("#lc-prop-label")
    if (labelEl) s.label = labelStr
    if (!Number.isNaN(rawX)) s.x = Number(unitsToPxX(rawX).toFixed(2))
    if (!Number.isNaN(rawY)) s.y = Number(unitsToPxY(rawY).toFixed(2))

    // Apply size, rotation, and visual styling to all currently selected shapes (preserving any blank fields)
    const targetIds = st.selectedIds.has(s.id) ? Array.from(st.selectedIds) : [s.id]
    targetIds.forEach(id => {
      const item = st.shapeMap.get(id)
      if (!item) return
      const stObj = parseStyle(item)

      const hasValidW = !Number.isNaN(rawW) && rawW > 0
      const hasValidH = !Number.isNaN(rawH) && rawH > 0
      const effWU = hasValidW ? Math.max(0.1, rawW) : pxToUnitsX(item.width)
      const effHU = hasValidH ? Math.max(0.1, rawH) : pxToUnitsY(item.height)
      const effRot = !Number.isNaN(rawRot) ? (((rawRot % 360) + 360) % 360) : Number(item.rotation || 0)

      if (item.shape_type !== "connector") {
        if (hasValidW) item.width = Math.max(4, Number(unitsToPxX(effWU).toFixed(2)))
        if (hasValidH) item.height = Math.max(4, Number(unitsToPxY(effHU).toFixed(2)))
        if (!Number.isNaN(rawRot)) item.rotation = effRot
      } else if (hasValidW || hasValidH) {
        const pts = getConnectorEndpoints(item)
        const newW = Math.max(8, Number(unitsToPxX(effWU).toFixed(2)))
        const newH = Math.max(8, Number(unitsToPxY(effHU).toFixed(2)))
        const dirX = pts.x2 >= pts.x1 ? 1 : -1
        const dirY = pts.y2 >= pts.y1 ? 1 : -1
        saveConnectorEndpoints(item, item.x, item.y, item.x + dirX * newW, item.y + dirY * newH)
      }

      const nextStroke = strokeVal || stObj.stroke_color || item.color || "#1e293b"
      item.color = nextStroke
      stObj.stroke_color = nextStroke
      if (!Number.isNaN(rawSW)) stObj.stroke_width = Math.max(0, rawSW)
      if (lStyleVal) stObj.stroke_style = lStyleVal
      if (fillVal) stObj.fill_color = fillVal
      if (!Number.isNaN(rawOp)) stObj.fill_opacity = Math.max(0, Math.min(100, rawOp)) / 100
      if (!Number.isNaN(rawFSize)) stObj.font_size = Math.max(6, Math.min(96, rawFSize))
      if (tColorVal) stObj.font_color = tColorVal
      if (fWeightVal) stObj.font_weight = fWeightVal
      if (tAlignVal) stObj.text_align = tAlignVal
      if (!Number.isNaN(rawTxtRot)) stObj.text_rotation = rawTxtRot
      stObj.custom_label = true
      if (item.shape_type === "area_header") {
        const areaCodeVal = getVal("#lc-prop-area-code").trim()
        const areaPillsVal = getVal("#lc-prop-area-pills").trim()
        if (areaCodeVal) stObj.area_code = areaCodeVal
        if (areaPillsVal) stObj.area_pills = areaPillsVal
      }
      syncStyleJson(item)
      updateShapeBounds(item)
    })

    if (modal) modal.style.display = "none"
    st.activeModalShapeId = null
    rebuildSpatialIndex()
    updateContextualToolbar()
    renderFrame()
    requestRender()
    commitCanvasToPython({ action: "save" })
  }

  function showPitchInspectorCard(shape) {
    if (!shape || !shape.pitch_id || !st.pitchMetrics[shape.pitch_id]) {
      pitchCard.style.display = "none"
      return
    }
    const pm = st.pitchMetrics[shape.pitch_id]
    const escHtml = (v) => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
    pcTitle.textContent = `🏭 Pitch ${pm.pitch_number} ${pm.pitch_name ? "— " + pm.pitch_name : ""}`
    const steps = Array.isArray(pm.steps) ? pm.steps : []
    const utilColor = pm.utilization_pct > 100 ? "#dc2626" : (pm.utilization_pct >= 85 ? "#d97706" : "#15803d")

    let stepsHtml = ""
    if (steps.length > 0) {
      stepsHtml = `<div style="max-height:110px; overflow-y:auto; margin-top:5px; border-top:1px solid #e2e8f0; padding-top:4px;">`
      steps.forEach(s => {
        stepsHtml += `
          <div style="display:flex; justify-content:space-between; gap:6px; padding:2px 0; border-bottom:1px dashed #f1f5f9;">
            <span style="font-weight:600; color:#1e293b;">#${escHtml(s.seq)} ${escHtml(s.operation)}</span>
            <span style="color:#475569; white-space:nowrap;">${Number(s.cycle_time_s).toFixed(1)}s</span>
          </div>
        `
      })
      stepsHtml += `</div>`
    }

    pcBody.innerHTML = `
      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span><strong>Area:</strong> ${escHtml(pm.area_name || "—")}</span>
        <span><strong>Status:</strong> ${escHtml(pm.pitch_status)}</span>
      </div>
      <div style="display:flex; justify-content:space-between; background:#f8fafc; padding:4px 6px; border-radius:4px; border:1px solid #e2e8f0;">
        <span><strong>CT / Takt:</strong> ${Number(pm.cycle_time_sec || 0)}s / ${Number(pm.target_takt_sec || 0)}s</span>
        <span style="font-weight:700; color:${utilColor};">${Number(pm.utilization_pct || 0)}%</span>
      </div>
      <div style="display:flex; justify-content:space-between; margin-top:4px; color:#334155;">
        <span>👷 <strong>Operators:</strong> ${Number(pm.operator_count || 0)}</span>
        <span>📋 <strong>PAAG Steps:</strong> ${Number(pm.step_count || 0)}</span>
      </div>
      ${stepsHtml}
    `
    pitchCard.style.display = "flex"
  }

  // Contextual Top Formatting Bar (Visible ONLY when 1+ shapes/connectors selected)
  function updateContextualToolbar() {
    const ctxBar = parentElement.querySelector("#lc-ctx-bar")
    if (!ctxBar) return
    if (st.selectedIds.size === 0) {
      ctxBar.style.display = "none"
      pitchCard.style.display = "none"
      return
    }
    ctxBar.style.display = "flex"
    const firstId = Array.from(st.selectedIds)[0]
    const s = st.shapeMap.get(firstId)
    if (!s) return

    const style = parseStyle(s)
    const setVal = (sel, val) => { const el = parentElement.querySelector(sel); if (el) el.value = val }

    setVal("#lc-ctx-label", s.label || "")
    setVal("#lc-ctx-fill", style.fill_color || "#ffffff")
    setVal("#lc-ctx-opacity", Math.round(Number(style.fill_opacity ?? 0.90) * 100))
    setVal("#lc-ctx-stroke", style.stroke_color || s.color || "#1e293b")
    setVal("#lc-ctx-sw", Number(style.stroke_width || 2))
    setVal("#lc-ctx-lstyle", style.stroke_style || "solid")
    setVal("#lc-ctx-fsize", Number(style.font_size || 12))
    setVal("#lc-ctx-tcolor", style.font_color || "#0f172a")
    setVal("#lc-ctx-txt-rot", String(style.text_rotation || 0))

    const connGrp = parentElement.querySelector("#lc-ctx-conn-group")
    const geomGrp = parentElement.querySelector("#lc-ctx-geom-group")
    if (s.shape_type === "connector") {
      if (connGrp) connGrp.style.display = "flex"
      if (geomGrp) geomGrp.style.display = "none"
      setVal("#lc-ctx-routing", style.routing || "orthogonal")
      setVal("#lc-ctx-arrow", style.arrow || "end")
    } else {
      if (connGrp) connGrp.style.display = "none"
      if (geomGrp) geomGrp.style.display = "flex"
      setVal("#lc-ctx-w", pxToUnitsX(s.width).toFixed(1))
      setVal("#lc-ctx-h", pxToUnitsY(s.height).toFixed(1))
      setVal("#lc-ctx-rot", Math.round(s.rotation || 0))
    }

    const pitchSel = parentElement.querySelector("#lc-ctx-pitch")
    if (pitchSel) {
      pitchSel.innerHTML = `<option value="">No Pitch Link</option>`
      const rawPid = String(s.pitch_id || "")
      const aliasedPid = rawPid && st.pitchMetrics[rawPid]?.pitch_id ? String(st.pitchMetrics[rawPid].pitch_id) : ""
      let matchedOpt = false
      st.pitches.forEach(p => {
        const opt = document.createElement("option")
        opt.value = String(p.pitch_id)
        opt.textContent = `${p.pitch_number} — ${p.pitch_name || p.area_name}`
        if (String(p.pitch_id) === rawPid || (aliasedPid && String(p.pitch_id) === aliasedPid)) {
          opt.selected = true
          matchedOpt = true
        }
        pitchSel.appendChild(opt)
      })
      if (rawPid && !matchedOpt) {
        const fallbackOpt = document.createElement("option")
        fallbackOpt.value = rawPid
        fallbackOpt.textContent = `${s.label || "Linked Pitch"} (Other Scenario)`
        fallbackOpt.selected = true
        pitchSel.appendChild(fallbackOpt)
      }
    }

    const layerSel = parentElement.querySelector("#lc-ctx-layer")
    if (layerSel) {
      layerSel.innerHTML = ""
      st.layers.forEach(l => {
        const opt = document.createElement("option")
        opt.value = l.id
        opt.textContent = l.name
        if (l.id === s.layer_id) opt.selected = true
        layerSel.appendChild(opt)
      })
    }

    const lockBtn = parentElement.querySelector("#lc-ctx-lock")
    if (lockBtn) lockBtn.textContent = s.locked ? "🔒" : "🔓"
  }

  function bindContextualInputs() {
    const applyToSelected = (fn) => {
      if (!st.selectedIds.size) return
      pushUndo()
      st.selectedIds.forEach(id => {
        const s = st.shapeMap.get(id)
        if (s) {
          fn(s, parseStyle(s))
          syncStyleJson(s)
          updateShapeBounds(s)
        }
      })
      rebuildSpatialIndex()
      renderShapeDrawer()
      renderLayerList()
      markUnsaved()
      requestRender()
    }

    const bind = (sel, evt, handler) => {
      const el = parentElement.querySelector(sel)
      if (el) el[evt] = handler
    }

    bind("#lc-ctx-label", "oninput", (e) => applyToSelected((s, stObj) => { s.label = e.target.value; stObj.custom_label = true }))
    bind("#lc-ctx-fill", "oninput", (e) => applyToSelected((s, stObj) => { stObj.fill_color = e.target.value }))
    bind("#lc-ctx-opacity", "onchange", (e) => applyToSelected((s, stObj) => {
      stObj.fill_opacity = Math.max(0, Math.min(100, Number(e.target.value) || 0)) / 100
    }))
    bind("#lc-ctx-stroke", "oninput", (e) => applyToSelected((s, stObj) => { s.color = e.target.value; stObj.stroke_color = e.target.value }))
    bind("#lc-ctx-sw", "onchange", (e) => applyToSelected((s, stObj) => { stObj.stroke_width = Number(e.target.value) || 2 }))
    bind("#lc-ctx-lstyle", "onchange", (e) => applyToSelected((s, stObj) => { stObj.stroke_style = e.target.value }))
    bind("#lc-ctx-routing", "onchange", (e) => applyToSelected((s, stObj) => { stObj.routing = e.target.value }))
    bind("#lc-ctx-arrow", "onchange", (e) => applyToSelected((s, stObj) => { stObj.arrow = e.target.value }))
    bind("#lc-ctx-w", "onchange", (e) => {
      const v = Math.max(0.2, Number(e.target.value) || 1)
      applyToSelected((s) => { s.width = Number(unitsToPxX(v).toFixed(2)) })
    })
    bind("#lc-ctx-h", "onchange", (e) => {
      const v = Math.max(0.2, Number(e.target.value) || 1)
      applyToSelected((s) => { s.height = Number(unitsToPxY(v).toFixed(2)) })
    })
    bind("#lc-ctx-rot", "onchange", (e) => {
      const v = ((Number(e.target.value) || 0) % 360 + 360) % 360
      applyToSelected((s) => { s.rotation = v })
    })
    bind("#lc-ctx-fsize", "onchange", (e) => applyToSelected((s, stObj) => { stObj.font_size = Number(e.target.value) || 12 }))
    bind("#lc-ctx-tcolor", "oninput", (e) => applyToSelected((s, stObj) => { stObj.font_color = e.target.value }))
    bind("#lc-ctx-txt-rot", "onchange", (e) => applyToSelected((s, stObj) => { stObj.text_rotation = Number(e.target.value) || 0 }))
    bind("#lc-ctx-pitch", "onchange", (e) => applyToSelected((s) => {
      s.pitch_id = e.target.value || null
      if (s.pitch_id && st.pitchMetrics[s.pitch_id]) {
        s.label = st.pitchMetrics[s.pitch_id].pitch_number
        showPitchInspectorCard(s)
      }
    }))
    bind("#lc-ctx-layer", "onchange", (e) => applyToSelected((s) => { s.layer_id = e.target.value }))
  }

  function commitCanvasToPython(extraPayload = {}) {
    const cleanShapes = st.shapes.map((s, idx) => {
      syncStyleJson(s)
      return {
        id: s.id,
        revision_id: s.revision_id,
        layer_id: s.layer_id || null,
        shape_type: s.shape_type,
        x: Number(s.x.toFixed(2)),
        y: Number(s.y.toFixed(2)),
        width: Number(s.width.toFixed(2)),
        height: Number(s.height.toFixed(2)),
        rotation: Number((s.rotation || 0).toFixed(2)),
        z_index: Number(s.z_index || (idx + 1) * 10),
        group_id: s.group_id || "",
        locked: Boolean(s.locked),
        source_shape_id: s.source_shape_id || null,
        target_shape_id: s.target_shape_id || null,
        color: s.color || "#1e293b",
        label: s.label || "",
        style_json: s.style_json || "{}",
        pitch_id: s.pitch_id || null,
        equipment_id: s.equipment_id || null
      }
    })
    const firstSel = st.selectedIds.size > 0 ? Array.from(st.selectedIds)[0] : ""
    markSynced()
    // Pre-update lastDataSig so Python's echo of this commit never overwrites live client state
    try {
      const parsedSig = JSON.parse(st.lastDataSig || "{}")
      parsedSig.scLen = cleanShapes.length
      parsedSig.shapesDigest = buildShapesDigest(cleanShapes)
      parsedSig.layersSig = (st.layers || []).map(l => `${l.id}:${l.name}:${l.visible ? 1 : 0}:${l.locked ? 1 : 0}:${l.z_index || 0}`).join("|")
      st.lastDataSig = JSON.stringify(parsedSig)
    } catch (_) {}
    setTriggerValue("canvas_commit", {
      commit_id: "c_" + Date.now() + "_" + Math.random().toString(36).slice(2, 7),
      action: extraPayload.action || "save",
      shapes: cleanShapes,
      layers: st.layers,
      selected_shape_id: firstSel,
      ...extraPayload
    })
  }

  const ctxMenuEl = parentElement.querySelector("#lc-context-menu")
  const hideContextMenu = () => { if (ctxMenuEl) ctxMenuEl.style.display = "none" }

  function getCanvasScreenCoords(ev) {
    const rect = mainCanvas.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    const logicalW = mainCanvas.width ? (mainCanvas.width / dpr) : rect.width
    const logicalH = mainCanvas.height ? (mainCanvas.height / dpr) : rect.height
    const scaleX = rect.width > 0 ? (logicalW / rect.width) : 1
    const scaleY = rect.height > 0 ? (logicalH / rect.height) : 1
    const sx = (ev.clientX - rect.left) * scaleX
    const sy = (ev.clientY - rect.top) * scaleY
    return { sx, sy, rect }
  }

  // Pointer Events on Main Canvas
  mainCanvas.onpointerdown = (ev) => {
    const { sx, sy } = getCanvasScreenCoords(ev)
    root.focus({ preventScroll: true })
    hideContextMenu()
    inlineEditor.style.display = "none"
    layersPopover.style.display = "none"
    gridPopover.style.display = "none"

    if (ev.button === 2) return // Handled by oncontextmenu

    const wpt = screenToWorld(sx, sy)
    st.mouseScreenX = sx; st.mouseScreenY = sy
    st.mouseWorldX = wpt.x; st.mouseWorldY = wpt.y

    if (ev.button === 1 || st.tool === "pan" || st.spaceDown) {
      st.interaction = { mode: "pan", startScreenX: sx, startScreenY: sy, startCamX: st.camX, startCamY: st.camY }
      mainCanvas.setPointerCapture(ev.pointerId)
      return
    }

    if (st.tool === "polygon") {
      const snapped = snapWorldCoord(wpt.x, wpt.y)
      if (st.polygonDraft.length >= 3) {
        const firstPt = st.polygonDraft[0]
        if (Math.hypot(snapped.x - firstPt[0], snapped.y - firstPt[1]) <= 12 / st.zoom) {
          finishPolygonDraft()
          return
        }
      }
      st.polygonDraft.push([snapped.x, snapped.y])
      requestRender()
      return
    }

    if (st.tool === "measure") {
      st.measureLine = { x1: wpt.x, y1: wpt.y, x2: wpt.x, y2: wpt.y }
      st.interaction = { mode: "measure", startWorldX: wpt.x, startWorldY: wpt.y }
      mainCanvas.setPointerCapture(ev.pointerId)
      requestRender()
      return
    }

    if (st.tool === "calibrate") {
      st.calibLine = { x1: wpt.x, y1: wpt.y, x2: wpt.x, y2: wpt.y }
      st.interaction = { mode: "calibrate", startWorldX: wpt.x, startWorldY: wpt.y }
      mainCanvas.setPointerCapture(ev.pointerId)
      requestRender()
      return
    }

    if (st.tool === "connector") {
      const portHit = findNearestPort(wpt.x, wpt.y, null)
      st.interaction = {
        mode: "draw_connector",
        startWorldX: portHit ? portHit.x : wpt.x,
        startWorldY: portHit ? portHit.y : wpt.y,
        sourcePort: portHit
      }
      mainCanvas.setPointerCapture(ev.pointerId)
      requestRender()
      return
    }

    const now = performance.now()
    const hit = hitTestWorld(wpt.x, wpt.y)
    const hHit = hitTestHandle(wpt.x, wpt.y)
    const dblTarget = hit || (hHit && hHit.shape ? hHit.shape : null)

    if (
      dblTarget &&
      !ev.shiftKey &&
      st.lastTapShapeId === dblTarget.id &&
      (now - (st.lastTapTime || 0)) < 450 &&
      Math.hypot(sx - (st.lastTapScreenX || 0), sy - (st.lastTapScreenY || 0)) < 24
    ) {
      st.lastTapTime = 0
      st.interaction = null
      st.selectedIds.clear()
      st.selectedIds.add(dblTarget.id)
      updateContextualToolbar()
      requestRender()
      openShapePropsModal(dblTarget)
      return
    }

    if (hHit) {
      st.lastTapShapeId = hHit.shape ? hHit.shape.id : null
      st.lastTapTime = now
      st.lastTapScreenX = sx
      st.lastTapScreenY = sy
      pushUndo()
      const s = hHit.shape
      if (hHit.handle === "rot") {
        st.interaction = {
          mode: "rotate",
          shape: s,
          centerX: s.x + s.width / 2,
          centerY: s.y + s.height / 2
        }
      } else {
        st.interaction = {
          mode: "resize", shape: s, handle: hHit.handle,
          startWorldX: wpt.x, startWorldY: wpt.y,
          origX: s.x, origY: s.y, origW: s.width, origH: s.height
        }
      }
      mainCanvas.setPointerCapture(ev.pointerId)
      return
    }

    if (hit) {
      st.lastTapShapeId = hit.id
      st.lastTapTime = now
      st.lastTapScreenX = sx
      st.lastTapScreenY = sy

      if (ev.shiftKey) {
        if (st.selectedIds.has(hit.id)) st.selectedIds.delete(hit.id)
        else st.selectedIds.add(hit.id)
      } else if (!st.selectedIds.has(hit.id)) {
        st.selectedIds.clear()
        if (hit.group_id) {
          st.shapes.forEach(gs => { if (gs.group_id === hit.group_id) st.selectedIds.add(gs.id) })
        } else {
          st.selectedIds.add(hit.id)
        }
      }

      if (hit.pitch_id) showPitchInspectorCard(hit)
      else pitchCard.style.display = "none"

      updateContextualToolbar()

      const layerMap = getLayerMap()
      const movingItems = []
      st.selectedIds.forEach(id => {
        const ms = st.shapeMap.get(id)
        if (ms && !isShapeLocked(ms, layerMap)) {
          const pts = ms.shape_type === "connector" ? getConnectorEndpoints(ms) : null
          movingItems.push({ shape: ms, origX: ms.x, origY: ms.y, pts })
        }
      })

      if (movingItems.length > 0) {
        st.interaction = {
          mode: "move", moved: false, primaryShape: hit, items: movingItems,
          startWorldX: wpt.x, startWorldY: wpt.y
        }
        mainCanvas.setPointerCapture(ev.pointerId)
      }
      requestRender()
    } else {
      st.lastTapShapeId = null
      st.lastTapTime = 0
      if (!ev.shiftKey) st.selectedIds.clear()
      pitchCard.style.display = "none"
      updateContextualToolbar()
      st.interaction = { mode: "marquee", startWorldX: wpt.x, startWorldY: wpt.y }
      mainCanvas.setPointerCapture(ev.pointerId)
      requestRender()
    }
  }

  mainCanvas.onpointermove = (ev) => {
    const { sx, sy, rect } = getCanvasScreenCoords(ev)
    const wpt = screenToWorld(sx, sy)
    st.mouseScreenX = sx; st.mouseScreenY = sy
    st.mouseWorldX = wpt.x; st.mouseWorldY = wpt.y

    const curEl = parentElement.querySelector("#lc-status-cursor")
    if (curEl) {
      curEl.textContent = `${pxToUnitsX(wpt.x).toFixed(1)}, ${pxToUnitsY(wpt.y).toFixed(1)} ${unitAbbr()}`
    }

    if (st.tool === "polygon" && st.polygonDraft.length > 0) {
      requestRender()
      return
    }

    if (!st.interaction) {
      const portHit = findNearestPort(wpt.x, wpt.y, null)
      st.hoveredPort = portHit
      const hit = portHit ? st.shapeMap.get(portHit.shapeId) : hitTestWorld(wpt.x, wpt.y)
      const nextHoverId = hit ? hit.id : null
      if (nextHoverId !== st.hoveredId || portHit) {
        st.hoveredId = nextHoverId
        requestRender()
      } else if (st.showRulers) {
        renderRulers(rect.width, rect.height, window.devicePixelRatio || 1)
      }
      return
    }

    const inter = st.interaction
    if (inter.mode === "pan") {
      st.camX = inter.startCamX + (sx - inter.startScreenX)
      st.camY = inter.startCamY + (sy - inter.startScreenY)
      requestRender()
      return
    }

    if (inter.mode === "measure" && st.measureLine) {
      st.measureLine.x2 = wpt.x; st.measureLine.y2 = wpt.y
      requestRender()
      return
    }

    if (inter.mode === "calibrate" && st.calibLine) {
      st.calibLine.x2 = wpt.x; st.calibLine.y2 = wpt.y
      requestRender()
      return
    }

    if (inter.mode === "draw_connector") {
      st.hoveredPort = findNearestPort(wpt.x, wpt.y, inter.sourcePort?.shapeId || null)
      if (st.hoveredPort) {
        st.hoveredId = st.hoveredPort.shapeId
        st.mouseWorldX = st.hoveredPort.x
        st.mouseWorldY = st.hoveredPort.y
      }
      requestRender()
      return
    }

    if (inter.mode === "rotate") {
      const s = inter.shape
      const rawDeg = (Math.atan2(wpt.y - inter.centerY, wpt.x - inter.centerX) * 180) / Math.PI + 90
      const normDeg = ((rawDeg % 360) + 360) % 360
      const snapStep = ev.shiftKey ? 15 : (ev.altKey ? 1 : 5)
      s.rotation = Math.round(normDeg / snapStep) * snapStep % 360
      floatHud.style.display = "block"
      floatHud.style.left = Math.min(rect.width - 190, sx + 14) + "px"
      floatHud.style.top = Math.max(8, sy - 32) + "px"
      floatHud.textContent = `Rotation: ${s.rotation}°`
      markUnsaved()
      requestRender()
      return
    }

    if (inter.mode === "move") {
      const dxRaw = wpt.x - inter.startWorldX
      const dyRaw = wpt.y - inter.startWorldY
      if (!inter.moved && Math.hypot(dxRaw, dyRaw) > 1.5 / st.zoom) {
        pushUndo()
        inter.moved = true
      }
      if (!inter.moved) return

      const p = inter.primaryShape
      const pFirst = inter.items.find(it => it.shape.id === p.id) || inter.items[0]
      let targetX = pFirst.origX + dxRaw
      let targetY = pFirst.origY + dyRaw

      const snapped = snapWorldCoord(targetX, targetY)
      targetX = snapped.x; targetY = snapped.y

      // Magnetic Edge-to-Edge & Center Alignment Snapping
      st.guideLines = []
      if (!ev.altKey && p.shape_type !== "connector") {
        const tol = 7 / st.zoom
        const nearby = querySpatialBox(targetX - 350, targetY - 350, targetX + p.width + 350, targetY + p.height + 350)
        for (let i = 0; i < nearby.length; i++) {
          const other = nearby[i]
          if (st.selectedIds.has(other.id) || other.shape_type === "connector") continue
          // Horizontal X snaps (left-to-right edge, right-to-left edge, left-to-left, center-to-center)
          if (Math.abs(targetX - (other.x + other.width)) < tol) {
            targetX = other.x + other.width; st.guideLines.push({ type: "v", pos: targetX })
          } else if (Math.abs((targetX + p.width) - other.x) < tol) {
            targetX = other.x - p.width; st.guideLines.push({ type: "v", pos: other.x })
          } else if (Math.abs(targetX - other.x) < tol) {
            targetX = other.x; st.guideLines.push({ type: "v", pos: targetX })
          } else if (Math.abs((targetX + p.width / 2) - (other.x + other.width / 2)) < tol) {
            targetX = other.x + other.width / 2 - p.width / 2
            st.guideLines.push({ type: "v", pos: other.x + other.width / 2 })
          }
          // Vertical Y snaps (top-to-bottom edge, bottom-to-top edge, top-to-top, middle-to-middle)
          if (Math.abs(targetY - (other.y + other.height)) < tol) {
            targetY = other.y + other.height; st.guideLines.push({ type: "h", pos: targetY })
          } else if (Math.abs((targetY + p.height) - other.y) < tol) {
            targetY = other.y - p.height; st.guideLines.push({ type: "h", pos: other.y })
          } else if (Math.abs(targetY - other.y) < tol) {
            targetY = other.y; st.guideLines.push({ type: "h", pos: targetY })
          } else if (Math.abs((targetY + p.height / 2) - (other.y + other.height / 2)) < tol) {
            targetY = other.y + other.height / 2 - p.height / 2
            st.guideLines.push({ type: "h", pos: other.y + other.height / 2 })
          }
        }
      }

      const effDx = targetX - pFirst.origX
      const effDy = targetY - pFirst.origY

      inter.items.forEach(it => {
        const s = it.shape
        if (s.shape_type === "connector" && it.pts) {
          if (!s.source_shape_id && !s.target_shape_id) {
            saveConnectorEndpoints(s, it.pts.x1 + effDx, it.pts.y1 + effDy, it.pts.x2 + effDx, it.pts.y2 + effDy)
          }
        } else {
          s.x = Number((it.origX + effDx).toFixed(2))
          s.y = Number((it.origY + effDy).toFixed(2))
          updateShapeBounds(s)
        }
      })

      floatHud.style.display = "block"
      floatHud.style.left = Math.min(rect.width - 190, sx + 14) + "px"
      floatHud.style.top = Math.max(8, sy - 32) + "px"
      floatHud.textContent = `${pxToUnitsX(p.width).toFixed(1)} × ${pxToUnitsY(p.height).toFixed(1)} ${unitAbbr()}  |  X: ${pxToUnitsX(p.x).toFixed(1)}, Y: ${pxToUnitsY(p.y).toFixed(1)}`
      markUnsaved()
      requestRender()
      return
    }

    if (inter.mode === "resize") {
      const s = inter.shape
      const hdl = inter.handle
      const snapped = snapWorldCoord(wpt.x, wpt.y)
      if (s.shape_type === "connector" && (hdl === "p1" || hdl === "p2")) {
        const pts = getConnectorEndpoints(s)
        const style = parseStyle(s)
        const portHit = findNearestPort(wpt.x, wpt.y, null)
        st.hoveredPort = portHit
        if (hdl === "p1") {
          s.source_shape_id = portHit ? portHit.shapeId : null
          if (portHit) style.source_port = portHit.port
          saveConnectorEndpoints(s, portHit ? portHit.x : snapped.x, portHit ? portHit.y : snapped.y, pts.x2, pts.y2)
        } else {
          s.target_shape_id = portHit ? portHit.shapeId : null
          if (portHit) style.target_port = portHit.port
          saveConnectorEndpoints(s, pts.x1, pts.y1, portHit ? portHit.x : snapped.x, portHit ? portHit.y : snapped.y)
        }
        markUnsaved()
        requestRender()
        return
      }
      const rawDx = snapped.x - inter.startWorldX
      const rawDy = snapped.y - inter.startWorldY
      const rad = -((s.rotation || 0) * Math.PI) / 180
      const dx = s.rotation ? (rawDx * Math.cos(rad) - rawDy * Math.sin(rad)) : rawDx
      const dy = s.rotation ? (rawDx * Math.sin(rad) + rawDy * Math.cos(rad)) : rawDy
      const minPx = 6

      let nx = inter.origX, ny = inter.origY, nw = inter.origW, nh = inter.origH
      if (hdl.includes("e")) nw = Math.max(minPx, inter.origW + dx)
      if (hdl.includes("s")) nh = Math.max(minPx, inter.origH + dy)
      if (hdl.includes("w")) {
        const cDx = Math.min(dx, inter.origW - minPx)
        nx = inter.origX + cDx; nw = inter.origW - cDx
      }
      if (hdl.includes("n")) {
        const cDy = Math.min(dy, inter.origH - minPx)
        ny = inter.origY + cDy; nh = inter.origH - cDy
      }

      s.x = Number(nx.toFixed(2)); s.y = Number(ny.toFixed(2))
      s.width = Number(nw.toFixed(2)); s.height = Number(nh.toFixed(2))
      updateShapeBounds(s)

      floatHud.style.display = "block"
      floatHud.style.left = Math.min(rect.width - 190, sx + 14) + "px"
      floatHud.style.top = Math.max(8, sy - 32) + "px"
      const wU = pxToUnitsX(s.width), hU = pxToUnitsY(s.height)
      floatHud.textContent = `${wU.toFixed(2)} × ${hU.toFixed(2)} ${unitAbbr()} (${(wU * hU).toFixed(1)} sq ${unitAbbr()})`
      markUnsaved()
      requestRender()
      return
    }

    if (inter.mode === "marquee") requestRender()
  }

  mainCanvas.onpointerup = () => {
    floatHud.style.display = "none"
    st.guideLines = []
    if (!st.interaction) return
    const inter = st.interaction
    st.interaction = null

    if (inter.mode === "move" || inter.mode === "resize" || inter.mode === "rotate") {
      rebuildSpatialIndex()
      updateContextualToolbar()
      requestRender()
      return
    }

    if (inter.mode === "marquee") {
      const x1 = Math.min(inter.startWorldX, st.mouseWorldX)
      const y1 = Math.min(inter.startWorldY, st.mouseWorldY)
      const x2 = Math.max(inter.startWorldX, st.mouseWorldX)
      const y2 = Math.max(inter.startWorldY, st.mouseWorldY)
      if (Math.hypot(x2 - x1, y2 - y1) > 4 / st.zoom) {
        const layerMap = getLayerMap()
        const boxed = querySpatialBox(x1, y1, x2, y2)
        boxed.forEach(s => {
          if (isShapeVisible(s, layerMap) && !isShapeLocked(s, layerMap)) {
            if (s._minX >= x1 && s._maxX <= x2 && s._minY >= y1 && s._maxY <= y2) {
              st.selectedIds.add(s.id)
            }
          }
        })
      }
      updateContextualToolbar()
      requestRender()
      return
    }

    if (inter.mode === "draw_connector") {
      const endPort = findNearestPort(st.mouseWorldX, st.mouseWorldY, inter.sourcePort?.shapeId || null)
      const x1 = inter.startWorldX, y1 = inter.startWorldY
      const x2 = endPort ? endPort.x : st.mouseWorldX
      const y2 = endPort ? endPort.y : st.mouseWorldY

      if (Math.hypot(x2 - x1, y2 - y1) > 8 / st.zoom) {
        pushUndo()
        const conn = normalizeShape({
          id: uid(),
          layer_id: inferLayerForShape("connector", false),
          shape_type: "connector",
          x: Math.min(x1, x2), y: Math.min(y1, y2),
          width: Math.max(8, Math.abs(x2 - x1)), height: Math.max(8, Math.abs(y2 - y1)),
          source_shape_id: inter.sourcePort ? inter.sourcePort.shapeId : null,
          target_shape_id: endPort ? endPort.shapeId : null,
          color: "#1e293b",
          label: "",
          style_json: {
            x1, y1, x2, y2,
            source_port: inter.sourcePort ? inter.sourcePort.port : "E",
            target_port: endPort ? endPort.port : "W",
            routing: "orthogonal",
            arrow: "end",
            stroke_color: "#1e293b",
            stroke_width: 2,
            stroke_style: "solid",
            font_size: 11
          }
        }, st.shapes.length)
        st.shapes.push(conn)
        rebuildSpatialIndex()
        st.selectedIds.clear()
        st.selectedIds.add(conn.id)
        renderLayerList()
        updateContextualToolbar()
        markUnsaved()
      }
      setTool("select")
      requestRender()
      return
    }

    if (inter.mode === "calibrate" && st.calibLine) {
      const distPx = Math.hypot(st.calibLine.x2 - st.calibLine.x1, st.calibLine.y2 - st.calibLine.y1)
      if (distPx > 5) {
        const modal = parentElement.querySelector("#lc-calib-modal")
        const info = parentElement.querySelector("#lc-calib-px-info")
        const unitSel = parentElement.querySelector("#lc-calib-unit")
        if (unitSel) unitSel.value = st.unit
        if (info) info.textContent = `Measured Reference Line: ${distPx.toFixed(1)} pixels on canvas.`
        if (modal) modal.style.display = "flex"
      } else {
        st.calibLine = null
      }
      requestRender()
    }
  }

  // Double-Click Shape on Canvas -> Open Full Shape Properties & Exact Size Modal
  mainCanvas.ondblclick = (ev) => {
    if (st.tool === "polygon") {
      finishPolygonDraft()
      return
    }
    const modal = parentElement.querySelector("#lc-shape-props-modal")
    if (modal && modal.style.display === "flex") return
    const { sx, sy } = getCanvasScreenCoords(ev)
    const wpt = screenToWorld(sx, sy)
    const hHit = hitTestHandle(wpt.x, wpt.y)
    const hit = hitTestWorld(wpt.x, wpt.y) || (hHit && hHit.shape ? hHit.shape : null)
    if (!hit) return

    st.interaction = null
    st.selectedIds.clear()
    st.selectedIds.add(hit.id)
    updateContextualToolbar()
    openShapePropsModal(hit)
  }

  // Right-Click Context Menu on Canvas
  mainCanvas.oncontextmenu = (ev) => {
    ev.preventDefault()
    const { sx, sy, rect } = getCanvasScreenCoords(ev)
    const wpt = screenToWorld(sx, sy)
    const hit = hitTestWorld(wpt.x, wpt.y)
    if (hit && !st.selectedIds.has(hit.id)) {
      st.selectedIds.clear()
      st.selectedIds.add(hit.id)
      updateContextualToolbar()
      requestRender()
    }
    if (st.selectedIds.size > 0 && ctxMenuEl) {
      ctxMenuEl.style.display = "flex"
      ctxMenuEl.style.left = Math.max(8, Math.min(rect.width - 220, sx)) + "px"
      ctxMenuEl.style.top = Math.max(8, Math.min(rect.height - 260, sy)) + "px"
    }
  }

  // Wheel Zoom Centered on Cursor
  mainCanvas.addEventListener("wheel", (ev) => {
    ev.preventDefault()
    const { sx, sy } = getCanvasScreenCoords(ev)
    const factor = ev.deltaY < 0 ? 1.14 : 0.88
    const nextZoom = Math.max(0.04, Math.min(10.0, st.zoom * factor))
    st.camX = sx - ((sx - st.camX) / st.zoom) * nextZoom
    st.camY = sy - ((sy - st.camY) / st.zoom) * nextZoom
    st.zoom = nextZoom
    requestRender()
  }, { passive: false })

  // Drag-and-Drop Stencils, Saved Custom Shapes & Unplaced Pitches onto Canvas
  mainCanvas.ondragover = (ev) => {
    ev.preventDefault()
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy"
  }
  mainCanvas.ondrop = (ev) => {
    ev.preventDefault()
    const payload = ev.dataTransfer ? ev.dataTransfer.getData("text/plain") : ""
    if (!payload) return
    const { sx, sy } = getCanvasScreenCoords(ev)
    const wpt = screenToWorld(sx, sy)
    if (payload.startsWith("stencil:")) {
      const stype = payload.slice("stencil:".length)
      if (stype) createStencilShape(stype, wpt.x, wpt.y)
    } else if (payload.startsWith("custom_stencil:")) {
      const cid = payload.slice("custom_stencil:".length)
      const cs = st.customStencils.find(item => String(item.id) === String(cid))
      if (cs) placeCustomStencil(cs, wpt.x, wpt.y)
    } else if (payload.startsWith("pitch:")) {
      const pid = payload.slice("pitch:".length)
      const pObj = st.pitches.find(p => String(p.pitch_id || p.id) === String(pid))
      if (pObj) placeScenarioPitchOnCanvas(pObj, wpt.x, wpt.y)
    }
  }

  // Keyboard Shortcuts
  root.onkeydown = (ev) => {
    if (ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT" || ev.target.tagName === "TEXTAREA")) return
    if (ev.code === "Space" && !st.spaceDown) {
      st.spaceDown = true
      mainCanvas.style.cursor = "grab"
    }
    if (ev.key === "Escape") {
      hideContextMenu()
      if (st.tool === "polygon") {
        st.polygonDraft = []
        setTool("select")
      }
      parentElement.querySelector("#lc-shape-props-modal").style.display = "none"
      parentElement.querySelector("#lc-custom-stencil-modal").style.display = "none"
      requestRender()
      return
    }
    if (ev.key === "Enter" && st.tool === "polygon") {
      ev.preventDefault()
      finishPolygonDraft()
      return
    }
    if (ev.key === "Home" || ((ev.ctrlKey || ev.metaKey) && ev.key === "0")) {
      ev.preventDefault()
      fitCanvasToStage()
      return
    }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") {
      ev.preventDefault()
      if (ev.shiftKey) performRedo()
      else performUndo()
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") {
      ev.preventDefault(); performRedo()
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "d") {
      ev.preventDefault(); duplicateSelected()
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "c") {
      ev.preventDefault()
      st.clipboard = Array.from(st.selectedIds).map(id => st.shapeMap.get(id)).filter(Boolean).map(s => JSON.parse(JSON.stringify(s)))
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "v") {
      ev.preventDefault()
      if (st.clipboard.length > 0) {
        pushUndo()
        st.selectedIds.clear()
        st.clipboard.forEach(orig => {
          const copy = normalizeShape({
            ...orig, id: uid(),
            x: Number(orig.x) + unitsToPxX(2),
            y: Number(orig.y) + unitsToPxY(2),
            pitch_id: null
          }, st.shapes.length)
          st.shapes.push(copy)
          st.selectedIds.add(copy.id)
        })
        rebuildSpatialIndex()
        renderLayerList()
        updateContextualToolbar()
        markUnsaved()
        requestRender()
      }
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "g") {
      ev.preventDefault(); toggleGroupSelected()
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
      ev.preventDefault(); commitCanvasToPython({ action: "save" })
    } else if (ev.key === "Delete" || ev.key === "Backspace") {
      ev.preventDefault(); deleteSelected()
    } else if (ev.key.toLowerCase() === "r") {
      ev.preventDefault()
      rotateSelectedBy(ev.shiftKey ? -90 : 90)
    } else if (ev.key.toLowerCase() === "p") {
      setTool("polygon")
    } else if (ev.key.toLowerCase() === "v") setTool("select")
    else if (ev.key.toLowerCase() === "l" || ev.key.toLowerCase() === "c") setTool("connector")
    else if (ev.key.toLowerCase() === "m") setTool("measure")
    else if (ev.key.toLowerCase() === "k") setTool("calibrate")
    else if (ev.key.toLowerCase() === "n") createStencilShape("callout")
    else if (ev.key.toLowerCase() === "t") createStencilShape("text")
    else if (ev.key.toLowerCase() === "f") createStencilShape("frame")
    else if (ev.key.toLowerCase() === "s") toggleDrawer()
  }

  root.onkeyup = (ev) => {
    if (ev.code === "Space") {
      st.spaceDown = false
      mainCanvas.style.cursor = "default"
    }
  }

  function setTool(toolName) {
    st.tool = toolName
    st.measureLine = null
    if (toolName !== "polygon") st.polygonDraft = []
    const map = {
      select: "#lc-rail-select",
      connector: "#lc-rail-connector",
      polygon: "#lc-rail-polygon",
      measure: "#lc-rail-measure"
    }
    Object.entries(map).forEach(([k, sel]) => {
      const btn = parentElement.querySelector(sel)
      if (btn) btn.classList.toggle("active", k === toolName)
    })
    const calBtn = parentElement.querySelector("#lc-btn-calibrate")
    if (calBtn) calBtn.classList.toggle("active", toolName === "calibrate")
    mainCanvas.style.cursor = toolName === "select" ? "default" : "crosshair"
    requestRender()
  }

  function toggleDrawer(forceState) {
    st.drawerOpen = forceState !== undefined ? forceState : !st.drawerOpen
    if (shapeDrawer) shapeDrawer.style.display = st.drawerOpen ? "flex" : "none"
    parentElement.querySelector("#lc-rail-shapes")?.classList.toggle("active", st.drawerOpen)
    parentElement.querySelector("#lc-btn-drawer-toggle")?.classList.toggle("active", st.drawerOpen)
    if (st.drawerOpen) renderShapeDrawer()
  }

  function duplicateSelected() {
    if (!st.selectedIds.size) return
    pushUndo()
    const newIds = new Set()
    st.selectedIds.forEach(id => {
      const orig = st.shapeMap.get(id)
      if (!orig) return
      const copy = normalizeShape({
        ...orig, id: uid(),
        x: orig.x + unitsToPxX(2),
        y: orig.y + unitsToPxY(2),
        pitch_id: null
      }, st.shapes.length)
      st.shapes.push(copy)
      newIds.add(copy.id)
    })
    st.selectedIds = newIds
    rebuildSpatialIndex()
    renderLayerList()
    updateContextualToolbar()
    markUnsaved()
    requestRender()
  }

  function deleteSelected() {
    if (!st.selectedIds.size) return
    const layerMap = getLayerMap()
    const deletedSet = new Set(
      Array.from(st.selectedIds).filter(id => {
        const s = st.shapeMap.get(id)
        return s && !isShapeLocked(s, layerMap)
      })
    )
    if (!deletedSet.size) return
    pushUndo()
    st.shapes.forEach(s => {
      if (s.shape_type === "connector" && !deletedSet.has(s.id)) {
        const dropSrc = s.source_shape_id && deletedSet.has(s.source_shape_id)
        const dropTgt = s.target_shape_id && deletedSet.has(s.target_shape_id)
        if (dropSrc || dropTgt) {
          const pts = getConnectorEndpoints(s)
          if (dropSrc) s.source_shape_id = null
          if (dropTgt) s.target_shape_id = null
          saveConnectorEndpoints(s, pts.x1, pts.y1, pts.x2, pts.y2)
        }
      }
    })
    st.shapes = st.shapes.filter(s => !deletedSet.has(s.id))
    deletedSet.forEach(id => st.selectedIds.delete(id))
    pitchCard.style.display = "none"
    rebuildSpatialIndex()
    renderShapeDrawer()
    renderLayerList()
    updateContextualToolbar()
    markUnsaved()
    requestRender()
  }

  function toggleGroupSelected() {
    if (st.selectedIds.size < 2) return
    pushUndo()
    const selectedArr = Array.from(st.selectedIds).map(id => st.shapeMap.get(id)).filter(Boolean)
    const existingGroup = selectedArr[0].group_id
    const allSame = existingGroup && selectedArr.every(s => s.group_id === existingGroup)
    const nextGroupId = allSame ? "" : ("grp_" + uid())
    selectedArr.forEach(s => { s.group_id = nextGroupId })
    markUnsaved()
    requestRender()
  }

  function alignSelected(mode) {
    const layerMap = getLayerMap()
    const arr = Array.from(st.selectedIds)
      .map(id => st.shapeMap.get(id))
      .filter(s => s && s.shape_type !== "connector" && !isShapeLocked(s, layerMap))
    if (arr.length < 2) return
    pushUndo()
    const minX = Math.min(...arr.map(s => s.x))
    const maxX = Math.max(...arr.map(s => s.x + s.width))
    const minY = Math.min(...arr.map(s => s.y))
    const maxY = Math.max(...arr.map(s => s.y + s.height))
    const midX = (minX + maxX) / 2, midY = (minY + maxY) / 2

    if (mode === "left") arr.forEach(s => { s.x = minX })
    else if (mode === "center") arr.forEach(s => { s.x = midX - s.width / 2 })
    else if (mode === "top") arr.forEach(s => { s.y = minY })
    else if (mode === "middle") arr.forEach(s => { s.y = midY - s.height / 2 })
    rebuildSpatialIndex()
    updateContextualToolbar()
    markUnsaved()
    requestRender()
  }

  // Bind UI Controls
  const onClick = (sel, fn) => { const el = parentElement.querySelector(sel); if (el) el.onclick = fn }

  onClick("#lc-btn-drawer-toggle", () => toggleDrawer())
  onClick("#lc-rail-shapes", () => toggleDrawer())
  onClick("#lc-drawer-close", () => toggleDrawer(false))
  onClick("#lc-rail-search", () => {
    toggleDrawer(true)
    setTimeout(() => parentElement.querySelector("#lc-shape-search")?.focus(), 30)
  })
  onClick("#lc-rail-select", () => setTool("select"))
  onClick("#lc-rail-note", () => createStencilShape("callout"))
  onClick("#lc-rail-text", () => createStencilShape("text"))
  onClick("#lc-rail-connector", () => setTool("connector"))
  onClick("#lc-rail-polygon", () => setTool("polygon"))
  onClick("#lc-rail-frame", () => createStencilShape("frame"))
  onClick("#lc-rail-image", () => bgFileInput?.click())
  onClick("#lc-rail-measure", () => setTool("measure"))
  onClick("#lc-rail-array", () => { parentElement.querySelector("#lc-array-modal").style.display = "flex" })
  onClick("#lc-btn-calibrate", () => setTool("calibrate"))

  // Empty card quick buttons
  onClick("#lc-empty-close", () => { st.emptyDismissed = true; updateEmptyCardVisibility() })
  onClick("#lc-empty-shapes", () => { st.emptyDismissed = true; updateEmptyCardVisibility(); toggleDrawer(true) })
  onClick("#lc-empty-pitches", () => {
    st.emptyDismissed = true
    updateEmptyCardVisibility()
    st.collapsedCats["pitches"] = false
    toggleDrawer(true)
  })
  onClick("#lc-empty-upload", () => { st.emptyDismissed = true; updateEmptyCardVisibility(); bgFileInput?.click() })

  const shapeSearch = parentElement.querySelector("#lc-shape-search")
  if (shapeSearch) shapeSearch.oninput = () => renderShapeDrawer()

  // Top bar Page Title & Scale Inputs
  const pageTitleIn = parentElement.querySelector("#lc-page-title")
  if (pageTitleIn) {
    pageTitleIn.onchange = () => {
      const val = pageTitleIn.value.trim()
      if (val && val !== st.pageTitle) {
        st.pageTitle = val
        commitCanvasToPython({ action: "rename_page", page_title: val })
      }
    }
  }

  const applyScaleInputs = () => {
    const wU = Math.max(1, Number(parentElement.querySelector("#lc-scale-w")?.value || 200))
    const hU = Math.max(1, Number(parentElement.querySelector("#lc-scale-h")?.value || 100))
    const uVal = parentElement.querySelector("#lc-scale-unit")?.value || st.unit
    st.unit = uVal
    const uIn = UNIT_TO_IN[uVal] || 12.0
    st.scalePxPerInX = st.imageWidth / (wU * uIn)
    st.scalePxPerInY = st.imageHeight / (hU * uIn)
    rulerCorner.textContent = unitAbbr()
    parentElement.querySelectorAll(".lc-unit-txt").forEach(el => { el.textContent = unitAbbr() })
    requestRender()
    commitCanvasToPython({
      action: "update_scale",
      width_value: wU,
      height_value: hU,
      unit: uVal
    })
  }
  const swIn = parentElement.querySelector("#lc-scale-w")
  const shIn = parentElement.querySelector("#lc-scale-h")
  const suIn = parentElement.querySelector("#lc-scale-unit")
  if (swIn) swIn.onchange = applyScaleInputs
  if (shIn) shIn.onchange = applyScaleInputs
  if (suIn) suIn.onchange = applyScaleInputs

  // Contextual Bar Action Buttons
  onClick("#lc-ctx-props", () => openShapePropsModal())
  onClick("#lc-ctx-rot90", () => rotateSelectedBy(90))
  onClick("#lc-ctx-weld", () => weldSelectedShapes())
  onClick("#lc-ctx-save-custom", () => openSaveCustomStencilModal())
  onClick("#lc-ctx-align-l", () => alignSelected("left"))
  onClick("#lc-ctx-align-c", () => alignSelected("center"))
  onClick("#lc-ctx-align-t", () => alignSelected("top"))
  onClick("#lc-ctx-align-m", () => alignSelected("middle"))
  onClick("#lc-ctx-front", () => {
    if (!st.selectedIds.size) return
    pushUndo()
    const maxZ = Math.max(0, ...st.shapes.map(s => s.z_index || 0))
    st.selectedIds.forEach(id => { const s = st.shapeMap.get(id); if (s) s.z_index = maxZ + 10 })
    markUnsaved(); requestRender()
  })
  onClick("#lc-ctx-back", () => {
    if (!st.selectedIds.size) return
    pushUndo()
    const minZ = Math.min(0, ...st.shapes.map(s => s.z_index || 0))
    st.selectedIds.forEach(id => { const s = st.shapeMap.get(id); if (s) s.z_index = minZ - 10 })
    markUnsaved(); requestRender()
  })
  onClick("#lc-ctx-group", () => toggleGroupSelected())
  onClick("#lc-ctx-lock", () => {
    if (!st.selectedIds.size) return
    pushUndo()
    st.selectedIds.forEach(id => { const s = st.shapeMap.get(id); if (s) s.locked = !s.locked })
    updateContextualToolbar(); markUnsaved(); requestRender()
  })
  onClick("#lc-ctx-dup", () => duplicateSelected())
  onClick("#lc-ctx-del", () => deleteSelected())

  // Right-Click Context Menu Action Bindings
  onClick("#lc-cm-props", () => { hideContextMenu(); openShapePropsModal() })
  onClick("#lc-cm-rot90", () => { hideContextMenu(); rotateSelectedBy(90) })
  onClick("#lc-cm-rot-ccw", () => { hideContextMenu(); rotateSelectedBy(-90) })
  onClick("#lc-cm-txt-rot", () => {
    hideContextMenu()
    if (!st.selectedIds.size) return
    pushUndo()
    st.selectedIds.forEach(id => {
      const s = st.shapeMap.get(id)
      if (!s) return
      const stObj = parseStyle(s)
      const cur = Number(stObj.text_rotation || 0)
      stObj.text_rotation = cur === -90 ? 0 : -90
      syncStyleJson(s)
    })
    updateContextualToolbar(); markUnsaved(); requestRender()
  })
  onClick("#lc-cm-dup", () => { hideContextMenu(); duplicateSelected() })
  onClick("#lc-cm-weld", () => { hideContextMenu(); weldSelectedShapes() })
  onClick("#lc-cm-save-custom", () => { hideContextMenu(); openSaveCustomStencilModal() })
  onClick("#lc-cm-group", () => { hideContextMenu(); toggleGroupSelected() })
  onClick("#lc-cm-front", () => {
    hideContextMenu()
    if (!st.selectedIds.size) return
    pushUndo()
    const maxZ = Math.max(0, ...st.shapes.map(s => s.z_index || 0))
    st.selectedIds.forEach(id => { const s = st.shapeMap.get(id); if (s) s.z_index = maxZ + 10 })
    markUnsaved(); requestRender()
  })
  onClick("#lc-cm-back", () => {
    hideContextMenu()
    if (!st.selectedIds.size) return
    pushUndo()
    const minZ = Math.min(0, ...st.shapes.map(s => s.z_index || 0))
    st.selectedIds.forEach(id => { const s = st.shapeMap.get(id); if (s) s.z_index = minZ - 10 })
    markUnsaved(); requestRender()
  })
  onClick("#lc-cm-lock", () => {
    hideContextMenu()
    if (!st.selectedIds.size) return
    pushUndo()
    st.selectedIds.forEach(id => { const s = st.shapeMap.get(id); if (s) s.locked = !s.locked })
    updateContextualToolbar(); markUnsaved(); requestRender()
  })
  onClick("#lc-cm-del", () => { hideContextMenu(); deleteSelected() })

  // Double-Click Shape Properties Modal Bindings
  const spModalEl = parentElement.querySelector("#lc-shape-props-modal")
  const closeSpModal = () => {
    st.activeModalShapeId = null
    if (spModalEl) spModalEl.style.display = "none"
  }
  onClick("#lc-prop-close-x", closeSpModal)
  onClick("#lc-prop-cancel", closeSpModal)
  onClick("#lc-prop-apply", (ev) => {
    if (ev) { ev.preventDefault(); ev.stopPropagation() }
    applyShapePropsModal()
  })
  onClick("#lc-prop-save-custom", (ev) => {
    if (ev) { ev.preventDefault(); ev.stopPropagation() }
    if (st.activeModalShapeId && !st.selectedIds.has(st.activeModalShapeId)) {
      st.selectedIds.clear()
      st.selectedIds.add(st.activeModalShapeId)
    }
    applyShapePropsModal()
    openSaveCustomStencilModal()
  })
  if (spModalEl) {
    spModalEl.onpointerdown = (ev) => {
      if (ev.target === spModalEl && (performance.now() - (st.modalOpenedAt || 0)) > 300) {
        closeSpModal()
      }
    }
    spModalEl.onkeydown = (ev) => {
      if (ev.key === "Enter" && ev.target && ev.target.tagName !== "TEXTAREA") {
        ev.preventDefault()
        ev.stopPropagation()
        applyShapePropsModal()
      } else if (ev.key === "Escape") {
        ev.preventDefault()
        ev.stopPropagation()
        closeSpModal()
      }
    }
  }
  parentElement.querySelectorAll(".lc-rot-preset").forEach(btn => {
    btn.onclick = () => {
      const rot = Number(btn.getAttribute("data-rot") || 0)
      const el = parentElement.querySelector("#lc-prop-rot")
      if (el) el.value = rot
    }
  })

  const opRange = parentElement.querySelector("#lc-prop-opacity-range")
  const opNum = parentElement.querySelector("#lc-prop-opacity-num")
  if (opRange && opNum) {
    opRange.oninput = () => { opNum.value = opRange.value }
    opNum.oninput = () => { opRange.value = opNum.value }
  }
  onClick("#lc-prop-op-zero", () => {
    if (opRange) opRange.value = 0
    if (opNum) opNum.value = 0
  })

  parentElement.querySelectorAll("#lc-prop-tcolor-swatches .lc-swatch").forEach(sw => {
    sw.onclick = () => {
      const col = sw.getAttribute("data-color")
      if (col) {
        const tcIn = parentElement.querySelector("#lc-prop-tcolor")
        if (tcIn) tcIn.value = col
      }
    }
  })

  parentElement.querySelectorAll("#lc-prop-fill-swatches .lc-swatch").forEach(sw => {
    sw.onclick = () => {
      const col = sw.getAttribute("data-color")
      if (col) {
        const fillIn = parentElement.querySelector("#lc-prop-fill")
        if (fillIn) fillIn.value = col
      }
      if (sw.hasAttribute("data-op")) {
        const opVal = Number(sw.getAttribute("data-op") || 0)
        if (opRange) opRange.value = opVal
        if (opNum) opNum.value = opVal
      } else if (opNum && Number(opNum.value) === 0) {
        if (opRange) opRange.value = 85
        opNum.value = 85
      }
    }
  })

  parentElement.querySelectorAll("#lc-prop-stroke-swatches .lc-swatch").forEach(sw => {
    sw.onclick = () => {
      const col = sw.getAttribute("data-color")
      if (col) {
        const strokeIn = parentElement.querySelector("#lc-prop-stroke")
        if (strokeIn) strokeIn.value = col
      }
    }
  })

  // Save Custom Stencil Modal Bindings
  onClick("#lc-custom-stencil-cancel", () => {
    const csModal = parentElement.querySelector("#lc-custom-stencil-modal")
    if (csModal) csModal.style.display = "none"
  })
  onClick("#lc-custom-stencil-save", () => saveSelectedAsCustomStencil())

  // Right Top Bar Controls
  const overlaySel = parentElement.querySelector("#lc-overlay-mode")
  if (overlaySel) {
    overlaySel.value = st.overlayMode
    overlaySel.onchange = (e) => { st.overlayMode = e.target.value; requestRender() }
  }
  onClick("#lc-btn-flow-chain", () => {
    st.showPitchChain = !st.showPitchChain
    parentElement.querySelector("#lc-btn-flow-chain")?.classList.toggle("active", st.showPitchChain)
    requestRender()
  })
  onClick("#lc-btn-export-png", () => {
    const offCanvas = document.createElement("canvas")
    offCanvas.width = Math.max(100, Math.round(st.imageWidth))
    offCanvas.height = Math.max(100, Math.round(st.imageHeight))
    const octx = offCanvas.getContext("2d")
    octx.fillStyle = "#ffffff"
    octx.fillRect(0, 0, offCanvas.width, offCanvas.height)
    const layerMap = getLayerMap()
    const facLayer = st.layers.find(l => l.name.toLowerCase().includes("facility"))
    const facVisible = facLayer ? facLayer.visible : true
    const facOpacity = facLayer ? Number(facLayer.opacity ?? 1.0) : 1.0
    if (st.bgImage && facVisible && !st.isBlankCanvas) {
      octx.save()
      octx.globalAlpha = facOpacity
      octx.drawImage(st.bgImage, 0, 0, st.imageWidth, st.imageHeight)
      octx.restore()
    }
    const prevSel = new Set(st.selectedIds)
    const prevHov = st.hoveredId
    const prevZoom = st.zoom
    st.selectedIds.clear()
    st.hoveredId = null
    st.zoom = 1.0
    const layerOrder = new Map()
    st.layers.forEach((l, idx) => layerOrder.set(l.id, Number(l.z_index || idx * 10)))
    const exportShapes = [...st.shapes].sort((a, b) => {
      const la = layerOrder.get(a.layer_id) || 0
      const lb = layerOrder.get(b.layer_id) || 0
      if (la !== lb) return la - lb
      return (a.z_index || 0) - (b.z_index || 0)
    })
    if (st.showPitchChain) drawPitchSequenceChain(octx, layerMap)
    for (let i = 0; i < exportShapes.length; i++) {
      const s = exportShapes[i]
      const layer = layerMap.get(s.layer_id)
      if (layer && !layer.visible) continue
      const layerAlpha = layer ? Number(layer.opacity ?? 1.0) : 1.0
      drawShapeOnCanvas(octx, s, layerAlpha, false)
    }
    st.selectedIds = prevSel
    st.hoveredId = prevHov
    st.zoom = prevZoom
    const link = document.createElement("a")
    link.download = `${(st.pageTitle || "pin_map").replace(/\s+/g, "_")}.png`
    link.href = offCanvas.toDataURL("image/png")
    link.click()
  })
  onClick("#lc-btn-save", () => commitCanvasToPython({ action: "save" }))

  // Bottom Bar Controls & Popovers
  onClick("#lc-btn-add-page", () => {
    const nextNum = (st.pages.length || 1) + 1
    commitCanvasToPython({ action: "add_page", page_title: `Page ${nextNum}` })
  })
  onClick("#lc-btn-layers-pop", () => {
    const open = layersPopover.style.display === "none"
    layersPopover.style.display = open ? "block" : "none"
    gridPopover.style.display = "none"
    parentElement.querySelector("#lc-btn-layers-pop")?.classList.toggle("active", open)
    if (open) renderLayerList()
  })
  onClick("#lc-layers-close", () => {
    layersPopover.style.display = "none"
    parentElement.querySelector("#lc-btn-layers-pop")?.classList.remove("active")
  })
  onClick("#lc-btn-grid-pop", () => {
    const open = gridPopover.style.display === "none"
    gridPopover.style.display = open ? "block" : "none"
    layersPopover.style.display = "none"
    parentElement.querySelector("#lc-btn-grid-pop")?.classList.toggle("active", open)
  })
  onClick("#lc-grid-close", () => {
    gridPopover.style.display = "none"
    parentElement.querySelector("#lc-btn-grid-pop")?.classList.remove("active")
  })

  onClick("#lc-btn-upload-bg", () => bgFileInput?.click())
  onClick("#lc-btn-clear-bg", () => {
    if (!window.confirm("Clear the background floorplan image and revert to a blank grid?\n\nDownstream effects: Removes the background drawing image from this layout revision and switches the canvas to a scaled blank grid. All placed Pin Map shapes, workstation pitches, equipment placements, and layers are preserved.")) return
    st.bgImage = null
    st.bgImageUrl = ""
    st.isBlankCanvas = true
    updateEmptyCardVisibility()
    renderFrame()
    commitCanvasToPython({ action: "clear_background" })
  })
  onClick("#lc-btn-sec-std", () => commitCanvasToPython({ action: "open_section_standards" }))
  onClick("#lc-btn-cad-rev", () => commitCanvasToPython({ action: "open_cad_revisions" }))

  if (bgFileInput) {
    bgFileInput.onchange = (ev) => {
      const file = ev.target.files && ev.target.files[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = () => {
        const dataUrl = String(reader.result || "")
        if (!dataUrl.startsWith("data:image/")) return
        const img = new Image()
        img.onload = () => {
          st.bgImage = img
          st.bgImageUrl = dataUrl
          st.isBlankCanvas = false
          st.emptyDismissed = true
          const facLayer = st.layers.find(l => l.name.toLowerCase().includes("facility") || l.name.toLowerCase().includes("floor"))
          if (facLayer) ensureLayerVisible(facLayer.id)
          const natW = Math.max(100, Number(img.naturalWidth || img.width || st.imageWidth))
          const natH = Math.max(100, Number(img.naturalHeight || img.height || st.imageHeight))
          const curWU = Math.max(1, Number(pxToUnitsX(st.imageWidth).toFixed(2)))
          const nextHU = Math.max(1, Number((curWU * (natH / natW)).toFixed(2)))
          st.imageWidth = natW
          st.imageHeight = natH
          const uIn = UNIT_TO_IN[st.unit] || 12.0
          st.scalePxPerInX = natW / (curWU * uIn)
          st.scalePxPerInY = natH / (nextHU * uIn)
          const shEl = parentElement.querySelector("#lc-scale-h")
          if (shEl) shEl.value = Number(nextHU.toFixed(1))
          updateEmptyCardVisibility()
          fitCanvasToStage()
          renderFrame()
          commitCanvasToPython({ action: "upload_background", background_data_url: dataUrl })
        }
        img.src = dataUrl
      }
      reader.readAsDataURL(file)
      bgFileInput.value = ""
    }
  }

  const chkRulers = parentElement.querySelector("#lc-chk-rulers")
  if (chkRulers) {
    chkRulers.checked = st.showRulers
    chkRulers.onchange = (e) => {
      st.showRulers = e.target.checked
      centerWrap.classList.toggle("no-rulers", !st.showRulers)
      requestRender()
    }
  }
  const chkGrid = parentElement.querySelector("#lc-chk-grid")
  if (chkGrid) {
    chkGrid.checked = st.showGrid
    chkGrid.onchange = (e) => { st.showGrid = e.target.checked; requestRender() }
  }
  const snapSel = parentElement.querySelector("#lc-snap-step")
  if (snapSel) {
    snapSel.value = st.snapStepUnits
    snapSel.onchange = (e) => { st.snapStepUnits = e.target.value }
  }
  const chkAutoLayer = parentElement.querySelector("#lc-chk-autolayer")
  if (chkAutoLayer) {
    chkAutoLayer.checked = st.autoLayer
    chkAutoLayer.onchange = (e) => { st.autoLayer = e.target.checked }
  }

  onClick("#lc-btn-undo", () => performUndo())
  onClick("#lc-btn-redo", () => performRedo())
  onClick("#lc-zoom-in", () => zoomAroundPoint(1.25))
  onClick("#lc-zoom-out", () => zoomAroundPoint(1 / 1.25))
  onClick("#lc-zoom-fit", () => fitCanvasToStage())
  onClick("#lc-btn-center-grid", () => fitCanvasToStage())
  onClick("#lc-rail-center-grid", () => fitCanvasToStage())
  onClick("#lc-return-grid-btn", () => fitCanvasToStage())
  onClick("#lc-fullscreen", () => {
    if (!document.fullscreenElement) root.requestFullscreen?.()
    else document.exitFullscreen?.()
  })

  onClick("#lc-btn-add-layer", () => {
    const name = window.prompt("New Layer Name:", `Custom Layer ${st.layers.length + 1}`)
    if (!name || !name.trim()) return
    pushUndo()
    const colors = ["#2563eb", "#0d9488", "#ea580c", "#7c3aed", "#dc2626", "#ca8a04"]
    const newL = {
      id: "layer_" + uid(),
      name: name.trim(),
      visible: true,
      locked: false,
      opacity: 1.0,
      z_index: (st.layers.length + 1) * 10,
      color: colors[st.layers.length % colors.length]
    }
    st.layers.push(newL)
    st.activeLayerId = newL.id
    markUnsaved()
    renderLayerList()
    updateContextualToolbar()
  })

  if (pcClose) pcClose.onclick = () => { pitchCard.style.display = "none" }

  // 2-Point Scale Calibration Modal
  onClick("#lc-calib-cancel", () => {
    st.calibLine = null
    parentElement.querySelector("#lc-calib-modal").style.display = "none"
    setTool("select")
    requestRender()
  })
  onClick("#lc-calib-apply", () => {
    if (!st.calibLine) return
    const distVal = Math.max(0.01, Number(parentElement.querySelector("#lc-calib-dist")?.value || 20))
    const unitVal = parentElement.querySelector("#lc-calib-unit")?.value || st.unit
    const pxDist = Math.hypot(st.calibLine.x2 - st.calibLine.x1, st.calibLine.y2 - st.calibLine.y1)
    const uIn = UNIT_TO_IN[unitVal] || 12.0
    const newPxPerIn = pxDist / (distVal * uIn)

    st.unit = unitVal
    st.scalePxPerInX = newPxPerIn
    st.scalePxPerInY = newPxPerIn
    rulerCorner.textContent = unitAbbr()
    parentElement.querySelectorAll(".lc-unit-txt").forEach(el => { el.textContent = unitAbbr() })

    const calibPayload = {
      x1_px: st.calibLine.x1, y1_px: st.calibLine.y1,
      x2_px: st.calibLine.x2, y2_px: st.calibLine.y2,
      real_distance: distVal, unit: unitVal
    }
    st.calibLine = null
    parentElement.querySelector("#lc-calib-modal").style.display = "none"
    setTool("select")
    requestRender()
    commitCanvasToPython({ action: "calibrate_scale", scale_calibration: calibPayload })
  })

  // Grid / Array Stamp & 20K Generator Modal
  onClick("#lc-arr-cancel", () => { parentElement.querySelector("#lc-array-modal").style.display = "none" })
  onClick("#lc-arr-preset-500", () => {
    parentElement.querySelector("#lc-arr-cols").value = 25
    parentElement.querySelector("#lc-arr-rows").value = 20
    parentElement.querySelector("#lc-arr-gapx").value = 0.5
    parentElement.querySelector("#lc-arr-gapy").value = 1.5
  })
  onClick("#lc-arr-preset-2500", () => {
    parentElement.querySelector("#lc-arr-cols").value = 50
    parentElement.querySelector("#lc-arr-rows").value = 50
    parentElement.querySelector("#lc-arr-gapx").value = 0.5
    parentElement.querySelector("#lc-arr-gapy").value = 0.5
  })
  onClick("#lc-arr-preset-20k", () => {
    parentElement.querySelector("#lc-arr-cols").value = 200
    parentElement.querySelector("#lc-arr-rows").value = 100
    parentElement.querySelector("#lc-arr-gapx").value = 0.2
    parentElement.querySelector("#lc-arr-gapy").value = 0.2
  })
  onClick("#lc-arr-apply", () => {
    const cols = Math.max(1, Math.min(250, Number(parentElement.querySelector("#lc-arr-cols")?.value || 10)))
    const rows = Math.max(1, Math.min(250, Number(parentElement.querySelector("#lc-arr-rows")?.value || 2)))
    const gapX = unitsToPxX(Number(parentElement.querySelector("#lc-arr-gapx")?.value || 1))
    const gapY = unitsToPxY(Number(parentElement.querySelector("#lc-arr-gapy")?.value || 2))

    pushUndo()
    const firstId = st.selectedIds.size > 0 ? Array.from(st.selectedIds)[0] : null
    const template = firstId ? st.shapeMap.get(firstId) : null

    const totalNew = cols * rows
    const isMassTest = totalNew >= 2000
    const wPx = template ? template.width : (isMassTest ? Math.max(4, st.imageWidth / (cols * 1.35)) : unitsToPxX(8))
    const hPx = template ? template.height : (isMassTest ? Math.max(4, st.imageHeight / (rows * 1.35)) : unitsToPxY(5))
    const startX = template ? template.x : unitsToPxX(2)
    const startY = template ? template.y : unitsToPxY(2)
    const effGapX = isMassTest ? wPx * 0.25 : gapX
    const effGapY = isMassTest ? hPx * 0.25 : gapY
    const targetLayerId = template ? template.layer_id : (st.activeLayerId || (st.layers[0]?.id || ""))

    let seq = 1
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (template && r === 0 && c === 0) { seq++; continue }
        const s = normalizeShape({
          id: uid(),
          layer_id: targetLayerId,
          shape_type: template ? template.shape_type : "rectangle",
          x: Number((startX + c * (wPx + effGapX)).toFixed(2)),
          y: Number((startY + r * (hPx + effGapY)).toFixed(2)),
          width: Number(wPx.toFixed(2)),
          height: Number(hPx.toFixed(2)),
          color: template ? template.color : "#1e293b",
          label: template ? `${template.label}-${seq}` : `P-${seq}`,
          style_json: template ? template.style_json : {
            stroke_color: "#1e293b",
            stroke_width: 1.5,
            fill_color: "#ffffff",
            fill_opacity: 0.90,
            font_size: 11
          }
        }, st.shapes.length)
        st.shapes.push(s)
        seq++
      }
    }

    parentElement.querySelector("#lc-array-modal").style.display = "none"
    st.emptyDismissed = true
    updateEmptyCardVisibility()
    rebuildSpatialIndex()
    renderLayerList()
    updateContextualToolbar()
    markUnsaved()
    renderFrame()
  })

  // Initial UI Population
  renderPageTabs()
  renderLayerList()
  renderShapeDrawer()
  updateContextualToolbar()
  bindContextualInputs()
  updateUndoRedoButtons()
  renderFrame()
  requestRender()

  const resizeObserver = new ResizeObserver(() => {
    if (!st.hasFittedStage && stage.clientWidth > 50 && stage.clientHeight > 50) {
      fitCanvasToStage()
    }
    renderFrame()
  })
  resizeObserver.observe(stage)
  return () => {
    resizeObserver.disconnect()
    if (st.rafId) {
      cancelAnimationFrame(st.rafId)
      st.rafId = 0
    }
    st.needsRender = false
  }
}
"""

_LAYOUT_CANVAS = st.components.v2.component(
    "paag_layout_canvas_v18",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def layout_image_data_url(image_path: str, modified_ns: int) -> str:
    """Read a local layout image file and encode it as a high-fidelity data URL."""
    del modified_ns
    if not image_path:
        return ""
    from utils.media_cache import cached_image_data_url

    return cached_image_data_url(
        image_path, max_dim=None, output_format="WEBP", quality=88
    ) or ""


def layout_canvas(
    image_url: str,
    image_width: int,
    image_height: int,
    scale_factor_px_per_in: float,
    unit: str,
    shapes: list[dict[str, Any]],
    selected_shape_id: str | None = None,
    *,
    scale_factor_px_per_in_x: float | None = None,
    scale_factor_px_per_in_y: float | None = None,
    layers: list[dict[str, Any]] | None = None,
    pitches: list[dict[str, Any]] | None = None,
    pitch_metrics: dict[str, dict[str, Any]] | None = None,
    section_standards: dict[str, dict[str, Any]] | None = None,
    custom_stencils: list[dict[str, Any]] | None = None,
    pages: list[dict[str, Any]] | None = None,
    active_page_id: str | None = None,
    page_title: str | None = None,
    is_blank_canvas: bool = False,
    key: str,
    on_select_shape: Callable[[], None] | None = None,
    on_shape_moved: Callable[[], None] | None = None,
    on_canvas_commit: Callable[[], None] | None = None,
) -> Any:
    """Render the interactive Lucidchart-style Pin Map & Floor Plan Layout Canvas.

    Falls back safely if executed outside a browser context (e.g. headless unit tests).
    """
    spx_x = float(
        scale_factor_px_per_in_x
        if scale_factor_px_per_in_x is not None
        else scale_factor_px_per_in
    )
    spx_y = float(
        scale_factor_px_per_in_y
        if scale_factor_px_per_in_y is not None
        else scale_factor_px_per_in
    )
    try:
        return _LAYOUT_CANVAS(
            key=key,
            data={
                "imageUrl": image_url,
                "imageWidth": int(image_width),
                "imageHeight": int(image_height),
                "scalePxPerIn": spx_x,
                "scalePxPerInX": spx_x,
                "scalePxPerInY": spx_y,
                "unit": str(unit),
                "shapes": shapes,
                "layers": layers or [],
                "pitches": pitches or [],
                "pitch_metrics": pitch_metrics or {},
                "section_standards": section_standards or {},
                "customStencils": custom_stencils or [],
                "pages": pages or [],
                "activePageId": str(active_page_id or ""),
                "pageTitle": str(page_title or "Page 1"),
                "isBlankCanvas": bool(is_blank_canvas),
                "selectedShapeId": str(selected_shape_id or ""),
            },
            on_select_shape_change=on_select_shape,
            on_shape_moved_change=on_shape_moved,
            on_canvas_commit_change=on_canvas_commit,
            width="stretch",
            height="content",
        )
    except Exception:
        return None

