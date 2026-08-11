from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps


_HTML = """
<div class="fishbone-shell">
  <div class="fishbone-toolbar">
    <div class="fishbone-title">
      <strong>Interactive assembly fishbone</strong>
      <span id="fishbone-summary"></span>
    </div>
    <div class="fishbone-actions">
      <button id="zoom-out" type="button" title="Zoom out">−</button>
      <button id="zoom-in" type="button" title="Zoom in">+</button>
      <button id="fit-view" type="button" title="Fit the entire fishbone">Fit</button>
      <button id="full-screen" type="button" title="Open the fishbone full screen">Full screen</button>
    </div>
  </div>
  <div class="fishbone-viewport">
    <svg id="fishbone-svg" role="img" aria-label="Interactive assembly fishbone">
      <g id="fishbone-world"></g>
    </svg>
    <div id="fishbone-tooltip" class="fishbone-tooltip" hidden>
      <img id="tooltip-image" alt="" />
      <div id="tooltip-no-image">No photo</div>
      <div class="tooltip-copy">
        <strong id="tooltip-number"></strong>
        <span id="tooltip-name"></span>
        <small id="tooltip-meta"></small>
      </div>
    </div>
    <div class="fishbone-hint">Scroll to zoom · Drag to pan · Hover over a part</div>
  </div>
</div>
"""


