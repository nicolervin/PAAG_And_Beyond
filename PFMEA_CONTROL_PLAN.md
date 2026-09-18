# PFMEA and Control Plan planning

_Project-owner-reviewed methodology and data-mapping plan. Nicole Ervin approved the Phase 2 PFMEA schema and editable module on August 31, 2026, the workbook-aligned flat presentation on September 1, 2026, and the scenario-specific Manufacturing Control Plan working draft on September 8, 2026._

## Purpose

Define how Process at a Glance supports a traditional AIAG-format Process FMEA (PFMEA) with collaborator-authored controls and how the implemented AIAG-format Control Plan working draft derives from classified PFMEA rows and explicitly selected, published Quality requirements.

Phase 2 PFMEA and the Phase 3 Control Plan body-table working draft are implemented. Issued document headers, revisions, approvals, and Word export remain deferred.

## Standard and format

The implemented PFMEA editor and its normal filtered export follow the 19-column body structure of the project-owner-provided `FRM-GEA-QYS-033 PFMEA Template.xlsx`. Retained Legacy Classification evidence remains stored for historical continuity but is hidden from the editor and normal export:

- Item #
- Process Function
- Potential Failure Mode
- Potential Effect(s) of Failure
- Severity
- Classification
- Potential Causes(s) of Failure
- Occurrence
- Current Process Controls - Prevention
- Current Process Controls - Detection
- Detection
- Risk Priority Number (RPN)
- Recommended Action(s)
- Responsibility and Target Completion Date
- Actions Taken
- Resulting Severity, Occurrence, Detection, and RPN

The working-draft Control Plan follows the standard AIAG Control Plan body-column structure:

- Process Step/Operation Description
- Machine, Device, Jig, and Tools
- Characteristics - Product
- Characteristics - Process
- Special Characteristic Classification
- Methods - Product/Process Specification and Tolerance
- Evaluation/Measurement Technique
- Sample Size
- Sample Frequency
- Control Method
- Reaction Plan

The flat editor is a presentation and editing projection over the existing normalized Effect, Cause, Control, risk-row, and Action records; it does not collapse or replace their one-to-many relationships. Item # displays the current Pitch, while Process Function/Requirements displays the live derived Op ID followed by the Work Element label using the same Yamazumi-description-with-operation-fallback lookup as Process at a Glance; `work_elements.id` remains the hidden stable relationship. Complete selector choices follow Fishbone traversal, Yamazumi Pitch sequence, and centerline-outward element sequence, with incomplete Op IDs remaining selectable afterward. Multiple Effects, Causes, controls, or Actions appear as repeated flat lines as required.

The editor retains native spreadsheet copy/paste for ordinary editable cells and rows. Prevention and Detection appear as read-only friendly tags in the grid and are edited through the visible selected-Cause panel immediately above it. That panel provides session-only **Copy Prevention**, **Copy Detection**, **Copy both**, and **Paste to selected Cause** actions. Compatible controls replace the chosen lists without a dialog and propagate to repeated flat lines backed by the same Cause. Incompatible step-specific Quality controls require explicit compatible-only confirmation; inactive or unavailable manual sources are omitted with an inline warning. Item #, derived RPN values, structured control tags, and hidden identifiers remain read-only in the grid and never accept pasted values. The governed **Duplicate selected PFMEA line** workflow remains the authoritative way to copy a complete line with applicable structured controls: it stages one independent draft, keeps only applicable same-step Quality references and active manual options, clears completion evidence and resulting ratings, and creates fresh normalized IDs at Save & Refresh without retaining source-line lineage. A later draft Process Function change confirms and removes step-specific Quality controls instead of copying or remapping their assignments; active manual controls and the Detection rating remain for review.

The project-wide **PFMEA patterns** catalog accelerates deliberate entry without turning engineering judgment into automatic data. A reviewed pattern stores one normalized Failure Mode graph with ordered Effects, Causes, recommended Actions, an optional Classification suggestion, and Cause-level Prevention/Detection suggestions. It never stores Severity, Occurrence, Detection, RPN, Responsibility, Target Completion Date, Actions Taken, or resulting values. **Save selected PFMEA line as pattern** captures only those approved reusable fields from one saved graph. Pattern management is audited in the existing PFMEA History group, and pattern deletion affects only the catalog—not PFMEA rows already created from it.

