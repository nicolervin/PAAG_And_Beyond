"""Read-only Process Flow Diagram projection and interactive visual component."""

from __future__ import annotations

from collections.abc import Callable
import html
import json
from typing import Any

import pandas as pd
import streamlit as st

from utils import store
from utils.store import (
    assembly_section_walk_order,
    get_planning_scenario,
    get_project,
    process_ergonomics_risk_work_element_ids,
    process_part_groups,
    work_element_criticality,
    work_element_op_contexts,
    yamazumi_context_for_process,
)


def _text(val: Any) -> str:
    return str(val or "").strip()


def process_flow_projection(
    project_id: str,
    scenario_id: str,
    shape_mode: str = "functional",
) -> dict[str, Any]:
    """Build a comprehensive, read-only Process Flow Diagram projection.

    Extracts Yamazumi Pitches (outer containers), Work Elements / Op IDs (inner blocks),
    sequence routing, and subassembly feeder injection curves without modifying database state.
    """
    scenario = get_planning_scenario(project_id, scenario_id)
    if not scenario:
        raise ValueError("Planning scenario not found.")

    takt_time_s = float(scenario.get("takt_time_s") or 0.0)
    if takt_time_s <= 0:
        proj = get_project(project_id)
        takt_time_s = float((proj or {}).get("takt_time_s") or 60.0)

    with store.connection() as conn:
        work_rows = [
            dict(r)
            for r in conn.execute(
                """SELECT id, sequence, station, operation, description,
                          cycle_time_s, part_number, tool, torque,
                          quality_requirement, ergo_requirement, location,
                          unit_orientation, output_assembly_number,
                          output_assembly_name, model_applicability, status
                   FROM work_elements
                   WHERE project_id=? AND scenario_id=?
                   ORDER BY sequence, id""",
                (project_id, scenario_id),
            ).fetchall()
        ]

        yamazumi_links = [
            dict(r)
            for r in conn.execute(
                """SELECT element.process_element_id, element.id AS element_id,
                          element.pitch_id, element.sequence AS element_sequence,
                          element.description AS element_description,
                          element.time_s AS element_time_s,
                          pitch.pitch_number, pitch.pitch_name, pitch.pitch_type,
                          pitch.sequence AS pitch_sequence, pitch.status AS pitch_status,
                          pitch.feeds_into_pitch_id,
                          area.id AS area_id, area.name AS area_name,
                          area.section_id
                   FROM yamazumi_elements element
                   JOIN yamazumi_areas area
                     ON area.id=element.area_id AND area.project_id=element.project_id
                   LEFT JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
                   WHERE element.project_id=? AND area.scenario_id=?
                     AND TRIM(COALESCE(element.process_element_id, ''))<>''
                   ORDER BY element.sequence, element.id""",
                (project_id, scenario_id),
            ).fetchall()
        ]

        pitch_rows = [
            dict(r)
            for r in conn.execute(
                """SELECT pitch.id, pitch.area_id, pitch.pitch_number,
                          pitch.pitch_name, pitch.pitch_type, pitch.status,
                          pitch.sequence, pitch.feeds_into_pitch_id,
                          area.name AS area_name, area.section_id
                   FROM yamazumi_pitches pitch
                   JOIN yamazumi_areas area ON area.id=pitch.area_id
                   WHERE pitch.project_id=? AND area.scenario_id=?
                   ORDER BY pitch.sequence, pitch.id""",
                (project_id, scenario_id),
            ).fetchall()
        ]

        quality_assigned_ids = {
            _text(r["work_element_id"])
            for r in conn.execute(
                """SELECT DISTINCT work_element_id
                   FROM quality_requirement_assignments
                   WHERE project_id=? AND scenario_id=?
                     AND work_element_id IS NOT NULL
                     AND COALESCE(unlinked_at, '')=''""",
                (project_id, scenario_id),
            ).fetchall()
            if _text(r["work_element_id"])
        }

    work_ids = [str(r["id"]) for r in work_rows]
    contexts = work_element_op_contexts(project_id, scenario_id, work_ids)
    criticality_map = work_element_criticality(project_id, scenario_id)
    ergo_risk_ids = process_ergonomics_risk_work_element_ids(project_id, scenario_id)

    # Gather paired parts summary
    pairing_by_work: dict[str, list[dict]] = {}
    for group in process_part_groups(project_id, scenario_id, active_only=True):
        wid = _text(group.get("work_element_id"))
        for opt in group.get("options", []):
            pairing_by_work.setdefault(wid, []).append(
                {
                    "part_number": _text(opt.get("part_number")),
                    "handling_type": _text(opt.get("handling_type") or "Consume"),
                    "group_name": _text(group.get("name")),
                }
            )

    # Group yamazumi links by work_element_id
    yam_by_work: dict[str, dict] = {}
    for row in yamazumi_links:
        wid = _text(row.get("process_element_id"))
        if wid and wid not in yam_by_work:
            yam_by_work[wid] = row

    # Build pitch lookup map
    pitch_map: dict[str, dict] = {}
    for pos, p in enumerate(pitch_rows):
        pid = _text(p["id"])
        ptype = _text(p.get("pitch_type")) or "Normal"
        is_feeder = ptype in {"Subassembly", "Kitter"}
        pitch_map[pid] = {
            "id": pid,
            "key": f"pitch:{pid}",
            "order": pos,
            "sequence": int(p.get("sequence") or (pos + 1) * 10),
            "number": _text(p.get("pitch_number")) or f"P{pos+1}",
            "name": _text(p.get("pitch_name")) or "Unnamed Pitch",
            "type": ptype,
            "is_feeder": is_feeder,
            "feeds_into_pitch_id": _text(p.get("feeds_into_pitch_id")),
            "area_name": _text(p.get("area_name")),
            "section_id": _text(p.get("section_id")),
            "operations": [],
            "total_time_s": 0.0,
        }

    # Add an unassigned pseudo-pitch if needed
    unassigned_pitch_id = "__unassigned__"
    pitch_map[unassigned_pitch_id] = {
        "id": unassigned_pitch_id,
        "key": f"pitch:{unassigned_pitch_id}",
        "order": 999999,
        "sequence": 999999,
        "number": "Unassigned",
        "name": "Unassigned Work Elements",
        "type": "Normal",
        "is_feeder": False,
        "feeds_into_pitch_id": "",
        "area_name": "Unassigned",
        "section_id": "",
        "operations": [],
        "total_time_s": 0.0,
    }

    # Detect feeder output operations & receiving injection targets
    feeder_pitch_ids = {pid for pid, p in pitch_map.items() if p["is_feeder"]}

    # Process operations
    operations: list[dict] = []
    for pos, w in enumerate(work_rows):
        wid = str(w["id"])
        ctx = contexts.get(wid, {})
        yam = yam_by_work.get(wid, {})
        pitch_id = _text(yam.get("pitch_id"))
        if not pitch_id or pitch_id not in pitch_map:
            pitch_id = unassigned_pitch_id

        duration = float(w.get("cycle_time_s") or yam.get("element_time_s") or 0.0)
        crit = list(criticality_map.get(wid, []))
        has_quality = wid in quality_assigned_ids or bool(_text(w.get("quality_requirement")))
        has_ergo = wid in ergo_risk_ids or bool(_text(w.get("ergo_requirement")))
        parts = pairing_by_work.get(wid, [])

        op_data = {
            "id": wid,
            "key": f"op:{wid}",
            "order": pos,
            "sort_order": int(ctx.get("sort_order", pos * 10)),
            "sequence": int(w.get("sequence") or (pos + 1) * 10),
            "op_id": _text(ctx.get("op_id")) or f"Op {pos+1}",
            "operation": _text(yam.get("element_description")) or _text(w.get("operation")),
            "description": _text(w.get("description")),
            "cycle_time_s": duration,
            "station": _text(w.get("station")),
            "pitch_id": pitch_id,
            "pitch_key": pitch_map[pitch_id]["key"],
            "tools": _text(w.get("tool")),
            "torque": _text(w.get("torque")),
            "criticality": crit,
            "has_quality_spec": has_quality,
            "ergonomics_risk": has_ergo,
            "parts": parts,
            "output_assembly_number": _text(w.get("output_assembly_number")),
            "output_assembly_name": _text(w.get("output_assembly_name")),
            "is_injection_target": False,
            "is_feeder_output": False,
            "shape": "square",
        }
        operations.append(op_data)
        pitch_map[pitch_id]["operations"].append(op_data)
        pitch_map[pitch_id]["total_time_s"] += duration

    # Mark feeder outputs and injection targets
    for p in pitch_map.values():
        if p["is_feeder"] and p["operations"]:
            last_op = p["operations"][-1]
            last_op["is_feeder_output"] = True
            target_pid = p["feeds_into_pitch_id"]
            if target_pid and target_pid in pitch_map:
                target_pitch = pitch_map[target_pid]
                if target_pitch["operations"]:
                    # Mark the receiving operation (first operation by default)
                    target_pitch["operations"][0]["is_injection_target"] = True

    # Determine shape for each operation
    for op in operations:
        if shape_mode == "uniform":
            op["shape"] = "square"
        else:
            # Functional shape derivation
            if op["criticality"] or op["has_quality_spec"]:
                op["shape"] = "diamond"
            elif op["is_feeder_output"] or op["is_injection_target"]:
                op["shape"] = "rounded"
            elif any(p.get("handling_type") == "Handle" for p in op["parts"]):
                op["shape"] = "rounded"
            else:
                op["shape"] = "square"

    # Clean empty pitches except if it's a feeder pitch needing visibility
    active_pitches = [
        p for p in pitch_map.values()
        if p["operations"] or (p["is_feeder"] and p["id"] != unassigned_pitch_id)
    ]
    active_pitches.sort(key=lambda item: (0 if not item["is_feeder"] else 1, item["order"]))

    # Update over_takt flags
    for p in active_pitches:
        p["over_takt"] = p["total_time_s"] > takt_time_s and takt_time_s > 0

    # Sequence edges
    sequence_edges: list[dict] = []
    # Intra-pitch sequence edges
    for p in active_pitches:
        ops = p["operations"]
        for left, right in zip(ops, ops[1:]):
            sequence_edges.append({
                "from": left["key"],
                "to": right["key"],
                "kind": "intra_pitch",
            })

    # Inter-pitch sequence edges (Main spine only)
    main_pitches = [p for p in active_pitches if not p["is_feeder"] and p["id"] != unassigned_pitch_id and p["operations"]]
    main_pitches.sort(key=lambda p: p["order"])
    for left_p, right_p in zip(main_pitches, main_pitches[1:]):
        sequence_edges.append({
            "from": left_p["operations"][-1]["key"],
            "to": right_p["operations"][0]["key"],
            "kind": "inter_pitch",
        })

    # Feeder injection edges
    feed_edges: list[dict] = []
    unresolved_feeds: list[dict] = []
    for p in active_pitches:
        if not p["is_feeder"]:
            continue
        target_pid = p["feeds_into_pitch_id"]
        source_op = p["operations"][-1] if p["operations"] else None
        target_pitch = pitch_map.get(target_pid)
        target_op = target_pitch["operations"][0] if (target_pitch and target_pitch["operations"]) else None

        if source_op and target_op:
            assembly_label = (
                source_op.get("output_assembly_number")
                or p.get("name")
                or "Subassembly"
            )
            if source_op.get("output_assembly_name"):
                assembly_label += f" ({source_op['output_assembly_name']})"
            feed_edges.append({
                "from": source_op["key"],
                "to": target_op["key"],
                "from_pitch_key": p["key"],
                "to_pitch_key": target_pitch["key"],
                "label": f"Injects: {assembly_label}",
                "assembly": assembly_label,
            })
        else:
            unresolved_feeds.append({
                "pitch_key": p["key"],
                "pitch_number": p["number"],
                "pitch_name": p["name"],
                "label": "Feeder destination unassigned in Yamazumi",
            })

    return {
        "scenario_name": _text(scenario.get("name")),
        "takt_time_s": takt_time_s,
        "shape_mode": shape_mode,
        "pitches": active_pitches,
        "operations": operations,
        "sequence_edges": sequence_edges,
        "feed_edges": feed_edges,
        "unresolved_feeds": unresolved_feeds,
        "metrics": {
            "total_operations": len(operations),
            "total_pitches": len(active_pitches),
            "feeder_pitches": len([p for p in active_pitches if p["is_feeder"]]),
            "total_work_time_s": round(sum(o["cycle_time_s"] for o in operations), 1),
            "bottlenecks": len([p for p in active_pitches if p["over_takt"]]),
        },
    }


