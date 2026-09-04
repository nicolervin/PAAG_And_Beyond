# PFMEA and Control Plan planning

_Project-owner-reviewed methodology and data-mapping plan. Nicole Ervin approved the Phase 2 PFMEA schema and editable module on August 31, 2026, and the workbook-aligned flat presentation on September 1, 2026. Control Plan methodology remains planning-only._

## Purpose

Define how Process at a Glance can support a traditional AIAG-format Process FMEA (PFMEA) with collaborator-authored controls, and how an AIAG-format Control Plan can later be generated from approved PFMEA rows and separately published Quality requirements.

Phase 2 PFMEA is implemented. This document remains the methodology and field-mapping authority for that implementation and the planning authority for the still-unimplemented Control Plan.

## Standard and format

The implemented PFMEA editor follows the 19-column body structure of the project-owner-provided `FRM-GEA-QYS-033 PFMEA Template.xlsx`:

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

The proposed Control Plan follows the standard AIAG Control Plan column structure:

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

The flat editor is a presentation and editing projection over the existing normalized Effect, Cause, Control, risk-row, and Action records; it does not collapse or replace their one-to-many relationships. Item # displays the saved Pitch, while Process Function/Requirements displays the saved Work Element label using the same Yamazumi-description-with-operation-fallback lookup as Process at a Glance; `work_elements.id` remains the hidden stable relationship. Multiple Effects, Causes, controls, or Actions appear as repeated flat lines as required.

The editor retains native spreadsheet copy/paste for ordinary editable cells and rows. Prevention and Detection multiselect cells additionally support native same-column Ctrl+C/Ctrl+V replacement while retaining hidden structured source identities and friendly displayed tags. Compatible controls stage without a dialog and propagate to repeated flat lines backed by the same Cause. Incompatible step-specific Quality controls require explicit compatible-only confirmation; inactive or unavailable manual sources are omitted with an inline warning. Item #, derived RPN values, and hidden identifiers remain read-only and never accept pasted values. The governed **Duplicate selected PFMEA line** workflow remains the authoritative way to copy a complete line with applicable structured controls: it stages one independent draft, keeps only applicable same-step Quality references and active manual options, clears completion evidence and resulting ratings, and creates fresh normalized IDs at Save & Refresh without retaining source-line lineage. A later draft Process Function change confirms and removes step-specific Quality controls instead of copying or remapping their assignments; active manual controls and the Detection rating remain for review. The selected-Cause panel also permits previewed replacement of Prevention, Detection, or both lists from another Cause.

This document intentionally does **not** define company-specific Severity, Occurrence, or Detection scale meanings, thresholds, or scoring guidance. The editor restricts each rating input to a whole-number selection from 1 through 10 without explaining what a score means. RPN remains only `Severity x Occurrence x Detection`.

## Connections

The implemented PFMEA layer and proposed future Control Plan layer enter the existing critical thread after Process at a Glance and Quality requirements:

```text
PITS / BOM evidence
    -> Parts Catalog
    -> Fishbone framework and Fishbone uses
    -> scenario-specific Yamazumi
    -> scenario-specific Process at a Glance
    -> project-wide Quality requirements
       -> scenario-specific published assignments to Process steps
       -> scenario-specific PFMEA
       -> Control Plan generated from approved PFMEA rows
```

PFMEA records link to the stable `work_elements.id` of a Process at a Glance step. Cause-level Prevention and Detection controls are explicit structured selections from the step's published `quality_requirement_assignments` or separate project-wide manual catalogs. No source is auto-classified, and the same published assignment may be deliberately selected once in each control list.

This layer must not rewrite, rebalance, reassign, or silently reinterpret Fishbone, Yamazumi, Process at a Glance, or Quality decisions. Imported or derived evidence may prefill a proposed PFMEA value, but it must never silently replace a collaborator-reviewed planning decision. The existing invariant remains controlling: **Imported evidence must never silently replace collaborator-reviewed planning decisions.**

## Scope