**Add PFMEA lines** accepts one or more Process Functions in live Op ID order and lets the collaborator choose a blank line or active pattern for each. The preview derives Item # and Process Function context and discloses unavailable sources before anything is staged. A Quality-definition suggestion becomes a structured control only when that definition already has a published assignment for the target scenario and exact `work_elements.id`; the workflow never creates or remaps an assignment. Active correct-catalog manual suggestions remain eligible. Accepting the preview creates fresh session-only graph identities and leaves every rating and completion field blank. Existing **Undo** discards the staged graphs and the ordinary atomic **Save & Refresh** is the only persistence path. No pattern lineage is stored on the generated PFMEA graph.

The **PFMEA completion assistant** is a read-only advisory view over saved and unsaved lines. It identifies missing Failure Mode, Effect, Cause, ratings, Classification, Prevention/Detection controls, and Recommended Action and can focus the next incomplete flat line without deleting filter-hidden draft rows. It stores no completion status, writes no audit event, and never prevents an incomplete row from saving; Process Function remains the only required field.

This document intentionally does **not** define company-specific Severity, Occurrence, or Detection scale meanings, thresholds, or scoring guidance. The editor restricts each rating input to a whole-number selection from 1 through 10 without explaining what a score means. RPN remains only `Severity x Occurrence x Detection`.

## Connections

The implemented PFMEA and Control Plan working-draft layers enter the existing critical thread after Process at a Glance and Quality requirements:

```text
PITS / BOM evidence
    -> Parts Catalog
    -> Fishbone framework and Fishbone uses
    -> scenario-specific Yamazumi
    -> scenario-specific Process at a Glance
    -> project-wide Quality requirements
       -> scenario-specific published assignments to Process steps
       -> scenario-specific PFMEA
       -> scenario-specific Control Plan working draft
```

PFMEA records link to the stable `work_elements.id` of a Process at a Glance step. Cause-level Prevention and Detection controls are explicit structured selections from the step's published `quality_requirement_assignments` or separate project-wide manual catalogs. No source is auto-classified, and the same published assignment may be deliberately selected once in each control list.

This layer must not rewrite, rebalance, reassign, or silently reinterpret Fishbone, Yamazumi, Process at a Glance, or Quality decisions. Imported or derived evidence may prefill a proposed PFMEA value, but it must never silently replace a collaborator-reviewed planning decision. The existing invariant remains controlling: **Imported evidence must never silently replace collaborator-reviewed planning decisions.**

## Scope

**Implemented PFMEA scope: Scenario-specific.** A PFMEA evaluates the process defined by scenario-owned `work_elements`, including the current sequence, Pitch, work description, and tools. Switching or cloning a planning scenario may produce a different process and therefore a different PFMEA. PFMEA queries and writes validate both `project_id` and `scenario_id`; project ID alone is insufficient.

**Implemented Control Plan working-draft scope: Scenario-specific through its source PFMEA.** The draft derives from classified PFMEA rows for one project and scenario. It is not an independently scoped project-wide document and never combines rows from different scenarios.

Project-wide `quality_requirements` remain reusable reference definitions, and their scenario-specific published copies remain on `quality_requirement_assignments`. They appear only as eligible row-specific PFMEA control sources after a collaborator links them to that Process step; selecting and classifying them remains explicit. Explicitly selected published assignments now supply Quality-backed lines in the Control Plan working draft. Issued-document use remains subject to later approval and revision rules.

Nicole Ervin approved PFMEA and working-draft Control Plan scenario cloning. Issued revisions and approval behavior remain future decisions.

## Data source mapping - PFMEA

The following mapping distinguishes fields already available, values that can be derived, and information that has no current persisted home.

