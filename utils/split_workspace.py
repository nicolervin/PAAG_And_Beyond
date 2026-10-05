from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx


_NAV_HTML = """<div class="split-nav-root"></div>"""

_NAV_CSS = """
.split-nav-root {
  color: var(--text-color);
  font-family: var(--font);
}
.split-nav-help {
  color: color-mix(in srgb, var(--text-color) 65%, transparent);
  font-size: .78rem;
  line-height: 1.25;
  margin: .25rem .15rem .55rem;
}
.split-nav-section {
  color: color-mix(in srgb, var(--text-color) 68%, transparent);
  font-size: .72rem;
  font-weight: 700;
  letter-spacing: .04em;
  margin: .72rem .4rem .25rem;
  text-transform: uppercase;
}
.split-nav-item {
  align-items: center;
  border: 1px solid transparent;
  border-radius: .5rem;
  cursor: pointer;
  display: flex;
  gap: .45rem;
  margin: .08rem 0;
  min-height: 2.15rem;
  padding: .35rem .45rem;
  user-select: none;
}
.split-nav-item:hover {
  background: color-mix(in srgb, var(--primary-color) 9%, transparent);
}
.split-nav-item.active {
  background: color-mix(in srgb, var(--primary-color) 14%, transparent);
  border-color: color-mix(in srgb, var(--primary-color) 36%, transparent);
  font-weight: 650;
}
.split-nav-item.secondary {
  border-color: color-mix(in srgb, var(--primary-color) 52%, transparent);
}
.split-nav-icon {
  font-family: "Material Symbols Rounded", "Material Symbols Outlined", sans-serif;
  font-size: 1.15rem;
  width: 1.35rem;
}
.split-nav-title {
  flex: 1;
  font-size: .9rem;
}
.split-nav-grip {
  color: color-mix(in srgb, var(--text-color) 48%, transparent);
  cursor: grab;
  font-size: 1rem;
  letter-spacing: -.12rem;
  padding-right: .12rem;
}
.split-nav-drop {
  align-items: center;
  border: 1px dashed color-mix(in srgb, var(--primary-color) 55%, transparent);
  border-radius: .55rem;
  color: color-mix(in srgb, var(--text-color) 72%, transparent);
  display: flex;
  font-size: .8rem;
  gap: .4rem;
  justify-content: center;
  margin-top: .75rem;
  min-height: 3rem;
  padding: .45rem;
  text-align: center;
}
.split-nav-drop.over {
  background: color-mix(in srgb, var(--primary-color) 14%, transparent);
  border-style: solid;
  color: var(--text-color);
}
.split-nav-open {
  align-items: center;
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
  border-radius: .5rem;
  display: flex;
  font-size: .8rem;
  gap: .35rem;
  margin-top: .55rem;
  padding: .4rem .5rem;
}
.split-nav-open span { flex: 1; }
.split-nav-close {
  background: transparent;
  border: 0;
  border-radius: .3rem;
  color: inherit;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: .2rem .35rem;
}
.split-nav-close:hover {
  background: color-mix(in srgb, var(--text-color) 10%, transparent);
}
"""

_NAV_JS = """
export default function(component) {
  const { parentElement, data, setTriggerValue } = component
  const root = parentElement.querySelector('.split-nav-root')
  if (!root) return
  root.innerHTML = ''

  const help = document.createElement('div')
  help.className = 'split-nav-help'
  help.textContent = 'Click to open. Drag a page to the split target to view two pages together.'
  root.appendChild(help)

  let draggedPath = ''
  let suppressClick = false
  for (const section of (data.sections || [])) {
    const heading = document.createElement('div')
    heading.className = 'split-nav-section'
    heading.textContent = section.name
    root.appendChild(heading)

    for (const page of (section.pages || [])) {
      const item = document.createElement('div')
      item.className = 'split-nav-item'
      if (page.url_path === data.active_url_path) item.classList.add('active')
      if (page.url_path === data.secondary_url_path) item.classList.add('secondary')
      item.draggable = true
      item.dataset.urlPath = page.url_path

      const icon = document.createElement('span')
      icon.className = 'split-nav-icon'
      icon.textContent = page.icon || 'description'
      item.appendChild(icon)

      const title = document.createElement('span')
      title.className = 'split-nav-title'
      title.textContent = page.title
      item.appendChild(title)

      const grip = document.createElement('span')
      grip.className = 'split-nav-grip'
      grip.title = 'Drag to split view'
      grip.textContent = '⠿'
      item.appendChild(grip)

      item.onclick = () => {
        if (suppressClick) return
        setTriggerValue('navigate', {
          url_path: page.url_path,
          nonce: Date.now(),
        })
      }
      item.ondragstart = (event) => {
        suppressClick = true
        draggedPath = page.url_path
        event.dataTransfer.effectAllowed = 'copy'
        event.dataTransfer.setData('text/plain', page.url_path)
      }
      item.ondragend = () => setTimeout(() => { suppressClick = false }, 0)
      root.appendChild(item)
    }
  }

  const drop = document.createElement('div')
  drop.className = 'split-nav-drop'
  drop.innerHTML = '<span class="split-nav-icon">vertical_split</span><span>Drop a page here to open split view</span>'
  drop.ondragover = (event) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
    drop.classList.add('over')
  }
  drop.ondragleave = () => drop.classList.remove('over')
  drop.ondrop = (event) => {
    event.preventDefault()
    drop.classList.remove('over')
    const urlPath = event.dataTransfer.getData('text/plain') || draggedPath
    if (urlPath) setTriggerValue('split', {url_path: urlPath, nonce: Date.now()})
  }
  root.appendChild(drop)

  if (data.secondary_title) {
    const open = document.createElement('div')
    open.className = 'split-nav-open'
    open.innerHTML = '<span class="split-nav-icon">view_column_2</span>'
    const label = document.createElement('span')
    label.textContent = `Split: ${data.secondary_title}`
    open.appendChild(label)
    const close = document.createElement('button')
    close.className = 'split-nav-close'
    close.title = 'Close split view'
    close.setAttribute('aria-label', 'Close split view')
    close.textContent = '×'
    close.onclick = () => setTriggerValue('close_split', {nonce: Date.now()})
    open.appendChild(close)
    root.appendChild(open)
  }
}
"""