**Implemented PFMEA scope: Scenario-specific.** A PFMEA evaluates the process defined by scenario-owned `work_elements`, including the current sequence, Pitch, work description, and tools. Switching or cloning a planning scenario may produce a different process and therefore a different PFMEA. PFMEA queries and writes validate both `project_id` and `scenario_id`; project ID alone is insufficient.

**Proposed Control Plan scope: Scenario-specific through its source PFMEA.** A Control Plan is generated from approved PFMEA rows for one project and scenario. It is not an independently scoped project-wide document and must not combine rows from different scenarios.

Project-wide `quality_requirements` remain reusable reference definitions, and their scenario-specific published copies remain on `quality_requirement_assignments`. They appear only as eligible row-specific PFMEA control sources after a collaborator links them to that Process step; selecting and classifying them remains explicit. Their future Control Plan use remains subject to later implementation and review rules.

Nicole Ervin approved the PFMEA scope and scenario-cloning behavior for Phase 2. Control Plan scope, issued revisions, and approval behavior remain future decisions.

## Data source mapping - PFMEA

The following mapping distinguishes fields already available, values that can be derived, and information that has no current persisted home.

| Traditional AIAG PFMEA field | Proposed source or derivation | Current availability | Future storage need |
| --- | --- | --- | --- |
| Process Function/Requirements | The Process at a Glance **Work Element** label: linked `yamazumi_elements.description` when present, otherwise `work_elements.operation`; Item # separately displays `work_elements.station` as Pitch | Available on the scenario-specific Process at a Glance step and snapshotted in `pfmea_entries` | Active Phase 2 snapshots remain unchanged until the explicit source-review action accepts current upstream values |
| Potential Failure Mode | Collaborator-authored failure mode associated with a Process step | Implemented in `pfmea_entries.potential_failure_mode` | Active Phase 2 storage |
| Potential Effect(s) of Failure | Collaborator-authored effect associated with a failure mode | Implemented as multiple `pfmea_effects` child rows | Active Phase 2 storage |
| Severity | Numeric rating entered for each Effect | Implemented in `pfmea_effects.severity`; no company scale is embedded | Active Phase 2 storage; scoring guidance remains open |
| Classification | Explicit PFMEA classification | Implemented in `pfmea_entries.class_code` with approved choices blank, Safety, or Critical Quality | Active Phase 2 storage; no Yamazumi flag is inferred |
| Potential Cause(s)/Mechanism(s) of Failure | Collaborator-authored cause associated with a failure mode | Implemented as multiple `pfmea_causes` child rows | Active Phase 2 storage |
| Occurrence | Numeric rating entered for each Cause | Implemented in `pfmea_causes.occurrence`; no company scale is embedded | Active Phase 2 storage; scoring guidance remains open |
| Current Process Controls - Prevention | Explicit Cause-level selections from applicable published Quality assignments or the project Prevention catalog | Implemented in `pfmea_prevention_selections`; the table provides friendly editable tags with validated same-column clipboard replacement, and the selected-Cause panel remains available | Active structured storage; Quality Type does not infer classification |
| Current Process Controls - Detection | Explicit Cause-level selections from applicable published Quality assignments or the project Detection catalog | Implemented in `pfmea_detection_selections`; the table provides friendly editable tags with validated same-column clipboard replacement, and the selected-Cause panel remains available | Active structured storage with retained source identity for future Control Plan review |
| Detection | Optional numeric rating associated with a Cause | Implemented in `pfmea_causes.detection`; it may exist without a selected Detection source. Detection-source changes set `detection_review_required`, while the rating itself is never changed automatically. | Active Phase 2 storage; scoring guidance remains open |
| RPN | Derived as initial Severity x Occurrence x Detection | Implemented for each flat Effect-Cause line | **Recalculate RPN** refreshes the unsaved display without saving; **Save & Refresh** recalculates and persists `pfmea_risk_rows.rpn` |
| Recommended Action(s) | Collaborator-authored response to the evaluated risk | Implemented as multiple `pfmea_actions` child rows | Active Phase 2 storage |
| Responsibility and Target Completion Date | Assigned collaborator/role and target date for each recommended action | Implemented in `pfmea_actions` | Active Phase 2 storage; role ownership remains open |
| Actions Taken | Completed action description | Implemented in `pfmea_actions.actions_taken` | Active Phase 2 storage |
| Resulting Severity | Post-action numeric Severity rating | Implemented in `pfmea_actions.resulting_severity` | Active Phase 2 storage |
| Resulting Occurrence | Post-action numeric Occurrence rating | Implemented in `pfmea_actions.resulting_occurrence` | Active Phase 2 storage |
| Resulting Detection | Post-action numeric Detection rating | Implemented in `pfmea_actions.resulting_detection` | Active Phase 2 storage |
| Resulting RPN | Derived from resulting Severity x resulting Occurrence x resulting Detection | Implemented when all three resulting ratings exist | **Recalculate RPN** refreshes the unsaved display without saving; **Save & Refresh** recalculates and persists `pfmea_actions.resulting_rpn` |

