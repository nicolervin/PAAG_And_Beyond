<!-- This document is reserved for module-specific guidance for the approved Quality requirements entry in DATA_DICTIONARY.md and does not supersede the authoritative data dictionary or design system. -->

## Purpose

The Quality page maintains the approved project-wide repository of reusable Quality requirements and manual PFMEA control options, plus the scenario-specific Process FMEA workflow. Contributors can deliberately publish repository updates to linked Process at a Glance requirements and explicitly select applicable published assignments or manual options as Cause-level PFMEA Prevention and Detection controls. Control Plan generation remains a future consumer and is not implemented.

## Connections

Repository definitions connect to scenario-specific Process at a Glance steps through `quality_requirement_assignments` and `work_elements.id`. PFMEA entries connect to the same stable Process step without changing upstream planning. Their Cause-level controls retain either the applicable published assignment identity or a project-wide manual-option identity, plus the acknowledged source version and collaborator-selected order. Nothing is auto-classified. Fishbone context remains inherited through the Process step rather than receiving a new direct relationship.

## Scope

Quality requirement definitions and manual Prevention/Detection option catalogs are project-wide. Process-step assignments, PFMEA records, and PFMEA control selections are scenario-specific, while a repository push can update assignments in more than one scenario within the selected project. The mixed-scope Quality page therefore displays the locked **Scenario-aware** boundary indicator; its PFMEA tab always uses the active scenario.

## Storage

`quality_requirements`, `quality_requirement_assignments`, and `quality_requirement_torque_details` retain their documented roles. PFMEA storage includes entries, Effects, Causes, RPN rows, Actions, two project-wide manual-option catalogs, and two scenario-specific structured selection tables. The workbook-aligned 19-column editor displays friendly control tags and supports native same-column Ctrl+C/Ctrl+V replacement between Prevention cells or between Detection cells. Compatible replacements stage silently and propagate to every displayed line backed by the same Cause; incompatible step-specific Quality sources require explicit compatible-only confirmation, and inactive or unavailable manual sources are omitted with an inline warning. The selected-Cause panel continues to provide row-specific multiselects and previewed control-list copying, while the shared footer saves PFMEA fields and selections atomically. Governed line duplication stages fresh PFMEA-owned records, clears completion evidence, retains only applicable same-step Quality references and active manual options, and never duplicates Quality definitions or assignments. A confirmed draft Process Function change removes incompatible Quality controls while preserving manual controls and the Detection rating for review. Source updates and cascaded removals mark Causes for review, and Detection-source changes preserve but flag the Detection rating. The first PFMEA opening with legacy `pfmea_controls` data requires Current editor, discards that text atomically, records counts without discarded text, and preserves Quality assignments. RPN and explicit repository publication behavior remain unchanged.

## Applicable standards

Follow the complete Shared Editable-Table Implementation Checklist in `DESIGN_SYSTEM.md`, including filtering, direct entry, stable hidden IDs, native row selection, relationship-safe confirmed deletion, meaningful bulk editing, filtered Excel export, **Undo**, and the footer **Save & Refresh** action. Every persisted save, bulk edit, deletion, source review, and push must use `record_audit_event()` with Editor attribution, affected rows, and the store timestamp when supplied. Keep one **History** expander at the bottom of the page with Requirements and PFMEA history tabs. Use canonical terminology and the traditional AIAG PFMEA field labels documented in `PFMEA_CONTROL_PLAN.md`.