# ==============================================================================
# Streamlit Component v2 for Process Flow Map
# ==============================================================================

_PROCESS_FLOW_HTML = """
<div class="pfd-shell">
  <div class="pfd-toolbar">
    <div class="pfd-title-group">
      <strong>Process Flow Diagram</strong>
      <span id="pfd-summary" class="pfd-summary"></span>
    </div>
    <div class="pfd-actions">
      <button id="pfd-zoom-out" type="button" title="Zoom out">−</button>
      <button id="pfd-zoom-in" type="button" title="Zoom in">+</button>
      <button id="pfd-fit" type="button" title="Fit to screen">Fit</button>
      <button id="pfd-reset" type="button" title="Reset view">Reset</button>
      <button id="pfd-full" type="button" title="Toggle full screen">Full screen</button>
    </div>
  </div>
  <div class="pfd-viewport">
    <svg id="pfd-svg" role="img" aria-label="Process Flow Diagram">
      <defs>
        <marker id="pfd-seq-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--st-secondary-text-color)"></path>
        </marker>
        <marker id="pfd-feed-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"></path>
        </marker>
      </defs>
      <g id="pfd-world"></g>
    </svg>
    <div id="pfd-tooltip" class="pfd-tooltip" hidden></div>
    <div class="pfd-hint">Scroll to zoom · Drag to pan · Click any operation block for details</div>
  </div>
</div>
"""