_SPLIT_NAVIGATION = st.components.v2.component(
    "paag_split_navigation_v1",
    html=_NAV_HTML,
    css=_NAV_CSS,
    js=_NAV_JS,
)


_DIVIDER_HTML = """<div class="split-divider" role="separator" aria-orientation="vertical" tabindex="0"><span>⋮</span></div>"""

_DIVIDER_CSS = """
.split-divider {
  align-items: center;
  background: color-mix(in srgb, var(--primary-color) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary-color) 28%, transparent);
  border-radius: 999px;
  cursor: col-resize;
  display: flex;
  height: min(68vh, 680px);
  justify-content: center;
  margin: .35rem auto;
  touch-action: none;
  width: .65rem;
}
.split-divider:hover,
.split-divider.dragging {
  background: color-mix(in srgb, var(--primary-color) 30%, transparent);
  border-color: var(--primary-color);
}
.split-divider span {
  color: color-mix(in srgb, var(--text-color) 55%, transparent);
  font-size: 1.05rem;
  pointer-events: none;
}
"""

_DIVIDER_JS = """
export default function(component) {
  const { parentElement, data, setTriggerValue } = component
  const handle = parentElement.querySelector('.split-divider')
  if (!handle) return

  const locateColumns = () => {
    const componentRoot = parentElement.getRootNode ? parentElement.getRootNode() : null
    const host = componentRoot && componentRoot.host ? componentRoot.host : parentElement
    const ownColumn = host.closest('[data-testid="stColumn"]')
    const block = ownColumn ? ownColumn.parentElement : null
    if (!block) return null
    const columns = Array.from(block.children).filter(
      child => child.matches && child.matches('[data-testid="stColumn"]')
    )
    return columns.length >= 3 ? {block, columns} : null
  }

  const applyRatio = (ratio) => {
    const found = locateColumns()
    if (!found) return
    const value = Math.max(.25, Math.min(.75, ratio))
    const leftPercent = value * 100
    const rightPercent = (1 - value) * 100
    found.columns[0].style.flex = `1 1 ${leftPercent}%`
    found.columns[2].style.flex = `1 1 ${rightPercent}%`
  }

  applyRatio(Number(data.ratio || .5))
  handle.onpointerdown = (event) => {
    const found = locateColumns()
    if (!found) return
    event.preventDefault()
    handle.classList.add('dragging')
    handle.setPointerCapture(event.pointerId)

    const move = (moveEvent) => {
      const rect = found.block.getBoundingClientRect()
      if (!rect.width) return
      applyRatio((moveEvent.clientX - rect.left) / rect.width)
    }
    const end = (endEvent) => {
      const rect = found.block.getBoundingClientRect()
      const ratio = Math.max(.25, Math.min(.75, (endEvent.clientX - rect.left) / rect.width))
      handle.classList.remove('dragging')
      handle.releasePointerCapture(event.pointerId)
      handle.removeEventListener('pointermove', move)
      handle.removeEventListener('pointerup', end)
      handle.removeEventListener('pointercancel', end)
      setTriggerValue('ratio', {value: ratio, nonce: Date.now()})
    }
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', end)
    handle.addEventListener('pointercancel', end)
  }
}
"""

_SPLIT_DIVIDER = st.components.v2.component(
    "paag_split_divider_v1",
    html=_DIVIDER_HTML,
    css=_DIVIDER_CSS,
    js=_DIVIDER_JS,
)


def component_event(component_key: str, event_name: str) -> dict[str, Any]:
    state = st.session_state.get(component_key, {}) or {}
    value = state.get(event_name) if hasattr(state, "get") else getattr(state, event_name, None)
    return dict(value or {})


def _is_app_test() -> bool:
    context = get_script_run_ctx()
    return bool(context and context.session_id == "test session id")


def split_navigation(
    sections: list[dict[str, Any]],
    *,
    active_url_path: str,
    secondary_url_path: str,
    secondary_title: str,
    key: str,
    on_navigate_change: Callable[[], None],
    on_split_change: Callable[[], None],
    on_close_split_change: Callable[[], None],
) -> None:
    if _is_app_test():
        st.caption("Split-view navigation is available in the browser.")
        return
    _SPLIT_NAVIGATION(
        key=key,
        data={
            "sections": sections,
            "active_url_path": active_url_path,
            "secondary_url_path": secondary_url_path,
            "secondary_title": secondary_title,
        },
        on_navigate_change=on_navigate_change,
        on_split_change=on_split_change,
        on_close_split_change=on_close_split_change,
        width="stretch",
        height="content",
    )


def split_divider(
    ratio: float,
    *,
    key: str,
    on_ratio_change: Callable[[], None],
) -> None:
    if _is_app_test():
        st.markdown("|")
        return
    _SPLIT_DIVIDER(
        key=key,
        data={"ratio": max(0.25, min(0.75, float(ratio)))},
        on_ratio_change=on_ratio_change,
        width="stretch",
        height="content",
    )
