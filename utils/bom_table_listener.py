"""Client-side hotkey and range-click listener for the BOM tree table."""

from __future__ import annotations

from typing import Any
import streamlit as st

_HTML = """<div class="bom-table-listener-anchor" style="display:none; height:0; width:0; overflow:hidden;" aria-hidden="true"></div>"""

_JS = """
export default function(component) {
  const { setTriggerValue } = component;
  if (window._paag_bom_listener_installed) return;
  window._paag_bom_listener_installed = true;

  let lastClickedRow = null;

  // Listen for pointerdown events on the table canvas
  window.parent.document.addEventListener('pointerdown', (e) => {
    try {
      const target = e.target;
      if (!target) return;
      const canvas = target.closest && target.closest('canvas.dvn-canvas');
      if (!canvas) return;

      const scroller = canvas.closest('.dvn-scroller') || canvas.parentElement;
      const rect = canvas.getBoundingClientRect();
      const scrollTop = scroller ? scroller.scrollTop : 0;
      // In Glide Data Grid, header height is ~36px and row height is ~35px
      const y = e.clientY - rect.top - 36 + scrollTop;
      if (y < 0) return; // Header click
      const clickedRow = Math.floor(y / 35);

      if (e.shiftKey && lastClickedRow !== null && lastClickedRow !== clickedRow) {
        const fromRow = Math.min(lastClickedRow, clickedRow);
        const toRow = Math.max(lastClickedRow, clickedRow);
        setTriggerValue("range_select", { from: fromRow, to: toRow, nonce: Date.now() });
      } else {
        lastClickedRow = clickedRow;
        setTriggerValue("row_anchor", { row: clickedRow, nonce: Date.now() });
      }
    } catch (err) {
      // Fail safely without disrupting the UI
    }
  }, true);

  // Listen for keyboard shortcuts (Shift+Up, Shift+Down)
  window.parent.document.addEventListener('keydown', (e) => {
    try {
      const activeEl = window.parent.document.activeElement;
      const activeTag = activeEl ? (activeEl.tagName || '').toLowerCase() : '';
      if (activeTag === 'input' || activeTag === 'textarea' || (activeEl && activeEl.isContentEditable)) {
        return;
      }
      if (e.shiftKey && e.key === 'ArrowUp') {
        e.preventDefault();
        setTriggerValue("shortcut", { action: "move_up", nonce: Date.now() });
      } else if (e.shiftKey && e.key === 'ArrowDown') {
        e.preventDefault();
        setTriggerValue("shortcut", { action: "move_down", nonce: Date.now() });
      }
    } catch (err) {
      // Fail safely
    }
  }, true);
}
"""

_BOM_LISTENER_COMPONENT = st.components.v2.component(
    "paag_bom_table_listener_v1",
    html=_HTML,
    js=_JS,
)


def bom_table_listener(*, key: str = "bom_table_listener") -> dict[str, Any] | None:
    """Render invisible event listener for Shift-click range selection and Shift+Arrow shortcuts."""
    try:
        return _BOM_LISTENER_COMPONENT(key=key, height="content")
    except Exception:
        return None