_PROCESS_FLOW_CSS = """
:host { color: var(--st-text-color); font-family: var(--st-font); }
.pfd-shell { box-sizing:border-box; width:100%; height:720px; min-height:720px; display:flex; flex-direction:column; border:1px solid var(--st-border-color); border-radius:var(--st-base-radius); overflow:hidden; background:var(--st-background-color); }
.pfd-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 14px; border-bottom:1px solid var(--st-border-color); background:var(--st-secondary-background-color); }
.pfd-title-group { display:flex; align-items:baseline; gap:12px; }
.pfd-summary { color:var(--st-secondary-text-color); font-size:.82rem; }
.pfd-actions { display:flex; gap:6px; }
.pfd-actions button { min-width:34px; height:32px; padding:0 10px; border:1px solid var(--st-border-color); border-radius:var(--st-button-radius); color:var(--st-text-color); background:var(--st-background-color); cursor:pointer; font:inherit; font-weight:600; }
.pfd-actions button:hover { color:var(--st-primary-color); border-color:var(--st-primary-color); }
.pfd-viewport { position:relative; flex:1 1 auto; min-height:0; overflow:hidden; touch-action:none; background-color:var(--st-background-color); background-image:radial-gradient(circle, color-mix(in srgb, var(--st-text-color) 11%, transparent) 1px, transparent 1px); background-size:20px 20px; }
#pfd-svg { display:block; width:100%; height:100%; cursor:grab; user-select:none; }
#pfd-svg.dragging { cursor:grabbing; }

/* Station / Pitch Container */
.pitch-container rect.pitch-bg { fill:color-mix(in srgb, var(--st-secondary-background-color) 50%, transparent); stroke:var(--st-border-color); stroke-width:1.5; rx:10; }
.pitch-container.feeder rect.pitch-bg { stroke:#3b82f6; stroke-dasharray:6 4; }
.pitch-title { fill:var(--st-text-color); font-size:13px; font-weight:700; }
.pitch-meta { fill:var(--st-secondary-text-color); font-size:11px; }
.pitch-pacing { font-size:11px; font-weight:600; }
.pitch-pacing.ok { fill:#16a34a; }
.pitch-pacing.over { fill:#dc2626; font-weight:700; }

/* Operation Blocks */
.op-node { cursor:pointer; outline:none; }
.op-node:hover .op-shape, .op-node:focus .op-shape { stroke:var(--st-primary-color); stroke-width:2.5; filter:drop-shadow(0 4px 10px rgba(0,0,0,.22)); }
.op-shape { fill:var(--st-background-color); stroke:var(--st-border-color); stroke-width:1.5; }
.op-shape.diamond { stroke:#d97706; }
.op-shape.rounded { stroke:#2563eb; }
.op-shape.injection-target { stroke:#2563eb; stroke-width:2.5; }
.op-id { font-size:12px; font-weight:700; fill:var(--st-primary-color); pointer-events:none; }
.op-seq { font-size:10px; fill:var(--st-secondary-text-color); pointer-events:none; }
.op-title { font-size:11px; font-weight:500; fill:var(--st-text-color); pointer-events:none; }
.op-time { font-size:11px; font-weight:600; fill:var(--st-secondary-text-color); pointer-events:none; }

/* Badges */
.badge-rect { rx:4; }
.badge-text { font-size:9px; font-weight:700; pointer-events:none; }
.badge-ctq .badge-rect { fill:#ffedd5; stroke:#ea580c; stroke-width:1; }
.badge-ctq .badge-text { fill:#9a3412; }
.badge-safety .badge-rect { fill:#fee2e2; stroke:#dc2626; stroke-width:1; }
.badge-safety .badge-text { fill:#991b1b; }
.badge-ergo .badge-rect { fill:#fef2f2; stroke:#ef4444; stroke-width:1; }
.badge-ergo .badge-text { fill:#b91c1c; }
.badge-consume .badge-rect { fill:#dcfce7; stroke:#16a34a; stroke-width:1; }
.badge-consume .badge-text { fill:#166534; }

/* Routing Edges */
.seq-edge { fill:none; stroke:var(--st-secondary-text-color); stroke-width:1.8; marker-end:url(#pfd-seq-arrow); }
.feed-edge { fill:none; stroke:#2563eb; stroke-width:2.8; stroke-dasharray:7 4; marker-end:url(#pfd-feed-arrow); }
.edge-label { fill:#1d4ed8; font-size:10px; font-weight:700; }

/* Unresolved Alerts */
.unresolved rect { fill:#fffbeb; stroke:#d97706; stroke-width:1.5; stroke-dasharray:5 4; rx:8; }
.unresolved text { fill:#92400e; font-size:11px; font-weight:600; }

.pfd-tooltip { position:absolute; z-index:10; max-width:340px; padding:8px 12px; border:1px solid var(--st-primary-color); border-radius:8px; background:var(--st-background-color); color:var(--st-text-color); box-shadow:0 8px 24px rgba(0,0,0,.22); pointer-events:none; font-size:.82rem; line-height:1.4; }
.pfd-tooltip[hidden] { display:none; }
.pfd-hint { position:absolute; right:12px; bottom:10px; padding:5px 8px; border-radius:6px; color:var(--st-secondary-text-color); background:color-mix(in srgb, var(--st-background-color) 88%, transparent); font-size:.75rem; pointer-events:none; }
.pfd-shell:fullscreen { width:100vw; height:100vh; min-height:0; border:0; border-radius:0; }
"""

