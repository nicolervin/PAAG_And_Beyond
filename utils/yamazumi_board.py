from __future__ import annotations

import json
import math
import re
from collections.abc import Callable

import streamlit as st

from utils.component_payload import json_safe
from utils.time_units import time_unit as time_unit_config

_PITCH_NUMBER_PAIR_RE = re.compile(r"^(.*?)(\d+)([^\d]*)$")


def _pitch_variants_list(pitch: dict) -> list[str]:
    raw_variants = pitch.get("model_variants")
    if isinstance(raw_variants, str):
        try:
            raw_variants = json.loads(raw_variants)
        except ValueError:
            raw_variants = [raw_variants] if raw_variants.strip() else []
    if not isinstance(raw_variants, list) or not raw_variants:
        fallback = str(pitch.get("model_variant") or "All models").strip() or "All models"
        return [fallback]
    cleaned = [str(item).strip() for item in raw_variants if str(item).strip()]
    return cleaned or ["All models"]


def _element_variants_list(element: dict) -> list[str]:
    raw_variants = element.get("model_variants")
    if isinstance(raw_variants, str):
        try:
            raw_variants = json.loads(raw_variants)
        except ValueError:
            raw_variants = [raw_variants] if raw_variants.strip() else []
    if not isinstance(raw_variants, list) or not raw_variants:
        fallback = str(element.get("model_variant") or "All models").strip() or "All models"
        return [fallback]
    cleaned = [str(item).strip() for item in raw_variants if str(item).strip()]
    return cleaned or ["All models"]


def merge_yamazumi_pitch_variants(
    pitches: list[dict],
    elements: list[dict] | None = None,
) -> list[dict]:
    if not pitches:
        return []
    element_variants_by_pitch: dict[str, list[str]] = {}
    for element in elements or []:
        if not isinstance(element, dict):
            continue
        pitch_id = str(element.get("pitch_id") or "").strip()
        if not pitch_id:
            continue
        bucket = element_variants_by_pitch.setdefault(pitch_id, [])
        for variant in _element_variants_list(element):
            if variant not in bucket:
                bucket.append(variant)

    merged_pitches: list[dict] = []
    for raw_pitch in pitches:
        pitch = dict(raw_pitch)
        pitch_id = str(pitch.get("id") or "").strip()
        variants = list(_pitch_variants_list(pitch))
        if pitch_id and pitch_id in element_variants_by_pitch:
            for variant in element_variants_by_pitch[pitch_id]:
                if variant not in variants:
                    variants.append(variant)
        pitch["model_variants"] = variants
        merged_pitches.append(pitch)
    return merged_pitches


def _pitch_card_base_width_px(pitch: dict | None) -> int:
    if not isinstance(pitch, dict):
        return 240
    variants = _pitch_variants_list(pitch)
    return max(240, len(variants) * 165 + 18)


def _pitch_pair_metadata(pitch: dict) -> tuple[str, str | None]:
    raw_number = str(pitch.get("pitch_number") or "").strip()
    match = _PITCH_NUMBER_PAIR_RE.match(raw_number)
    if not match:
        return "south", None
    prefix, digits, suffix = match.groups()
    number = int(digits)
    if number <= 0:
        return "south", None
    side = "north" if number % 2 == 1 else "south"
    odd_number = number if number % 2 == 1 else number - 1
    normalized_prefix = prefix.strip().casefold()
    normalized_suffix = suffix.strip().casefold()
    return side, f"{normalized_prefix}::{odd_number}::{normalized_suffix}"


