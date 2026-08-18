# Process at a Glance (PAAG) — Feature Roadmap & Spec

*Companion to AGENTS.md and PROJECT_STATUS.md. This document specifies planned enhancements to the Process at a Glance module (currently app_pages/process.py), in build order. Each numbered phase is intended to become its own scoped Codex task — do not implement multiple phases in a single session.*

---

## Phase 0 — Rename

**Goal:** Align naming across the app.

- Change navigation label from "Process plan" to "Process at a Glance" in streamlit_app.py.
- Update on-page headings/copy in app_pages/process.py that currently say "Process plan" to say "Process at a Glance."
- Display-only change. No schema, variable, or file rename.

**Status: Complete.**

**Interim section behavior:** The detail dialog can copy unit orientation and conveyor height to every existing Process at a Glance step tied to the same Fishbone section in the active scenario. This is a one-time fill, not the persistent section-level inheritance planned for Phase 3.

---

## Phase 1 — Data-entry UI redesign

**Goal:** Replace the current single wide flat table for per-step details with a friendlier entry pattern.

**Decision:** Option 1 selected — keep the main table for fast/compact editing of frequently changed fields (sequence, pitch, operation, time, status, model applicability). Move detailed per-step fields into a tabbed detail dialog opened via the existing Details button pattern.

**Dialog tabs:**
- Step details
- Tool
- Unit orientation and heights
- Parts and models
- Future equipment and sub-touches (placeholder until Phases 2 and 4 are built)

**Requirements:**
- Dialog has explicit Save and Cancel actions.
- Fields shown in the dialog are edited only there, not duplicated in the main table.
- Follows existing editable-table and dialog/state-reset conventions in AGENTS.md (unsaved-edit detection, editor reset after save, audit history).

**Status: Complete.**

---

## Phase 2 — Equipment / Resource catalog

**Goal:** Introduce a per-project catalog of tools and equipment, referenceable from process steps, with roll-up reporting.

**Data model — two record types under one catalog:**

*Off-the-shelf / mobile tools*
- Name/label
- Category (e.g., DC tool, hand tool, power tool — controlled list, extensible)
- Notes/spec (free text)
- No section binding required (mobile — can be used at multiple pitches)

*Fixed / custom equipment*
- Name/label
- Category (e.g., robot, flipper, fixture)
- Richer detail fields: specification notes, supplier/vendor (optional), custom-build notes
- Bound to a specific Fishbone main-spine section

**Scope rules:**
- One catalog per project (not shared/global) — each program may need a different mix.
- Simple reference/tag only — no consumption tracking, no availability warnings, no conflict checking.

**UI requirements:**
- New CRUD screen/tab for managing the catalog (follow existing editable-table standard: header, save/undo, bulk edit/delete, Excel export, history).
- A way to tag one or more catalog items onto a process step in Process at a Glance (e.g., multiselect referencing the catalog).
- A roll-up report view: count of equipment by type, filterable/groupable by Fishbone section (e.g., "3 DC tools on Subassembly Line 1, 15 total across project").

**Explicitly deferred:** conflict detection, quantity limits, cross-program equipment sharing.

---

## Phase 3 — Section-level physical line dimensions

**Goal:** Move conveyor geometry from per-step entry to per-Fishbone-main-spine-section entry, since it is physically consistent across a section in most cases. Platform height and pit depth belong in a future ergonomics workflow rather than this line-setup phase.

**Data model:**
- One record per Fishbone main-spine section, per scenario, holding: conveyor height (in), conveyor width (in), conveyor length (ft), and unit orientation.
- Process at a Glance steps display these values (inherited from their section) rather than requiring re-entry per step.

**Open design question to resolve at build time:** Should a step be allowed to override an inherited section value for an exceptional case? Recommendation: yes, allow an optional per-step override field that defaults to blank/inherited. Confirm with Nicole before implementing if this needs revisiting.

**UI requirements:**
- Add a section-level "Line setup" or "Equipment & layout" panel/tab where these values are entered once per section.
- Existing per-step conveyor-height values in Process at a Glance become read-only display (showing the inherited inch value) unless overridden.

---

## Phase 4 — Multi-touch ("sub-touch") support

**Goal:** Allow one Fishbone part-use to be broken into multiple independent line items ("sub-touches") in Process at a Glance, each separately assignable to a station/pitch and separately timed.

**Data model:**
- A sub-touch record links back to a parent Fishbone part-use (so the system knows N sub-touches collectively represent 1 unit of that part-use for BOM/consumption purposes).
- Each sub-touch has its own description (e.g., "plug 3 wires"), its own cycle time, and its own station/pitch assignment — independent of sibling sub-touches.
- Can (future, Phase 9 dependency) carry its own visual annotation reference.
- A part-use with no sub-touches behaves exactly as today (single line item) — sub-touches are optional.

**UI requirements:**
- From a paired part-use in Process at a Glance, allow the IE to "split into sub-touches" or "add a sub-touch," each becoming its own row in the plan, independently assignable to any pitch.
- Visible indicator grouping sub-touches back to their parent part (e.g., shared tag/label or expandable grouping), even when assigned to different stations.
- Reporting/exports should show both "by part" (rolled up) and "by step" (individual sub-touches) views.

**Explicitly out of scope for this phase:** visual annotation on individual sub-touches (Phase 9).

---

## Phase 5 — Conflict-flag detection & review workflow