| Traditional AIAG PFMEA field | Proposed source or derivation | Current availability | Future storage need |
| --- | --- | --- | --- |
| Process Function/Requirements | The current derived **Op ID** followed by the Process at a Glance **Work Element** label: linked `yamazumi_elements.description` when present, otherwise `work_elements.operation`; Item # separately displays current `work_elements.station` as Pitch | The hidden relationship and reviewed Process values are available on the scenario-specific Process step and snapshotted in `pfmea_entries`; Op ID remains live and non-persisted | Active Phase 2 snapshots remain unchanged until the explicit source-review action accepts current upstream values; Op ID display changes do not re-key PFMEA |
| Potential Failure Mode | Collaborator-authored failure mode associated with a Process step | Implemented in `pfmea_entries.potential_failure_mode` | Active Phase 2 storage |
| Potential Effect(s) of Failure | Collaborator-authored effect associated with a failure mode | Implemented as multiple `pfmea_effects` child rows | Active Phase 2 storage |
| Severity | Numeric rating entered for each Effect | Implemented in `pfmea_effects.severity`; no company scale is embedded | Active Phase 2 storage; scoring guidance remains open |
| Classification | Explicit PFMEA classification | `pfmea_entries.class_code` stores blank or `S`, `R`, `E`, `P`, `P-`, `Q`, `E-`, `M`, `PM`; the UI shows their approved meanings. `legacy_class_code` retains retired Critical Quality evidence. Safety/Product Safety migrate to `S`; Critical Quality migrates to legacy-plus-blank with one project-scoped editor-attributed audit event. | Active Phase 2 storage; no Yamazumi flag is inferred |
| Potential Cause(s)/Mechanism(s) of Failure | Collaborator-authored cause associated with a failure mode | Implemented as multiple `pfmea_causes` child rows | Active Phase 2 storage |
| Occurrence | Numeric rating entered for each Cause | Implemented in `pfmea_causes.occurrence`; no company scale is embedded | Active Phase 2 storage; scoring guidance remains open |
| Current Process Controls - Prevention | Explicit Cause-level selections from applicable published Quality assignments or the project Prevention catalog | Implemented in `pfmea_prevention_selections`; the grid shows read-only friendly tags, while the selected-Cause panel above it provides editing and validated session-only copy/paste | Active structured storage; Quality Type does not infer classification |
| Current Process Controls - Detection | Explicit Cause-level selections from applicable published Quality assignments or the project Detection catalog | Implemented in `pfmea_detection_selections`; the grid shows read-only friendly tags, while the selected-Cause panel above it provides editing and validated session-only copy/paste | Active structured storage with retained source identity used by the Control Plan working draft |
| Detection | Optional numeric rating associated with a Cause | Implemented in `pfmea_causes.detection`; it may exist without a selected Detection source. Detection-source changes set `detection_review_required`, while the rating itself is never changed automatically. | Active Phase 2 storage; scoring guidance remains open |
| RPN | Derived as initial Severity x Occurrence x Detection | Implemented for each flat Effect-Cause line | **Recalculate RPN** refreshes the unsaved display without saving; **Save & Refresh** recalculates and persists `pfmea_risk_rows.rpn` |
| Recommended Action(s) | Collaborator-authored response to the evaluated risk | Implemented as multiple `pfmea_actions` child rows | Active Phase 2 storage |
| Responsibility and Target Completion Date | Assigned collaborator/role and target date for each recommended action | Implemented in `pfmea_actions` | Active Phase 2 storage; role ownership remains open |
| Actions Taken | Completed action description | Implemented in `pfmea_actions.actions_taken` | Active Phase 2 storage |
| Resulting Severity | Post-action numeric Severity rating | Implemented in `pfmea_actions.resulting_severity` | Active Phase 2 storage |
| Resulting Occurrence | Post-action numeric Occurrence rating | Implemented in `pfmea_actions.resulting_occurrence` | Active Phase 2 storage |
| Resulting Detection | Post-action numeric Detection rating | Implemented in `pfmea_actions.resulting_detection` | Active Phase 2 storage |
| Resulting RPN | Derived from resulting Severity x resulting Occurrence x resulting Detection | Implemented when all three resulting ratings exist | **Recalculate RPN** refreshes the unsaved display without saving; **Save & Refresh** recalculates and persists `pfmea_actions.resulting_rpn` |

### Existing Quality content used by the Control Plan working draft

For a linked Process step, the working draft uses the published fields on `quality_requirement_assignments` only when that assignment is explicitly selected as a PFMEA Prevention control, Detection control, or both:

- `requirement_type`
- `description`
- `unique_identifier`
- `pass_fail`
- `target_value`
- `tolerances`
- `unit`

These values are displayed live and are not replaced by unpushed repository edits. Torque-only Tool type, Tool orientation, and Screw bit type are appended to Measurement / Evaluation context. They remain supporting evidence rather than automatically authored Control method text.

### Special Characteristic assessment