### Existing Quality content for future Control Plan work

For a linked Process step, future Control Plan work may use the published fields on `quality_requirement_assignments`:

- `requirement_type`
- `description`
- `unique_identifier`
- `pass_fail`
- `target_value`
- `tolerances`
- `unit`

These values are displayed live when their published assignment is explicitly selected as a structured PFMEA control; they are not copied or auto-classified. Torque-only Tool type, Tool orientation, and Screw bit type remain project-wide repository details in `quality_requirement_torque_details` and may support future Control Plan work subject to an approved rule.

### Special Characteristic assessment

No existing field is an authoritative PFMEA or Control Plan Special Characteristic flag/classification.

Yamazumi supports project-wide flag definitions, including the protected CTQ and Safety names, while each `yamazumi_elements` row stores selected flag names as JSON text. A Yamazumi element can be soft-linked to a Process step through `yamazumi_elements.process_element_id`. This makes CTQ or Safety a possible **review signal**, but not a safe authoritative mapping, because:

- the flag is stored on Yamazumi work rather than on the Quality assignment or PFMEA record;
- the relationship to Process at a Glance is a soft link;
- a generic CTQ flag does not define the required PFMEA Class or Control Plan symbol/classification; and
- no approved rule says that every CTQ or Safety flag must become a special characteristic.

Therefore Special Characteristic classification requires a new reviewed, persisted field unless the project owner separately approves a precise mapping from Yamazumi flags. Any suggested value derived from CTQ or Safety must remain visibly proposed until a collaborator approves it.

## Storage

Nicole Ervin approved the base Phase 2 schema on August 31, 2026 and the structured Cause-level control-selection extension on September 2, 2026. The active `pfmea_*` tables are authoritative in `DATA_DICTIONARY.md`. No Control Plan table, scoring table, PFMEA approval lifecycle, or issued-revision table is approved by this implementation.

The Phase 2 persistence represents the following analysis records; document approval and issued-revision storage remain future decisions:

- one or more failure modes associated with a stable Process at a Glance `work_elements.id`;
- effects, causes, initial S/O/D ratings, the restricted Classification value, and ordered structured Prevention/Detection source selections;
- explicit Quality-assignment references or project-wide manual-option references, with no automatic classification;
- recommended actions, responsibility, target date, completion evidence, and Actions Taken;
- resulting S/O/D ratings and the corresponding derived RPN;
- persisted initial and resulting RPN values for historical save evidence.

Future decisions and storage may still be required for:

- a PFMEA document/header with status, revision/version identity, and approval state;
- immutable issued revisions sufficient to reproduce an approved PFMEA and generated Control Plan; and
- generated Control Plan rows or a reproducible generation snapshot.

