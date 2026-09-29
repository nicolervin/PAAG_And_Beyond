"""Interactive 2D plant floor plan layout canvas component with SVG rendering,

pan/zoom, and shape manipulation.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Callable

import streamlit as st
from PIL import Image

_HTML = """
<div class="layout-shell">
  <div class="layout-toolbar">
    <div class="layout-title">
      <strong id="layout-title-text">2D Floor Plan Canvas</strong>
      <span id="layout-scale-badge"></span>
    </div>
    <div class="layout-actions">
      <button id="btn-zoom-out" type="button" title="Zoom out">−</button>
      <button id="btn-zoom-in" type="button" title="Zoom in">+</button>
      <button id="btn-fit" type="button" title="Fit to viewport">Fit</button>
      <button id="btn-reset" type="button" title="Actual size (100%)">100%</button>
      <button id="btn-fullscreen" type="button" title="Full screen">Full screen</button>
    </div>
  </div>
  <div class="layout-viewport">
    <svg id="layout-svg" role="img" aria-label="Floor plan layout canvas">
      <defs id="layout-defs"></defs>
      <g id="layout-world">
        <image id="layout-bg-img" preserveAspectRatio="none"></image>
        <g id="layout-shapes-layer"></g>
        <g id="layout-snap-guides"></g>
        <g id="layout-handles-layer"></g>
      </g>
    </svg>
    <div id="layout-hud" class="layout-hud">
      <span id="hud-coords">X: 0, Y: 0</span>
      <span id="hud-shape-info"></span>
    </div>
    <div class="layout-hint">Scroll to zoom · Drag canvas to pan · Click shape to select / drag to move</div>
  </div>