**Goal:** Detect upstream changes (in Yamazumi or Fishbone/parts) that affect data already pulled into a Process at a Glance step, and surface a non-blocking flag for IE review — without any automatic reversion.

**Trigger scope:**
- Only fires for Yamazumi work elements or Fishbone parts that are already linked/paired into a Process at a Glance step.
- Changes to "floating" (unlinked) Yamazumi work or Fishbone parts generate no signal at all.

**Trigger conditions (confirm exact list at build time):**
- A linked Yamazumi work element's time changes
- A linked Yamazumi work element's pitch/station assignment changes
- A linked Yamazumi work element's assigned parts change
- A linked Fishbone part's name, image, or other referenced attribute changes

**Behavior when triggered:**
- Set a visible, non-blocking flag/badge on the affected row in both Process at a Glance and Yamazumi & balancing.
- No automatic reversion of the upstream change. No automatic Concern creation.
- IE reviews the flag and chooses one of two actions:
  1. Acknowledge / mark reviewed — simple dismiss button, clears the flag, no further record created.
  2. Raise as concern — creates a new record in the existing Questions & Concerns table (pre-filled where possible), then follows the standard Concerns workflow (owner, priority, status).

**Data model:**
- New lightweight table (e.g., paag_flags) recording: what changed, when, which Process at a Glance step/Yamazumi element it affects, and current flag status (open/acknowledged).
- Reuses existing Questions & Concerns table/schema for the "raise as concern" path.

---

## Phase 6 — Visual slide layout, Phase A (data + images, no annotation)

**Goal:** Build a per-pitch, widescreen "slide-style" view combining stored part images and text data, replacing manual PowerPoint copy-paste. Auto-updates when upstream approved data changes.

**Content per pitch "slide":**
- Text data already captured in Process at a Glance for that pitch (operation, description, cycle time, tool/equipment tags, quality/ergo requirements, location, dimensions inherited from section, model applicability, status)
- Part images already stored in the Parts catalog for parts used at that pitch (main CAD image at minimum)

**UI requirements:**
- A new view mode (separate screen or a mode within Process at a Glance) that renders one pitch at a time (or a selector to page through pitches) in a widescreen layout.
- Data shown must reflect current approved plan state — updates automatically as underlying data changes (and is approved/acknowledged per Phase 5). No manual copy/paste step.

**Explicitly out of scope for this phase:** manual annotation, PDF export, Yamazumi stack image capture.

---

## Phase 7 — PDF export of slide layout

**Goal:** Export the Phase 6 slide layout to a printable PDF, one page per selected pitch.

**Requirements:**
- User can select one or more pitches and export to PDF.
- Page/canvas size must be planned as printable from the start (e.g., standard slide/letter/A-size aspect ratio) since Phase 9 (annotation) will need to respect this same canvas size.
- One PDF page per pitch, matching the on-screen slide layout as closely as practical.

---

## Phase 8 — Yamazumi stack image integration

**Goal:** Pull the Yamazumi stack visualization for the relevant pitch into the slide layout as an image, alongside part images and text.

**Requirements:**
- Capture or render the Yamazumi stack visual (from utils/yamazumi_board.py) as a static image usable in the slide layout and PDF export.
- Auto-updates when the underlying Yamazumi data changes (subject to the same conflict-flag/approval awareness as Phase 5).

*Note: sequencing with Phase 6 may be adjustable — confirm with Codex at build time whether it's more efficient to build image capture once and use it in both phases together.*

---

## Phase 9 — Manual annotation layer

**Goal:** Allow the IE to add arrows, shapes, text boxes, and colors on top of part images and Yamazumi stack images within the slide layout, with persistence.

**Requirements:**
- Annotations are drawn on top of images (part photos, Yamazumi stack) within the fixed printable canvas size established in Phase 7.
- Annotations must be saved and persist — reappearing each time that pitch's slide is viewed, tied to that specific pitch (and likely scenario/revision).
- If the underlying image or data changes upstream, existing annotations tied to that image should be flagged as potentially needing manual review/update — reusing the Phase 5 flag mechanism rather than inventing a new one.
- Must remain within the printable canvas size so PDF export continues to work correctly with annotations included.

**Technical note:** This will be a Streamlit Components v2 custom component, similar in nature to the existing interactive Fishbone and Yamazumi board components already in the app.

---

## Deferred / pending separate decision (not part of this roadmap's build order)

**Torque and quality-owned requirement fields:**
- Torque, quality, and ergonomics entry has been removed from the IE-owned Process at a Glance detail dialog. Existing saved values are preserved and remain visible in the read-only Requirements view.
- Torque and other quality-owned specifications belong with Quality Engineers in a future editable Requirements workflow that can feed PFMEA/control-plan work.
- Platform height and pit depth belong in a future ergonomics workflow. Existing saved values are preserved until that workflow is designed.
- Status: the Process at a Glance removal is complete; ownership and editing design for the future Requirements and ergonomics workflows remains a separate phase.

---

## How to use this document with Codex

- Tackle one phase per session (or split a phase further if it still feels large once you're in it).
- Before implementing, always start a phase with a checkpoint commit.
- For phases with an "open design question" or anything ambiguous, have Codex ask before building, or bring it back to planning first — don't let it guess on anything not explicitly settled above.
- Update PROJECT_STATUS.md as each phase completes, and update this file if a phase's design changes during implementation.