The implementation uses stable string UUIDs, explicit project/scenario boundary validation, and separate Effect, Cause, Prevention-selection, Detection-selection, risk-calculation, and Action child records. Project-wide manual catalogs use case-insensitively unique Labels and Active state. The main table flattens normalized records for workbook-aligned display, while a selected-Cause panel provides row-specific multiselects and hidden IDs preserve source identity and order.

On the first PFMEA opening for a project that still contains legacy `pfmea_controls`, a nonblank Current editor is required. Those legacy rows and their text are atomically discarded; one project-scoped audit event records only removed-row and affected-Cause counts. Quality requirements and assignments remain unchanged, and the obsolete table is dropped after all projects are migrated.

## Data source mapping - Control Plan

The Control Plan is generated from **approved PFMEA rows**. It is not independently authored in parallel with the PFMEA. A generated row must retain traceability to its source PFMEA record, failure mode, Process step, and applicable published Quality assignment(s).

| Standard AIAG Control Plan field | Proposed source | Current availability | Future storage or decision |
| --- | --- | --- | --- |
| Process Step/Operation Description | Approved PFMEA Process Function/Requirements, originally sourced from the linked `work_elements` row | Process step source exists | Use the approved PFMEA value/snapshot so later Process edits do not silently rewrite an issued plan |
| Machine, Device, Jig, and Tools | `work_elements.tool`; for Torque requirements, supporting `quality_requirement_torque_details` Tool type, Tool orientation, and Screw bit type | Partially available; the broader Equipment/Resource catalog in `PAAG_ROADMAP.md` is not implemented | May require new PFMEA/control-method storage or a future approved equipment relationship |
| Characteristics - Product | Approved PFMEA/Quality characteristic explicitly classified as a product characteristic | Quality Description, Type, and specification data are available, but Product versus Process classification is absent | **New persisted classification required** |
| Characteristics - Process | Approved PFMEA/Quality characteristic explicitly classified as a process characteristic | Quality Description, Type, and specification data are available, but Product versus Process classification is absent | **New persisted classification required** |
| Special Characteristic Classification | Approved PFMEA Class/Special Characteristic value | No authoritative current source | **New persisted reviewed field required**, subject to the open CTQ mapping decision |
| Product/Process Specification and Tolerance | Published assignment Target value, Tolerances, Unit, Pass/fail, Description, and Unique identifier | Available on `quality_requirement_assignments` | Future Control Plan generation must preserve the reviewed published assignment values and not substitute unpushed repository edits |
| Evaluation/Measurement Technique | Approved detection/control method; Quality Type and Torque tool details may provide supporting context | Only partial descriptive context exists | **New persisted storage required** for the actual evaluation or measurement technique |
| Sample Size | Approved PFMEA/control strategy | No current field | **New persisted storage required** |
| Sample Frequency | Approved PFMEA/control strategy | No current field | **New persisted storage required** |
| Control Method | Approved PFMEA Prevention/Detection controls plus the implemented disposition of applicable Recommended Actions | Existing Quality controls provide a starting point, but there is no reviewed Control Method field | **New persisted storage or explicit generation rule required** |
| Reaction Plan | Approved response derived from applicable PFMEA Recommended Actions and Actions Taken | PFMEA Actions now exist, but their Control Plan disposition is not implemented | **New explicit disposition rule and future Control Plan storage required** |

### PFMEA action flow into the Control Plan

Recommended Actions must not flow into a released Control Plan merely because they were entered. The proposed sequence is:

1. A PFMEA row identifies risk and records recommended action(s).
2. Responsibility and Target Completion Date are assigned.
3. The completed response is recorded in Actions Taken.
4. Resulting Severity, Occurrence, and Detection are reviewed and approved; resulting RPN is calculated.
5. The approved action disposition identifies what becomes a standing **Control Method**, what becomes a **Reaction Plan**, what changes the specification or evaluation technique, and what does not belong in the Control Plan.
6. Control Plan generation uses only those approved dispositions and the approved PFMEA row values.

This avoids treating every recommendation as an operational control. A recommended mistake-proofing change may become a Prevention control and Control Method; a containment or escalation response may become a Reaction Plan; an action that only completes a design change may affect neither field. That disposition requires explicit collaborator review and cannot be inferred safely from free text.