`pfmea_entries.class_code` is the reviewed, persisted PFMEA and Control Plan Classification source. Yamazumi no longer stores or edits flags. For downstream read-only Process context, Nicole Ervin approved these PFMEA codes as CTQ-equivalent: `E`, `P`, `P-`, `Q`, and `E-`. A linked Process step displays **CTQ** when at least one PFMEA entry carries one of those codes. **Safety** is separate and derives from an active scenario-specific `safety_requirements` row linked to the same `work_elements.id`.

These tags are calculated live for Process at a Glance and Yamazumi presentation. They do not alter PFMEA Classification, create a Control Plan item, or persist a flag on `work_elements` or `yamazumi_elements`.

## Storage

Nicole Ervin approved the base Phase 2 schema on August 31, 2026, the structured Cause-level control-selection extension on September 2, 2026, and the scenario-specific `control_plan_items` working-draft table on September 8, 2026. The active `pfmea_*` and `control_plan_items` tables are authoritative in `DATA_DICTIONARY.md`. No scoring table, PFMEA approval lifecycle, issued-document table, or issued-revision table is approved by this implementation.

The Phase 2 persistence represents the following analysis records; document approval and issued-revision storage remain future decisions:

- one or more failure modes associated with a stable Process at a Glance `work_elements.id`;
- effects, causes, initial S/O/D ratings, the restricted Classification value, and ordered structured Prevention/Detection source selections;
- explicit Quality-assignment references or project-wide manual-option references, with no automatic classification;
- recommended actions, responsibility, target date, completion evidence, and Actions Taken;
- resulting S/O/D ratings and the corresponding derived RPN;
- persisted initial and resulting RPN values for historical save evidence.

Future decisions and storage may still be required for:

- a PFMEA document/header with status, revision/version identity, and approval state;
- immutable issued revisions sufficient to reproduce an approved PFMEA and issued Control Plan.

The implementation uses stable string UUIDs, explicit project/scenario boundary validation, and separate Effect, Cause, Prevention-selection, Detection-selection, risk-calculation, and Action child records. Project-wide manual catalogs use case-insensitively unique Labels and Active state. The main table flattens normalized records for workbook-aligned display, while a selected-Cause panel provides row-specific multiselects and hidden IDs preserve source identity and order.

On the first PFMEA opening for a project that still contains legacy `pfmea_controls`, a nonblank Current editor is required. Those legacy rows and their text are atomically discarded; one project-scoped audit event records only removed-row and affected-Cause counts. Quality requirements and assignments remain unchanged, and the obsolete table is dropped after all projects are migrated.

## Data source mapping - Control Plan

The working draft is projected from **classified PFMEA entries**. It retains hidden traceability to its PFMEA entry, Process step, and applicable published Quality assignment. Opening the tab writes nothing; a stored `control_plan_items` row is created when the collaborator saves MCP-owned fields, source acknowledgement, or exclusion state.

| Standard AIAG Control Plan field | Proposed source | Current availability | Future storage or decision |
| --- | --- | --- | --- |
| Pr. Nº | Collaborator-curated scenario-specific number synchronized across every characteristic line sharing one hidden `work_elements.id` | Implemented as nullable `control_plan_items.pr_number`, displayed to one decimal place on the first currently visible operation line | It is document display data only and never controls order, grouping, relationships, or the deferred Process Flow Map |
| Characteristic number | Curated Process number plus a manual positive whole-number suffix override or the lowest available automatic suffix | Implemented through nullable `control_plan_items.characteristic_suffix`; `.9` is followed by `.10`, and a non-whole base can display as `97.5.1` | Suffixes change labels only; `sequence` remains authoritative for characteristic order |
| Station / Pitch | Current `work_elements.station` resolved through the hidden Process-step relationship | Implemented read-only on every characteristic line; blank displays as Unassigned | A difference from the PFMEA Pitch snapshot raises the existing source-review flag without changing either source |
| Op ID | Current live Op ID resolved through hidden `work_elements.id` | Implemented as a pinned read-only value repeated on every characteristic line and included in filtered export | Supplies full within-Pitch position and active operation order without becoming stored Control Plan identity |
| Process Step/Operation Description | PFMEA Process Function snapshot | Implemented read-only as Operation | Issued snapshot remains deferred |
| Machine, Device, Jig, and Tools | Collaborator-authored MCP field | Implemented as Machine / fixture | Equipment catalog relationship remains deferred |
| Characteristics - Product | Published Quality Description or PFMEA fallback, after explicit placement | Stored placement remains `Product / Part`; the **Characteristic type** editor displays it as Product | Blank type remains visibly incomplete |
| Characteristics - Process | Published Quality Description or PFMEA fallback, after explicit placement | Implemented as Process characteristic | Blank placement remains visibly incomplete |
| Special Characteristic Classification | Current PFMEA short code | Implemented read-only as CL with nine-code legend | Issued snapshot remains deferred |
| Product/Process Specification and Tolerance | Published assignment Target value, Tolerances, and Unit | Implemented read-only | Unpushed repository edits remain invisible |
| Evaluation/Measurement Technique | Published Quality Type plus current Torque tool details when applicable | Implemented as supporting read-only context | Final collaborator-authored method remains separate |
| Sample Size | Collaborator-authored MCP field | Implemented | No value is inferred |
| Sample Frequency | Collaborator-authored MCP field | Implemented | No value is inferred |
| Control Method | Collaborator-authored MCP field with PFMEA controls shown as evidence | Implemented | Evidence is never silently promoted to final text |
| Reaction Plan | Collaborator-authored Decision rule / corrective action and reference documents, with PFMEA Actions shown as evidence | Implemented working-draft field | Issued disposition remains deferred |