_PROCESS_FLOW_JS = """
const NS = "http://www.w3.org/2000/svg"
const states = new WeakMap()
function node(name, attrs={}) { const el=document.createElementNS(NS, name); Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v))); return el }
function clamp(val, low, high) { return Math.max(low, Math.min(high, val)) }
function addText(parent, val, x, y, cls="") { const t=node("text",{x, y, class:cls}); t.textContent=val || ""; parent.appendChild(t); return t }
function short(val, size) { val=String(val || ""); return val.length > size ? val.slice(0, size-1)+"…" : val }

export default function(component) {
  const {data, parentElement, setTriggerValue} = component
  const shell = parentElement.querySelector(".pfd-shell")
  const viewport = parentElement.querySelector(".pfd-viewport")
  const svg = parentElement.querySelector("#pfd-svg")
  const world = parentElement.querySelector("#pfd-world")
  const tooltip = parentElement.querySelector("#pfd-tooltip")
  if (!shell || !viewport || !svg || !world || !data) return

  let state = states.get(parentElement)
  if (!state) { state={scale:1, x:30, y:30, drag:false, px:0, py:0, signature:"", fitted:false}; states.set(parentElement, state) }

  const pitches = data.pitches || []
  const operations = data.operations || []
  const seqEdges = data.sequence_edges || []
  const feedEdges = data.feed_edges || []
  const unresolved = data.unresolved_feeds || []
  const metrics = data.metrics || {}

  const sig = pitches.map(p=>p.key+":"+p.total_time_s).join("|") + "::" + operations.map(o=>o.key+":"+o.shape).join("|")
  if (sig !== state.signature) { state.signature = sig; state.fitted = false }

  parentElement.querySelector("#pfd-summary").textContent =
    `${metrics.total_pitches || pitches.length} Pitches · ${metrics.total_operations || operations.length} Operations · Total Work: ${metrics.total_work_time_s || 0}s`
  world.replaceChildren()

  // Layout parameters
  const opW = 190, opH = 114, opGapX = 35
  const pitchPadding = 24
  const mainSpineY = 240
  const feederY = 40
  const opMap = new Map()
  const pitchBoxMap = new Map()

  // Separate main line pitches and feeder pitches
  const mainPitches = pitches.filter(p => !p.is_feeder)
  const feederPitches = pitches.filter(p => p.is_feeder)

  // Layout Main Spine Pitches left-to-right
  let curMainX = 40
  mainPitches.forEach((p) => {
    const ops = p.operations || []
    const innerW = ops.length > 0 ? ops.length * opW + (ops.length - 1) * opGapX : 220
    const pW = innerW + pitchPadding * 2
    const pH = opH + 68

    pitchBoxMap.set(p.key, {x: curMainX, y: mainSpineY, w: pW, h: pH, pitch: p})

    // Draw pitch container
    const gP = node("g", {class: "pitch-container main"})
    gP.appendChild(node("rect", {x: curMainX, y: mainSpineY, width: pW, height: pH, class: "pitch-bg"}))
    addText(gP, `${p.number} — ${short(p.name, 26)}`, curMainX + pitchPadding, mainSpineY + 22, "pitch-title")
    const pacingCls = p.over_takt ? "pitch-pacing over" : "pitch-pacing ok"
    const pacingText = `${p.total_time_s.toFixed(1)}s / Takt ${data.takt_time_s || 60}s${p.over_takt ? " ⚠️ OVER TAKT" : ""}`
    addText(gP, pacingText, curMainX + pW - pitchPadding - 140, mainSpineY + 22, pacingCls)
    world.appendChild(gP)

    // Position operations inside
    ops.forEach((op, idx) => {
      const ox = curMainX + pitchPadding + idx * (opW + opGapX)
      const oy = mainSpineY + 42
      opMap.set(op.key, {x: ox, y: oy, w: opW, h: opH, op})
    })

    curMainX += pW + 55
  })

  // Layout Feeder Pitches above main spine
  let curFeederX = 40
  feederPitches.forEach((p) => {
    const ops = p.operations || []
    const innerW = ops.length > 0 ? ops.length * opW + (ops.length - 1) * opGapX : 220
    const pW = innerW + pitchPadding * 2
    const pH = opH + 68

    pitchBoxMap.set(p.key, {x: curFeederX, y: feederY, w: pW, h: pH, pitch: p})

    const gP = node("g", {class: "pitch-container feeder"})
    gP.appendChild(node("rect", {x: curFeederX, y: feederY, width: pW, height: pH, class: "pitch-bg"}))
    addText(gP, `Feeder: ${p.number} — ${short(p.name, 24)}`, curFeederX + pitchPadding, feederY + 22, "pitch-title")
    addText(gP, `${p.total_time_s.toFixed(1)}s`, curFeederX + pW - pitchPadding - 45, feederY + 22, "pitch-meta")
    world.appendChild(gP)

    ops.forEach((op, idx) => {
      const ox = curFeederX + pitchPadding + idx * (opW + opGapX)
      const oy = feederY + 42
      opMap.set(op.key, {x: ox, y: oy, w: opW, h: opH, op})
    })

    curFeederX += pW + 55
  })

  // Draw Sequence Edges Layer
  const seqEdgeLayer = node("g", {class: "seq-edge-layer"})
  seqEdges.forEach((e) => {
    const from = opMap.get(e.from)
    const to = opMap.get(e.to)
    if (!from || !to) return
    const x1 = from.x + from.w, y1 = from.y + from.h / 2
    const x2 = to.x, y2 = to.y + to.h / 2
    const path = node("path", {
      d: `M ${x1} ${y1} C ${x1 + 18} ${y1}, ${x2 - 18} ${y2}, ${x2} ${y2}`,
      class: "seq-edge"
    })
    seqEdgeLayer.appendChild(path)
  })
  world.appendChild(seqEdgeLayer)

  // Draw Feeder Injection Edges Layer
  const feedEdgeLayer = node("g", {class: "feed-edge-layer"})
  feedEdges.forEach((e) => {
    const from = opMap.get(e.from)
    const to = opMap.get(e.to)
    if (!from || !to) return
    const x1 = from.x + from.w / 2, y1 = from.y + from.h
    const x2 = to.x + to.w / 2, y2 = to.y
    const midY = (y1 + y2) / 2
    const path = node("path", {
      d: `M ${x1} ${y1} C ${x1} ${midY + 20}, ${x2} ${midY - 20}, ${x2} ${y2}`,
      class: "feed-edge"
    })
    feedEdgeLayer.appendChild(path)

    // Injection label badge
    if (e.assembly) {
      const lx = (x1 + x2) / 2 - 40, ly = midY - 6
      const lblBg = node("rect", {x: lx - 6, y: ly - 12, width: 140, height: 18, rx: 4, fill: "var(--st-background-color)", stroke: "#2563eb", "stroke-width": 1})
      feedEdgeLayer.appendChild(lblBg)
      addText(feedEdgeLayer, short(`Inject: ${e.assembly}`, 20), lx, ly, "edge-label")
    }
  })
  world.appendChild(feedEdgeLayer)

  // Draw Operations Layer
  const opLayer = node("g", {class: "op-layer"})
  operations.forEach((op) => {
    const geom = opMap.get(op.key)
    if (!geom) return
    const {x, y, w, h} = geom

    const g = node("g", {
      class: "op-node",
      tabindex: "0",
      role: "button",
      "aria-label": `${op.op_id}. ${op.operation}. Time ${op.cycle_time_s}s. Click for details.`
    })

    // Draw shape
    const shape = op.shape || "square"
    const shapeCls = `op-shape ${shape}${op.is_injection_target ? " injection-target" : ""}`
    if (shape === "diamond") {
      const dPath = `M ${x + w/2} ${y} L ${x + w} ${y + h/2} L ${x + w/2} ${y + h} L ${x} ${y + h/2} Z`
      g.appendChild(node("path", {d: dPath, class: shapeCls}))
    } else if (shape === "rounded") {
      g.appendChild(node("rect", {x, y, width: w, height: h, rx: 26, ry: 26, class: shapeCls}))
    } else {
      g.appendChild(node("rect", {x, y, width: w, height: h, rx: 7, ry: 7, class: shapeCls}))
    }

    // Header: Op ID and Sequence
    addText(g, op.op_id, x + 12, y + 20, "op-id")
    addText(g, `#${op.sequence}`, x + w - 38, y + 20, "op-seq")

    // Center: Operation name
    addText(g, short(op.operation, 26), x + 12, y + 44, "op-title")

    // Lower: Cycle Time
    addText(g, `${op.cycle_time_s.toFixed(1)}s`, x + 12, y + 70, "op-time")

    // Badges strip
    let badgeX = x + 60
    if (op.criticality && op.criticality.includes("CTQ")) {
      const bg = node("g", {class: "badge-ctq"})
      bg.appendChild(node("rect", {x: badgeX, y: y + 58, width: 32, height: 16, class: "badge-rect"}))
      addText(bg, "CTQ", badgeX + 6, y + 70, "badge-text")
      g.appendChild(bg)
      badgeX += 36
    }
    if (op.criticality && op.criticality.includes("Safety")) {
      const bg = node("g", {class: "badge-safety"})
      bg.appendChild(node("rect", {x: badgeX, y: y + 58, width: 34, height: 16, class: "badge-rect"}))
      addText(bg, "SAFE", badgeX + 4, y + 70, "badge-text")
      g.appendChild(bg)
      badgeX += 38
    }
    if (op.ergonomics_risk) {
      const bg = node("g", {class: "badge-ergo"})
      bg.appendChild(node("rect", {x: badgeX, y: y + 58, width: 34, height: 16, class: "badge-rect"}))
      addText(bg, "ERGO", badgeX + 4, y + 70, "badge-text")
      g.appendChild(bg)
      badgeX += 38
    }
    if (op.parts && op.parts.length > 0) {
      const bg = node("g", {class: "badge-consume"})
      bg.appendChild(node("rect", {x: badgeX, y: y + 58, width: 28, height: 16, class: "badge-rect"}))
      addText(bg, "PRT", badgeX + 4, y + 70, "badge-text")
      g.appendChild(bg)
    }

    // Footnote: Tool or Injection marker
    if (op.is_injection_target) {
      addText(g, "⤹ Injected Subassembly", x + 12, y + 96, "edge-label")
    } else if (op.tools) {
      addText(g, short(`Tool: ${op.tools}`, 22), x + 12, y + 96, "op-seq")
    }

    // Tooltip listeners
    const showTooltip = (event) => {
      tooltip.innerHTML = `<strong>${op.op_id} · ${op.operation}</strong><br>` +
        `Sequence: #${op.sequence} · Time: ${op.cycle_time_s.toFixed(1)}s<br>` +
        `Parts: ${op.parts ? op.parts.length : 0} paired · Tool: ${op.tools || 'None'}<br>` +
        `<small style="color:var(--st-secondary-text-color)">Click block to inspect full details</small>`
      tooltip.hidden = false
      const bounds = viewport.getBoundingClientRect()
      tooltip.style.left = `${clamp(event.clientX - bounds.left + 14, 8, bounds.width - 340)}px`
      tooltip.style.top = `${clamp(event.clientY - bounds.top + 14, 8, bounds.height - 90)}px`
    }
    g.addEventListener("pointerenter", showTooltip)
    g.addEventListener("pointermove", showTooltip)
    g.addEventListener("pointerleave", () => tooltip.hidden = true)

    // Click selection
    const select = () => setTriggerValue("detail", {key: op.key})
    g.addEventListener("click", select)
    g.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault()
        select()
      }
    })

    opLayer.appendChild(g)
  })
  world.appendChild(opLayer)

  // Unresolved Feeder Alerts
  unresolved.forEach((item, idx) => {
    const g = node("g", {class: "unresolved"})
    const ux = 40 + idx * 260, uy = feederY + 180
    g.appendChild(node("rect", {x: ux, y: uy, width: 240, height: 32}))
    addText(g, `⚠️ ${item.pitch_number}: ${item.label}`, ux + 10, uy + 20)
    world.appendChild(g)
  })

  // Viewport navigation helpers
  function apply() { world.setAttribute("transform", `translate(${state.x} ${state.y}) scale(${state.scale})`) }
  function bounds() { try { return world.getBBox() } catch { return {x:0, y:0, width:1, height:1} } }
  function fit() {
    const b = bounds(), w = viewport.clientWidth, h = viewport.clientHeight
    if (!w || !h || !b.width || !b.height) return
    state.scale = clamp(Math.min((w - 60) / b.width, (h - 60) / b.height), 0.15, 1.3)
    state.x = (w - b.width * state.scale) / 2 - b.x * state.scale
    state.y = (h - b.height * state.scale) / 2 - b.y * state.scale
    apply()
  }
  function zoom(factor) {
    const cx = viewport.clientWidth / 2, cy = viewport.clientHeight / 2, old = state.scale
    state.scale = clamp(old * factor, 0.12, 3.0)
    state.x = cx - (cx - state.x) * (state.scale / old)
    state.y = cy - (cy - state.y) * (state.scale / old)
    apply()
  }

  svg.onwheel = (event) => { event.preventDefault(); zoom(event.deltaY < 0 ? 1.12 : 0.89) }
  svg.onpointerdown = (event) => {
    if (event.target.closest(".op-node")) return
    state.drag = true
    state.px = event.clientX
    state.py = event.clientY
    svg.classList.add("dragging")
    svg.setPointerCapture(event.pointerId)
  }
  svg.onpointermove = (event) => {
    if (!state.drag) return
    state.x += event.clientX - state.px
    state.y += event.clientY - state.py
    state.px = event.clientX
    state.py = event.clientY
    apply()
  }
  svg.onpointerup = svg.onpointercancel = () => {
    state.drag = false
    svg.classList.remove("dragging")
  }

  parentElement.querySelector("#pfd-zoom-out").onclick = () => zoom(0.83)
  parentElement.querySelector("#pfd-zoom-in").onclick = () => zoom(1.2)
  parentElement.querySelector("#pfd-fit").onclick = fit
  parentElement.querySelector("#pfd-reset").onclick = () => { state.scale = 1; state.x = 30; state.y = 30; apply() }
  parentElement.querySelector("#pfd-full").onclick = async () => {
    if (document.fullscreenElement === shell) await document.exitFullscreen()
    else await shell.requestFullscreen()
    setTimeout(fit, 80)
  }

  if (!state.fitted) {
    state.fitted = true
    requestAnimationFrame(() => requestAnimationFrame(fit))
  } else {
    apply()
  }
}
"""

