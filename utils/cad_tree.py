from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from utils.component_payload import json_safe

_HTML = """
<div class="cad-tree-shell">
  <div class="cad-tree-toolbar">
    <div class="search-box">
      <span class="search-icon">🔍</span>
      <input type="text" id="cad-tree-search" placeholder="Search Model Browser (part #, description)..." autocomplete="off" />
      <button id="search-clear" type="button" title="Clear search" style="display:none;">✕</button>
    </div>
    <div class="toolbar-actions">
      <button id="btn-expand-all" type="button" title="Expand all assembly groups">➕ Expand all</button>
      <button id="btn-collapse-all" type="button" title="Collapse all assembly groups">➖ Collapse all</button>
    </div>
  </div>
  <div class="cad-tree-viewport">
    <div id="cad-tree-root" class="tree-root"></div>
  </div>
  <div class="cad-tree-footer">
    <span id="cad-tree-status">Loading model structure...</span>
  </div>
</div>
"""

_CSS = """
:host {
  color: var(--st-text-color, #222);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 13px;
}
.cad-tree-shell {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 620px;
  min-height: 520px;
  border: 1px solid var(--st-border-color, #d0d7de);
  border-radius: 8px;
  background: var(--st-background-color, #ffffff);
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.cad-tree-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  background: var(--st-secondary-background-color, #f6f8fa);
  border-bottom: 1px solid var(--st-border-color, #d0d7de);
}
.search-box {
  position: relative;
  flex: 1 1 auto;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 8px;
  font-size: 11px;
  color: #6e7781;
  pointer-events: none;
}
#cad-tree-search {
  width: 100%;
  box-sizing: border-box;
  padding: 5px 24px 5px 26px;
  font-size: 12px;
  border: 1px solid var(--st-border-color, #d0d7de);
  border-radius: 5px;
  background: var(--st-background-color, #ffffff);
  color: var(--st-text-color, #222);
  outline: none;
}
#cad-tree-search:focus {
  border-color: #0969da;
  box-shadow: 0 0 0 2px rgba(9, 105, 218, 0.2);
}
#search-clear {
  position: absolute;
  right: 6px;
  border: none;
  background: transparent;
  color: #6e7781;
  cursor: pointer;
  font-size: 11px;
  padding: 2px 4px;
}
.toolbar-actions {
  display: flex;
  gap: 6px;
}
.toolbar-actions button {
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid var(--st-border-color, #d0d7de);
  border-radius: 5px;
  background: var(--st-background-color, #ffffff);
  color: var(--st-text-color, #222);
  cursor: pointer;
  white-space: nowrap;
}
.toolbar-actions button:hover {
  background: var(--st-secondary-background-color, #f3f4f6);
  border-color: #8c959f;
}
.cad-tree-viewport {
  flex: 1 1 auto;
  overflow-y: auto;
  overflow-x: auto;
  padding: 6px 4px;
  background: var(--st-background-color, #ffffff);
}
.tree-root {
  display: flex;
  flex-direction: column;
  min-width: max-content;
}
.tree-node {
  display: flex;
  flex-direction: column;
}
.node-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 6px;
  border-radius: 4px;
  cursor: pointer;
  user-select: none;
  line-height: 20px;
  white-space: nowrap;
  transition: background 0.1s ease;
  border-left: 3px solid transparent;
}
.node-row:hover {
  background: rgba(9, 105, 218, 0.08);
}
.node-row.selected {
  background: rgba(9, 105, 218, 0.16) !important;
  border-left: 3px solid #0969da;
  font-weight: 600;
}
.node-row.search-match {
  background: #fff8c5 !important;
}
.chevron {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  font-size: 10px;
  color: #57606a;
  cursor: pointer;
  transition: transform 0.15s ease;
  user-select: none;
}
.chevron.empty {
  visibility: hidden;
  pointer-events: none;
}
.chevron.open {
  transform: rotate(90deg);
}
.node-icon {
  font-size: 13px;
  line-height: 1;
}
.node-part-no {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-weight: 700;
  font-size: 12px;
  color: var(--st-text-color, #24292f);
}
.node-depth-badge {
  font-size: 10px;
  padding: 0 4px;
  border-radius: 3px;
  background: #eaeef2;
  color: #57606a;
  font-family: monospace;
}
.node-desc {
  font-size: 12px;
  color: #57606a;
  margin-right: 4px;
}
.node-qty {
  font-size: 11px;
  padding: 0 5px;
  border-radius: 10px;
  background: #f0f3f6;
  color: #24292f;
  border: 1px solid #d0d7de;
}
.node-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 10px;
  margin-left: 4px;
}
.node-badge.missing-catalog {
  background: #ffebe9;
  color: #cf222e;
  border: 1px solid #ff8182;
}
.node-badge.missing-fishbone {
  background: #fff8c5;
  color: #9a6700;
  border: 1px solid #d4a72c;
}
.node-badge.placed {
  background: #dafbe1;
  color: #1a7f37;
  border: 1px solid #4ac26b;
}
.node-children {
  display: none;
  flex-direction: column;
  margin-left: 14px;
  border-left: 1px dashed #d0d7de;
  padding-left: 4px;
}
.node-children.open {
  display: flex;
}
.cad-tree-footer {
  padding: 5px 10px;
  font-size: 11px;
  color: #57606a;
  background: var(--st-secondary-background-color, #f6f8fa);
  border-top: 1px solid var(--st-border-color, #d0d7de);
}
"""