### PFMEA action flow into the Control Plan

Recommended Actions must not flow into a released Control Plan merely because they were entered. The proposed sequence is:

1. A PFMEA row identifies risk and records recommended action(s).
2. Responsibility and Target Completion Date are assigned.
3. The completed response is recorded in Actions Taken.
4. Resulting Severity, Occurrence, and Detection are reviewed and approved; resulting RPN is calculated.
5. The approved action disposition identifies what becomes a standing **Control Method**, what becomes a **Reaction Plan**, what changes the specification or evaluation technique, and what does not belong in the Control Plan.
6. Control Plan generation uses only those approved dispositions and the approved PFMEA row values.

This avoids treating every recommendation as an operational control. A recommended mistake-proofing change may become a Prevention control and Control Method; a containment or escalation response may become a Reaction Plan; an action that only completes a design change may affect neither field. That disposition requires explicit collaborator review and cannot be inferred safely from free text.

The current Control Plan working draft persists only its approved MCP-owned fields, synchronized Process number, optional Characteristic suffix override, and source acknowledgement. New operations receive non-persistent Process-number suggestions in PFMEA Process order; suggestions become stored only through **Save & Refresh**. The pinned read-only Op ID repeats the full live identifier on every line and exposes the same physical Process order used by the PFMEA selector and Control Plan projection. When saved numbers no longer match that order, **Renumber Pr. Nº by Op ID** stages `1.0`, `2.0`, `3.0`, and so forth across all active qualifying operations, including filter-hidden lines. The action preserves manual suffixes and unrelated draft edits; Undo discards it, and Save & Refresh persists it atomically with one editor-attributed event containing the operation count. Excluded and source-ineligible retained items remain unchanged. Automatic suffixes reserve manual values and fill the lowest available positive whole numbers in stable characteristic order. Suffixes are appended text segments, so `.9` is followed by `.10`; changing the Process number rebuilds the label while preserving the suffix, and the existing characteristic `sequence` remains authoritative for line order. Duplicate numbers across different operations and duplicate manual suffixes within one operation require an explicit **Save anyway** confirmation but do not alter relationships. Lines are grouped by hidden Process-step identity; because Streamlit does not support merged cells, repeated Process number and Operation values—and identical repeated Machine / fixture values—are blanked only in rendered/exported copies. The read-only Station / Pitch column repeats the current Process at a Glance Pitch on every characteristic line; a mismatch with the PFMEA Pitch snapshot remains visibly flagged for source review. Derived PFMEA and published Quality evidence remains read-only; issued-document authoring and immutable revision behavior remain open project-owner decisions.

## Approval and generation boundaries

- Draft PFMEA Process Function content may be prefilled from Process at a Glance. Prevention and Detection controls remain explicit structured collaborator selections; published Quality assignments are referenced, not duplicated or silently classified.
- Prefill is proposed evidence, not approval.
- Only approved PFMEA rows may generate a released Control Plan.
- Repository Quality changes affect PFMEA input only after the existing explicit push updates the published assignment and a collaborator reviews the PFMEA impact.
- A Process-step rebalance that preserves `work_elements.id` preserves the relationship, but an issued PFMEA or Control Plan must follow the approved revision policy rather than silently changing its displayed Pitch or Seq.
- Control Plan generation must report incomplete required fields instead of inventing Sample Size, Sample Frequency, Control Method, Reaction Plan, ratings, or classifications.
- Regeneration must be explicit, validated as a complete operation, and auditable. It must not silently overwrite a previously issued output.