_CSS = """
:host { color: var(--st-text-color); font-family: var(--st-font); }
.fishbone-shell { box-sizing: border-box; width: 100%; height: 700px; min-height: 700px; display: flex; flex-direction: column; border: 1px solid var(--st-border-color); border-radius: var(--st-base-radius); overflow: hidden; background: var(--st-background-color); }
.fishbone-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--st-border-color); background: var(--st-secondary-background-color); }
.fishbone-title { min-width: 0; display: flex; align-items: baseline; gap: 10px; }
.fishbone-title span { color: var(--st-secondary-text-color); font-size: .82rem; white-space: nowrap; }
.fishbone-actions { display: flex; gap: 6px; }
.fishbone-actions button { min-width: 34px; height: 32px; padding: 0 10px; border: 1px solid var(--st-border-color); border-radius: var(--st-button-radius); color: var(--st-text-color); background: var(--st-background-color); cursor: pointer; font: inherit; font-weight: 600; }
.fishbone-actions button:hover { border-color: var(--st-primary-color); color: var(--st-primary-color); }
.fishbone-viewport { position: relative; flex: 1 1 auto; min-height: 0; overflow: hidden; background-color: var(--st-background-color); background-image: radial-gradient(circle, color-mix(in srgb, var(--st-text-color) 13%, transparent) 1px, transparent 1px); background-size: 22px 22px; touch-action: none; }
#fishbone-svg { display: block; width: 100%; height: 100%; cursor: grab; user-select: none; }
#fishbone-svg.dragging { cursor: grabbing; }
.part-card > rect { transition: stroke-width .12s ease, filter .12s ease; }
.part-card:hover > rect, .part-card:focus > rect { stroke-width: 4; filter: drop-shadow(0 5px 8px rgba(0, 0, 0, .24)); }
.fishbone-hint { position: absolute; right: 12px; bottom: 10px; padding: 5px 8px; border-radius: 6px; color: var(--st-secondary-text-color); background: color-mix(in srgb, var(--st-background-color) 88%, transparent); font-size: .75rem; pointer-events: none; }
.fishbone-tooltip { position: absolute; z-index: 5; width: 300px; display: grid; grid-template-columns: 112px 1fr; gap: 10px; padding: 10px; border: 1px solid var(--st-primary-color); border-radius: 10px; background: var(--st-background-color); box-shadow: 0 12px 32px rgba(0, 0, 0, .24); pointer-events: none; }
.fishbone-tooltip[hidden] { display: none; }
.fishbone-tooltip img, #tooltip-no-image { width: 112px; height: 88px; border-radius: 7px; object-fit: contain; background: var(--st-secondary-background-color); }
#tooltip-no-image { display: grid; place-items: center; color: var(--st-secondary-text-color); font-size: .8rem; }
.tooltip-copy { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.tooltip-copy strong { color: var(--st-primary-color); overflow-wrap: anywhere; }
.tooltip-copy span { line-height: 1.25; }
.tooltip-copy small { color: var(--st-secondary-text-color); line-height: 1.35; }
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

export default function(component) {
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
  if (!shell || !viewport || !svg || !world || !data) return

  let state = instanceState.get(parentElement)
  if (!state) {
    state = { scale: 1, x: 0, y: 0, dragging: false, pointerX: 0, pointerY: 0, fitted: false, signature: "" }
    instanceState.set(parentElement, state)
  }
  world.replaceChildren()

  const sections = data.sections || []
  const edges = data.edges || []
  const parts = data.parts || []
  const dataSignature = `${sections.map((section) => section.id).join("|")}::${parts.map((part) => part.id).join("|")}`
  if (state.signature !== dataSignature) {
    state.signature = dataSignature
    state.fitted = false
  }
  summary.textContent = `${sections.length} sections · ${parts.length} placed parts`
  const edgeLayer = svgElement("g", { class: "edge-layer" })
  const partEdgeLayer = svgElement("g", { class: "part-edge-layer" })
  const sectionLayer = svgElement("g", { class: "section-layer" })
  const partLayer = svgElement("g", { class: "part-layer" })
  world.append(edgeLayer, partEdgeLayer, sectionLayer, partLayer)
  const sectionById = new Map()
  const partsBySection = new Map()
  parts.forEach((part) => {
    const group = partsBySection.get(part.section_id) || []
    group.push(part)
    partsBySection.set(part.section_id, group)
  })

  const xSpacing = 390
  const ySpacing = 270
  sections.forEach((section) => {
    section.sx = Number(section.x) * xSpacing
    section.sy = Number(section.depth) * ySpacing
    sectionById.set(section.id, section)
  })

  edges.forEach((edge) => {
    const start = sectionById.get(edge.from)
    const end = sectionById.get(edge.to)
    if (!start || !end) return
    edgeLayer.appendChild(svgElement("line", {
      x1: start.sx, y1: start.sy, x2: end.sx, y2: end.sy,
      stroke: "var(--st-border-color)", "stroke-width": 5, "stroke-linecap": "round"
    }))
  })

  sections.forEach((section) => {
    const group = svgElement("g", { transform: `translate(${section.sx} ${section.sy})` })
    const isMain = section.type === "Main spine"
    group.appendChild(svgElement("rect", {
      x: -108, y: -29, width: 216, height: 58, rx: 14,
      fill: isMain ? "var(--st-primary-color)" : "var(--st-secondary-background-color)",
      stroke: "var(--st-primary-color)", "stroke-width": 3
    }))
    const label = svgElement("text", {
      x: 0, y: -2, "text-anchor": "middle", "dominant-baseline": "middle",
      fill: isMain ? "white" : "var(--st-text-color)", "font-size": 15, "font-weight": 700
    })
    label.textContent = section.name
    group.appendChild(label)
    const count = svgElement("text", {
      x: 0, y: 17, "text-anchor": "middle", fill: isMain ? "white" : "var(--st-secondary-text-color)", "font-size": 11
    })
    count.textContent = `${section.parts} part${section.parts === 1 ? "" : "s"}`
    group.appendChild(count)
    sectionLayer.appendChild(group)

    const sectionParts = partsBySection.get(section.id) || []
    const columns = Math.min(4, Math.max(1, sectionParts.length))
    sectionParts.forEach((part, index) => {
      const column = index % columns
      const row = Math.floor(index / columns)
      const px = section.sx + (column - (columns - 1) / 2) * 88
      const py = section.depth === 0 ? section.sy - 142 - row * 102 : section.sy + 74 + row * 102
      partEdgeLayer.appendChild(svgElement("line", {
        x1: section.sx, y1: section.sy + (section.depth === 0 ? -29 : 29), x2: px, y2: py,
        stroke: "var(--st-border-color)", "stroke-width": 2
      }))
      const card = svgElement("g", { class: "part-card", transform: `translate(${px} ${py})`, tabindex: 0 })
      card.style.cursor = "pointer"
      card.appendChild(svgElement("rect", {
        x: -36, y: -36, width: 72, height: 82, rx: 9,
        fill: "var(--st-background-color)", stroke: "var(--st-primary-color)", "stroke-width": 2
      }))
      if (part.image) {
        card.appendChild(svgElement("image", {
          href: part.image, x: -32, y: -32, width: 64, height: 60, preserveAspectRatio: "xMidYMid meet"
        }))
      } else {
        const placeholder = svgElement("text", {
          x: 0, y: -1, "text-anchor": "middle", fill: "var(--st-secondary-text-color)", "font-size": 11
        })
        placeholder.textContent = "No photo"
        card.appendChild(placeholder)
      }
      const partNumber = svgElement("text", {
        x: 0, y: 39, "text-anchor": "middle", fill: "var(--st-text-color)", "font-size": 10, "font-weight": 700
      })
      partNumber.textContent = part.part_number.length > 12 ? `${part.part_number.slice(0, 11)}…` : part.part_number
      card.appendChild(partNumber)

      const showTooltip = (event) => {
        tooltipNumber.textContent = part.part_number
        tooltipName.textContent = part.description || "No description"
        tooltipMeta.textContent = `${part.section_name} · Qty ${part.quantity} · ${part.models || "All models"}`
        tooltipImage.hidden = !part.image
        tooltipNoImage.hidden = Boolean(part.image)
        if (part.image) tooltipImage.src = part.image
        tooltip.hidden = false
        const bounds = viewport.getBoundingClientRect()
        const width = 300
        const x = clamp(event.clientX - bounds.left + 16, 8, Math.max(8, bounds.width - width - 8))
        const y = clamp(event.clientY - bounds.top + 16, 8, Math.max(8, bounds.height - 122))
        tooltip.style.left = `${x}px`
        tooltip.style.top = `${y}px`
      }
      card.onpointerenter = showTooltip
      card.onpointermove = showTooltip
      card.onpointerleave = () => { tooltip.hidden = true }
      card.onfocus = (event) => showTooltip({ clientX: viewport.getBoundingClientRect().left + viewport.clientWidth / 2, clientY: viewport.getBoundingClientRect().top + 80 })
      card.onblur = () => { tooltip.hidden = true }
      partLayer.appendChild(card)
    })
  })

  const applyTransform = () => {
    world.setAttribute("transform", `translate(${state.x} ${state.y}) scale(${state.scale})`)
  }
  const fit = () => {
    const bounds = world.getBBox()
    const width = Math.max(viewport.clientWidth, 300)
    const height = Math.max(viewport.clientHeight, 300)
    if (!bounds.width || !bounds.height) return
    state.scale = clamp(Math.min((width - 70) / bounds.width, (height - 70) / bounds.height), .08, 1.35)
    state.x = (width - bounds.width * state.scale) / 2 - bounds.x * state.scale
    state.y = (height - bounds.height * state.scale) / 2 - bounds.y * state.scale
    applyTransform()
  }
  const zoomAtCenter = (factor) => {
    const cx = viewport.clientWidth / 2
    const cy = viewport.clientHeight / 2
    const next = clamp(state.scale * factor, .08, 4)
    state.x = cx - (cx - state.x) * next / state.scale
    state.y = cy - (cy - state.y) * next / state.scale
    state.scale = next
    applyTransform()
  }

  svg.onwheel = (event) => {
    event.preventDefault()
    const bounds = svg.getBoundingClientRect()
    const px = event.clientX - bounds.left
    const py = event.clientY - bounds.top
    const next = clamp(state.scale * (event.deltaY < 0 ? 1.12 : .89), .08, 4)
    state.x = px - (px - state.x) * next / state.scale
    state.y = py - (py - state.y) * next / state.scale
    state.scale = next
    applyTransform()
  }
  svg.onpointerdown = (event) => {
    state.dragging = true
    state.pointerX = event.clientX
    state.pointerY = event.clientY
    svg.setPointerCapture(event.pointerId)
    svg.classList.add("dragging")
  }
  svg.onpointermove = (event) => {
    if (!state.dragging) return
    state.x += event.clientX - state.pointerX
    state.y += event.clientY - state.pointerY
    state.pointerX = event.clientX
    state.pointerY = event.clientY
    applyTransform()
  }
  svg.onpointerup = svg.onpointercancel = (event) => {
    state.dragging = false
    svg.classList.remove("dragging")
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId)
  }
  parentElement.querySelector("#zoom-in").onclick = () => zoomAtCenter(1.2)
  parentElement.querySelector("#zoom-out").onclick = () => zoomAtCenter(.83)
  parentElement.querySelector("#fit-view").onclick = fit
  parentElement.querySelector("#full-screen").onclick = async () => {
    if (document.fullscreenElement === shell) await document.exitFullscreen()
    else await shell.requestFullscreen()
    setTimeout(fit, 80)
  }
  if (!state.fitted) {
    state.fitted = true
    requestAnimationFrame(() => requestAnimationFrame(fit))
  } else {
    applyTransform()
  }
  const resizeObserver = new ResizeObserver((entries) => {
    const bounds = entries[0]?.contentRect
    if (!bounds || !bounds.width || !bounds.height) return
    if (Math.abs((state.lastWidth || 0) - bounds.width) > 2 || Math.abs((state.lastHeight || 0) - bounds.height) > 2) {
      state.lastWidth = bounds.width
      state.lastHeight = bounds.height
      requestAnimationFrame(fit)
    }
  })
  resizeObserver.observe(viewport)
  return () => resizeObserver.disconnect()
}
"""


_FISHBONE_COMPONENT = st.components.v2.component(
    "interactive_fishbone_canvas",
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
    path = Path(str(image_path or ""))
    try:
        return _thumbnail_data_url(str(path), path.stat().st_mtime_ns)
    except OSError:
        return ""


def interactive_fishbone(
    sections: list[dict],
    edges: list[dict],
    parts: list[dict],
    *,
    key: str,
) -> None:
    _FISHBONE_COMPONENT(
        key=key,
        data={"sections": sections, "edges": edges, "parts": parts},
        width="stretch",
        height="content",
    )
