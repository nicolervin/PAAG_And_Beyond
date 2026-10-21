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
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.split-nav-actions {
  align-items: center;
  display: inline-flex;
  gap: .25rem;
}
.split-nav-popout {
  align-items: center;
  border-radius: .25rem;
  color: color-mix(in srgb, var(--text-color) 45%, transparent);
  cursor: pointer;
  display: inline-flex;
  justify-content: center;
  line-height: 1;
  padding: .15rem .2rem;
  text-decoration: none;
  transition: color .15s ease, background .15s ease;
}
.split-nav-popout:hover {
  background: color-mix(in srgb, var(--primary-color) 18%, transparent);
  color: var(--primary-color);
}
.split-nav-popout-icon {
  font-family: "Material Symbols Rounded", "Material Symbols Outlined", sans-serif;
  font-size: 1.05rem;
  line-height: 1;
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

  if (data.show_help !== false) {
    const help = document.createElement('div')
    help.className = 'split-nav-help'
    help.textContent = 'Click to open. Use ⧉ to pop out to a new window. Drag to split view.'
    root.appendChild(help)
  }

  const makePageUrl = (urlPath) => {
    try {
      const parts = window.location.pathname.split('/').filter(Boolean)
      if (parts.length > 0) {
        const last = parts[parts.length - 1]
        if (last === data.active_url_path || last === data.secondary_url_path) {
          parts.pop()
        }
      }
      const basePath = '/' + (parts.length > 0 ? parts.join('/') + '/' : '')
      const cleanPath = (urlPath && urlPath !== '__default__') ? urlPath : ''
      const targetUrl = new URL(basePath + cleanPath, window.location.origin)
      if (cleanPath) {
        targetUrl.searchParams.set('page', cleanPath)
      }
      if (data.project_id) {
        targetUrl.searchParams.set('project_id', data.project_id)
      }
      if (data.scenario_id) {
        targetUrl.searchParams.set('scenario_id', data.scenario_id)
      }
      return targetUrl.toString()
    } catch (e) {
      const q = []
      if (urlPath && urlPath !== '__default__') q.push('page=' + encodeURIComponent(urlPath))
      if (data.project_id) q.push('project_id=' + encodeURIComponent(data.project_id))
      if (data.scenario_id) q.push('scenario_id=' + encodeURIComponent(data.scenario_id))
      const qs = q.length > 0 ? '?' + q.join('&') : ''
      return (urlPath && urlPath !== '__default__') ? `./${urlPath}${qs}` : `./${qs}`
    }
  }

  let draggedPath = ''
  let suppressClick = false
  for (const section of (data.sections || [])) {
    if (section.name) {
      const heading = document.createElement('div')
      heading.className = 'split-nav-section'
      heading.textContent = section.name
      root.appendChild(heading)
    }

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

      const actions = document.createElement('div')
      actions.className = 'split-nav-actions'

      const popout = document.createElement('a')
      popout.className = 'split-nav-popout'
      popout.title = `Open ${page.title} in new window or tab`
      popout.setAttribute('aria-label', `Open ${page.title} in new window or tab`)
      popout.target = '_blank'
      popout.rel = 'noopener noreferrer'
      popout.href = makePageUrl(page.url_path)
      popout.onclick = (event) => {
        event.stopPropagation()
      }
      const popoutIcon = document.createElement('span')
      popoutIcon.className = 'split-nav-popout-icon'
      popoutIcon.textContent = 'open_in_new'
      popout.appendChild(popoutIcon)
      actions.appendChild(popout)

      const grip = document.createElement('span')
      grip.className = 'split-nav-grip'
      grip.title = 'Drag to split view'
      grip.textContent = '⠿'
      actions.appendChild(grip)

      item.appendChild(actions)

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

  if (data.show_drop_zone !== false) {
    const drop = document.createElement('div')
    drop.className = 'split-nav-drop'
    drop.innerHTML = '<span class="split-nav-icon">splitscreen</span><span>Drop a page here to open split view</span>'
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
      open.innerHTML = '<span class="split-nav-icon">splitscreen</span>'
      const label = document.createElement('span')
      label.textContent = `Split: ${data.secondary_title}`
      open.appendChild(label)

      const popoutSecondary = document.createElement('a')
      popoutSecondary.className = 'split-nav-popout'
      popoutSecondary.title = `Pop out ${data.secondary_title} to separate window`
      popoutSecondary.setAttribute('aria-label', `Pop out ${data.secondary_title} to separate window`)
      popoutSecondary.target = '_blank'
      popoutSecondary.rel = 'noopener noreferrer'
      popoutSecondary.href = makePageUrl(data.secondary_url_path)
      popoutSecondary.onclick = (e) => e.stopPropagation()
      const popSecIcon = document.createElement('span')
      popSecIcon.className = 'split-nav-popout-icon'
      popSecIcon.textContent = 'open_in_new'
      popoutSecondary.appendChild(popSecIcon)
      open.appendChild(popoutSecondary)

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
}
"""

_SPLIT_NAVIGATION = st.components.v2.component(
    "paag_split_navigation_v3",
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


def build_page_url(
    url_path: str = "",
    *,
    project_id: str | None = None,
    scenario_id: str | None = None,
    query_params: dict[str, Any] | None = None,
) -> str:
    """Build a relative URL targeting a page with project and scenario query parameters.

    This helper is suitable for st.link_button and <a> tags to pop out pages into
    separate browser windows or tabs while maintaining project and scenario context.
    """
    pid = project_id if project_id is not None else st.session_state.get("project_id")
    sid = scenario_id if scenario_id is not None else st.session_state.get("scenario_id")

    clean_path = url_path.strip() if url_path and url_path != "__default__" else ""
    if not clean_path and not url_path:
        curr = str(st.session_state.get("current_url_path") or "")
        if curr and curr != "__default__":
            clean_path = curr

    params: dict[str, Any] = {}
    if clean_path:
        params["page"] = clean_path
    if pid:
        params["project_id"] = str(pid)
    if sid:
        params["scenario_id"] = str(sid)
    if query_params:
        for k, v in query_params.items():
            if v is not None:
                params[k] = str(v)

    from urllib.parse import urlencode

    qs = f"?{urlencode(params)}" if params else ""
    if clean_path:
        return f"./{clean_path}{qs}"
    return f"./{qs}" if qs else "./"


def split_navigation(
    sections: list[dict[str, Any]],
    *,
    active_url_path: str,
    secondary_url_path: str,
    secondary_title: str,
    project_id: str = "",
    scenario_id: str = "",
    show_help: bool = True,
    show_drop_zone: bool = True,
    key: str,
    on_navigate_change: Callable[[], None],
    on_split_change: Callable[[], None],
    on_close_split_change: Callable[[], None],
) -> None:
    if _is_app_test():
        if show_drop_zone:
            st.caption("Split-view navigation is available in the browser.")
        return
    _SPLIT_NAVIGATION(
        key=key,
        data={
            "sections": sections,
            "active_url_path": active_url_path,
            "secondary_url_path": secondary_url_path,
            "secondary_title": secondary_title,
            "project_id": str(project_id or ""),
            "scenario_id": str(scenario_id or ""),
            "show_help": bool(show_help),
            "show_drop_zone": bool(show_drop_zone),
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