_PROCESS_FLOW_COMPONENT = None


def _get_process_flow_component():
    global _PROCESS_FLOW_COMPONENT
    try:
        from streamlit.runtime import Runtime
        if Runtime.exists():
            registry = Runtime.instance().bidi_component_registry
            if registry.get("paag_process_flow_map_v1") is None:
                return st.components.v2.component(
                    "paag_process_flow_map_v1",
                    html=_PROCESS_FLOW_HTML,
                    css=_PROCESS_FLOW_CSS,
                    js=_PROCESS_FLOW_JS,
                )
    except Exception:
        pass
    if _PROCESS_FLOW_COMPONENT is None:
        _PROCESS_FLOW_COMPONENT = st.components.v2.component(
            "paag_process_flow_map_v1",
            html=_PROCESS_FLOW_HTML,
            css=_PROCESS_FLOW_CSS,
            js=_PROCESS_FLOW_JS,
        )
    return _PROCESS_FLOW_COMPONENT


def render_process_flow_diagram(
    project_id: str,
    scenario_id: str,
    *,
    key: str,
    shape_mode: str = "functional",
) -> None:
    """Render the read-only Process Flow Diagram tab and handle operation inspections."""
    try:
        projection = process_flow_projection(project_id, scenario_id, shape_mode=shape_mode)
    except Exception as exc:
        st.error(f"Could not load process flow: {exc}")
        return

    if not projection.get("operations"):
        st.info("No Work Elements found in this Scenario to map.")
        return

    # Metrics summary strip
    metrics = projection["metrics"]
    m_cols = st.columns(4)
    m_cols[0].metric("Total Pitches", metrics["total_pitches"])
    m_cols[1].metric("Total Operations", metrics["total_operations"])
    m_cols[2].metric("Total Work Time", f"{metrics['total_work_time_s']} s")
    m_cols[3].metric("Takt Bottlenecks", metrics["bottlenecks"], help="Pitches where total cycle time exceeds takt time")

    request_key = f"process_flow_detail_{project_id}_{scenario_id}"

    def stage_detail() -> None:
        event = st.session_state.get(key, {}) or {}
        detail = event.get("detail") or {}
        selected_key = str(detail.get("key") or "")
        valid_keys = {item["key"] for item in projection.get("operations", [])}
        if selected_key in valid_keys:
            st.session_state[request_key] = selected_key

    try:
        component_fn = _get_process_flow_component()
        component_fn(
            key=key,
            data=projection,
            on_detail_change=stage_detail,
            width="stretch",
            height="content",
        )
    except ValueError as exc:
        if "not registered" in str(exc).lower():
            st.caption(f"Process flow map ready ({len(projection['operations'])} operations)")
        else:
            raise

    selected_key = st.session_state.pop(request_key, "")
    if selected_key:
        op = next((o for o in projection["operations"] if o["key"] == selected_key), None)
        if op:
            _show_operation_detail_dialog(op)