## Open questions for project-owner decision

1. What company-specific definitions, scales, and guidance govern initial and resulting Severity, Occurrence, and Detection ratings?
2. What rating thresholds or rules, if any, require action, special escalation, or prevent approval? Is RPN alone sufficient, or are additional company rules required?
3. **Resolved for Phase 2:** PFMEA uses one entry per failure mode per Process step, so one step can have multiple failure modes.
4. **Resolved for Phase 2:** One failure mode can have multiple Effects and Causes. Each Effect has Severity; each Cause has Occurrence, Detection, and its own collaborator-authored Prevention and Detection control text.
5. Must historical PFMEA revisions be preserved similarly to PITS source revisions, including immutable snapshots of the Process step and manually authored PFMEA controls used at approval time?
6. **Resolved for Phase 2:** Scenario cloning creates an independent editable PFMEA graph with new IDs, remapped Process and Quality-assignment links, reused project-wide manual options, preserved control order/review state, and source-entry lineage. No Draft/Approved lifecycle value is inferred.
7. Which PFMEA lifecycle states and approval transitions are required? No universal Draft/In review/Approved status model should be assumed without this decision.
8. Does Yamazumi CTQ or Safety propose a Special Characteristic value, automatically require review, or have no direct PFMEA mapping? Which symbols or Class values are company-approved?
9. **Resolved for current PFMEA authoring:** Prevention and Detection are separate Cause-level structured selections. Collaborators explicitly classify applicable published Quality assignments or choose the corresponding project-wide manual options; Quality Type never infers the classification.
10. **Resolved for the working draft:** the collaborator explicitly selects blank, Product / Part, or Process placement.
11. **Resolved for the working draft:** each PFMEA/applicable published Quality-definition combination produces one characteristic line; Prevention plus Detection use of the same assignment is deduplicated.
12. Which completed PFMEA actions become Control Method content, which become Reaction Plan content, and who approves that disposition?
13. **Partially resolved:** the Control Plan body is an editable in-app working draft. Issued/export snapshot behavior remains open.
14. Which collaborator role owns PFMEA authorship and approval, and which role owns Control Plan authorship and approval? Role ownership must be explicitly approved under `AGENTS.md`.
15. Are issued PFMEA and Control Plan records revision-controlled together, or may a Control Plan have a separate revision and approval lifecycle?
16. What Process events require PFMEA re-review beyond the implemented Work Element snapshot check: a Pitch or Seq move, tool change, Fishbone part change, or Yamazumi CTQ/Safety change? Selected Quality/catalog source changes already flag affected Causes without changing ratings.
17. What export formats and document header fields are required, including customer, part/process identity, model year/program, core team, key dates, and document/revision identifiers?

## Phased build recommendation

Each phase should be a separately scoped, owner-approved task. Completion of this planning document does not commit the project to build any phase.

### Phase 0 - Owner decisions and proposal approval

**Goal:** Resolve the open questions that control record grain, scope, ratings, ownership, revision history, and output behavior.

- Approve the company-specific S/O/D rating references separately from this methodology.
- Decide failure-mode/effect/cause/action multiplicity.
- Confirm scenario cloning and revision rules.
- Confirm collaborator roles and approval authority.
- **Resolved for the working draft:** provide an in-app governed body-table view; issued export remains deferred.
- Update the `DATA_DICTIONARY.md` Proposed modules section before schema work.

### Phase 1 - Schema and data model

**Goal:** Add only the approved scenario-specific PFMEA persistence and traceability model.

- Store stable links to `work_elements` and retain explicit Cause-level source identity for selected published Quality assignments or manual catalog options.
- Add the approved failure mode, effect, cause, rating, class, control, action, responsibility, target-date, completion, and resulting-rating structure.
- Define document/revision snapshots and scenario-cloning behavior.
- Add store-layer validation, project/scenario boundaries, audit requirements, and focused tests.
- Do not add Control Plan authoring in this phase.

**Status: Implemented as the approved scenario-specific PFMEA model on August 31, 2026, with structured control catalogs/selections approved and implemented September 2, 2026.**

### Phase 2 - PFMEA editable module

**Goal:** Provide the governed traditional AIAG PFMEA workflow over the approved schema.