If the future Control Plan is editable in the app, edits to generated fields should update an approved PFMEA/control-source record through a governed workflow rather than create an untraceable independent version. The final authoring model remains an open project-owner decision.

## Approval and generation boundaries

- Draft PFMEA Process Function content may be prefilled from Process at a Glance. Prevention and Detection controls remain collaborator-authored PFMEA text; published Quality assignments are not copied into them.
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
10. Who classifies a characteristic as Product or Process for Control Plan output?
11. Should multiple published Quality assignments on one Process step produce one Control Plan row per characteristic, or be grouped under one Process step?
12. Which completed PFMEA actions become Control Method content, which become Reaction Plan content, and who approves that disposition?
13. Are Control Plans exported snapshots, similar to the existing Excel planning snapshot, or maintained as an editable in-app module? If editable, which generated fields may be changed and where is their authoritative source?
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
- Confirm whether the Control Plan is export-only or an in-app governed view.
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

**Status: Implemented in the Quality page on August 31, 2026, with the workbook presentation corrected September 1, structured Cause-level controls implemented September 2, governed PFMEA line/control copying implemented September 3, and native validated control-cell clipboard replacement implemented September 4, 2026.** Item # uses Pitch and Process Function uses the Process at a Glance Work Element. The 19-column table shows friendly editable control tags; native same-column Ctrl+C/Ctrl+V stages compatible replacements and uses a non-dismissible compatible-only confirmation when Quality sources belong to another Process Function. A selected-Cause panel continues to stage applicable published Quality assignments and project-wide manual options into the same atomic PFMEA Save & Refresh. Native clipboard entry remains available for ordinary editable values, while deliberate line duplication creates fresh normalized records, omits completion evidence, and safely retains only applicable structured controls. Live source changes and cascaded removals are review-flagged without changing Detection. Legacy free-text rows are discarded once with editor-attributed count-only evidence while Quality assignments remain intact. RPN, high-risk, Process-source review, and scenario-cloning behavior remain as documented; no scoring scale or approval lifecycle is added.

### Phase 3 - Control Plan generation

**Goal:** Generate the standard AIAG Control Plan fields from approved PFMEA rows.

- Generate one row at the approved characteristic/process grain.
- Combine approved PFMEA content with the explicitly selected structured Quality-assignment sources and any other separately reviewed published Quality assignment values.
- Require approved Product/Process and Special Characteristic classifications.
- Require explicit evaluation technique, sample, frequency, Control Method, and Reaction Plan sources.
- Trace every generated row back to its PFMEA row, Process step, and Quality assignment(s).
- Validate the complete output and block release when required information is missing.

### Phase 4 - Export and issued revision handling

**Goal:** Produce reviewable, reproducible PFMEA and Control Plan outputs.

- Add the approved Excel and/or document export formats.
- Preserve flat, stable output columns required by downstream consumers.
- Include approved document header and revision metadata.
- Verify that an issued export can be reproduced from its saved revision/snapshot.
- Keep regeneration explicit and audit every issue/reissue action.

## Out of scope for this planning document

- Application code, database migrations, tables, fields, pages, navigation, or UI controls
- Company-specific Severity, Occurrence, or Detection scales
- PFMEA or Control Plan approval workflow implementation
- PFMEA or Control Plan export implementation
- Work instructions
- Changes to Process at a Glance, Quality, Fishbone, Yamazumi, Pin Map, or PITS behavior
- Automatic AI generation of failure modes, effects, causes, ratings, actions, or classifications

## Review status

- **Requested by:** Nicole Ervin, project owner
- **Planning requested:** August 31, 2026
- **Implementation status:** Phase 1 schema/data model and Phase 2 editable PFMEA module approved and implemented August 31, 2026
- **Next decision:** Separate project-owner review of scoring guidance, PFMEA approval lifecycle, and Phase 3 Control Plan generation
