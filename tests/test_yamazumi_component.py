from __future__ import annotations

import json
import inspect
import unittest
from unittest.mock import patch

from utils import yamazumi_board as board_module


class YamazumiComponentTests(unittest.TestCase):
    def test_unassigned_card_is_only_rendered_for_unassigned_work(self) -> None:
        self.assertIn('id="unassigned"', board_module._HTML)
        self.assertIn(
            "data.show_unassigned && Object.keys(grouped.__unassigned__ || {}).length",
            board_module._JS,
        )
        self.assertIn("unassigned.appendChild(makePitch({", board_module._JS)
        self.assertIn("pitch_number: 'Unassigned'", board_module._JS)
        self.assertIn(
            "const acceptsWork = !pitch.id || pitch.status === 'Active'",
            board_module._JS,
        )
        self.assertIn("card.ondrop = event =>", board_module._JS)
        self.assertIn("pitch_id: pitch.id || null", board_module._JS)

    def test_drop_slots_emit_position_anchors_without_changing_orientation(self) -> None:
        self.assertIn("const displayItems = side === 'north' ? [...items].reverse() : items", board_module._JS)
        self.assertIn("appendDropSlot(logicalIndex + 1)", board_module._JS)
        self.assertIn("before_element_id: items[logicalIndex]?.id || null", board_module._JS)
        self.assertIn("after_element_id: logicalIndex > 0", board_module._JS)
        self.assertIn("paag_yamazumi_drag_board_v48", inspect.getsource(board_module))
        self.assertIn(
            "setTriggerValue('edit_element', { element_id: item.id, model_variant: variant })",
            board_module._JS,
        )

    def test_paired_north_and_south_pitches_share_synchronized_column_widths(self) -> None:
        self.assertIn(".pitch-placeholder", board_module._CSS)
        self.assertIn("const pairKeyFrom = pitch =>", board_module._JS)
        self.assertIn("const oddNumber = number % 2 ? number : number - 1", board_module._JS)
        self.assertIn("const applyPairWidth = (pair, widthValue) =>", board_module._JS)
        self.assertIn("const alignPairedPitches = () =>", board_module._JS)
        self.assertIn("alignPairedPitches()", board_module._JS)

        nexus_pitches = []
        for idx in range(1, 21):
            variants = (
                ["All models", "Pedestal / Riser = Riser"]
                if idx in {11, 13, 14, 15, 16, 17, 18}
                else ["All models"]
            )
            nexus_pitches.append(
                {
                    "id": f"pitch-{idx}",
                    "area_id": "area-assembly-1",
                    "pitch_number": f"01-PED-{idx:03d}",
                    "pitch_name": f"Station {idx}",
                    "status": "Active",
                    "model_variants": variants,
                }
            )
        annotated, pairs = board_module.build_yamazumi_pitch_pairs(nexus_pitches)
        self.assertEqual(len(pairs), 10)
        by_number = {item["pitch_number"]: item for item in annotated}
        self.assertEqual(by_number["01-PED-011"]["pair_index"], 5)
        self.assertEqual(by_number["01-PED-012"]["pair_index"], 5)
        self.assertEqual(by_number["01-PED-011"]["pair_width_px"], 348)
        self.assertEqual(by_number["01-PED-012"]["pair_width_px"], 348)
        self.assertEqual(by_number["01-PED-013"]["pair_index"], 6)
        self.assertEqual(by_number["01-PED-014"]["pair_index"], 6)
        self.assertEqual(by_number["01-PED-013"]["pair_width_px"], 348)
        self.assertEqual(by_number["01-PED-014"]["pair_width_px"], 348)

        suffixed_and_cross_area = [
            {"id": "p27", "area_id": "a2", "pitch_number": "01-PED-027", "model_variants": ["All models", "Riser"]},
            {"id": "p27a", "area_id": "da", "pitch_number": "01-PED-027(A)", "model_variants": ["All models"]},
            {"id": "p28", "area_id": "a2", "pitch_number": "01-PED-028", "model_variants": ["All models"]},
            {"id": "p35", "area_id": "a2", "pitch_number": "01-PED-035", "model_variants": ["All models"]},
            {"id": "p36", "area_id": "pack", "pitch_number": "01-PED-036", "model_variants": ["All models"]},
        ]
        annotated_extra, extra_pairs = board_module.build_yamazumi_pitch_pairs(suffixed_and_cross_area)
        extra_by_number = {item["pitch_number"]: item for item in annotated_extra}
        self.assertEqual(extra_by_number["01-PED-027"]["pair_index"], extra_by_number["01-PED-028"]["pair_index"])
        self.assertNotEqual(extra_by_number["01-PED-027(A)"]["pair_index"], extra_by_number["01-PED-028"]["pair_index"])
        self.assertEqual(extra_by_number["01-PED-035"]["pair_index"], extra_by_number["01-PED-036"]["pair_index"])
        self.assertEqual(len(extra_pairs), 3)

    def test_hovered_work_element_expands_for_readability(self) -> None:
        self.assertIn("el.style.setProperty('--element-height', `${elementHeight}px`)", board_module._JS)
        self.assertIn(".board:not(.is-dragging) .element:hover", board_module._CSS)
        self.assertIn("min-height:max(var(--element-height, 34px), 38px)", board_module._CSS)
        self.assertIn(".board:not(.is-dragging) .element:hover .element-description", board_module._CSS)

    def test_element_flags_are_not_rendered_or_sent_to_card_markup(self) -> None:
        self.assertNotIn(".flags", board_module._CSS)
        self.assertNotIn("item.flags", board_module._JS)
        self.assertNotIn('class="flags"', board_module._JS)

    def test_full_screen_control_uses_browser_api_and_reflows_board(self) -> None:
        self.assertIn('id="full-screen"', board_module._HTML)
        self.assertIn(".board.fullscreen-board", board_module._CSS)
        self.assertIn("await fullScreenTarget.requestFullscreen()", board_module._JS)
        self.assertIn("await document.exitFullscreen()", board_module._JS)
        self.assertIn("const fullScreenTarget = document.documentElement", board_module._JS)
        self.assertIn("document.fullscreenElement === fullScreenTarget", board_module._JS)
        self.assertIn("board.classList.toggle('fullscreen-board'", board_module._JS)
        self.assertIn("'Exit Full Screen' : 'Full Screen'", board_module._JS)
        self.assertIn("fullScreen.setAttribute('aria-pressed'", board_module._JS)
        self.assertIn("new ResizeObserver(scheduleLayout)", board_module._JS)
        self.assertIn("document.addEventListener('fullscreenchange'", board_module._JS)
        self.assertIn("document.removeEventListener('fullscreenchange'", board_module._JS)
        self.assertIn("resizeObserver.disconnect()", board_module._JS)

    def test_full_screen_collapses_sidebar_and_restores_prior_expanded_state(self) -> None:
        self.assertIn('[data-testid="stSidebar"]', board_module._JS)
        self.assertIn("getAttribute('aria-expanded') === 'true'", board_module._JS)
        self.assertIn('[data-testid="stSidebarCollapseButton"] button', board_module._JS)
        self.assertIn('button[data-testid="stExpandSidebarButton"]', board_module._JS)
        self.assertIn("window.__paagYamazumiSidebarWasExpanded = isSidebarExpanded()", board_module._JS)
        self.assertIn("collapseSidebarIfExpanded()", board_module._JS)
        self.assertIn("if (shouldRestoreSidebar)", board_module._JS)
        self.assertIn("expandSidebarIfCollapsed()", board_module._JS)

    def test_full_screen_zoom_and_pan_controls(self) -> None:
        self.assertIn('id="fullscreen-zoom-controls"', board_module._HTML)
        self.assertIn('id="zoom-out"', board_module._HTML)
        self.assertIn('id="zoom-in"', board_module._HTML)
        self.assertIn('id="fit-view"', board_module._HTML)
        self.assertIn('id="zoom-reset"', board_module._HTML)
        self.assertIn('id="board-zoom-stage"', board_module._HTML)
        self.assertIn(".board.fullscreen-board .fullscreen-zoom-controls", board_module._CSS)
        self.assertIn("const setZoomScale = (nextScale, anchor = null) =>", board_module._JS)
        self.assertIn("const fitBoardView = () =>", board_module._JS)
        self.assertIn("scrollContainer.addEventListener('wheel', handleBoardWheel, { passive: false })", board_module._JS)
        self.assertIn("scrollContainer.removeEventListener('wheel', handleBoardWheel)", board_module._JS)
        self.assertIn("const delta = event.deltaY < 0 ? 1.12 : 0.89", board_module._JS)
        self.assertIn("boardContent.style.transform = `scale(${activeScale})`", board_module._JS)
        self.assertIn("(stackRect.bottom - laneRect.top) / activeScale - taktPixels", board_module._JS)
        self.assertIn("(stackRect.top - laneRect.top) / activeScale + taktPixels", board_module._JS)

    def test_full_screen_fixed_top_toolbar_options(self) -> None:
        self.assertIn('id="board-toolbar-title"', board_module._HTML)
        self.assertIn('id="add-pitch"', board_module._HTML)
        self.assertIn('id="scale-mode-toggle"', board_module._HTML)
        self.assertIn('id="scale-to-scale"', board_module._HTML)
        self.assertIn('id="scale-readable"', board_module._HTML)
        self.assertIn('id="print-board"', board_module._HTML)
        self.assertIn('id="full-screen"', board_module._HTML)
        self.assertIn(".board.fullscreen-board .board-actions { width:100%; box-sizing:border-box;", board_module._CSS)
        self.assertIn("const setBoardScaleMode = (nextMode, { notify = true } = {}) =>", board_module._JS)
        self.assertIn("setTriggerValue('scale_mode', { scale_mode: isReadableMode ? 'readable' : 'to_scale' })", board_module._JS)
        self.assertIn("const printYamazumiBoard = (filterMode = 'all') =>", board_module._JS)
        self.assertIn("printBtn.onclick = openPrintDialog", board_module._JS)

    def test_dialog_actions_keep_document_full_screen(self) -> None:
        for trigger_name in ("add_pitch", "add_element", "edit_pitch", "edit_element"):
            self.assertIn(
                f"setTriggerValue('{trigger_name}'", board_module._JS
            )
        self.assertNotIn("triggerAfterFullScreenExit", board_module._JS)

    def test_full_screen_board_has_explicit_two_axis_scrolling(self) -> None:
        self.assertIn('class="board-content"', board_module._HTML)
        self.assertIn("width:max-content", board_module._CSS)
        self.assertIn("overflow:scroll", board_module._CSS)
        self.assertIn("scrollbar-gutter:stable both-edges", board_module._CSS)
        self.assertIn("::-webkit-scrollbar", board_module._CSS)
        self.assertIn(".board.fullscreen-board .board-actions", board_module._CSS)

    def test_board_renders_separate_read_only_criticality_tags(self) -> None:
        self.assertIn("item.criticality || []", board_module._JS)
        self.assertIn("criticality-tag", board_module._JS)
        self.assertIn("Derived from PFMEA Classification", board_module._JS)
        self.assertIn("Derived from an active Safety requirement", board_module._JS)
        self.assertNotIn("item.flags", board_module._JS)
    def test_selected_time_unit_scales_labels_and_preserves_height_ratio(self) -> None:
        self.assertIn("const displayTime = value =>", board_module._JS)
        self.assertIn("${formatTime(total)} / ${formatTakt(data.takt)}", board_module._JS)
        self.assertIn(
            "displayTime(item.time_s) / displayTakt * taktPixels", board_module._JS
        )

    def test_assigned_lanes_use_an_accurate_takt_line_and_proportional_scale(self) -> None:
        self.assertIn("const taktPixels = 155", board_module._JS)
        self.assertIn(
            "Number.isFinite(Number(data.takt)) && Number(data.takt) > 0",
            board_module._JS,
        )
        self.assertIn("if (pitch.id && hasTakt && !isReadableMode) stack.classList.add('takt-scale')", board_module._JS)
        self.assertIn("drawTaktLine(north, 'north')", board_module._JS)

    def test_readable_mode_expands_work_elements_and_hides_takt_line(self) -> None:
        self.assertIn("let isReadableMode = String(data.scale_mode || 'to_scale') === 'readable'", board_module._JS)
        self.assertIn("board.classList.toggle('readable-mode', isReadableMode)", board_module._JS)
        self.assertIn("if (!hasTakt || isReadableMode) return", board_module._JS)
        self.assertIn(".board.readable-mode .element", board_module._CSS)
        self.assertIn(".board.readable-mode .element-description", board_module._CSS)
        self.assertIn('id="scale-notice"', board_module._HTML)
        self.assertIn("drawTaktLine(south, 'south')", board_module._JS)
        self.assertIn("lane.scrollWidth - 4", board_module._JS)
        self.assertIn("Math.max(0, displayTime(item.time_s)", board_module._JS)
        self.assertNotIn("Math.max(34, displayTime(item.time_s)", board_module._JS)
        self.assertIn(".variants { display:flex; align-items:stretch; gap:6px; overflow:visible; }", board_module._CSS)
        self.assertNotIn(".variants { display:flex; align-items:flex-start; gap:6px; overflow-x:auto; }", board_module._CSS)
        self.assertIn("const equalizePitchFrames = () =>", board_module._JS)
        self.assertIn("equalizePitchFrames()", board_module._JS)
        self.assertIn("for (const element of allStacks) element.style.minHeight = `${maxStackHeight}px`", board_module._JS)
        self.assertIn("element.style.minHeight = `${maxPitchHeight}px`", board_module._JS)

    def test_unassigned_and_invalid_takt_do_not_receive_a_takt_line(self) -> None:
        self.assertIn("if (!hasTakt || isReadableMode) return", board_module._JS)
        self.assertIn("if (pitch.id && hasTakt && !isReadableMode)", board_module._JS)
        self.assertNotIn("drawTaktLine(unassigned", board_module._JS)
        self.assertIn(": 34", board_module._JS)

    def test_nullable_link_fields_are_strict_json_at_component_boundary(self) -> None:
        with patch.object(
            board_module, "_YAMAZUMI_BOARD", return_value=object()
        ) as mounted_component:
            board_module.yamazumi_board(
                [{"id": "pitch-1", "assignment_id": float("nan")}],
                [
                    {
                        "id": "element-1",
                        "assignment_id": float("nan"),
                        "process_element_id": float("nan"),
                    }
                ],
                ["Base"],
                float("nan"),
                time_unit="minutes",
                takt_time_unit="hours",
                key="yamazumi-test",
                on_move=lambda: None,
                on_add_pitch=lambda: None,
                on_add_element=lambda: None,
                on_edit_pitch=lambda: None,
                on_edit_element=lambda: None,
            )

        payload = mounted_component.call_args.kwargs["data"]
        self.assertIsNone(payload["pitches"][0]["assignment_id"])
        self.assertIsNone(payload["elements"][0]["assignment_id"])
        self.assertIsNone(payload["elements"][0]["process_element_id"])
        self.assertEqual(payload["takt"], 0.0)
        self.assertEqual(payload["time_unit"], "minutes")
        self.assertEqual(payload["seconds_per_unit"], 60.0)
        self.assertEqual(payload["time_decimals"], 3)
        self.assertEqual(payload["time_suffix"], "min")
        self.assertEqual(payload["takt_time_unit"], "hours")
        self.assertEqual(payload["takt_seconds_per_unit"], 3600.0)
        self.assertEqual(payload["takt_decimals"], 4)
        self.assertEqual(payload["takt_suffix"], "hr")
        self.assertTrue(payload["show_unassigned"])
        encoded = json.dumps(payload, allow_nan=False)
        self.assertNotIn("NaN", encoded)

    def test_payload_hides_and_shows_unassigned_from_current_elements(self) -> None:
        callbacks = {
            "on_move": lambda: None,
            "on_add_pitch": lambda: None,
            "on_add_element": lambda: None,
            "on_edit_pitch": lambda: None,
            "on_edit_element": lambda: None,
        }
        with patch.object(board_module, "_YAMAZUMI_BOARD", return_value=object()) as mount:
            board_module.yamazumi_board(
                [], [{"id": "assigned", "pitch_id": "pitch-1"}], ["Base"], 60,
                time_unit="seconds", takt_time_unit="seconds",
                key="assigned-only", **callbacks,
            )
            self.assertFalse(mount.call_args.kwargs["data"]["show_unassigned"])
            board_module.yamazumi_board(
                [],
                [
                    {"id": "assigned", "pitch_id": "pitch-1"},
                    {"id": "unassigned-one", "pitch_id": None},
                    {"id": "unassigned-two", "pitch_id": None},
                ],
                ["Base"],
                60,
                time_unit="seconds",
                takt_time_unit="seconds",
                key="with-unassigned",
                **callbacks,
            )
            self.assertTrue(mount.call_args.kwargs["data"]["show_unassigned"])

    def test_moved_element_variants_merge_into_destination_pitch_variants(self) -> None:
        pitches = [
            {
                "id": "pitch-1",
                "area_id": "area-1",
                "pitch_number": "01-PED-001",
                "pitch_name": "Station 1",
                "status": "Active",
                "model_variants": ["All models"],
            }
        ]
        elements = [
            {
                "id": "el-1",
                "pitch_id": "pitch-1",
                "model_variant": "Pedestal / Riser = Riser",
                "model_variants": ["Pedestal / Riser = Riser"],
            }
        ]
        merged = board_module.merge_yamazumi_pitch_variants(pitches, elements)
        self.assertEqual(
            merged[0]["model_variants"],
            ["All models", "Pedestal / Riser = Riser"],
        )
        annotated, _ = board_module.build_yamazumi_pitch_pairs(pitches, elements)
        self.assertEqual(
            annotated[0]["model_variants"],
            ["All models", "Pedestal / Riser = Riser"],
        )
        self.assertEqual(annotated[0]["pair_width_px"], 348)
        self.assertIn("Object.keys(grouped[pitch.id] || {})", board_module._JS)


if __name__ == "__main__":
    unittest.main()