def build_yamazumi_pitch_pairs(
    pitches: list[dict],
    elements: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    paired_columns: list[dict] = []
    pairs_by_key: dict[str, dict] = {}
    for raw_pitch in merge_yamazumi_pitch_variants(pitches, elements):
        pitch = dict(raw_pitch)
        side, pair_key = _pitch_pair_metadata(pitch)
        pair = pairs_by_key.get(pair_key) if pair_key else None
        if pair is None or pair.get(side) is not None:
            pair = {
                "pair_index": len(paired_columns),
                "pair_key": pair_key,
                "north": None,
                "south": None,
            }
            paired_columns.append(pair)
            if pair_key and pair_key not in pairs_by_key:
                pairs_by_key[pair_key] = pair
        pair[side] = pitch

    annotated_pitches: list[dict] = []
    pair_summaries: list[dict] = []
    for pair_index, pair in enumerate(paired_columns):
        north_pitch = pair.get("north")
        south_pitch = pair.get("south")
        pair_width_px = max(
            _pitch_card_base_width_px(north_pitch),
            _pitch_card_base_width_px(south_pitch),
        )
        for side in ("north", "south"):
            side_pitch = pair.get(side)
            if isinstance(side_pitch, dict):
                side_pitch["pair_index"] = pair_index
                side_pitch["pair_side"] = side
                side_pitch["pair_key"] = pair.get("pair_key")
                side_pitch["pair_width_px"] = pair_width_px
                annotated_pitches.append(side_pitch)
        pair_summaries.append(
            {
                "pair_index": pair_index,
                "pair_key": pair.get("pair_key"),
                "pair_width_px": pair_width_px,
                "north_pitch_id": north_pitch.get("id") if isinstance(north_pitch, dict) else None,
                "north_pitch_number": (
                    north_pitch.get("pitch_number") if isinstance(north_pitch, dict) else None
                ),
                "south_pitch_id": south_pitch.get("id") if isinstance(south_pitch, dict) else None,
                "south_pitch_number": (
                    south_pitch.get("pitch_number") if isinstance(south_pitch, dict) else None
                ),
            }
        )
    return annotated_pitches, pair_summaries



_HTML = """
<div class="board">
  <div class="board-header" id="board-header">
    <div class="board-actions" id="board-actions">
      <div class="board-toolbar-title" id="board-toolbar-title">
        <strong>Interactive Yamazumi</strong>
        <span id="board-toolbar-summary"></span>
      </div>
      <div class="board-toolbar-controls">
        <button id="add-pitch" type="button">＋ Add Pitch</button>
        <div class="scale-mode-toggle" id="scale-mode-toggle" role="group" aria-label="Board display scale">
          <button id="scale-to-scale" type="button" class="scale-mode-btn active" data-scale-mode="to_scale" aria-pressed="true" title="Scale work elements proportionally to cycle time">To Scale</button>
          <button id="scale-readable" type="button" class="scale-mode-btn" data-scale-mode="readable" aria-pressed="false" title="Expand work elements so text is readable">Readable</button>
        </div>
        <button id="print-board" type="button" title="Print the Yamazumi board">🖨️ Print</button>
        <div class="fullscreen-zoom-controls" id="fullscreen-zoom-controls">
          <button id="zoom-out" type="button" title="Zoom out">−</button>
          <button id="zoom-in" type="button" title="Zoom in">+</button>
          <button id="fit-view" type="button" title="Fit the entire Yamazumi board">Fit</button>
          <button id="zoom-reset" type="button" title="Reset zoom to 100%">100%</button>
        </div>
        <button id="full-screen" type="button" title="Open the Yamazumi board full screen" aria-pressed="false">Full Screen</button>
      </div>
    </div>
    <div class="scale-notice" id="scale-notice" hidden>Readable mode: Work elements are expanded for readability and are not scaled to cycle time (red takt time line hidden).</div>
    <div class="legend" id="legend"></div>
  </div>
  <div class="board-viewport" id="board-viewport">
    <div class="board-zoom-stage" id="board-zoom-stage">
      <div class="board-content" id="board-content">
      <div class="unassigned-lane" id="unassigned"></div>
      <div class="lane-label">North Side · Odd Pitches</div>
      <div class="lane north" id="north"></div>
      <div class="line"><span>Assembly Flow →</span></div>
      <div class="lane south" id="south"></div>
      <div class="lane-label">South Side · Even Pitches</div>
      </div>
    </div>
  </div>
  <div class="print-dialog-backdrop" id="print-dialog-backdrop" hidden>
    <div class="print-dialog" role="dialog" aria-modal="true" aria-labelledby="print-dialog-title">
      <div class="print-dialog-header">
        <strong id="print-dialog-title">Print Interactive Yamazumi</strong>
        <button type="button" class="print-dialog-close" id="print-dialog-close" title="Close">✕</button>
      </div>
      <div class="print-dialog-body">
        <p class="print-dialog-prompt">Would you like to print all pitches or only pitches that contain work elements?</p>
        <label class="print-dialog-option selected" id="print-opt-all-label">
          <input type="radio" name="yamazumi-print-scope" id="print-opt-all" value="all" checked>
          <div class="print-dialog-option-text">
            <strong>Print all pitches</strong>
            <span id="print-opt-all-desc">Include all pitches on the board, including empty pitches.</span>
          </div>
        </label>
        <label class="print-dialog-option" id="print-opt-elements-label">
          <input type="radio" name="yamazumi-print-scope" id="print-opt-elements" value="with_elements">
          <div class="print-dialog-option-text">
            <strong>Print pitches that contain work elements</strong>
            <span id="print-opt-elements-desc">Only print pitches that contain work elements; empty pitches will not be included.</span>
          </div>
        </label>
      </div>
      <div class="print-dialog-footer">
        <button type="button" class="print-dialog-btn secondary" id="print-dialog-cancel">Cancel</button>
        <button type="button" class="print-dialog-btn primary" id="print-dialog-confirm">🖨️ Print</button>
      </div>
    </div>
  </div>
</div>
"""

_CSS = """
:host { display:block; width:100%; max-width:100%; color: var(--st-text-color); font-family: var(--st-font); }
.board { position:relative; box-sizing:border-box; width:100%; max-width:100%; min-width:0; padding:4px 2px 16px; overflow:visible; background:var(--st-background-color); }
.board.fullscreen-board { position:fixed; inset:0; z-index:999995; width:100vw; height:100vh; max-width:100vw; min-width:0; display:flex; flex-direction:column; padding:0; overflow:hidden; background:var(--st-background-color); }
.board-header { position:sticky; left:0; z-index:30; box-sizing:border-box; width:100%; max-width:100%; flex:0 0 auto; background:var(--st-background-color); }
.board.fullscreen-board .board-header { position:sticky; top:0; left:0; z-index:999996; padding:0; border-bottom:1px solid var(--st-border-color); background:var(--st-background-color); box-shadow:0 2px 8px rgba(0,0,0,.08); }
.board-viewport { position:relative; box-sizing:border-box; width:100%; max-width:100%; min-width:0; overflow-x:auto; overflow-y:visible; }
.board.fullscreen-board .board-viewport { flex:1 1 auto; min-height:0; padding:12px; overflow:scroll; overscroll-behavior:contain; scrollbar-gutter:stable both-edges; scrollbar-color:var(--st-secondary-text-color) var(--st-secondary-background-color); }
.board.fullscreen-board.is-panning .board-viewport { cursor:grabbing; user-select:none; }
.board.fullscreen-board .board-viewport::-webkit-scrollbar { width:14px; height:14px; }
.board.fullscreen-board .board-viewport::-webkit-scrollbar-track { background:var(--st-secondary-background-color); }
.board.fullscreen-board .board-viewport::-webkit-scrollbar-thumb { border:3px solid var(--st-secondary-background-color); border-radius:10px; background:var(--st-secondary-text-color); }
.board-zoom-stage { position:relative; box-sizing:border-box; width:max-content; min-width:100%; }
.board-content { box-sizing:border-box; width:max-content; min-width:100%; transform-origin:0 0; }
.board-actions { display:flex; align-items:center; gap:8px; margin:2px 0 10px; flex-wrap:wrap; }
.board.fullscreen-board .board-actions { width:100%; box-sizing:border-box; margin:0; padding:10px 16px; border-bottom:1px solid var(--st-border-color); border-radius:0; background:var(--st-secondary-background-color); justify-content:space-between; gap:12px; flex-wrap:wrap; }
.board-toolbar-title { display:none; align-items:baseline; gap:10px; min-width:0; }
.board.fullscreen-board .board-toolbar-title { display:flex; }
.board-toolbar-title strong { font-size:.95rem; color:var(--st-text-color); }
.board-toolbar-title span { color:var(--st-secondary-text-color); font-size:.82rem; white-space:nowrap; }
.board-toolbar-controls { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.scale-mode-toggle { display:none; align-items:center; gap:2px; padding:2px; border:1px solid var(--st-border-color); border-radius:7px; background:var(--st-background-color); }
.board.fullscreen-board .scale-mode-toggle { display:inline-flex; }
.scale-mode-toggle button.scale-mode-btn { border:none; border-radius:5px; padding:4px 10px; font-size:.8rem; font-weight:650; color:var(--st-secondary-text-color); background:transparent; cursor:pointer; }
.scale-mode-toggle button.scale-mode-btn:hover { color:var(--st-primary-color); }
.scale-mode-toggle button.scale-mode-btn.active { background:var(--st-primary-color); color:#fff; }
#print-board { display:none; }
.board.fullscreen-board #print-board { display:inline-flex; align-items:center; gap:4px; }
.fullscreen-zoom-controls { display:none; align-items:center; gap:6px; margin-left:2px; }
.board.fullscreen-board .fullscreen-zoom-controls { display:inline-flex; }
.fullscreen-zoom-controls button { min-width:34px; text-align:center; }
.board-actions button:not(.scale-mode-btn), .add-element, .edit-pitch, .edit-element { border:1px solid var(--st-primary-color); border-radius:6px; padding:5px 9px; color:var(--st-primary-color); background:var(--st-background-color); cursor:pointer; font-weight:650; }
.board.fullscreen-board .board-actions button:not(.scale-mode-btn) { min-height:32px; padding:4px 10px; border-color:var(--st-border-color); color:var(--st-text-color); font-size:.84rem; }
.board.fullscreen-board .board-actions button#add-pitch { background:var(--st-primary-color); border-color:var(--st-primary-color); color:#fff; }
.board.fullscreen-board .board-actions button:not(.scale-mode-btn):hover { border-color:var(--st-primary-color); color:var(--st-primary-color); }
.board.fullscreen-board .board-actions button#add-pitch:hover { opacity:.92; color:#fff; }
.board-actions button:disabled { cursor:not-allowed; opacity:.55; }
.scale-notice { display:none; margin:0 2px 8px; padding:6px 10px; border:1px solid var(--st-primary-color); border-radius:6px; background:color-mix(in srgb, var(--st-primary-color) 10%, var(--st-background-color)); font-size:.8rem; font-weight:600; }
.board.fullscreen-board.readable-mode .scale-notice { display:block; margin:8px 16px; }
@media print {
  .board.fullscreen-board { position:static !important; width:max-content !important; height:auto !important; padding:0 !important; overflow:visible !important; }
  .board-actions, .pitch-actions, .edit-element, .takt-line, .status, .print-dialog-backdrop { display:none !important; }
  .board-viewport, .board-zoom-stage, .board-content { transform:none !important; width:max-content !important; height:auto !important; overflow:visible !important; }
  .pitch, .pitch-placeholder, .lane { break-inside:avoid !important; page-break-inside:avoid !important; }
  .element { height:auto !important; flex:0 0 auto !important; min-height:32px !important; padding:5px 8px 6px 8px !important; overflow:visible !important; }
  .element.has-criticality { min-height:44px !important; padding-bottom:22px !important; }
  .element strong { top:5px !important; right:6px !important; }
  .element-description { height:auto !important; overflow:visible !important; padding-right:48px !important; line-height:1.25 !important; }
}
.lane { position:relative; display:flex; gap:10px; min-height:230px; padding:8px 2px; }
.lane.north { align-items:flex-end; }
.lane.south { align-items:flex-start; }
.takt-line { position:absolute; left:2px; z-index:10; height:0; border-top:2px solid #d32f2f; pointer-events:none; }
.lane-label { position:sticky; left:2px; z-index:15; width:max-content; margin:8px 2px 0; padding-right:8px; font-weight:700; color:var(--st-secondary-text-color); background:var(--st-background-color); }
.line { border-top:4px solid #c62828; margin:0; text-align:center; color:#c62828; font-weight:700; }
.line span { position:relative; top:-13px; padding:0 10px; background:var(--st-background-color); }
.pitch { position:relative; z-index:1; box-sizing:border-box; flex:0 0 240px; min-width:240px; display:flex; flex-direction:column; border:1px solid var(--st-border-color); border-radius:9px; background:var(--st-background-color); padding:9px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
.pitch-placeholder { box-sizing:border-box; flex:0 0 240px; min-width:240px; visibility:hidden; pointer-events:none; }
.pitch.north .variants { order:1; align-items:flex-end; }
.pitch.north .pitch-info { order:2; margin-top:6px; }
.pitch.south .pitch-info { order:1; margin-bottom:6px; }
.pitch.south .variants { order:2; }
.pitch.north .variant { display:flex; flex-direction:column-reverse; }
.pitch.north .variant-title { align-items:flex-start; box-sizing:border-box; margin:4px 0 0; }
.pitch.north .stack { flex-direction:column; justify-content:flex-end; }
.pitch.south .stack { justify-content:flex-start; }
.pitch.blocked { background:repeating-linear-gradient(135deg, #eceff1, #eceff1 8px, #cfd8dc 8px, #cfd8dc 16px); }
.pitch.open { background:#d7eef5; }
.pitch.blocked, .pitch.open { opacity:.78; }
.pitch.blocked .stack, .pitch.open .stack { cursor:not-allowed; }
.pitch.dragover { outline:3px solid var(--st-primary-color); }
.pitch-header { display:flex; justify-content:space-between; gap:8px; margin-bottom:5px; }
.pitch-info { box-sizing:border-box; }
.address { font-weight:800; color:var(--st-primary-color); }
.status { font-size:.75rem; text-transform:uppercase; color:var(--st-secondary-text-color); }
.name { min-height:28px; font-weight:650; }
.pitch-actions { display:flex; gap:6px; margin-top:5px; }
.pitch-actions button { flex:1; font-size:.76rem; padding:4px 6px; }
.variants { display:flex; align-items:stretch; gap:6px; overflow:visible; }
.variant { flex:1 0 155px; display:flex; flex-direction:column; border-top:2px solid var(--st-border-color); margin-top:8px; padding-top:6px; overflow:visible; }
.variant-title { display:flex; justify-content:space-between; gap:5px; font-size:.78rem; font-weight:750; margin-bottom:4px; }
.stack { min-height:120px; flex:1 1 auto; border:1px solid var(--st-border-color); display:flex; flex-direction:column; background:color-mix(in srgb, var(--st-secondary-background-color) 45%, transparent); overflow:visible; }
.stack.takt-scale { min-height:155px; }
.drop-slot { flex:0 0 8px; min-height:8px; margin:-4px 0; position:relative; z-index:3; }
.drop-slot.dragover { min-height:14px; flex-basis:14px; margin:-7px 0; background:color-mix(in srgb, var(--st-primary-color) 28%, transparent); outline:2px dashed var(--st-primary-color); }
.element { position:relative; box-sizing:border-box; height:var(--element-height, 34px); flex:0 0 var(--element-height, 34px); min-height:0; padding:5px 38px 5px 6px; border-top:1px solid rgba(0,0,0,.14); font-size:.72rem; cursor:grab; overflow:hidden; transition:min-height .12s ease, box-shadow .12s ease; }
.board:not(.is-dragging) .element:hover, .board:not(.is-dragging) .element:focus-within { height:auto; flex:0 0 auto; min-height:max(var(--element-height, 34px), 38px); overflow:visible; z-index:5; box-shadow:0 2px 6px rgba(0,0,0,.18); }
.board:not(.is-dragging) .element.has-criticality:hover, .board:not(.is-dragging) .element.has-criticality:focus-within { min-height:max(var(--element-height, 34px), 52px); padding-bottom:22px; }
.element strong { position:absolute; top:4px; right:38px; margin-left:5px; white-space:nowrap; }
.element-description { display:block; height:100%; padding-right:38px; overflow:hidden; line-height:1.2; overflow-wrap:anywhere; }
.board:not(.is-dragging) .element:hover .element-description, .board:not(.is-dragging) .element:focus-within .element-description { height:auto; overflow:visible; }
.board.readable-mode .element { height:auto; flex:0 0 auto; min-height:42px; padding:6px 8px 24px 8px; overflow:visible; }
.board.readable-mode .element.has-criticality { min-height:52px; padding-bottom:26px; }
.board.readable-mode .element strong { top:6px; right:6px; }
.board.readable-mode .element-description { height:auto; overflow:visible; padding-right:48px; line-height:1.3; }
.edit-element { position:absolute; right:3px; bottom:3px; padding:1px 4px; border-color:rgba(0,0,0,.35); color:#111; font-size:.68rem; line-height:1.2; }
.criticality { position:absolute; left:3px; bottom:3px; z-index:2; display:flex; gap:3px; max-width:calc(100% - 43px); pointer-events:none; }
.criticality-tag { box-sizing:border-box; padding:1px 4px; border:1px solid currentColor; border-radius:3px; background:#fff; font-weight:900; line-height:1.2; white-space:nowrap; }
.criticality-tag.ctq { color:#8a4b00; background:#fff4d6; }
.criticality-tag.safety { color:#8b0000; background:#ffe8e8; }
.legend { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:4px; font-size:.8rem; }
.board.fullscreen-board .legend { padding:8px 18px 8px 18px; margin-bottom:0; background:var(--st-background-color); }
.swatch { width:12px; height:12px; display:inline-block; border-radius:2px; margin-right:4px; }
.unassigned-lane { display:flex; margin:8px 2px 12px; }
.pitch.unassigned { flex-basis:240px; border-style:dashed; }
.board.print-dialog-open { z-index:1000020; }
.print-dialog-backdrop { position:fixed; inset:0; z-index:1000025; display:flex; align-items:center; justify-content:center; padding:16px; background:rgba(15, 23, 42, 0.48); backdrop-filter:blur(2px); }
.print-dialog-backdrop[hidden] { display:none !important; }
.print-dialog { width:100%; max-width:460px; border:1px solid var(--st-border-color); border-radius:12px; background:var(--st-background-color); color:var(--st-text-color); box-shadow:0 16px 40px rgba(0,0,0,.24); overflow:hidden; }
.print-dialog-header { display:flex; align-items:center; justify-content:space-between; padding:14px 18px; border-bottom:1px solid var(--st-border-color); background:var(--st-secondary-background-color); }
.print-dialog-header strong { font-size:1rem; font-weight:700; }
.print-dialog-close { border:none; background:transparent; color:var(--st-secondary-text-color); font-size:1rem; line-height:1; padding:4px 8px; border-radius:6px; cursor:pointer; }
.print-dialog-close:hover { background:color-mix(in srgb, var(--st-text-color) 10%, transparent); color:var(--st-text-color); }
.print-dialog-body { padding:16px 18px; display:flex; flex-direction:column; gap:10px; }
.print-dialog-prompt { margin:0 0 4px; font-size:.9rem; color:var(--st-text-color); font-weight:600; }
.print-dialog-option { display:flex; align-items:flex-start; gap:10px; padding:11px 13px; border:1.5px solid var(--st-border-color); border-radius:9px; background:var(--st-background-color); cursor:pointer; transition:border-color .12s ease, background .12s ease; }
.print-dialog-option:hover { border-color:var(--st-primary-color); }
.print-dialog-option.selected { border-color:var(--st-primary-color); background:color-mix(in srgb, var(--st-primary-color) 8%, var(--st-background-color)); }
.print-dialog-option input[type="radio"] { margin:3px 0 0; accent-color:var(--st-primary-color); cursor:pointer; }
.print-dialog-option-text { display:flex; flex-direction:column; gap:3px; min-width:0; }
.print-dialog-option-text strong { font-size:.9rem; font-weight:700; color:var(--st-text-color); }
.print-dialog-option-text span { font-size:.8rem; color:var(--st-secondary-text-color); line-height:1.35; }
.print-dialog-footer { display:flex; align-items:center; justify-content:flex-end; gap:8px; padding:12px 18px; border-top:1px solid var(--st-border-color); background:var(--st-secondary-background-color); }
.print-dialog-btn { border-radius:7px; padding:7px 14px; font-size:.86rem; font-weight:650; cursor:pointer; border:1px solid var(--st-border-color); background:var(--st-background-color); color:var(--st-text-color); }
.print-dialog-btn.secondary:hover { border-color:var(--st-text-color); }
.print-dialog-btn.primary { border-color:var(--st-primary-color); background:var(--st-primary-color); color:#ffffff; }
.print-dialog-btn.primary:hover { opacity:.92; }
"""

_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component
  const escapeHtml = value => String(value ?? '').replace(
    /[&<>"']/g,
    character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[character]
  )
  const north = parentElement.querySelector('#north')
  const south = parentElement.querySelector('#south')
  const unassigned = parentElement.querySelector('#unassigned')
  const legend = parentElement.querySelector('#legend')
  const scaleNotice = parentElement.querySelector('#scale-notice')
  const actionsBar = parentElement.querySelector('#board-actions') || parentElement.querySelector('.board-actions')
  const toolbarTitle = parentElement.querySelector('#board-toolbar-title')
  const toolbarSummary = parentElement.querySelector('#board-toolbar-summary')
  const addPitch = parentElement.querySelector('#add-pitch')
  const scaleModeToggle = parentElement.querySelector('#scale-mode-toggle')
  const scaleToScaleBtn = parentElement.querySelector('#scale-to-scale')
  const scaleReadableBtn = parentElement.querySelector('#scale-readable')
  const printBtn = parentElement.querySelector('#print-board')
  const fullScreen = parentElement.querySelector('#full-screen')
  const zoomControls = parentElement.querySelector('#fullscreen-zoom-controls')
  const zoomInBtn = parentElement.querySelector('#zoom-in')
  const zoomOutBtn = parentElement.querySelector('#zoom-out')
  const fitViewBtn = parentElement.querySelector('#fit-view')
  const zoomResetBtn = parentElement.querySelector('#zoom-reset')
  const boardViewport = parentElement.querySelector('#board-viewport') || parentElement.querySelector('.board-viewport')
  const zoomStage = parentElement.querySelector('#board-zoom-stage')
  const boardContent = parentElement.querySelector('#board-content') || parentElement.querySelector('.board-content')
  const board = parentElement.querySelector('.board')
  const scrollContainer = boardViewport || board
  if (!north || !south || !unassigned || !legend || !addPitch || !fullScreen || !board || !scrollContainer) return
  const fullScreenTarget = document.documentElement
  const isBoardFullScreen = () => (
    document.fullscreenElement === fullScreenTarget ||
    document.webkitFullscreenElement === fullScreenTarget
  )
  const MIN_ZOOM = 0.2
  const MAX_ZOOM = 3.0
  const clampZoom = value => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(value) || 1))
  let zoomScale = isBoardFullScreen() && Number.isFinite(Number(window.__paagYamazumiFullscreenZoom))
    ? clampZoom(window.__paagYamazumiFullscreenZoom)
    : 1
  const getActiveZoomScale = () => (isBoardFullScreen() ? clampZoom(zoomScale) : 1)
  let isReadableMode = String(data.scale_mode || 'to_scale') === 'readable'
  const syncScaleModeControls = () => {
    board.classList.toggle('readable-mode', isReadableMode)
    if (scaleNotice) scaleNotice.hidden = !isReadableMode
    if (scaleToScaleBtn) {
      scaleToScaleBtn.classList.toggle('active', !isReadableMode)
      scaleToScaleBtn.setAttribute('aria-pressed', String(!isReadableMode))
    }
    if (scaleReadableBtn) {
      scaleReadableBtn.classList.toggle('active', isReadableMode)
      scaleReadableBtn.setAttribute('aria-pressed', String(isReadableMode))
    }
  }
  syncScaleModeControls()
  addPitch.onclick = () => setTriggerValue('add_pitch', { requested: true })
  legend.innerHTML = `<span><i class="swatch" style="background:#35c84a"></i>Cycle</span>`
    + `<span><i class="swatch" style="background:#ffd54f"></i>Periodic</span>`
    + `<span><i class="swatch" style="background:#ef5350"></i>Fluctuation</span>`
  north.innerHTML = ''; south.innerHTML = ''; unassigned.innerHTML = ''
  const grouped = {}
  const secondsPerUnit = Math.max(Number(data.seconds_per_unit || 1), Number.EPSILON)
  const timeDecimals = Math.max(0, Number(data.time_decimals || 0))
  const timeSuffix = String(data.time_suffix || 's')
  const taktSecondsPerUnit = Math.max(Number(data.takt_seconds_per_unit || 1), Number.EPSILON)
  const taktDecimals = Math.max(0, Number(data.takt_decimals || 0))
  const taktSuffix = String(data.takt_suffix || 's')
  const taktPixels = 155
  const hasTakt = Number.isFinite(Number(data.takt)) && Number(data.takt) > 0
  const displayTime = value => Number(value || 0) / secondsPerUnit
  const formatTime = value => `${displayTime(value).toFixed(timeDecimals)} ${timeSuffix}`
  const formatTakt = value => `${(Number(value || 0) / taktSecondsPerUnit).toFixed(taktDecimals)} ${taktSuffix}`
  if (toolbarSummary) {
    const pitchCount = (data.pitches || []).length
    const elementCount = (data.elements || []).length
    const taktSummary = hasTakt ? `Takt: ${formatTakt(data.takt)}` : 'Takt: Not set'
    toolbarSummary.textContent = `${pitchCount} pitch${pitchCount === 1 ? '' : 'es'} · ${elementCount} work element${elementCount === 1 ? '' : 's'} · ${taktSummary}`
  }
  for (const element of (data.elements || [])) {
    const pitch = element.pitch_id || '__unassigned__'
    grouped[pitch] ||= {}
    let elementVariants = element.model_variants
    if (typeof elementVariants === 'string') {
      try { elementVariants = JSON.parse(elementVariants) } catch { elementVariants = [elementVariants] }
    }
    if (!Array.isArray(elementVariants) || !elementVariants.length) {
      elementVariants = [element.model_variant || 'All models']
    }
    for (const variant of [...new Set(elementVariants)]) {
      grouped[pitch][variant] ||= []
      grouped[pitch][variant].push(element)
    }
  }
  const makePitch = (pitch, side = 'neutral') => {
    const card = document.createElement('div')
    card.className = `pitch ${side} ${(pitch.status || '').toLowerCase()}`
    card.dataset.pitch = pitch.id || ''
    const pitchVariants = pitch.id
      ? [...new Set([...(pitch.model_variants || ['All models']), ...Object.keys(grouped[pitch.id] || {})])]
      : [...new Set(Object.keys(grouped.__unassigned__ || {}).concat(['All models']))]
    card.style.flexBasis = `${Math.max(240, pitchVariants.length * 165 + 18)}px`
    const pitchMeta = [pitch.pitch_type, pitch.status].filter(Boolean).join(' · ')
    card.innerHTML = `<div class="pitch-info"><div class="pitch-header"><span class="address">${pitch.pitch_number || 'Unassigned'}</span><span class="status">${pitchMeta}</span></div><div class="name">${pitch.pitch_name || ''}</div><div class="pitch-actions"></div></div><div class="variants"></div>`
    const variantWrap = card.querySelector('.variants')
    const pitchActions = card.querySelector('.pitch-actions')
    for (const variant of pitchVariants) {
      const items = [...((grouped[pitch.id || '__unassigned__'] || {})[variant] || [])]
      items.sort((a, b) => {
        const sequenceDifference = Number(a.sequence || 0) - Number(b.sequence || 0)
        if (sequenceDifference !== 0) return sequenceDifference
        return String(a.description || '').localeCompare(String(b.description || ''))
      })
      const total = items.reduce((sum,item) => sum + Number(item.time_s || 0), 0)
      const displayItems = side === 'north' ? [...items].reverse() : items
      const block = document.createElement('div')
      block.className = 'variant'
      block.innerHTML = `<div class="variant-title"><span>${variant}</span><span>${formatTime(total)} / ${formatTakt(data.takt)}</span></div><div class="stack"></div>`
      const stack = block.querySelector('.stack')
      if (pitch.id) stack.dataset.assignedPitch = 'true'
      if (pitch.id && hasTakt && !isReadableMode) stack.classList.add('takt-scale')
      const appendDropSlot = logicalIndex => {
        const slot = document.createElement('div')
        slot.className = 'drop-slot'
        slot.dataset.insertIndex = String(logicalIndex)
        slot.ondragover = event => {
          event.preventDefault(); event.stopPropagation(); slot.classList.add('dragover')
        }
        slot.ondragleave = () => slot.classList.remove('dragover')
        slot.ondrop = event => {
          event.preventDefault(); event.stopPropagation(); slot.classList.remove('dragover')
          board.classList.remove('is-dragging')
          setTriggerValue('move', {
            element_id: event.dataTransfer.getData('text/plain'),
            pitch_id: pitch.id || null,
            insert_index: logicalIndex,
            before_element_id: items[logicalIndex]?.id || null,
            after_element_id: logicalIndex > 0 ? items[logicalIndex - 1]?.id || null : null,
          })
        }
        stack.appendChild(slot)
      }
      if (side !== 'north') appendDropSlot(0)
      for (const item of displayItems) {
        const logicalIndex = items.findIndex(candidate => candidate.id === item.id)
        if (side === 'north') appendDropSlot(logicalIndex + 1)
        const el = document.createElement('div')
        const color = item.work_type === 'Periodic'
          ? '#ffd54f'
          : item.work_type === 'Fluctuation'
            ? '#ef5350'
            : '#35c84a'
        const displayTakt = Math.max(displayTime(data.takt), Number.EPSILON)
        el.className = 'element'
        el.draggable = true
        el.dataset.id = item.id
        el.style.background = color
        const scaledHeightPx = hasTakt && pitch.id
          ? Math.max(0, displayTime(item.time_s) / displayTakt * taktPixels)
          : 34
        el.dataset.scaledHeightPx = String(scaledHeightPx)
        const elementHeight = !isReadableMode && hasTakt && pitch.id
          ? scaledHeightPx
          : 34
        el.style.setProperty('--element-height', `${elementHeight}px`)
        const criticality = (item.criticality || []).map(tag => {
          const normalized = String(tag).toLowerCase()
          const source = tag === 'CTQ'
            ? 'Derived from PFMEA Classification'
            : 'Derived from an active Safety requirement'
          return `<span class="criticality-tag ${normalized}" title="${source}">${escapeHtml(tag)}</span>`
        }).join('')
        if (criticality) el.classList.add('has-criticality')
        el.innerHTML = `<strong>${formatTime(item.time_s)}</strong><span class="element-description">${item.description}</span>${criticality ? `<span class="criticality">${criticality}</span>` : ''}<button type="button" class="edit-element" title="Edit work element">Edit</button>`
        el.title = `${item.description} · ${formatTime(item.time_s)} · ${item.work_region || 'None'}`
        el.ondragstart = event => {
          board.classList.add('is-dragging')
          event.dataTransfer.setData('text/plain', item.id)
        }
        el.ondragend = () => board.classList.remove('is-dragging')
        el.querySelector('.edit-element').onclick = event => {
          event.preventDefault(); event.stopPropagation()
          setTriggerValue('edit_element', { element_id: item.id, model_variant: variant })
        }
        stack.appendChild(el)
        if (side !== 'north') appendDropSlot(logicalIndex + 1)
      }
      if (side === 'north') appendDropSlot(0)
      variantWrap.appendChild(block)
    }
    const acceptsWork = !pitch.id || pitch.status === 'Active'
    if (pitch.id) {
      const editButton = document.createElement('button')
      editButton.type = 'button'
      editButton.className = 'edit-pitch'
      editButton.textContent = 'Edit Pitch'
      editButton.onclick = event => {
        event.preventDefault(); event.stopPropagation()
        setTriggerValue('edit_pitch', { pitch_id: pitch.id })
      }
      pitchActions.appendChild(editButton)
    }
    if (acceptsWork) {
      const addButton = document.createElement('button')
      addButton.type = 'button'
      addButton.className = 'add-element'
      addButton.textContent = '＋ Add Element'
      addButton.onclick = () => setTriggerValue('add_element', { pitch_id: pitch.id || null, pitch_number: pitch.pitch_number || 'Unassigned' })
      pitchActions.appendChild(addButton)
      card.ondragover = event => { event.preventDefault(); card.classList.add('dragover') }
      card.ondragleave = () => card.classList.remove('dragover')
      card.ondrop = event => {
        event.preventDefault(); card.classList.remove('dragover')
        board.classList.remove('is-dragging')
        setTriggerValue('move', {
          element_id: event.dataTransfer.getData('text/plain'),
          pitch_id: pitch.id || null,
          before_element_id: null,
          after_element_id: null,
        })
      }
    } else {
      card.title = `${pitch.status} pitches must be changed to Active before work can be assigned.`
    }
    return card
  }
  const makePitchPlaceholder = side => {
    const placeholder = document.createElement('div')
    placeholder.className = `pitch-placeholder ${side}`
    placeholder.setAttribute('aria-hidden', 'true')
    return placeholder
  }
  const numberFrom = value => { const found = String(value || '').match(/(\d+)(?!.*\d)/); return found ? Number(found[1]) : 0 }
  const pairKeyFrom = pitch => {
    if (pitch && pitch.pair_key) return String(pitch.pair_key)
    const match = String(pitch.pitch_number || '').trim().match(/^(.*?)(\d+)([^\d]*)$/)
    if (!match) return null
    const number = Number(match[2] || 0)
    if (number <= 0) return null
    const oddNumber = number % 2 ? number : number - 1
    const prefix = String(match[1] || '').trim().toLowerCase()
    const suffix = String(match[3] || '').trim().toLowerCase()
    return `${prefix}::${oddNumber}::${suffix}`
  }
  const applyPairWidth = (pair, widthValue) => {
    const widthPx = `${Math.max(240, Math.ceil(Number(widthValue) || 240))}px`
    for (const node of [pair.northNode, pair.southNode]) {
      node.style.flex = `0 0 ${widthPx}`
      node.style.flexBasis = widthPx
      node.style.width = widthPx
      node.style.minWidth = widthPx
      node.style.maxWidth = widthPx
    }
  }
  if (data.show_unassigned && Object.keys(grouped.__unassigned__ || {}).length) {
    unassigned.appendChild(makePitch({
      id: null,
      pitch_number: 'Unassigned',
      pitch_name: 'Drop Work Here',
      status: 'Active',
      model_variants: ['All models'],
    }, 'unassigned'))
  }
  const pitchPairs = []
  const pairsByKey = new Map()
  for (const pitch of (data.pitches || [])) {
    const side = pitch.pair_side === 'north' || pitch.pair_side === 'south'
      ? pitch.pair_side
      : (numberFrom(pitch.pitch_number) % 2 ? 'north' : 'south')
    const pairKey = pairKeyFrom(pitch)
    let pair = pairKey ? pairsByKey.get(pairKey) : null
    if (!pair || pair[side]) {
      pair = { north: null, south: null }
      pitchPairs.push(pair)
      if (pairKey && !pairsByKey.has(pairKey)) pairsByKey.set(pairKey, pair)
    }
    pair[side] = pitch
  }
  const pairedNodes = pitchPairs.map((pair, pairIndex) => {
    const northNode = pair.north ? makePitch(pair.north, 'north') : makePitchPlaceholder('north')
    const southNode = pair.south ? makePitch(pair.south, 'south') : makePitchPlaceholder('south')
    northNode.dataset.pairIndex = String(pairIndex)
    southNode.dataset.pairIndex = String(pairIndex)
    const northBasis = Number.parseFloat(northNode.style.flexBasis) || 240
    const southBasis = Number.parseFloat(southNode.style.flexBasis) || 240
    const baseWidth = Math.max(
      northBasis,
      southBasis,
      Number(pair.north?.pair_width_px) || 0,
      Number(pair.south?.pair_width_px) || 0,
    )
    const pairEntry = { northNode, southNode, baseWidth }
    applyPairWidth(pairEntry, baseWidth)
    north.appendChild(northNode)
    south.appendChild(southNode)
    return pairEntry
  })
  const alignPairedPitches = () => {
    const activeScale = getActiveZoomScale()
    for (const pair of pairedNodes) {
      applyPairWidth(pair, pair.baseWidth)
      pair.northNode.style.maxWidth = ''
      pair.southNode.style.maxWidth = ''
    }
    const syncedWidths = pairedNodes.map(pair => Math.max(
      pair.baseWidth,
      Math.ceil(pair.northNode.getBoundingClientRect().width / activeScale),
      Math.ceil(pair.southNode.getBoundingClientRect().width / activeScale),
    ))
    pairedNodes.forEach((pair, index) => {
      applyPairWidth(pair, syncedWidths[index])
    })
  }
  const alignLaneBaselines = lane => {
    const pitchInfos = [...lane.querySelectorAll('.pitch-info')]
    const titles = [...lane.querySelectorAll('.variant-title')]
    for (const element of [...pitchInfos, ...titles]) element.style.minHeight = ''
    const infoBandHeight = Math.max(0, ...pitchInfos.map(element => element.scrollHeight))
    const titleBandHeight = Math.max(0, ...titles.map(element => element.scrollHeight))
    for (const element of pitchInfos) element.style.minHeight = `${infoBandHeight}px`
    for (const element of titles) element.style.minHeight = `${titleBandHeight}px`
  }
  const equalizePitchFrames = () => {
    const allPitches = [
      ...north.querySelectorAll('.pitch'),
      ...south.querySelectorAll('.pitch'),
      ...unassigned.querySelectorAll('.pitch'),
    ]
    const allPlaceholders = [
      ...north.querySelectorAll('.pitch-placeholder'),
      ...south.querySelectorAll('.pitch-placeholder'),
    ]
    const allPitchInfos = [
      ...north.querySelectorAll('.pitch-info'),
      ...south.querySelectorAll('.pitch-info'),
      ...unassigned.querySelectorAll('.pitch-info'),
    ]
    const allTitles = [
      ...north.querySelectorAll('.variant-title'),
      ...south.querySelectorAll('.variant-title'),
      ...unassigned.querySelectorAll('.variant-title'),
    ]
    const allStacks = [
      ...north.querySelectorAll('.stack'),
      ...south.querySelectorAll('.stack'),
      ...unassigned.querySelectorAll('.stack'),
    ]
    for (const element of [
      ...allPitchInfos,
      ...allTitles,
      ...allStacks,
      ...allPitches,
      ...allPlaceholders,
    ]) {
      element.style.minHeight = ''
    }
    alignLaneBaselines(north)
    alignLaneBaselines(south)
    const infoBandHeight = Math.max(0, ...allPitchInfos.map(element => element.scrollHeight))
    const titleBandHeight = Math.max(0, ...allTitles.map(element => element.scrollHeight))
    for (const element of allPitchInfos) element.style.minHeight = `${infoBandHeight}px`
    for (const element of allTitles) element.style.minHeight = `${titleBandHeight}px`
    const defaultStackMinHeight = (!isReadableMode && hasTakt) ? taktPixels : 120
    const maxStackHeight = Math.max(
      defaultStackMinHeight,
      ...allStacks.map(element => Math.max(element.scrollHeight, element.offsetHeight)),
    )
    for (const element of allStacks) element.style.minHeight = `${maxStackHeight}px`
    const maxPitchHeight = Math.max(
      0,
      ...allPitches.map(element => Math.max(element.scrollHeight, element.offsetHeight)),
    )
    for (const element of [...allPitches, ...allPlaceholders]) {
      element.style.minHeight = `${maxPitchHeight}px`
    }
  }
  const drawTaktLine = (lane, side) => {
    lane.querySelectorAll('.takt-line').forEach(line => line.remove())
    if (!hasTakt || isReadableMode) return
    const stack = lane.querySelector('.stack.takt-scale')
    if (!stack) return
    const activeScale = getActiveZoomScale()
    const laneRect = lane.getBoundingClientRect()
    const stackRect = stack.getBoundingClientRect()
    const line = document.createElement('div')
    line.className = 'takt-line'
    line.setAttribute('aria-hidden', 'true')
    line.style.top = `${side === 'north'
      ? (stackRect.bottom - laneRect.top) / activeScale - taktPixels
      : (stackRect.top - laneRect.top) / activeScale + taktPixels}px`
    line.style.width = `${Math.max(0, lane.scrollWidth - 4)}px`
    lane.appendChild(line)
  }
  const applyZoomTransform = () => {
    const activeScale = getActiveZoomScale()
    if (zoomResetBtn) {
      zoomResetBtn.textContent = `${Math.round(activeScale * 100)}%`
    }
    if (!boardContent || !zoomStage) return
    if (!isBoardFullScreen() || Math.abs(activeScale - 1) < 0.001) {
      boardContent.style.minWidth = ''
      boardContent.style.transform = ''
      zoomStage.style.width = ''
      zoomStage.style.height = ''
      return
    }
    const viewportInnerWidth = Math.max(0, scrollContainer.clientWidth - 24)
    boardContent.style.minWidth = `${viewportInnerWidth}px`
    boardContent.style.transform = `scale(${activeScale})`
    const unscaledWidth = Math.max(boardContent.scrollWidth, boardContent.offsetWidth)
    const unscaledHeight = Math.max(boardContent.scrollHeight, boardContent.offsetHeight)
    zoomStage.style.width = `${Math.ceil(unscaledWidth * activeScale)}px`
    zoomStage.style.height = `${Math.ceil(unscaledHeight * activeScale)}px`
  }
  const setZoomScale = (nextScale, anchor = null) => {
    const prevScale = getActiveZoomScale()
    const targetScale = isBoardFullScreen() ? clampZoom(nextScale) : 1
    zoomScale = targetScale
    window.__paagYamazumiFullscreenZoom = isBoardFullScreen() ? targetScale : 1
    const anchorX = anchor && Number.isFinite(anchor.x) ? anchor.x : scrollContainer.clientWidth / 2
    const anchorY = anchor && Number.isFinite(anchor.y) ? anchor.y : scrollContainer.clientHeight / 2
    const contentX = (scrollContainer.scrollLeft + anchorX) / prevScale
    const contentY = (scrollContainer.scrollTop + anchorY) / prevScale
    applyZoomTransform()
    drawTaktLine(north, 'north')
    drawTaktLine(south, 'south')
    if (anchor && anchor.resetScroll) {
      scrollContainer.scrollLeft = 0
      scrollContainer.scrollTop = 0
    } else if (isBoardFullScreen() && Math.abs(targetScale - prevScale) > 0.0001) {
      scrollContainer.scrollLeft = Math.max(0, contentX * targetScale - anchorX)
      scrollContainer.scrollTop = Math.max(0, contentY * targetScale - anchorY)
    }
  }
  const fitBoardView = () => {
    if (!isBoardFullScreen() || !boardContent) return
    const prevMinWidth = boardContent.style.minWidth
    boardContent.style.minWidth = '0px'
    const contentW = Math.max(boardContent.scrollWidth, north.scrollWidth, south.scrollWidth, 240)
    const contentH = Math.max(boardContent.scrollHeight, 240)
    boardContent.style.minWidth = prevMinWidth
    const availW = Math.max(scrollContainer.clientWidth - 32, 100)
    const availH = Math.max(scrollContainer.clientHeight - 36, 100)
    const fitScale = clampZoom(Math.min(availW / contentW, availH / contentH, 1.35))
    setZoomScale(fitScale, { resetScroll: true })
  }
  const layoutBoard = () => {
    board.style.paddingTop = ''
    alignPairedPitches()
    equalizePitchFrames()
    drawTaktLine(north, 'north')
    drawTaktLine(south, 'south')
    applyZoomTransform()
  }
  const scheduleLayout = () => {
    requestAnimationFrame(() => requestAnimationFrame(layoutBoard))
  }
  const setBoardScaleMode = (nextMode, { notify = true } = {}) => {
    const nextReadable = String(nextMode || 'to_scale') === 'readable'
    isReadableMode = nextReadable
    syncScaleModeControls()
    for (const stack of board.querySelectorAll('.stack[data-assigned-pitch="true"]')) {
      stack.classList.toggle('takt-scale', Boolean(hasTakt && !isReadableMode))
    }
    for (const el of board.querySelectorAll('.element')) {
      const scaledHeight = Number(el.dataset.scaledHeightPx)
      const elementHeight = !isReadableMode && Number.isFinite(scaledHeight) ? scaledHeight : 34
      el.style.setProperty('--element-height', `${elementHeight}px`)
    }
    layoutBoard()
    scheduleLayout()
    if (notify) {
      setTriggerValue('scale_mode', { scale_mode: isReadableMode ? 'readable' : 'to_scale' })
    }
  }
  if (scaleToScaleBtn) {
    scaleToScaleBtn.onclick = () => setBoardScaleMode('to_scale')
  }
  if (scaleReadableBtn) {
    scaleReadableBtn.onclick = () => setBoardScaleMode('readable')
  }
  const printYamazumiBoard = (filterMode = 'all') => {
    const onlyWithElements = filterMode === 'with_elements'
    layoutBoard()
    try {
      let printFrame = document.getElementById('paag-yamazumi-print-frame')
      if (!printFrame) {
        printFrame = document.createElement('iframe')
        printFrame.id = 'paag-yamazumi-print-frame'
        printFrame.setAttribute('aria-hidden', 'true')
        document.body.appendChild(printFrame)
      }
      printFrame.style.cssText = 'position:fixed;left:-10000px;top:0;width:1056px;height:816px;border:0;visibility:hidden;pointer-events:none;'
      const frameDoc = printFrame.contentDocument || printFrame.contentWindow?.document
      const frameWin = printFrame.contentWindow
      if (!frameDoc || !frameWin || !boardContent) {
        window.print()
        return
      }
      const styleContent = parentElement.querySelector('style')?.textContent || ''
      const MAX_PRINT_ROW_WIDTH = 1300
      const LANE_GAP = 8
      const buildSideChunks = cards => {
        const items = cards.map(card => {
          const variantCount = Math.max(1, card.querySelectorAll('.variant').length)
          const cardWidth = Math.max(240, variantCount * 165 + 18)
          return { card, cardWidth, variantCount }
        })
        if (items.length === 0) return []
        const totalWidth = items.reduce(
          (sum, item, idx) => sum + item.cardWidth + (idx > 0 ? LANE_GAP : 0),
          0,
        )
        if (totalWidth <= MAX_PRINT_ROW_WIDTH) return [items]
        const chunks = []
        let currentChunk = []
        let currentWidth = 0
        for (let i = 0; i < items.length; i += 1) {
          const item = items[i]
          const addedWidth = currentChunk.length === 0 ? item.cardWidth : item.cardWidth + LANE_GAP
          if (currentChunk.length > 0 && currentWidth + addedWidth > MAX_PRINT_ROW_WIDTH) {
            chunks.push(currentChunk)
            currentChunk = [item]
            currentWidth = item.cardWidth
          } else {
            currentChunk.push(item)
            currentWidth += addedWidth
          }
        }
        if (currentChunk.length > 0) {
          chunks.push(currentChunk)
        }
        return chunks
      }
      const getChunkWeight = chunk => chunk.reduce(
        (sum, item) => sum + Math.max(1, Number(item.variantCount) || 1),
        0,
      )
      const rawNorthCards = [...north.querySelectorAll('.pitch')]
      const rawSouthCards = [...south.querySelectorAll('.pitch')]
      const northCards = onlyWithElements
        ? rawNorthCards.filter(card => card.querySelectorAll('.element').length > 0)
        : rawNorthCards
      const southCards = onlyWithElements
        ? rawSouthCards.filter(card => card.querySelectorAll('.element').length > 0)
        : rawSouthCards
      const northChunks = buildSideChunks(northCards)
      const southChunks = buildSideChunks(southCards)
      const allUnfilteredChunks = [
        ...buildSideChunks(rawNorthCards),
        ...buildSideChunks(rawSouthCards),
      ]
      const maxUnfilteredWeight = allUnfilteredChunks.reduce(
        (maxW, chunk) => Math.max(maxW, getChunkWeight(chunk)),
        1,
      )
      const pageSpecs = []
      northChunks.forEach((chunk, idx) => {
        pageSpecs.push({
          side: 'north',
          sideLabel: 'North Side · Odd Pitches',
          sidePartLabel: northChunks.length > 1 ? ` (${idx + 1}/${northChunks.length})` : '',
          chunk,
          chunkWeight: getChunkWeight(chunk),
          includeUnassigned: !onlyWithElements && pageSpecs.length === 0,
        })
      })
      southChunks.forEach((chunk, idx) => {
        pageSpecs.push({
          side: 'south',
          sideLabel: 'South Side · Even Pitches',
          sidePartLabel: southChunks.length > 1 ? ` (${idx + 1}/${southChunks.length})` : '',
          chunk,
          chunkWeight: getChunkWeight(chunk),
          includeUnassigned: !onlyWithElements && pageSpecs.length === 0,
        })
      })
      if (pageSpecs.length === 0) {
        pageSpecs.push({
          side: 'north',
          sideLabel: 'North Side · Odd Pitches',
          sidePartLabel: '',
          chunk: [],
          chunkWeight: 0,
          includeUnassigned: !onlyWithElements,
        })
      }
      const maxPrintedWeight = pageSpecs.reduce(
        (maxW, spec) => Math.max(maxW, spec.chunkWeight || 0),
        0,
      )
      const referenceWeight = Math.max(
        1,
        maxPrintedWeight,
        Math.min(4, maxUnfilteredWeight),
      )
      const printedPitchCount = northCards.length + southCards.length
      const elementCount = (data.elements || []).length
      const taktSummary = hasTakt ? `Takt: ${formatTakt(data.takt)}` : 'Takt: Not set'
      const summaryText = `${printedPitchCount} pitch${printedPitchCount === 1 ? '' : 'es'} · ${elementCount} work element${elementCount === 1 ? '' : 's'} · ${taktSummary}`
      const noticeText = scaleNotice
        ? scaleNotice.textContent
        : 'Readable mode: Work elements are expanded for readability and are not scaled to cycle time (red takt time line hidden).'
      const sheetsHtml = pageSpecs.map((spec, pageIndex) => {
        const pageLabel = ` · ${spec.sideLabel}${spec.sidePartLabel}`
          + (pageSpecs.length > 1 ? ` · Page ${pageIndex + 1} of ${pageSpecs.length}` : '')
        const unassignedHtml = spec.includeUnassigned && unassigned.children.length > 0
          ? `<div class="unassigned-lane">${unassigned.innerHTML}</div>`
          : ''
        const slotWidthExpr = `(100% - ${(referenceWeight - 1) * LANE_GAP}px) / ${referenceWeight}`
        const cardsHtml = spec.chunk.map(({ card, variantCount }) => {
          const clone = card.cloneNode(true)
          clone.querySelectorAll('.status').forEach(el => el.remove())
          const weight = Math.max(1, Number(variantCount) || 1)
          const cardWidthExpr = `calc(${weight} * (${slotWidthExpr}) + ${(weight - 1) * LANE_GAP}px)`
          clone.style.setProperty('--pitch-print-width', cardWidthExpr)
          clone.style.flex = `0 0 ${cardWidthExpr}`
          clone.style.flexBasis = cardWidthExpr
          clone.style.width = cardWidthExpr
          clone.style.minWidth = '0'
          clone.style.maxWidth = cardWidthExpr
          return clone.outerHTML
        }).join('')
        let lanesHtml = ''
        if (spec.chunk.length > 0) {
          if (spec.side === 'north') {
            lanesHtml = `<div class="lane-label">${escapeHtml(spec.sideLabel + spec.sidePartLabel)}</div>`
              + `<div class="lane north">${cardsHtml}</div>`
              + `<div class="line"><span>Assembly Flow →</span></div>`
          } else {
            lanesHtml = `<div class="line"><span>Assembly Flow →</span></div>`
              + `<div class="lane south">${cardsHtml}</div>`
              + `<div class="lane-label">${escapeHtml(spec.sideLabel + spec.sidePartLabel)}</div>`
          }
        }
        return `<section class="print-sheet"><div class="board readable-mode print-page-stage">`
          + `<div class="print-page-header"><div class="print-page-title"><strong>Interactive Yamazumi</strong><span>${escapeHtml(summaryText + pageLabel)}</span></div><div class="legend">${legend.innerHTML}</div></div>`
          + `<div class="scale-notice">${escapeHtml(noticeText)}</div>`
          + unassignedHtml
          + lanesHtml
          + `</div></section>`
      }).join('')
      frameDoc.open()
      frameDoc.write(`<!doctype html><html><head><meta charset="utf-8"><title>Interactive Yamazumi</title><style>
        @page { size: landscape; margin: 3mm; }
        :root {
          --st-text-color: #111827;
          --st-secondary-text-color: #4b5563;
          --st-background-color: #ffffff;
          --st-secondary-background-color: #f3f4f6;
          --st-border-color: #d1d5db;
          --st-primary-color: #2563eb;
          --st-font: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        html, body {
          margin: 0 !important;
          padding: 0 !important;
          width: 100% !important;
          background: #ffffff;
          color: var(--st-text-color);
          font-family: var(--st-font);
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
        }
        ${styleContent}
        .print-sheet {
          box-sizing: border-box !important;
          width: 100% !important;
          height: 98.5vh !important;
          min-height: 98.5vh !important;
          max-height: 98.5vh !important;
          display: flex !important;
          flex-direction: column !important;
          page-break-after: always;
          break-after: page;
          page-break-inside: avoid !important;
          break-inside: avoid !important;
          margin: 0 !important;
          padding: 0 !important;
          overflow: hidden !important;
        }
        .print-sheet:last-child {
          page-break-after: auto;
          break-after: auto;
        }
        .print-page-stage.board {
          position: static !important;
          box-sizing: border-box !important;
          width: 100% !important;
          min-width: 0 !important;
          max-width: 100% !important;
          height: 100% !important;
          flex: 1 1 auto !important;
          display: flex !important;
          flex-direction: column !important;
          overflow: visible !important;
          padding: 2px 4px !important;
          margin: 0 !important;
        }
        .print-page-stage .pitch,
        .print-page-stage .pitch-placeholder,
        .print-page-stage .lane {
          page-break-inside: avoid !important;
          break-inside: avoid !important;
        }
        .print-page-header {
          flex: 0 0 auto !important;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin: 0 2px 2px;
        }
        .print-page-title {
          display: flex;
          align-items: baseline;
          gap: 10px;
        }
        .print-page-title strong {
          font-size: .95rem;
        }
        .print-page-title span {
          font-size: .8rem;
          color: var(--st-secondary-text-color);
        }
        .print-page-stage .legend {
          margin: 0 !important;
          padding: 0 !important;
          font-size: .8rem !important;
        }
        .print-page-stage .scale-notice {
          flex: 0 0 auto !important;
          display: block !important;
          margin: 0 2px 3px !important;
          padding: 3px 8px !important;
          font-size: .74rem !important;
        }
        .print-page-stage .lane-label {
          flex: 0 0 auto !important;
          position: static !important;
          margin: 2px 2px 2px !important;
          font-size: .82rem !important;
        }
        .print-page-stage .line {
          flex: 0 0 auto !important;
          margin: 6px 0 4px !important;
        }
        .print-page-stage .lane,
        .print-page-stage .lane.north,
        .print-page-stage .lane.south {
          flex: 1 1 auto !important;
          width: 100% !important;
          min-width: 0 !important;
          min-height: 0 !important;
          box-sizing: border-box !important;
          display: flex !important;
          justify-content: flex-start !important;
          align-items: stretch !important;
          gap: 8px !important;
          padding: 2px 0 !important;
          margin: 0 !important;
        }
        .print-page-stage .pitch,
        .print-page-stage .pitch-placeholder {
          flex: 0 0 var(--pitch-print-width, auto) !important;
          width: var(--pitch-print-width, auto) !important;
          max-width: var(--pitch-print-width, none) !important;
          min-width: 0 !important;
          height: auto !important;
          min-height: 0 !important;
          box-sizing: border-box !important;
          display: flex !important;
          flex-direction: column !important;
          padding: 8px !important;
          margin: 0 !important;
        }
        .print-page-stage .pitch-info {
          flex: 0 0 auto !important;
        }
        .print-page-stage .address {
          font-size: .95rem !important;
        }
        .print-page-stage .status {
          display: none !important;
        }
        .print-page-stage .name {
          min-height: 22px !important;
          font-size: .88rem !important;
        }
        .print-page-stage .variants,
        .print-page-stage .pitch.north .variants,
        .print-page-stage .pitch.south .variants {
          flex: 1 1 auto !important;
          min-height: 0 !important;
          min-width: 0 !important;
          width: 100% !important;
          display: flex !important;
          align-items: stretch !important;
          gap: 8px !important;
        }
        .print-page-stage .variant {
          flex: 1 1 0% !important;
          min-width: 0 !important;
          min-height: 0 !important;
          margin-top: 4px !important;
          padding-top: 4px !important;
        }
        .print-page-stage .pitch.north .variant {
          display: flex !important;
          flex-direction: column-reverse !important;
        }
        .print-page-stage .pitch.south .variant {
          display: flex !important;
          flex-direction: column !important;
        }
        .print-page-stage .variant-title {
          flex: 0 0 auto !important;
          font-size: .84rem !important;
        }
        .print-page-stage .stack,
        .print-page-stage .pitch.north .stack,
        .print-page-stage .pitch.south .stack {
          flex: 1 1 auto !important;
          min-height: 0 !important;
          height: auto !important;
          width: 100% !important;
          box-sizing: border-box !important;
        }
        .board-actions, .pitch-actions, .edit-element, .takt-line, .status, .print-dialog-backdrop {
          display: none !important;
        }
        .print-page-stage.readable-mode .element {
          height: auto !important;
          flex: 0 0 auto !important;
          min-height: 34px !important;
          padding: 6px 10px 6px 10px !important;
          font-size: .8rem !important;
          overflow: visible !important;
        }
        .print-page-stage.readable-mode .element.has-criticality {
          min-height: 46px !important;
          padding-bottom: 22px !important;
        }
        .print-page-stage.readable-mode .element strong {
          top: 5px !important;
          right: 8px !important;
          font-size: .8rem !important;
        }
        .print-page-stage.readable-mode .element-description {
          height: auto !important;
          overflow: visible !important;
          padding-right: 52px !important;
          line-height: 1.25 !important;
        }
      </style></head><body>${sheetsHtml}</body></html>`)
      frameDoc.close()
      const prepareAndPrint = () => {
        try {
          frameDoc.querySelectorAll('.takt-line, .status').forEach(el => el.remove())
          frameDoc.querySelectorAll('.stack').forEach(el => el.classList.remove('takt-scale'))
          frameDoc.querySelectorAll('.element').forEach(el => {
            el.style.removeProperty('--element-height')
            el.style.height = 'auto'
          })
          frameDoc.querySelectorAll('.pitch-info, .variant-title, .stack, .pitch, .pitch-placeholder').forEach(el => {
            el.style.minHeight = ''
          })
          for (const sheet of frameDoc.querySelectorAll('.print-sheet')) {
            const stage = sheet.querySelector('.print-page-stage')
            if (!stage) continue
            const infos = [...stage.querySelectorAll('.pitch-info')]
            const titles = [...stage.querySelectorAll('.variant-title')]
            const maxInfoH = Math.max(0, ...infos.map(el => el.scrollHeight))
            const maxTitleH = Math.max(0, ...titles.map(el => el.scrollHeight))
            for (const el of infos) el.style.minHeight = `${maxInfoH}px`
            for (const el of titles) el.style.minHeight = `${maxTitleH}px`
            const availH = sheet.clientHeight
            const neededH = stage.scrollHeight
            if (availH > 0 && neededH > availH + 2) {
              const zoomFactor = Math.max(0.45, (availH - 2) / neededH)
              stage.style.zoom = String(zoomFactor)
            }
          }
          requestAnimationFrame(() => {
            try {
              frameWin.focus()
              frameWin.print()
            } catch {
              window.print()
            }
          })
        } catch {
          window.print()
        }
      }
      requestAnimationFrame(() => requestAnimationFrame(prepareAndPrint))
    } catch {
      window.print()
    }
  }
  const printDialogBackdrop = parentElement.querySelector('#print-dialog-backdrop')
  const printDialogCloseBtn = parentElement.querySelector('#print-dialog-close')
  const printDialogCancelBtn = parentElement.querySelector('#print-dialog-cancel')
  const printDialogConfirmBtn = parentElement.querySelector('#print-dialog-confirm')
  const printOptAllRadio = parentElement.querySelector('#print-opt-all')
  const printOptElementsRadio = parentElement.querySelector('#print-opt-elements')
  const printOptAllLabel = parentElement.querySelector('#print-opt-all-label')
  const printOptElementsLabel = parentElement.querySelector('#print-opt-elements-label')
  const printOptAllDesc = parentElement.querySelector('#print-opt-all-desc')
  const printOptElementsDesc = parentElement.querySelector('#print-opt-elements-desc')

  const syncPrintDialogSelection = () => {
    const isWithElements = Boolean(printOptElementsRadio?.checked)
    if (printOptAllLabel) printOptAllLabel.classList.toggle('selected', !isWithElements)
    if (printOptElementsLabel) printOptElementsLabel.classList.toggle('selected', isWithElements)
  }

  const closePrintDialog = () => {
    if (printDialogBackdrop) printDialogBackdrop.hidden = true
    board.classList.remove('print-dialog-open')
  }

  const openPrintDialog = () => {
    if (!printDialogBackdrop) {
      printYamazumiBoard('all')
      return
    }
    const allPitchCards = [
      ...north.querySelectorAll('.pitch'),
      ...south.querySelectorAll('.pitch'),
    ]
    const withElementsCards = allPitchCards.filter(
      card => card.querySelectorAll('.element').length > 0,
    )
    if (printOptAllDesc) {
      printOptAllDesc.textContent = `Include all pitches on the board, including empty pitches (${allPitchCards.length} pitch${allPitchCards.length === 1 ? '' : 'es'}).`
    }
    if (printOptElementsDesc) {
      printOptElementsDesc.textContent = `Only print pitches that contain work elements; empty pitches will not be included (${withElementsCards.length} pitch${withElementsCards.length === 1 ? '' : 'es'}).`
    }
    const savedMode = window.__paagYamazumiPrintFilterMode === 'with_elements' ? 'with_elements' : 'all'
    if (printOptAllRadio) printOptAllRadio.checked = savedMode === 'all'
    if (printOptElementsRadio) printOptElementsRadio.checked = savedMode === 'with_elements'
    syncPrintDialogSelection()
    printDialogBackdrop.hidden = false
    board.classList.add('print-dialog-open')
    requestAnimationFrame(() => {
      if (printDialogConfirmBtn) printDialogConfirmBtn.focus()
    })
  }

  if (printOptAllRadio) printOptAllRadio.onchange = syncPrintDialogSelection
  if (printOptElementsRadio) printOptElementsRadio.onchange = syncPrintDialogSelection
  if (printDialogCloseBtn) printDialogCloseBtn.onclick = closePrintDialog
  if (printDialogCancelBtn) printDialogCancelBtn.onclick = closePrintDialog
  if (printDialogBackdrop) {
    printDialogBackdrop.onclick = event => {
      if (event.target === printDialogBackdrop) closePrintDialog()
    }
  }
  if (printDialogConfirmBtn) {
    printDialogConfirmBtn.onclick = () => {
      const selectedMode = printOptElementsRadio?.checked ? 'with_elements' : 'all'
      window.__paagYamazumiPrintFilterMode = selectedMode
      closePrintDialog()
      printYamazumiBoard(selectedMode)
    }
  }
  const handlePrintDialogKeyDown = event => {
    if (!printDialogBackdrop || printDialogBackdrop.hidden) return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      closePrintDialog()
    }
  }
  if (printBtn) {
    printBtn.onclick = openPrintDialog
  }
  if (zoomInBtn) {
    zoomInBtn.onclick = () => {
      if (!isBoardFullScreen()) return
      setZoomScale(zoomScale * 1.2)
    }
  }
  if (zoomOutBtn) {
    zoomOutBtn.onclick = () => {
      if (!isBoardFullScreen()) return
      setZoomScale(zoomScale / 1.2)
    }
  }
  if (fitViewBtn) {
    fitViewBtn.onclick = () => {
      if (!isBoardFullScreen()) return
      fitBoardView()
    }
  }
  if (zoomResetBtn) {
    zoomResetBtn.onclick = () => {
      if (!isBoardFullScreen()) return
      setZoomScale(1, { resetScroll: false })
    }
  }
  const handleBoardWheel = event => {
    if (!isBoardFullScreen()) return
    const target = event.target instanceof Element ? event.target : null
    if (target && target.closest('.board-actions')) return
    event.preventDefault()
    const rect = scrollContainer.getBoundingClientRect()
    const anchorX = event.clientX - rect.left
    const anchorY = event.clientY - rect.top
    const delta = event.deltaY < 0 ? 1.12 : 0.89
    setZoomScale(zoomScale * delta, { x: anchorX, y: anchorY })
  }
  let panState = null
  const handlePanStart = event => {
    if (!isBoardFullScreen() || event.button !== 0) return
    const target = event.target instanceof Element ? event.target : null
    if (target && target.closest('.element, button, input, select, textarea, a, .board-actions')) return
    panState = {
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: scrollContainer.scrollLeft,
      scrollTop: scrollContainer.scrollTop,
    }
    board.classList.add('is-panning')
  }
  const handlePanMove = event => {
    if (!panState) return
    scrollContainer.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX)
    scrollContainer.scrollTop = panState.scrollTop - (event.clientY - panState.startY)
  }
  const handlePanEnd = () => {
    if (!panState) return
    panState = null
    board.classList.remove('is-panning')
  }
  const ensureGlobalFullScreenStyle = () => {
    const styleId = 'paag-yamazumi-fullscreen-global-style'
    if (document.getElementById(styleId)) return
    const styleEl = document.createElement('style')
    styleEl.id = styleId
    styleEl.textContent = `
      html.paag-yamazumi-fullscreen-active header[data-testid="stHeader"],
      html.paag-yamazumi-fullscreen-active [data-testid="stHeader"],
      html.paag-yamazumi-fullscreen-active .stAppHeader,
      html.paag-yamazumi-fullscreen-active [data-testid="stToolbar"],
      html.paag-yamazumi-fullscreen-active [data-testid="stDecoration"],
      html.paag-yamazumi-fullscreen-active [data-testid="stStatusWidget"],
      html.paag-yamazumi-fullscreen-active [data-testid="stSidebar"],
      html.paag-yamazumi-fullscreen-active [data-testid="stSidebarCollapsedControl"],
      html.paag-yamazumi-fullscreen-active [data-testid="stExpandSidebarButton"],
      html.paag-yamazumi-fullscreen-active [data-testid="collapsedControl"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
        overflow: hidden !important;
        pointer-events: none !important;
      }
      html.paag-yamazumi-fullscreen-active [data-testid="stModal"],
      html.paag-yamazumi-fullscreen-active [data-baseweb="modal"] {
        z-index: 1000010 !important;
      }
    `
    ;(document.head || document.documentElement).appendChild(styleEl)
  }
  const getSidebarElement = () => document.querySelector('[data-testid="stSidebar"]')
  const isSidebarExpanded = () => getSidebarElement()?.getAttribute('aria-expanded') === 'true'
  const collapseSidebarIfExpanded = () => {
    if (!isSidebarExpanded()) return
    const collapseButton =
      document.querySelector('[data-testid="stSidebarCollapseButton"] button') ||
      document.querySelector('[data-testid="stSidebarCollapseButton"]')
    if (typeof collapseButton?.click === 'function') collapseButton.click()
  }
  const expandSidebarIfCollapsed = () => {
    if (isSidebarExpanded()) return
    const expandButton =
      document.querySelector('button[data-testid="stExpandSidebarButton"]') ||
      document.querySelector('[data-testid="stExpandSidebarButton"] button') ||
      document.querySelector('[data-testid="stExpandSidebarButton"]') ||
      document.querySelector('[data-testid="stSidebarCollapsedControl"] button')
    if (typeof expandButton?.click === 'function') expandButton.click()
  }
  const updateFullScreenControl = () => {
    const isFullScreen = isBoardFullScreen()
    const wasFullScreen = Boolean(window.__paagYamazumiFullScreenActive)
    ensureGlobalFullScreenStyle()
    document.documentElement.classList.toggle('paag-yamazumi-fullscreen-active', isFullScreen)
    if (isFullScreen && !wasFullScreen) {
      if (typeof window.__paagYamazumiSidebarWasExpanded !== 'boolean') {
        window.__paagYamazumiSidebarWasExpanded = isSidebarExpanded()
      }
      window.__paagYamazumiFullScreenActive = true
      collapseSidebarIfExpanded()
    } else if (!isFullScreen && wasFullScreen) {
      const shouldRestoreSidebar = Boolean(window.__paagYamazumiSidebarWasExpanded)
      window.__paagYamazumiFullScreenActive = false
      window.__paagYamazumiSidebarWasExpanded = undefined
      scrollContainer.scrollTop = 0
      if (shouldRestoreSidebar) {
        expandSidebarIfCollapsed()
      }
    }
    if (!isFullScreen) {
      zoomScale = 1
      window.__paagYamazumiFullscreenZoom = 1
    }
    fullScreen.textContent = isFullScreen ? 'Exit Full Screen' : 'Full Screen'
    fullScreen.title = isFullScreen
      ? 'Exit the full-screen Yamazumi board'
      : 'Open the Yamazumi board full screen'
    fullScreen.setAttribute('aria-pressed', String(isFullScreen))
    board.classList.toggle('fullscreen-board', isFullScreen)
    applyZoomTransform()
    scheduleLayout()
  }
  if (typeof fullScreenTarget.requestFullscreen !== 'function') {
    fullScreen.disabled = true
    fullScreen.title = 'Full screen is not available in this browser'
  } else {
    fullScreen.onclick = async () => {
      try {
        if (isBoardFullScreen()) {
          await document.exitFullscreen()
        } else {
          window.__paagYamazumiSidebarWasExpanded = isSidebarExpanded()
          await fullScreenTarget.requestFullscreen()
        }
        updateFullScreenControl()
      } catch {
        if (!isBoardFullScreen()) {
          window.__paagYamazumiSidebarWasExpanded = undefined
        }
        updateFullScreenControl()
      }
    }
  }
  if (typeof board.__paagCleanup === 'function') {
    board.__paagCleanup()
  }
  document.addEventListener('fullscreenchange', updateFullScreenControl)
  document.addEventListener('webkitfullscreenchange', updateFullScreenControl)
  document.addEventListener('keydown', handlePrintDialogKeyDown, true)
  scrollContainer.addEventListener('wheel', handleBoardWheel, { passive: false })
  scrollContainer.addEventListener('mousedown', handlePanStart)
  window.addEventListener('mousemove', handlePanMove)
  window.addEventListener('mouseup', handlePanEnd)
  const resizeObserver = new ResizeObserver(scheduleLayout)
  resizeObserver.observe(board)
  if (boardViewport && boardViewport !== board) resizeObserver.observe(boardViewport)
  resizeObserver.observe(north)
  resizeObserver.observe(south)
  const cleanup = () => {
    document.removeEventListener('fullscreenchange', updateFullScreenControl)
    document.removeEventListener('webkitfullscreenchange', updateFullScreenControl)
    document.removeEventListener('keydown', handlePrintDialogKeyDown, true)
    scrollContainer.removeEventListener('wheel', handleBoardWheel)
    scrollContainer.removeEventListener('mousedown', handlePanStart)
    window.removeEventListener('mousemove', handlePanMove)
    window.removeEventListener('mouseup', handlePanEnd)
    resizeObserver.disconnect()
  }
  board.__paagCleanup = cleanup
  // Normalize bands across all pitches after wrapping has been measured. This
  // gives every stack in a lane one shared baseline beside the assembly flow.
  layoutBoard()
  scheduleLayout()
  updateFullScreenControl()
  const printToken = Number(data.print_request_token || 0)
  if (printToken > 0) {
    if (window.__paagYamazumiLastPrintToken !== printToken) {
      window.__paagYamazumiLastPrintToken = printToken
      requestAnimationFrame(() => openPrintDialog())
    }
  } else {
    window.__paagYamazumiLastPrintToken = 0
  }
  return () => {
    if (board.__paagCleanup === cleanup) board.__paagCleanup = null
    if (!isBoardFullScreen()) {
      document.documentElement.classList.remove('paag-yamazumi-fullscreen-active')
    }
    document.removeEventListener('fullscreenchange', updateFullScreenControl)
    document.removeEventListener('webkitfullscreenchange', updateFullScreenControl)
    document.removeEventListener('keydown', handlePrintDialogKeyDown, true)
    scrollContainer.removeEventListener('wheel', handleBoardWheel)
    scrollContainer.removeEventListener('mousedown', handlePanStart)
    window.removeEventListener('mousemove', handlePanMove)
    window.removeEventListener('mouseup', handlePanEnd)
    resizeObserver.disconnect()
  }
}
"""

_YAMAZUMI_BOARD_HOT_RELOAD_REV = 20

_YAMAZUMI_BOARD = st.components.v2.component(
    "paag_yamazumi_drag_board_v47",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def yamazumi_board(
    pitches: list[dict],
    elements: list[dict],
    variants: list[str],
    takt: float,
    *,
    time_unit: str,
    takt_time_unit: str,
    scale_mode: str = "to_scale",
    print_request_token: int = 0,
    key: str,
    on_move: Callable[[], None],
    on_add_pitch: Callable[[], None],
    on_add_element: Callable[[], None],
    on_edit_pitch: Callable[[], None],
    on_edit_element: Callable[[], None],
    on_scale_mode: Callable[[], None] | None = None,
):
    safe_takt = float(takt)
    if not math.isfinite(safe_takt):
        safe_takt = 0.0
    unit = time_unit_config(time_unit)
    takt_unit = time_unit_config(takt_time_unit)
    normalized_scale_mode = (
        "readable"
        if str(scale_mode or "").strip().lower() in {"readable", "not_scaled"}
        else "to_scale"
    )
    safe_elements = json_safe(elements)
    paired_pitches, pitch_pairs = build_yamazumi_pitch_pairs(pitches, safe_elements)
    return _YAMAZUMI_BOARD(
        key=key,
        data=json_safe(
            {
                "pitches": paired_pitches,
                "pitch_pairs": pitch_pairs,
                "elements": safe_elements,
                "show_unassigned": any(
                    not element.get("pitch_id") for element in safe_elements
                ),
                "variants": variants,
                "takt": safe_takt,
                "time_unit": unit.key,
                "seconds_per_unit": unit.seconds_per_unit,
                "time_decimals": unit.decimals,
                "time_suffix": unit.suffix,
                "takt_time_unit": takt_unit.key,
                "takt_seconds_per_unit": takt_unit.seconds_per_unit,
                "takt_decimals": takt_unit.decimals,
                "takt_suffix": takt_unit.suffix,
                "scale_mode": normalized_scale_mode,
                "print_request_token": int(print_request_token or 0),
            }
        ),
        on_move_change=on_move,
        on_add_pitch_change=on_add_pitch,
        on_add_element_change=on_add_element,
        on_edit_pitch_change=on_edit_pitch,
        on_edit_element_change=on_edit_element,
        on_scale_mode_change=on_scale_mode or (lambda: None),
        width="stretch",
        height="content",
    )