</div>
"""

_CSS = """
:host {
  color: var(--st-text-color, #1a1a1a);
  font-family: var(--st-font, sans-serif);
}
.layout-shell {
  box-sizing: border-box;
  width: 100%;
  height: 640px;
  min-height: 500px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--st-border-color, #d0d7de);
  border-radius: var(--st-base-radius, 8px);
  overflow: hidden;
  background: var(--st-background-color, #ffffff);
}
.layout-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--st-border-color, #d0d7de);
  background: var(--st-secondary-background-color, #f6f8fa);
}
.layout-title {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.layout-title span {
  color: var(--st-secondary-text-color, #57606a);
  font-size: .82rem;
  white-space: nowrap;
}
.layout-actions {
  display: flex;
  gap: 6px;
}
.layout-actions button {
  min-width: 32px;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--st-border-color, #d0d7de);
  border-radius: var(--st-button-radius, 6px);
  color: var(--st-text-color, #1a1a1a);
  background: var(--st-background-color, #ffffff);
  cursor: pointer;
  font: inherit;
  font-size: .85rem;
  font-weight: 600;
}
.layout-actions button:hover {
  border-color: var(--st-primary-color, #1976d2);
  color: var(--st-primary-color, #1976d2);
}
.layout-viewport {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  background-color: var(--st-background-color, #ffffff);
  background-image: radial-gradient(circle, color-mix(in srgb, var(--st-text-color, #000) 10%, transparent) 1px, transparent 1px);
  background-size: 20px 20px;
  touch-action: none;
}
#layout-svg {
  display: block;
  width: 100%;
  height: 100%;
  cursor: grab;
  user-select: none;
}
#layout-svg.dragging {
  cursor: grabbing;
}
.layout-shape {
  cursor: pointer;
  transition: filter .12s ease;
}
.layout-shape:hover {
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, .25));
}
.layout-shape.selected {
  filter: drop-shadow(0 3px 8px rgba(25, 118, 210, .4));
}
.layout-handle {
  fill: #ffffff;
  stroke: #1976d2;
  stroke-width: 2;
  cursor: nwse-resize;
}
.layout-handle.ne, .layout-handle.sw {
  cursor: nesw-resize;
}
.snap-guide {
  stroke: #00bcd4;
  stroke-width: 1.5;
  stroke-dasharray: 4 4;
  pointer-events: none;
}
.layout-hud {
  position: absolute;
  left: 12px;
  bottom: 10px;
  display: flex;
  gap: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--st-background-color, #fff) 90%, transparent);
  border: 1px solid var(--st-border-color, #d0d7de);
  font-size: .75rem;
  font-family: monospace;
  pointer-events: none;
  box-shadow: 0 1px 3px rgba(0,0,0,.08);
}
.layout-hint {
  position: absolute;
  right: 12px;
  bottom: 10px;
  padding: 4px 8px;
  border-radius: 6px;
  color: var(--st-secondary-text-color, #57606a);
  background: color-mix(in srgb, var(--st-background-color, #fff) 88%, transparent);
  font-size: .75rem;
  pointer-events: none;
}
.layout-shell:fullscreen {
  width: 100vw;
  height: 100vh;
  min-height: 0;
  border: 0;
  border-radius: 0;
}
.layout-shell:fullscreen .layout-viewport {
  min-height: 0;
}
"""

_JS = """
const SVG_NS = "http://www.w3.org/2000/svg"
const instanceState = new WeakMap()

function svgEl(name, attrs = {}) {
  const el = document.createElementNS(SVG_NS, name)
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)))
  return el
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v))
}

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]))
}

export default function(component) {
  const { data, parentElement, setTriggerValue } = component
  const shell = parentElement.querySelector(".layout-shell")
  const viewport = parentElement.querySelector(".layout-viewport")
  const svg = parentElement.querySelector("#layout-svg")
  const world = parentElement.querySelector("#layout-world")
  const defs = parentElement.querySelector("#layout-defs")
  const bgImg = parentElement.querySelector("#layout-bg-img")
  const shapesLayer = parentElement.querySelector("#layout-shapes-layer")
  const snapGuides = parentElement.querySelector("#layout-snap-guides")
  const handlesLayer = parentElement.querySelector("#layout-handles-layer")
  const scaleBadge = parentElement.querySelector("#layout-scale-badge")
  const hudCoords = parentElement.querySelector("#hud-coords")
  const hudShapeInfo = parentElement.querySelector("#hud-shape-info")

  if (!shell || !viewport || !svg || !world || !data) return

  let state = instanceState.get(parentElement)
  if (!state) {
    state = {
      scale: 1,
      x: 0,
      y: 0,
      isPanning: false,
      panningX: 0,
      panningY: 0,
      draggingShape: null,
      resizingHandle: null,
      dragStartX: 0,
      dragStartY: 0,
      shapeStart: null,
      fitted: false,
      selectedId: data.selectedShapeId || "",
      lastWidth: 0,
      lastHeight: 0
    }
    instanceState.set(parentElement, state)
  }

  if (data.selectedShapeId !== undefined && data.selectedShapeId !== state.selectedId) {
    state.selectedId = data.selectedShapeId
  }

  const imgW = Number(data.imageWidth || 1000)
  const imgH = Number(data.imageHeight || 800)
  const pxPerIn = Number(data.scalePxPerIn || 1.0)
  const unit = String(data.unit || "feet")

  const unitFactor = (unit === "feet") ? 12.0 : (unit === "yards" ? 36.0 : (unit === "miles" ? 63360.0 : 1.0))

  function pxToDisplay(px) {
    const inches = px / pxPerIn
    const val = inches / unitFactor
    return val >= 10 ? val.toFixed(1) : val.toFixed(2)
  }

  function formatDim(px) {
    return `${pxToDisplay(px)} ${unit}`
  }

  // Update background image
  if (data.imageUrl) {
    bgImg.setAttribute("href", data.imageUrl)
    bgImg.setAttribute("x", "0")
    bgImg.setAttribute("y", "0")
    bgImg.setAttribute("width", String(imgW))
    bgImg.setAttribute("height", String(imgH))
  }

  // Scale badge
  scaleBadge.textContent = `${imgW}×${imgH} px · 1 ${unit} = ${(pxPerIn * unitFactor).toFixed(1)} px`

  // Build arrow marker in defs
  defs.replaceChildren()
  const marker = svgEl("marker", {
    id: "arrow-head",
    viewBox: "0 0 10 10",
    refX: "7",
    refY: "5",
    markerWidth: "6",
    markerHeight: "6",
    orient: "auto-start-reverse"
  })
  const arrowPath = svgEl("path", {
    d: "M 0 1 L 10 5 L 0 9 z",
    fill: "#1976d2"
  })
  marker.appendChild(arrowPath)
  defs.appendChild(marker)

  // Render shapes
  shapesLayer.replaceChildren()
  handlesLayer.replaceChildren()

  const shapes = data.shapes || []

  function getShapePoints(s) {
    const w = s.width
    const h = s.height
    if (s.shape_type === "triangle") {
      return `${s.x + w / 2},${s.y} ${s.x + w},${s.y + h} ${s.x},${s.y + h}`
    } else if (s.shape_type === "hexagon") {
      const cx = s.x + w / 2
      const cy = s.y + h / 2
      const rx = w / 2
      const ry = h / 2
      const pts = []
      for (let i = 0; i < 6; i++) {
        const angle = (i * 60 - 30) * Math.PI / 180
        pts.push(`${cx + rx * Math.cos(angle)},${cy + ry * Math.sin(angle)}`)
      }
      return pts.join(" ")
    }
    return ""
  }

  function renderHandles(targetShape) {
    handlesLayer.replaceChildren()
    if (!targetShape) return
    const selBox = svgEl("rect", {
      x: targetShape.x,
      y: targetShape.y,
      width: targetShape.width,
      height: targetShape.height,
      fill: "none",
      stroke: "#1976d2",
      "stroke-width": 1.5,
      "stroke-dasharray": "4 3",
      "pointer-events": "none"
    })
    handlesLayer.appendChild(selBox)

    const badge = svgEl("text", {
      x: targetShape.x + targetShape.width / 2,
      y: targetShape.y - 8,
      "text-anchor": "middle",
      "font-size": 11,
      "font-weight": "600",
      fill: "#1976d2",
      "pointer-events": "none"
    })
    badge.textContent = `${formatDim(targetShape.width)} × ${formatDim(targetShape.height)}`
    handlesLayer.appendChild(badge)

    const handleSize = 8
    const handles = [
      { type: "nw", x: targetShape.x - handleSize/2, y: targetShape.y - handleSize/2 },
      { type: "ne", x: targetShape.x + targetShape.width - handleSize/2, y: targetShape.y - handleSize/2 },
      { type: "se", x: targetShape.x + targetShape.width - handleSize/2, y: targetShape.y + targetShape.height - handleSize/2 },
      { type: "sw", x: targetShape.x - handleSize/2, y: targetShape.y + targetShape.height - handleSize/2 }
    ]

    handles.forEach(h => {
      const handleEl = svgEl("rect", {
        class: `layout-handle ${h.type}`,
        x: h.x,
        y: h.y,
        width: handleSize,
        height: handleSize
      })

      handleEl.onpointerdown = (event) => {
        event.stopPropagation()
        state.resizingHandle = { handle: h.type, shape: targetShape }
        state.dragStartX = event.clientX
        state.dragStartY = event.clientY
        state.shapeStart = { x: targetShape.x, y: targetShape.y, width: targetShape.width, height: targetShape.height }
        svg.setPointerCapture(event.pointerId)
      }

      handlesLayer.appendChild(handleEl)
    })
  }

  shapes.forEach(s => {
    let style = {}
    try {
      style = typeof s.style_json === "string" ? JSON.parse(s.style_json) : (s.style_json || {})
    } catch {
      style = {}
    }

    const strokeColor = style.stroke_color || s.color || "#1976d2"
    const strokeWidth = Number(style.stroke_width || 2)
    const strokeStyle = style.stroke_style || "solid"
    const dashArray = strokeStyle === "dashed" ? "8 5" : (strokeStyle === "dotted" ? "3 3" : "none")
    const fillColor = style.fill_color || s.color || "#1976d2"
    const fillOpacity = (style.fill_opacity !== undefined) ? Number(style.fill_opacity) : 0.25
    const fontSize = Number(style.font_size || 14)
    const fontColor = style.font_color || "#1a1a1a"
    const fontWeight = style.font_weight || "bold"

    const isSelected = (s.id === state.selectedId)

    const group = svgEl("g", {
      class: `layout-shape ${isSelected ? "selected" : ""}`,
      "data-id": s.id
    })

    if (s.rotation) {
      group.setAttribute("transform", `rotate(${s.rotation} ${s.x + s.width / 2} ${s.y + s.height / 2})`)
    }

    let geomEl = null

    if (s.shape_type === "rectangle") {
      geomEl = svgEl("rect", {
        x: s.x,
        y: s.y,
        width: Math.max(10, s.width),
        height: Math.max(10, s.height),
        rx: "4",
        fill: fillColor,
        "fill-opacity": fillOpacity,
        stroke: strokeColor,
        "stroke-width": strokeWidth,
        "stroke-dasharray": dashArray
      })
    } else if (s.shape_type === "circle") {
      const r = Math.max(5, Math.min(s.width, s.height) / 2)
      geomEl = svgEl("circle", {
        cx: s.x + s.width / 2,
        cy: s.y + s.height / 2,
        r: r,
        fill: fillColor,
        "fill-opacity": fillOpacity,
        stroke: strokeColor,
        "stroke-width": strokeWidth,
        "stroke-dasharray": dashArray
      })
    } else if (s.shape_type === "oval") {
      geomEl = svgEl("ellipse", {
        cx: s.x + s.width / 2,
        cy: s.y + s.height / 2,
        rx: Math.max(5, s.width / 2),
        ry: Math.max(5, s.height / 2),
        fill: fillColor,
        "fill-opacity": fillOpacity,
        stroke: strokeColor,
        "stroke-width": strokeWidth,
        "stroke-dasharray": dashArray
      })
    } else if (s.shape_type === "triangle" || s.shape_type === "hexagon") {
      geomEl = svgEl("polygon", {
        points: getShapePoints(s),
        fill: fillColor,
        "fill-opacity": fillOpacity,
        stroke: strokeColor,
        "stroke-width": strokeWidth,
        "stroke-dasharray": dashArray
      })
    } else if (s.shape_type === "arrow") {
      const cy = s.y + s.height / 2
      geomEl = svgEl("line", {
        x1: s.x,
        y1: cy,
        x2: s.x + s.width,
        y2: cy,
        stroke: strokeColor,
        "stroke-width": Math.max(4, strokeWidth * 2),
        "stroke-dasharray": dashArray,
        "marker-end": "url(#arrow-head)"
      })
    } else if (s.shape_type === "text") {
      // Background pill if requested
      if (style.bg_pill) {
        const bgPill = svgEl("rect", {
          x: s.x,
          y: s.y,
          width: Math.max(20, s.width),
          height: Math.max(20, s.height),
          rx: "4",
          fill: fillColor,
          "fill-opacity": fillOpacity || 0.8,
          stroke: strokeColor,
          "stroke-width": strokeWidth
        })
        group.appendChild(bgPill)
      }
      geomEl = svgEl("text", {
        x: s.x + 8,
        y: s.y + fontSize + 4,
        "font-size": fontSize,
        "font-family": "sans-serif",
        "font-weight": fontWeight,
        fill: fontColor
      })
      geomEl.textContent = s.label || "Text"
    }

    if (geomEl) group.appendChild(geomEl)

    // Add centered label for non-text shapes if label exists
    if (s.shape_type !== "text" && s.label) {
      const cx = s.x + s.width / 2
      const cy = s.y + s.height / 2
      
      if (style.bg_pill) {
        const estW = s.label.length * (fontSize * 0.6) + 12
        const estH = fontSize + 8
        const pill = svgEl("rect", {
          x: cx - estW / 2,
          y: cy - estH / 2,
          width: estW,
          height: estH,
          rx: "4",
          fill: "#ffffff",
          "fill-opacity": 0.88,
          stroke: strokeColor,
          "stroke-width": 1
        })
        group.appendChild(pill)
      }

      const textEl = svgEl("text", {
        x: cx,
        y: cy + (fontSize * 0.35),
        "text-anchor": "middle",
        "font-size": fontSize,
        "font-family": "sans-serif",
        "font-weight": fontWeight,
        fill: fontColor,
        "pointer-events": "none"
      })
      textEl.textContent = s.label
      group.appendChild(textEl)
    }

    // Interactive shape selection & dragging
    group.onpointerdown = (event) => {
      event.stopPropagation()
      state.draggingShape = s
      state.dragStartX = event.clientX
      state.dragStartY = event.clientY
      state.shapeStart = { x: s.x, y: s.y, width: s.width, height: s.height }

      if (state.selectedId !== s.id) {
        state.selectedId = s.id
        if (setTriggerValue) {
          setTriggerValue("select_shape", { shape_id: s.id })
        }
      }
      svg.setPointerCapture(event.pointerId)
      updateSelectionHud(s)
    }

    shapesLayer.appendChild(group)

    if (isSelected) {
      renderHandles(s)
      updateSelectionHud(s)
    }
  })

  function updateSelectionHud(s) {
    if (!s) {
      hudShapeInfo.textContent = ""
      return
    }
    hudShapeInfo.textContent = `Selected: ${s.label || s.shape_type} [${formatDim(s.width)} × ${formatDim(s.height)}]`
  }

  // Viewport transforms (Pan & Zoom)
  function applyTransform() {
    world.setAttribute("transform", `translate(${state.x}, ${state.y}) scale(${state.scale})`)
  }

  function fit() {
    const vw = viewport.clientWidth || 800
    const vh = viewport.clientHeight || 500
    if (vw <= 0 || vh <= 0) return
    const pad = 24
    const scaleX = (vw - pad * 2) / imgW
    const scaleY = (vh - pad * 2) / imgH
    state.scale = clamp(Math.min(scaleX, scaleY), 0.05, 5.0)
    state.x = (vw - imgW * state.scale) / 2
    state.y = (vh - imgH * state.scale) / 2
    applyTransform()
  }

  function reset100() {
    const vw = viewport.clientWidth || 800
    const vh = viewport.clientHeight || 500
    state.scale = 1.0
    state.x = (vw - imgW) / 2
    state.y = (vh - imgH) / 2
    applyTransform()
  }

  function zoomAt(clientX, clientY, factor) {
    const rect = svg.getBoundingClientRect()
    const px = clientX - rect.left
    const py = clientY - rect.top
    const next = clamp(state.scale * factor, 0.05, 5.0)
    state.x = px - (px - state.x) * next / state.scale
    state.y = py - (py - state.y) * next / state.scale
    state.scale = next
    applyTransform()
  }

  // Pointer & mouse events
  svg.onwheel = (event) => {
    event.preventDefault()
    const factor = event.deltaY < 0 ? 1.15 : 0.87
    zoomAt(event.clientX, event.clientY, factor)
  }

  svg.onpointerdown = (event) => {
    if (event.target === svg || event.target === bgImg) {
      state.isPanning = true
      state.panningX = event.clientX
      state.panningY = event.clientY
      svg.classList.add("dragging")
      svg.setPointerCapture(event.pointerId)
      if (state.selectedId) {
        state.selectedId = ""
        updateSelectionHud(null)
        if (setTriggerValue) {
          setTriggerValue("select_shape", { shape_id: "" })
        }
      }
    }
  }

  svg.onpointermove = (event) => {
    const rect = svg.getBoundingClientRect()
    const worldX = (event.clientX - rect.left - state.x) / state.scale
    const worldY = (event.clientY - rect.top - state.y) / state.scale
    hudCoords.textContent = `X: ${pxToDisplay(worldX)} ${unit}, Y: ${pxToDisplay(worldY)} ${unit}`

    if (state.isPanning) {
      state.x += event.clientX - state.panningX
      state.y += event.clientY - state.panningY
      state.panningX = event.clientX
      state.panningY = event.clientY
      applyTransform()
    } else if (state.draggingShape && state.shapeStart) {
      const dx = (event.clientX - state.dragStartX) / state.scale
      const dy = (event.clientY - state.dragStartY) / state.scale
      const s = state.draggingShape
      let newX = Math.round(state.shapeStart.x + dx)
      let newY = Math.round(state.shapeStart.y + dy)

      // Magnetic snapping against other shapes
      if (snapGuides) snapGuides.replaceChildren()
      const SNAP_DIST = Math.max(12, 16 / state.scale)
      let snappedGuideX = null
      let snappedGuideY = null

      const otherShapes = (data.shapes || []).filter(o => o.id !== s.id)
      for (const other of otherShapes) {
        const oL = Number(other.x), oR = Number(other.x) + Number(other.width)
        const oT = Number(other.y), oB = Number(other.y) + Number(other.height)
        const oCx = Number(other.x) + Number(other.width) / 2
        const oCy = Number(other.y) + Number(other.height) / 2

        // Snap X (left to right, right to left, left to left, right to right, center to center)
        if (Math.abs(newX - oR) < SNAP_DIST) {
          newX = Math.round(oR)
          snappedGuideX = oR
        } else if (Math.abs(newX + s.width - oL) < SNAP_DIST) {
          newX = Math.round(oL - s.width)
          snappedGuideX = oL
        } else if (Math.abs(newX - oL) < SNAP_DIST) {
          newX = Math.round(oL)
          snappedGuideX = oL
        } else if (Math.abs(newX + s.width - oR) < SNAP_DIST) {
          newX = Math.round(oR - s.width)
          snappedGuideX = oR
        } else if (Math.abs(newX + s.width / 2 - oCx) < SNAP_DIST) {
          newX = Math.round(oCx - s.width / 2)
          snappedGuideX = oCx
        }

        // Snap Y (top to bottom, bottom to top, top to top, bottom to bottom, center to center)
        if (Math.abs(newY - oB) < SNAP_DIST) {
          newY = Math.round(oB)
          snappedGuideY = oB
        } else if (Math.abs(newY + s.height - oT) < SNAP_DIST) {
          newY = Math.round(oT - s.height)
          snappedGuideY = oT
        } else if (Math.abs(newY - oT) < SNAP_DIST) {
          newY = Math.round(oT)
          snappedGuideY = oT
        } else if (Math.abs(newY + s.height - oB) < SNAP_DIST) {
          newY = Math.round(oB - s.height)
          snappedGuideY = oB
        } else if (Math.abs(newY + s.height / 2 - oCy) < SNAP_DIST) {
          newY = Math.round(oCy - s.height / 2)
          snappedGuideY = oCy
        }
      }

      // Render snap guidelines if snapped
      if (snapGuides) {
        if (snappedGuideX !== null) {
          const lineX = svgEl("line", {
            x1: snappedGuideX,
            y1: -2000,
            x2: snappedGuideX,
            y2: imgH + 2000,
            class: "snap-guide"
          })
          snapGuides.appendChild(lineX)
        }
        if (snappedGuideY !== null) {
          const lineY = svgEl("line", {
            x1: -2000,
            y1: snappedGuideY,
            x2: imgW + 2000,
            y2: snappedGuideY,
            class: "snap-guide"
          })
          snapGuides.appendChild(lineY)
        }
      }

      s.x = newX
      s.y = newY

      // re-render shapes & handles
      const group = shapesLayer.querySelector(`[data-id="${s.id}"]`)
      if (group) {
        const rectEl = group.querySelector("rect, circle, ellipse, polygon, line, text")
        if (rectEl) {
          if (s.shape_type === "rectangle") {
            rectEl.setAttribute("x", s.x)
            rectEl.setAttribute("y", s.y)
          } else if (s.shape_type === "circle" || s.shape_type === "oval") {
            rectEl.setAttribute("cx", s.x + s.width / 2)
            rectEl.setAttribute("cy", s.y + s.height / 2)
          } else if (s.shape_type === "triangle" || s.shape_type === "hexagon") {
            rectEl.setAttribute("points", getShapePoints(s))
          } else if (s.shape_type === "arrow") {
            rectEl.setAttribute("x1", s.x)
            rectEl.setAttribute("y1", s.y + s.height / 2)
            rectEl.setAttribute("x2", s.x + s.width)
            rectEl.setAttribute("y2", s.y + s.height / 2)
          } else if (s.shape_type === "text") {
            rectEl.setAttribute("x", s.x + 8)
            rectEl.setAttribute("y", s.y + 18)
          }
        }
      }
      renderHandles(s)
      updateSelectionHud(s)
    } else if (state.resizingHandle && state.shapeStart) {
      const dx = (event.clientX - state.dragStartX) / state.scale
      const dy = (event.clientY - state.dragStartY) / state.scale
      const { handle, shape } = state.resizingHandle
      if (handle === "se") {
        shape.width = Math.max(10, Math.round(state.shapeStart.width + dx))
        shape.height = Math.max(10, Math.round(state.shapeStart.height + dy))
      } else if (handle === "sw") {
        shape.x = Math.round(state.shapeStart.x + dx)
        shape.width = Math.max(10, Math.round(state.shapeStart.width - dx))
        shape.height = Math.max(10, Math.round(state.shapeStart.height + dy))
      } else if (handle === "ne") {
        shape.y = Math.round(state.shapeStart.y + dy)
        shape.width = Math.max(10, Math.round(state.shapeStart.width + dx))
        shape.height = Math.max(10, Math.round(state.shapeStart.height - dy))
      } else if (handle === "nw") {
        shape.x = Math.round(state.shapeStart.x + dx)
        shape.y = Math.round(state.shapeStart.y + dy)
        shape.width = Math.max(10, Math.round(state.shapeStart.width - dx))
        shape.height = Math.max(10, Math.round(state.shapeStart.height - dy))
      }
      const group = shapesLayer.querySelector(`[data-id="${shape.id}"]`)
      if (group) {
        const rectEl = group.querySelector("rect, circle, ellipse, polygon, line, text")
        if (rectEl && shape.shape_type === "rectangle") {
          rectEl.setAttribute("x", shape.x)
          rectEl.setAttribute("y", shape.y)
          rectEl.setAttribute("width", shape.width)
          rectEl.setAttribute("height", shape.height)
        }
      }
      renderHandles(shape)
      updateSelectionHud(shape)
    }
  }

  svg.onpointerup = svg.onpointercancel = (event) => {
    if (snapGuides) snapGuides.replaceChildren()
    if (state.isPanning) {
      state.isPanning = false
      svg.classList.remove("dragging")
    }
    if (state.draggingShape) {
      const s = state.draggingShape
      state.draggingShape = null
      state.shapeStart = null
      if (setTriggerValue) {
        setTriggerValue("shape_moved", {
          shape_id: s.id,
          x: s.x,
          y: s.y,
          width: s.width,
          height: s.height
        })
      }
    }
    if (state.resizingHandle) {
      const s = state.resizingHandle.shape
      state.resizingHandle = null
      state.shapeStart = null
      if (setTriggerValue) {
        setTriggerValue("shape_moved", {
          shape_id: s.id,
          x: s.x,
          y: s.y,
          width: s.width,
          height: s.height
        })
      }
    }
    if (svg.hasPointerCapture(event.pointerId)) {
      svg.releasePointerCapture(event.pointerId)
    }
  }

  // Toolbar button listeners
  parentElement.querySelector("#btn-zoom-in").onclick = () => {
    zoomAt(viewport.clientWidth / 2, viewport.clientHeight / 2, 1.25)
  }
  parentElement.querySelector("#btn-zoom-out").onclick = () => {
    zoomAt(viewport.clientWidth / 2, viewport.clientHeight / 2, 0.8)
  }
  parentElement.querySelector("#btn-fit").onclick = fit
  parentElement.querySelector("#btn-reset").onclick = reset100
  parentElement.querySelector("#btn-fullscreen").onclick = async () => {
    if (document.fullscreenElement === shell) {
      await document.exitFullscreen()
    } else {
      await shell.requestFullscreen()
    }
    setTimeout(fit, 80)
  }

  // Initial fit
  if (!state.fitted) {
    state.fitted = true
    requestAnimationFrame(() => requestAnimationFrame(fit))
  } else {
    applyTransform()
  }

  // ResizeObserver for window resizing
  const resizeObserver = new ResizeObserver((entries) => {
    const bounds = entries[0]?.contentRect
    if (!bounds || !bounds.width || !bounds.height) return
    if (Math.abs((state.lastWidth || 0) - bounds.width) > 4 || Math.abs((state.lastHeight || 0) - bounds.height) > 4) {
      state.lastWidth = bounds.width
      state.lastHeight = bounds.height
      requestAnimationFrame(fit)
    }
  })
  resizeObserver.observe(viewport)
  return () => resizeObserver.disconnect()
}
"""

_LAYOUT_CANVAS = st.components.v2.component(
    "paag_layout_canvas_v2",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


@st.cache_data(show_spinner=False, max_entries=128)
def layout_image_data_url(image_path: str, modified_ns: int) -> str:
    """Read a local layout image file and encode it as a high-fidelity data URL."""
    del modified_ns
    path = Path(image_path)
    if not path.is_file():
        return ""
    try:
        suffix = path.suffix.lower()
        mime = "image/png"
        if suffix in {".jpg", ".jpeg"}:
            mime = "image/jpeg"
        elif suffix == ".webp":
            mime = "image/webp"
        data = path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except (OSError, ValueError):
        return ""


def layout_canvas(
    image_url: str,
    image_width: int,
    image_height: int,
    scale_factor_px_per_in: float,
    unit: str,
    shapes: list[dict[str, Any]],
    selected_shape_id: str | None = None,
    *,
    key: str,
    on_select_shape: Callable[[], None] | None = None,
    on_shape_moved: Callable[[], None] | None = None,
) -> Any:
    """Render the interactive floor plan layout canvas.

    Falls back safely if executed outside a browser context (e.g. headless unit tests).
    """
    try:
        return _LAYOUT_CANVAS(
            key=key,
            data={
                "imageUrl": image_url,
                "imageWidth": int(image_width),
                "imageHeight": int(image_height),
                "scalePxPerIn": float(scale_factor_px_per_in),
                "unit": str(unit),
                "shapes": shapes,
                "selectedShapeId": str(selected_shape_id or ""),
            },
            on_select_shape_change=on_select_shape,
            on_shape_moved_change=on_shape_moved,
            width="stretch",
            height="content",
        )
    except Exception:
        return None