@st.dialog("Job Operation Details", width="large")
def _show_operation_detail_dialog(op: dict[str, Any]) -> None:
    """Display a clean, read-only inspector modal for a clicked operation."""
    st.subheader(f"{op['op_id']} — {op['operation']}")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Sequence:** #{op['sequence']}")
        st.markdown(f"**Station:** {op['station'] or 'Unassigned'}")
        st.markdown(f"**Cycle Time:** {op['cycle_time_s']:.1f} s")
        if op["tools"]:
            st.markdown(f"**Tool / Fixture:** {op['tools']}")
        if op["torque"]:
            st.markdown(f"**Torque Spec:** {op['torque']}")
    with col2:
        crit_badges = []
        if "CTQ" in op.get("criticality", []):
            crit_badges.append("🟠 **CTQ** (Critical to Quality)")
        if "Safety" in op.get("criticality", []):
            crit_badges.append("🔴 **Safety Critical**")
        if op.get("ergonomics_risk"):
            crit_badges.append("⚠️ **Ergonomics Risk**")
        st.markdown(f"**Criticality:** {', '.join(crit_badges) if crit_badges else 'Standard Operation'}")
        if op.get("output_assembly_number"):
            st.markdown(f"**Outputs Subassembly:** {op['output_assembly_number']} — {op.get('output_assembly_name', '')}")
        if op.get("is_injection_target"):
            st.info("This operation receives an injected subassembly from a feeder line.")

    st.divider()
    st.markdown("##### Part Requirements")
    parts = op.get("parts", [])
    if parts:
        df = pd.DataFrame(parts)
        df.rename(columns={"part_number": "Part Number", "handling_type": "Handling", "group_name": "Group"}, inplace=True)
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.caption("No parts paired to this operation.")