- Prefill Process Function/Requirements from Process at a Glance and provide direct multiline entry for Prevention and Detection controls.
- Support the approved failure-mode/effect/cause grain and S/O/D workflow.
- Follow all applicable `DESIGN_SYSTEM.md` standards, including scope badge, stable hidden IDs, relationship-safe deletion, Save & Refresh, Undo, audit logging, and bottom History.
- Surface upstream changes for review without silently replacing approved PFMEA decisions.

**Status: Implemented in the Quality page on August 31, 2026, with the workbook presentation corrected September 1, structured Cause-level controls implemented September 2, governed PFMEA line/control copying implemented September 3, the short-code Classification model implemented September 8, live Op ID Process Function context implemented September 11, and panel-based structured-control editing implemented September 14, 2026.** Item # uses the current Pitch and Process Function displays `Op ID — Work Element` while retaining hidden `work_elements.id` as the relationship. The workbook-aligned grid shows friendly read-only control tags. The visible selected-Cause panel above the grid stages applicable published Quality assignments and project-wide manual options, and its explicit session-only copy/paste actions use a non-dismissible compatible-only confirmation when Quality sources belong to another Process Function. Native clipboard entry remains available for ordinary editable values, while deliberate line duplication creates fresh normalized records, omits completion evidence, and safely retains only applicable structured controls. Live source changes and cascaded removals are review-flagged without changing Detection. Legacy free-text rows are discarded once with editor-attributed count-only evidence while Quality assignments remain intact. RPN, high-risk, Process-source review, and scenario-cloning behavior remain as documented; no scoring scale or approval lifecycle is added.

### Phase 3 - Control Plan working draft

**Goal:** Derive and edit the standard AIAG Control Plan body fields from classified PFMEA rows.

- Generate one row at the approved characteristic/process grain.
- Combine approved PFMEA content with the explicitly selected structured Quality-assignment sources and any other separately reviewed published Quality assignment values.
- Require explicit Product / Part or Process placement before a characteristic is complete; display the current PFMEA short Classification code as CL.
- Keep evaluation evidence derived and require collaborator-authored sample, frequency, Control Method, and Decision rule text.
- Trace every generated row back to its PFMEA row, Process step, and Quality assignment(s).
- Surface incomplete working-draft fields without inventing values; release validation remains deferred.

**Status: Working-draft body table implemented September 8, 2026, with collaborator-curated Process numbering and characteristic suffix overrides implemented September 9, 2026, and the interactive Phase 10 Process Flow Map implemented September 16, 2026.** The implementation derives qualifying lines and number suggestions without writing on view, persists MCP-owned fields, synchronized Process numbers, optional suffix overrides, and source acknowledgement, retains orphaned/source-ineligible content for review, supports confirmed exclusion/restore and explicit compatible relinking, and clones scenario data with fresh IDs. The read-only map shows all Process steps in live Op ID order, including plain operations without Control Plan characteristics; it uses Fishbone hierarchy for lanes and Yamazumi feeder relationships for exact joins. The audited legacy backfill preserves the former `process_sequence_snapshot.0` display before numbers become independently curated. Issued status, document headers, approvals, Word/print export, and structured reject routing are not implemented.

### Phase 4 - Export and issued revision handling

**Goal:** Produce reviewable, reproducible PFMEA and Control Plan outputs.

- Add the approved Excel and/or document export formats.
- Preserve flat, stable output columns required by downstream consumers.
- Include approved document header and revision metadata.
- Verify that an issued export can be reproduced from its saved revision/snapshot.
- Keep regeneration explicit and audit every issue/reissue action.

## Out of scope for this planning document

- Company-specific Severity, Occurrence, or Detection scales
- PFMEA or Control Plan approval workflow implementation
- PFMEA or Control Plan export implementation
- Work instructions
- Changes to Process at a Glance, Fishbone, Yamazumi, Pin Map, or PITS behavior
- Automatic AI generation of failure modes, effects, causes, ratings, actions, or classifications

## Review status

- **Requested by:** Nicole Ervin, project owner
- **Planning requested:** August 31, 2026
- **Implementation status:** Phase 1 schema/data model, Phase 2 editable PFMEA module, and Phase 3 MCP working-draft body implemented; working draft approved September 8, 2026
- **Next decision:** Separate project-owner review of scoring guidance, PFMEA/Control Plan approval lifecycles, issued document headers, and Word export
