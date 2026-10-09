from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import streamlit as st


_HTML = """
<div class="annotator-shell" id="annotator-shell">
  <div class="annotator-toolbar">
    <div class="tool-group tools-bar">
      <button type="button" class="tool-btn active" data-tool="select" title="Select & Move (V)">👆 Select</button>
      <button type="button" class="tool-btn" data-tool="arrow" title="Arrow (A)">↗️ Arrow</button>
      <button type="button" class="tool-btn" data-tool="rect" title="Rectangle Box (R)">🔲 Box</button>
      <button type="button" class="tool-btn" data-tool="circle" title="Circle (C)">⭕ Circle</button>
      <button type="button" class="tool-btn" data-tool="text" title="Text Callout (T)">💬 Callout</button>
      <button type="button" class="tool-btn" data-tool="badge" title="Step Badge (B)">🔢 Badge</button>
      <button type="button" class="tool-btn" data-tool="pen" title="Freehand Pen (P)">✏️ Pen</button>
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
      <span class="toolbar-label">Line:</span>
      <select id="stroke-width-select" class="toolbar-select">
        <option value="2">Thin</option>
        <option value="4" selected>Med</option>
        <option value="7">Thick</option>
      </select>
      <span class="toolbar-label" style="margin-left:4px;">Next #:</span>
      <input type="number" id="next-badge-num" class="toolbar-num-input" value="1" min="1" max="99" />
    </div>
    <div class="tool-divider"></div>
    <div class="tool-group actions-bar">
      <button type="button" id="btn-undo" class="action-btn" title="Undo (Ctrl+Z)">↶ Undo</button>
      <button type="button" id="btn-redo" class="action-btn" title="Redo (Ctrl+Y)">↷ Redo</button>
      <button type="button" id="btn-del" class="action-btn danger" title="Delete Selected">🗑️ Del</button>
      <button type="button" id="btn-clear" class="action-btn" title="Clear All Markup">🧹 Clear</button>
    </div>
    <div class="tool-group save-bar">
      <button type="button" id="btn-save" class="save-btn" title="Apply annotations and save">💾 Apply & Save Markup</button>
    </div>
  </div>
  <div class="canvas-viewport" id="canvas-viewport">
    <canvas id="annotation-canvas"></canvas>
    <div id="text-edit-overlay" class="text-edit-overlay" style="display:none;">
      <input type="text" id="text-edit-input" placeholder="Type callout note..." />
      <button type="button" id="text-edit-ok">OK</button>
      <button type="button" id="text-edit-cancel">Cancel</button>
    </div>
  </div>
  <div class="annotator-statusbar">
    <span id="annotator-status">Select a tool to annotate · Click and drag on image</span>
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
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: var(--st-secondary-background-color, #f8fafc);
  border-bottom: 1px solid var(--st-border-color, #cbd5e1);
  user-select: none;
}
.tool-group {
  display: flex;
  align-items: center;
  gap: 4px;
}
.tool-divider {
  width: 1px;
  height: 24px;
  background: var(--st-border-color, #cbd5e1);
  margin: 0 4px;
}
.toolbar-label {
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--st-secondary-text-color, #64748b);
}
.tool-btn, .action-btn {
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
.action-btn.danger:hover {
  background: #ef4444;
  color: #ffffff;
  border-color: #ef4444;
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
  height: 520px;
  min-height: 400px;
  background: #1e293b;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  user-select: none;
}
#annotation-canvas {
  display: block;
  max-width: 100%;
  max-height: 100%;
  cursor: crosshair;
  box-shadow: 0 4px 20px rgba(0,0,0,0.4);
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

_JS = """
export default function(component) {
  const { parentElement, data, setTriggerValue } = component;
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
  const nextBadgeInput = parentElement.querySelector("#next-badge-num");

  let currentTool = "select";
  let currentColor = "#ef4444";
  let currentStrokeWidth = 4;
  let shapes = [];
  let undoStack = [];
  let redoStack = [];
  let selectedShapeId = null;
  let isDrawing = false;
  let isDragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let activeShape = null;
  let img = new Image();
  let imgLoaded = false;
  let scale = 1.0;
  let canvasDispW = 800;
  let canvasDispH = 500;

  // Initialize tool buttons
  parentElement.querySelectorAll(".tool-btn").forEach(btn => {
    btn.onclick = () => {
      parentElement.querySelectorAll(".tool-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentTool = btn.dataset.tool;
      selectedShapeId = null;
      canvas.style.cursor = currentTool === "select" ? "default" : "crosshair";
      statusEl.textContent = `Tool: ${btn.textContent.trim()} · ${getToolHint(currentTool)}`;
      render();
    };
  });

  // Initialize color swatches
  parentElement.querySelectorAll(".color-swatch").forEach(swatch => {
    swatch.onclick = () => {
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

  strokeSelect.onchange = () => {
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
      case "select": return "Click shape to select · Drag to move · Del to delete";
      case "arrow": return "Click and drag to point arrow";
      case "rect": return "Click and drag to draw focus box";
      case "circle": return "Click and drag to circle component";
      case "text": return "Click where you want the callout note";
      case "badge": return "Click where you want the step number badge";
      case "pen": return "Click and drag to draw freehand markup";
      default: return "";
    }
  }

  function pushUndo() {
    undoStack.push(JSON.stringify(shapes));
    if (undoStack.length > 30) undoStack.shift();
    redoStack = [];
    updateStatus();
  }

  parentElement.querySelector("#btn-undo").onclick = () => {
    if (undoStack.length > 0) {
      redoStack.push(JSON.stringify(shapes));
      shapes = JSON.parse(undoStack.pop());
      selectedShapeId = null;
      render();
    }
  };

  parentElement.querySelector("#btn-redo").onclick = () => {
    if (redoStack.length > 0) {
      undoStack.push(JSON.stringify(shapes));
      shapes = JSON.parse(redoStack.pop());
      selectedShapeId = null;
      render();
    }
  };

  parentElement.querySelector("#btn-del").onclick = () => {
    if (selectedShapeId) {
      pushUndo();
      shapes = shapes.filter(s => s.id !== selectedShapeId);
      selectedShapeId = null;
      render();
    }
  };

  parentElement.querySelector("#btn-clear").onclick = () => {
    if (shapes.length > 0 && confirm("Clear all annotations?")) {
      pushUndo();
      shapes = [];
      selectedShapeId = null;
      render();
    }
  };

  // Save composite button
  parentElement.querySelector("#btn-save").onclick = () => {
    if (!imgLoaded) return;
    statusEl.textContent = "Generating high-resolution composite...";
    const offscreen = document.createElement("canvas");
    offscreen.width = img.naturalWidth;
    offscreen.height = img.naturalHeight;
    const offCtx = offscreen.getContext("2d");
    offCtx.drawImage(img, 0, 0, img.naturalWidth, img.naturalHeight);

    // Draw all shapes at 1:1 scale
    shapes.forEach(shape => drawShape(offCtx, shape, 1.0, false));

    const dataUrl = offscreen.toDataURL("image/png");
    setTriggerValue("save", {
      annotations_json: JSON.stringify(shapes),
      data_url: dataUrl,
      count: shapes.length,
    });
    statusEl.textContent = `Applied ${shapes.length} annotations! Saving...`;
  };

  function updateStatus() {
    countEl.textContent = `${shapes.length} annotation${shapes.length === 1 ? '' : 's'}`;
  }

  // Load image
  if (data && data.image_data_url) {
    img.crossOrigin = "anonymous";
    img.onload = () => {
      imgLoaded = true;
      if (data.annotations_json) {
        try {
          shapes = JSON.parse(data.annotations_json) || [];
        } catch(e) {
          shapes = [];
        }
      }
      if (data.initial_badge_number) {
        nextBadgeInput.value = data.initial_badge_number;
      }
      resizeCanvas();
      render();
    };
    img.src = data.image_data_url;
  }

  function resizeCanvas() {
    if (!imgLoaded) return;
    const vpW = viewport.clientWidth || 800;
    const vpH = viewport.clientHeight || 520;
    const natW = img.naturalWidth;
    const natH = img.naturalHeight;

    const rW = (vpW - 24) / natW;
    const rH = (vpH - 24) / natH;
    scale = Math.min(rW, rH, 1.0);
    canvasDispW = Math.round(natW * scale);
    canvasDispH = Math.round(natH * scale);

    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvasDispW * dpr;
    canvas.height = canvasDispH * dpr;
    canvas.style.width = `${canvasDispW}px`;
    canvas.style.height = `${canvasDispH}px`;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
  }

  window.addEventListener("resize", () => {
    resizeCanvas();
    render();
  });

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

  // Pointer interactions
  canvas.onpointerdown = (e) => {
    if (!imgLoaded) return;
    canvas.setPointerCapture(e.pointerId);
    const pos = getCanvasPos(e);

    if (currentTool === "select") {
      const hit = findHitShape(pos.natX, pos.natY);
      if (hit) {
        selectedShapeId = hit.id;
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
    if (isDragging) {
      isDragging = false;
      canvas.style.cursor = currentTool === "select" ? "default" : "crosshair";
      pushUndo();
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
    } else if (s.type === "rect" || s.type === "circle" || s.type === "badge" || s.type === "text") {
      s.x += dx; s.y += dy;
    } else if (s.type === "pen") {
      s.points.forEach(p => { p.x += dx; p.y += dy; });
    }
  }

  function findHitShape(nx, ny) {
    for (let i = shapes.length - 1; i >= 0; i--) {
      const s = shapes[i];
      if (s.type === "arrow") {
        const d = distToSegment(nx, ny, s.x1, s.y1, s.x2, s.y2);
        if (d < Math.max(18, s.strokeWidth * 3)) return s;
      } else if (s.type === "rect") {
        const xMin = Math.min(s.x, s.x + s.w);
        const xMax = Math.max(s.x, s.x + s.w);
        const yMin = Math.min(s.y, s.y + s.h);
        const yMax = Math.max(s.y, s.y + s.h);
        if (nx >= xMin - 10 && nx <= xMax + 10 && ny >= yMin - 10 && ny <= yMax + 10) return s;
      } else if (s.type === "circle") {
        const cx = s.x + s.w / 2;
        const cy = s.y + s.h / 2;
        const rx = Math.abs(s.w / 2) + 10;
        const ry = Math.abs(s.h / 2) + 10;
        const norm = Math.pow((nx - cx)/rx, 2) + Math.pow((ny - cy)/ry, 2);
        if (norm <= 1.0) return s;
      } else if (s.type === "badge") {
        const d = Math.hypot(nx - s.x, ny - s.y);
        if (d <= Math.max(20, s.strokeWidth * 4.5)) return s;
      } else if (s.type === "text") {
        const tw = s.boxW || 120;
        const th = s.boxH || 30;
        if (nx >= s.x && nx <= s.x + tw && ny >= s.y && ny <= s.y + th) return s;
      } else if (s.type === "pen") {
        for (let j = 0; j < s.points.length - 1; j++) {
          const d = distToSegment(nx, ny, s.points[j].x, s.points[j].y, s.points[j+1].x, s.points[j+1].y);
          if (d < Math.max(16, s.strokeWidth * 3)) return s;
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
  function openTextOverlay(dx, dy, nx, ny) {
    pendingTextNatPos = { nx, ny };
    textOverlay.style.left = `${Math.min(viewport.clientWidth - 260, Math.max(10, dx))}px`;
    textOverlay.style.top = `${Math.min(viewport.clientHeight - 60, Math.max(10, dy))}px`;
    textOverlay.style.display = "flex";
    textInput.value = "";
    setTimeout(() => textInput.focus(), 50);
  }

  textOkBtn.onclick = () => {
    const txt = textInput.value.trim();
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
      });
      render();
    }
    textOverlay.style.display = "none";
    pendingTextNatPos = null;
  };

  textCancelBtn.onclick = () => {
    textOverlay.style.display = "none";
    pendingTextNatPos = null;
  };

  textInput.onkeydown = (e) => {
    if (e.key === "Enter") textOkBtn.click();
    if (e.key === "Escape") textCancelBtn.click();
  };

  // Main render loop
  function render() {
    if (!imgLoaded) return;
    ctx.clearRect(0, 0, canvasDispW, canvasDispH);
    ctx.drawImage(img, 0, 0, canvasDispW, canvasDispH);

    // Render saved shapes
    shapes.forEach(shape => {
      const isSelected = shape.id === selectedShapeId;
      drawShape(ctx, shape, scale, isSelected);
    });

    // Render active drawing shape
    if (activeShape) {
      drawShape(ctx, activeShape, scale, false);
    }
    updateStatus();
  }

  function drawShape(targetCtx, s, sc, isSelected) {
    targetCtx.save();
    targetCtx.strokeStyle = s.color;
    targetCtx.fillStyle = s.color;
    targetCtx.lineWidth = Math.max(2, s.strokeWidth * sc);
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
      const headLen = Math.max(14 * sc, targetCtx.lineWidth * 3.8);
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
      const r = Math.max(13 * sc, s.strokeWidth * 3.6 * sc);
      // Outer high-contrast dark disc with border
      targetCtx.beginPath();
      targetCtx.arc(bx, by, r, 0, Math.PI * 2);
      targetCtx.fillStyle = "#0f172a";
      targetCtx.fill();
      targetCtx.strokeStyle = s.color;
      targetCtx.lineWidth = Math.max(2, 2.5 * sc);
      targetCtx.stroke();

      // Number text inside
      targetCtx.fillStyle = "#ffffff";
      targetCtx.font = `800 ${Math.round(r * 1.15)}px sans-serif`;
      targetCtx.textAlign = "center";
      targetCtx.textBaseline = "middle";
      targetCtx.fillText(String(s.badgeNum || 1), bx, by + 1);

    } else if (s.type === "text") {
      const tx = s.x * sc, ty = s.y * sc;
      const fontSize = Math.max(14 * sc, s.strokeWidth * 3.4 * sc);
      targetCtx.font = `700 ${fontSize}px sans-serif`;
      const txt = s.text || "";
      const metrics = targetCtx.measureText(txt);
      const padX = 8 * sc;
      const padY = 5 * sc;
      const boxW = metrics.width + padX * 2;
      const boxH = fontSize + padY * 2;
      s.boxW = boxW / sc;
      s.boxH = boxH / sc;

      // Callout box with subtle shadow
      targetCtx.shadowColor = "rgba(0,0,0,0.5)";
      targetCtx.shadowBlur = 6 * sc;
      targetCtx.fillStyle = "#0f172a";
      targetCtx.fillRect(tx, ty, boxW, boxH);
      targetCtx.shadowBlur = 0;

      targetCtx.strokeStyle = s.color;
      targetCtx.lineWidth = Math.max(1.5, 2 * sc);
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
    }

    // Selection highlight
    if (isSelected) {
      targetCtx.strokeStyle = "#0284c7";
      targetCtx.lineWidth = 1.5;
      targetCtx.setLineDash([4, 4]);
      if (s.type === "badge") {
        const r = Math.max(13 * sc, s.strokeWidth * 3.6 * sc) + 5;
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
      } else if (s.type === "text") {
        targetCtx.strokeRect(s.x * sc - 4, s.y * sc - 4, (s.boxW || 100) * sc + 8, (s.boxH || 30) * sc + 8);
      }
    }
    targetCtx.restore();
  }
}
"""

_IMAGE_ANNOTATOR = st.components.v2.component(
    "paag_image_annotator_v1",
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
) -> Any:
    """Render the in-app interactive image annotation and markup tool."""
    try:
        return _IMAGE_ANNOTATOR(
            key=key,
            data={
                "image_data_url": image_data_url,
                "annotations_json": annotations_json,
                "initial_badge_number": initial_badge_number,
            },
            on_save_change=lambda: None,
            width="stretch",
            height="content",
        )
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

