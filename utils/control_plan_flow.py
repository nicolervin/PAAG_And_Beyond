"""Interactive, read-only Manufacturing Control Plan Process Flow Map."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st


_HTML = """
<div class="flow-shell">
  <div class="flow-toolbar">
    <div><strong>Manufacturing Process flow map</strong><span id="flow-summary"></span></div>
    <div class="flow-actions">
      <button id="flow-zoom-out" type="button" title="Zoom out">−</button>
      <button id="flow-zoom-in" type="button" title="Zoom in">+</button>
      <button id="flow-fit" type="button" title="Fit the complete map">Fit</button>
      <button id="flow-reset" type="button" title="Reset the map view">Reset</button>
      <button id="flow-full" type="button" title="Open full screen">Full screen</button>
    </div>
  </div>
  <div class="flow-viewport">
    <svg id="flow-svg" role="img" aria-label="Manufacturing Control Plan Process flow map">
      <defs>
        <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker>
      </defs>
      <g id="flow-world"></g>
    </svg>
    <div id="flow-tooltip" class="flow-tooltip" hidden></div>
    <div class="flow-hint">Scroll to zoom · Drag to pan · Select a characteristic for details</div>
  </div>
</div>
"""


_CSS = """
:host { color: var(--st-text-color); font-family: var(--st-font); }
.flow-shell { box-sizing:border-box; width:100%; height:720px; min-height:720px; display:flex; flex-direction:column; border:1px solid var(--st-border-color); border-radius:var(--st-base-radius); overflow:hidden; background:var(--st-background-color); }
.flow-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 12px; border-bottom:1px solid var(--st-border-color); background:var(--st-secondary-background-color); }
.flow-toolbar > div:first-child { display:flex; align-items:baseline; gap:10px; min-width:0; }
#flow-summary { color:var(--st-secondary-text-color); font-size:.82rem; white-space:nowrap; }
.flow-actions { display:flex; gap:6px; }
.flow-actions button { min-width:34px; height:32px; padding:0 10px; border:1px solid var(--st-border-color); border-radius:var(--st-button-radius); color:var(--st-text-color); background:var(--st-background-color); cursor:pointer; font:inherit; font-weight:600; }
.flow-actions button:hover { color:var(--st-primary-color); border-color:var(--st-primary-color); }
.flow-viewport { position:relative; flex:1 1 auto; min-height:0; overflow:hidden; touch-action:none; background-color:var(--st-background-color); background-image:radial-gradient(circle, color-mix(in srgb, var(--st-text-color) 13%, transparent) 1px, transparent 1px); background-size:22px 22px; }
#flow-svg { display:block; width:100%; height:100%; cursor:grab; user-select:none; }
#flow-svg.dragging { cursor:grabbing; }
#flow-arrow path { fill:var(--st-secondary-text-color); }
.edge { fill:none; stroke:var(--st-secondary-text-color); stroke-width:2; marker-end:url(#flow-arrow); }
.feed-edge { stroke:var(--st-primary-color); stroke-width:3; }
.hierarchy-edge { fill:none; stroke:var(--st-secondary-text-color); stroke-width:1.5; stroke-dasharray:7 6; }
.lane { fill:color-mix(in srgb, var(--st-secondary-background-color) 62%, transparent); stroke:var(--st-border-color); stroke-width:1; }
.lane-label { fill:var(--st-text-color); font-size:14px; font-weight:700; }
.pitch-label { fill:var(--st-secondary-text-color); font-size:11px; }
.operation rect { fill:var(--st-background-color); stroke:var(--st-text-color); stroke-width:2; rx:7; }
.operation text { fill:var(--st-text-color); font-size:12px; pointer-events:none; }
.operation .op-id { font-weight:700; fill:var(--st-primary-color); }
.characteristic { cursor:pointer; outline:none; }
.characteristic ellipse { stroke-width:2.5; }
.characteristic.product ellipse { fill:#dbeafe; stroke:#2563eb; }
.characteristic.process ellipse { fill:#dcfce7; stroke:#16a34a; }
.characteristic.unassigned ellipse { fill:var(--st-background-color); stroke:#d97706; stroke-dasharray:7 4; }
.characteristic text { fill:#111827; font-size:11px; pointer-events:none; }
.characteristic:hover ellipse, .characteristic:focus ellipse { stroke-width:4; filter:drop-shadow(0 4px 7px rgba(0,0,0,.25)); }
.unresolved rect { fill:#fffbeb; stroke:#d97706; stroke-width:2; stroke-dasharray:6 4; rx:16; }
.unresolved text { fill:#92400e; font-size:12px; font-weight:700; }
.flow-tooltip { position:absolute; z-index:5; max-width:340px; padding:9px 11px; border:1px solid var(--st-primary-color); border-radius:8px; background:var(--st-background-color); color:var(--st-text-color); box-shadow:0 10px 28px rgba(0,0,0,.22); pointer-events:none; font-size:.82rem; line-height:1.4; }
.flow-tooltip[hidden] { display:none; }
.flow-hint { position:absolute; right:12px; bottom:10px; padding:5px 8px; border-radius:6px; color:var(--st-secondary-text-color); background:color-mix(in srgb, var(--st-background-color) 88%, transparent); font-size:.75rem; pointer-events:none; }
.flow-shell:fullscreen { width:100vw; height:100vh; min-height:0; border:0; border-radius:0; }
"""


_JS = """
const NS = "http://www.w3.org/2000/svg"
const states = new WeakMap()
function node(name, attrs={}) { const value=document.createElementNS(NS,name); Object.entries(attrs).forEach(([k,v])=>value.setAttribute(k,String(v))); return value }
function clamp(value, low, high) { return Math.max(low, Math.min(high, value)) }
function addText(parent, value, x, y, cls="") { const text=node("text",{x,y,class:cls}); text.textContent=value || ""; parent.appendChild(text); return text }
function short(value, size) { value=String(value || ""); return value.length > size ? value.slice(0,size-1)+"…" : value }

export default function(component) {
  const {data, parentElement, setTriggerValue}=component
  const shell=parentElement.querySelector(".flow-shell"), viewport=parentElement.querySelector(".flow-viewport"), svg=parentElement.querySelector("#flow-svg"), world=parentElement.querySelector("#flow-world"), tooltip=parentElement.querySelector("#flow-tooltip")
  if (!shell || !viewport || !svg || !world || !data) return
  let state=states.get(parentElement)
  if (!state) { state={scale:1,x:24,y:24,drag:false,px:0,py:0,signature:"",fitted:false}; states.set(parentElement,state) }
  const operations=data.operations || [], characteristics=data.characteristics || [], sections=data.sections || [], pitches=data.pitches || []
  const signature=operations.map(x=>x.key).join("|")+"::"+characteristics.map(x=>x.key).join("|")
  if (signature !== state.signature) { state.signature=signature; state.fitted=false }
  parentElement.querySelector("#flow-summary").textContent=`${operations.length} operations · ${characteristics.length} characteristics`
  world.replaceChildren()

  const sectionMap=new Map(sections.map((section,index)=>[section.key,{...section,index}]))
  const operationMap=new Map()
  const operationsBySection=new Map()
  operations.forEach(op=>{ const key=op.section_key || "unlinked"; if(!operationsBySection.has(key)) operationsBySection.set(key,[]); operationsBySection.get(key).push(op) })
  const laneKeys=[...sections.map(x=>x.key), ...(operationsBySection.has("unlinked")?["unlinked"]:[])].filter(key=>operationsBySection.has(key))
  const laneHeight=360, left=150, stepX=300, boxW=230, boxH=116
  const lanePosition=new Map()
  laneKeys.forEach((sectionKey,laneIndex)=>{
    const ops=operationsBySection.get(sectionKey) || [], y=80+laneIndex*laneHeight
    lanePosition.set(sectionKey,{x:38,y})
    const section=sectionMap.get(sectionKey)
    const lane=node("rect",{x:20,y:y-45,width:Math.max(760,ops.length*stepX+220),height:laneHeight-28,class:"lane",rx:12}); world.appendChild(lane)
    addText(world, section?.name || "Unlinked Process steps", 38, y-16, "lane-label")
    addText(world, section ? `${section.section_type} · hierarchy depth ${section.depth}` : "No Fishbone section link", 38, y+4, "pitch-label")
    ops.forEach((op,index)=>{
      const x=left+index*stepX, opY=y+72
      operationMap.set(op.key,{x,y:opY,w:boxW,h:boxH,op})
      const g=node("g",{class:"operation",tabindex:"0",role:"group","aria-label":`${op.op_id}. ${op.operation}. Station or Pitch ${op.station_pitch}`})
      g.appendChild(node("rect",{x,y:opY,width:boxW,height:boxH}))
      addText(g, `Pr. Nº ${op.pr_number ?? "—"}`, x+12, opY+22)
      addText(g, short(op.op_id,32), x+12, opY+43, "op-id")
      addText(g, short(op.operation,34), x+12, opY+67)
      addText(g, short(`Station / Pitch: ${op.station_pitch}`,35), x+12, opY+91)
      world.appendChild(g)
    })
  })

  const edgeLayer=node("g")
  ;(data.section_edges||[]).forEach(edge=>{
    const from=lanePosition.get(edge.from), to=lanePosition.get(edge.to); if(!from || !to)return
    edgeLayer.appendChild(node("path",{d:`M ${from.x+45} ${from.y+8} C ${from.x-25} ${from.y+90}, ${to.x-25} ${to.y-90}, ${to.x+45} ${to.y-18}`,class:"hierarchy-edge"}))
  })
  ;[...(data.sequence_edges||[]), ...(data.feed_edges||[])].forEach(edge=>{
    const from=operationMap.get(edge.from), to=operationMap.get(edge.to); if(!from || !to) return
    const x1=from.x+from.w, y1=from.y+from.h/2, x2=to.x, y2=to.y+to.h/2
    const path=node("path",{d:`M ${x1} ${y1} C ${x1+60} ${y1}, ${x2-60} ${y2}, ${x2} ${y2}`,class:`edge ${edge.kind==="feed"?"feed-edge":""}`})
    edgeLayer.appendChild(path)
  })
  world.insertBefore(edgeLayer,world.firstChild)

  const charsByOperation=new Map()
  characteristics.forEach(item=>{ if(!charsByOperation.has(item.operation_key)) charsByOperation.set(item.operation_key,[]); charsByOperation.get(item.operation_key).push(item) })
  charsByOperation.forEach((items,opKey)=>{
    const op=operationMap.get(opKey); if(!op) return
    items.forEach((item,index)=>{
      const above=item.placement==="product", offset=index*74-(items.length-1)*37
      const cx=op.x+op.w/2+offset, cy=above?op.y-62:op.y+op.h+62
      const g=node("g",{class:`characteristic ${item.placement}`,tabindex:"0",role:"button","aria-label":`${item.placement} characteristic ${item.number || "unnumbered"}: ${item.description}. Select for details.`})
      g.appendChild(node("ellipse",{cx,cy,rx:104,ry:43}))
      addText(g, short(`${item.number || "—"} ${item.description}`,29), cx-90, cy-4)
      addText(g, short(`CL ${item.classification || "—"}`,28), cx-90, cy+17)
      const show=(event)=>{ tooltip.textContent=`${item.number || "Unnumbered"} · ${item.description} · ${item.placement} · CL ${item.classification || "—"}`; tooltip.hidden=false; const bounds=viewport.getBoundingClientRect(); tooltip.style.left=`${clamp(event.clientX-bounds.left+14,8,bounds.width-355)}px`; tooltip.style.top=`${clamp(event.clientY-bounds.top+14,8,bounds.height-90)}px` }
      g.addEventListener("pointerenter",show); g.addEventListener("pointermove",show); g.addEventListener("pointerleave",()=>tooltip.hidden=true); g.addEventListener("focus",()=>{tooltip.textContent=`${item.number || "Unnumbered"} · ${item.description} · Select for full details`; tooltip.hidden=false; tooltip.style.left="12px"; tooltip.style.top="12px"}); g.addEventListener("blur",()=>tooltip.hidden=true)
      const select=()=>setTriggerValue("detail",{key:item.key})
      g.addEventListener("click",select); g.addEventListener("keydown",event=>{if(event.key==="Enter" || event.key===" "){event.preventDefault();select()}})
      world.appendChild(g)
    })
  })

  ;(data.unresolved_feeds||[]).forEach((item,index)=>{
    const laneIndex=Math.max(0,laneKeys.indexOf(item.section_key)), x=60, y=80+laneIndex*laneHeight+270+index*42
    const g=node("g",{class:"unresolved"}); g.appendChild(node("rect",{x,y,width:190,height:32})); addText(g,item.label,x+14,y+21); world.appendChild(g)
  })

  function apply(){ world.setAttribute("transform",`translate(${state.x} ${state.y}) scale(${state.scale})`) }
  function bounds(){ try{return world.getBBox()}catch{return {x:0,y:0,width:1,height:1}} }
  function fit(){ const b=bounds(), w=viewport.clientWidth, h=viewport.clientHeight; if(!w||!h||!b.width||!b.height)return; state.scale=clamp(Math.min((w-50)/b.width,(h-50)/b.height),.16,1.25); state.x=(w-b.width*state.scale)/2-b.x*state.scale; state.y=(h-b.height*state.scale)/2-b.y*state.scale; apply() }
  function zoom(factor){ const cx=viewport.clientWidth/2,cy=viewport.clientHeight/2,old=state.scale; state.scale=clamp(old*factor,.12,3); state.x=cx-(cx-state.x)*(state.scale/old); state.y=cy-(cy-state.y)*(state.scale/old); apply() }
  svg.onwheel=event=>{event.preventDefault();zoom(event.deltaY<0?1.12:.89)}
  svg.onpointerdown=event=>{if(event.target.closest(".characteristic"))return; state.drag=true;state.px=event.clientX;state.py=event.clientY;svg.classList.add("dragging");svg.setPointerCapture(event.pointerId)}
  svg.onpointermove=event=>{if(!state.drag)return;state.x+=event.clientX-state.px;state.y+=event.clientY-state.py;state.px=event.clientX;state.py=event.clientY;apply()}
  svg.onpointerup=svg.onpointercancel=()=>{state.drag=false;svg.classList.remove("dragging")}
  parentElement.querySelector("#flow-zoom-out").onclick=()=>zoom(.83)
  parentElement.querySelector("#flow-zoom-in").onclick=()=>zoom(1.2)
  parentElement.querySelector("#flow-fit").onclick=fit
  parentElement.querySelector("#flow-reset").onclick=()=>{state.scale=1;state.x=24;state.y=24;apply()}
  parentElement.querySelector("#flow-full").onclick=async()=>{if(document.fullscreenElement===shell)await document.exitFullscreen();else await shell.requestFullscreen();setTimeout(fit,80)}
  if(!state.fitted){state.fitted=true;requestAnimationFrame(()=>requestAnimationFrame(fit))}else apply()
}
"""


_COMPONENT = st.components.v2.component(
    "paag_control_plan_process_flow_v1",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def control_plan_process_flow(
    payload: dict,
    *,
    key: str,
    on_detail_change: Callable[[], None],
) -> None:
    """Render the Process Flow Map and emit only a narrow detail-selection event."""
    _COMPONENT(
        key=key,
        data=payload,
        on_detail_change=on_detail_change,
        width="stretch",
        height="content",
    )