_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component
  if (!parentElement || !data) return

  const rootEl = parentElement.querySelector("#cad-tree-root")
  const searchInput = parentElement.querySelector("#cad-tree-search")
  const clearBtn = parentElement.querySelector("#search-clear")
  const expandAllBtn = parentElement.querySelector("#btn-expand-all")
  const collapseAllBtn = parentElement.querySelector("#btn-collapse-all")
  const statusEl = parentElement.querySelector("#cad-tree-status")

  if (!rootEl) return

  const escapeHtml = (str) => {
    return String(str || "").replace(/[&<>"']/g, (m) => {
      switch (m) {
        case "&": return "&amp;"
        case "<": return "&lt;"
        case ">": return "&gt;"
        case '"': return "&quot;"
        case "'": return "&#39;"
        default: return m
      }
    })
  }

  const roots = data.roots || []
  const selectedId = data.selected_id || null
  let totalNodesCount = 0

  rootEl.innerHTML = ""

  function createNodeElement(node) {
    totalNodesCount++
    const hasChildren = Array.isArray(node.children) && node.children.length > 0
    const nodeEl = document.createElement("div")
    nodeEl.className = "tree-node"
    nodeEl.dataset.id = node.id
    nodeEl.dataset.partNo = (node.part_number || "").toLowerCase()
    nodeEl.dataset.desc = (node.description || "").toLowerCase()
    nodeEl.dataset.tracker = (node.child_tracker || "").toLowerCase()

    const rowEl = document.createElement("div")
    rowEl.className = "node-row" + (node.id === selectedId ? " selected" : "")

    // Chevron
    const chevron = document.createElement("span")
    chevron.className = "chevron" + (hasChildren ? "" : " empty")
    chevron.innerHTML = "▶"

    // Icon
    const icon = document.createElement("span")
    icon.className = "node-icon"
    icon.textContent = hasChildren ? "📁" : "📄"

    // Depth badge
    const depthBadge = document.createElement("span")
    depthBadge.className = "node-depth-badge"
    depthBadge.textContent = "L" + node.depth

    // Part number
    const partNo = document.createElement("span")
    partNo.className = "node-part-no"
    partNo.textContent = node.part_number || "—"

    // Description
    const desc = document.createElement("span")
    desc.className = "node-desc"
    desc.textContent = "— " + (node.description || "Uncataloged item")

    // Quantity
    const qty = document.createElement("span")
    qty.className = "node-qty"
    qty.textContent = "×" + (node.quantity ?? 1)

    // Status Badge
    let badgeHtml = ""
    if (!node.in_catalog) {
      badgeHtml = '<span class="node-badge missing-catalog">Missing from Catalog</span>'
    } else if (!node.in_fishbone) {
      badgeHtml = '<span class="node-badge missing-fishbone">Missing from Fishbone</span>'
    } else {
      const sec = (node.fishbone_sections && node.fishbone_sections.length) ? node.fishbone_sections[0] : "Placed"
      badgeHtml = '<span class="node-badge placed">Placed: ' + escapeHtml(sec) + '</span>'
    }

    rowEl.appendChild(chevron)
    rowEl.appendChild(icon)
    rowEl.appendChild(depthBadge)
    rowEl.appendChild(partNo)
    rowEl.appendChild(desc)
    rowEl.appendChild(qty)
    if (badgeHtml) {
      const bWrapper = document.createElement("span")
      bWrapper.innerHTML = badgeHtml
      rowEl.appendChild(bWrapper.firstChild)
    }

    nodeEl.appendChild(rowEl)

    let childrenEl = null
    if (hasChildren) {
      childrenEl = document.createElement("div")
      childrenEl.className = "node-children"
      for (const child of node.children) {
        childrenEl.appendChild(createNodeElement(child))
      }
      nodeEl.appendChild(childrenEl)

      // Toggle function
      const toggle = (forceOpen) => {
        const isOpen = childrenEl.classList.contains("open")
        const nextState = forceOpen !== undefined ? forceOpen : !isOpen
        if (nextState) {
          childrenEl.classList.add("open")
          chevron.classList.add("open")
        } else {
          childrenEl.classList.remove("open")
          chevron.classList.remove("open")
        }
      }

      chevron.addEventListener("click", (e) => {
        e.stopPropagation()
        toggle()
      })

      rowEl.addEventListener("dblclick", (e) => {
        e.stopPropagation()
        toggle()
      })
    }

    // Row selection on single click
    rowEl.addEventListener("click", (e) => {
      e.stopPropagation()
      parentElement.querySelectorAll(".node-row.selected").forEach((el) => el.classList.remove("selected"))
      rowEl.classList.add("selected")
      if (setTriggerValue) {
        setTriggerValue("select_node", { node_id: node.id })
      }
    })

    return nodeEl
  }

  for (const root of roots) {
    rootEl.appendChild(createNodeElement(root))
  }

  // Open the first level of roots by default so user sees top assemblies immediately
  rootEl.querySelectorAll(":scope > .tree-node > .node-children").forEach((ch) => {
    ch.classList.add("open")
    const prev = ch.previousElementSibling
    if (prev) {
      const chv = prev.querySelector(".chevron")
      if (chv) chv.classList.add("open")
    }
  })

  // If a node was pre-selected, reveal its path and scroll into view
  if (selectedId) {
    const selNode = rootEl.querySelector(`.tree-node[data-id="${selectedId}"]`)
    if (selNode) {
      let curr = selNode.parentElement
      while (curr && curr !== rootEl) {
        if (curr.classList.contains("node-children")) {
          curr.classList.add("open")
          const parentRow = curr.previousElementSibling
          if (parentRow) {
            const chv = parentRow.querySelector(".chevron")
            if (chv) chv.classList.add("open")
          }
        }
        curr = curr.parentElement
      }
      setTimeout(() => {
        selNode.scrollIntoView({ behavior: "smooth", block: "center" })
      }, 50)
    }
  }

  // Toolbar actions
  expandAllBtn.onclick = () => {
    rootEl.querySelectorAll(".node-children").forEach((c) => c.classList.add("open"))
    rootEl.querySelectorAll(".chevron").forEach((c) => {
      if (!c.classList.contains("empty")) c.classList.add("open")
    })
  }

  collapseAllBtn.onclick = () => {
    rootEl.querySelectorAll(".node-children").forEach((c) => c.classList.remove("open"))
    rootEl.querySelectorAll(".chevron").forEach((c) => c.classList.remove("open"))
  }

  // Filter/search
  const filterTree = (query) => {
    const q = (query || "").trim().toLowerCase()
    clearBtn.style.display = q ? "inline-block" : "none"
    const allNodes = rootEl.querySelectorAll(".tree-node")

    if (!q) {
      allNodes.forEach((n) => {
        n.style.display = ""
        const row = n.querySelector(":scope > .node-row")
        if (row) row.classList.remove("search-match")
      })
      statusEl.textContent = `${totalNodesCount} items in model structure`
      return
    }

    let matchCount = 0
    // Evaluate leaves first to propagate visibility upwards
    allNodes.forEach((n) => {
      const match = (n.dataset.partNo.includes(q) || n.dataset.desc.includes(q) || n.dataset.tracker.includes(q))
      const row = n.querySelector(":scope > .node-row")
      if (match) {
        matchCount++
        row.classList.add("search-match")
      } else {
        row.classList.remove("search-match")
      }
      n.dataset.selfMatch = match ? "1" : "0"
    })

    // Walk nodes to ensure parents of matching nodes are visible and expanded
    allNodes.forEach((n) => {
      const hasMatchingDescendant = n.querySelector(`.tree-node[data-self-match="1"]`) !== null
      const selfMatch = n.dataset.selfMatch === "1"
      if (selfMatch || hasMatchingDescendant) {
        n.style.display = ""
        if (hasMatchingDescendant) {
          const ch = n.querySelector(":scope > .node-children")
          if (ch) {
            ch.classList.add("open")
            const chv = n.querySelector(":scope > .node-row > .chevron")
            if (chv) chv.classList.add("open")
          }
        }
      } else {
        n.style.display = "none"
      }
    })

    statusEl.textContent = `${matchCount} items match "${q}"`
  }

  searchInput.oninput = (e) => filterTree(e.target.value)
  clearBtn.onclick = () => {
    searchInput.value = ""
    filterTree("")
    searchInput.focus()
  }

  statusEl.textContent = `${totalNodesCount} items in model structure`
}
"""

_CAD_MODEL_TREE = st.components.v2.component(
    "paag_cad_model_tree_v1",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def cad_model_tree(
    roots: list[dict[str, Any]],
    *,
    selected_id: str | None = None,
    key: str = "cad_model_tree",
    on_select_node: Callable[[], None] | None = None,
) -> None:
    """Render the high-performance CAD Model Browser tree component with instant click-to-expand chevrons."""
    safe_roots = json_safe(roots)
    _CAD_MODEL_TREE(
        key=key,
        data={
            "roots": safe_roots,
            "selected_id": selected_id,
        },
        on_select_node_change=on_select_node,
        width="stretch",
        height="content",
    )
