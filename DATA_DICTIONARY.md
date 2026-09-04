# Process at a Glance data dictionary

This file is the authoritative reference for every Process at a Glance database table, its business purpose, ownership scope, and relationships. No new database table or field should be added without updating this file in the same change. When code, labels, or older documentation disagree with this file, stop and resolve the discrepancy with the project owner before extending the data model.

## Active tables

### `projects`

- **Purpose:** The top-level record for an NPI planning project. It holds the project identity, program or product, product line, lead industrial engineer, baseline revision, status, default takt time, notes, and timestamps.
- **Key relationships:** Parent of `planning_scenarios`, `parts`, `project_models`, `complexity_features`, `assembly_sections`, `concerns`, source-import records, Yamazumi records, Process at a Glance records, and `audit_log` entries.
- **Scope:** Project-wide; this is the root of all other business data.

### `planning_scenarios`

- **Purpose:** A named planning branch used to compare alternative takt, balancing, and process plans without mixing their records.
- **Key relationships:** Belongs to `projects`. May reference another `planning_scenarios` row as its parent. Owns `part_scenario_activity`, `yamazumi_areas`, `work_elements`, and `process_part_groups`. Scenario cloning copies the applicable scenario-owned planning data.
- **Scope:** Scenario-specific.

### `concerns`

- **Purpose:** Tracks project questions, concerns, decisions, and assumptions, including ownership, priority, status, and optional related part or station text.
- **Key relationships:** Belongs directly to `projects`. Related-part and related-station values are descriptive text rather than enforced foreign keys.
- **Scope:** Project-wide.

### `audit_log`

- **Purpose:** Stores lightweight history for supported saves and workflow actions, including the logical table or workflow name, action, row count, Current editor text, JSON details, and timestamp.
- **Key relationships:** Belongs to `projects`. It does not have a direct scenario foreign key; scenario identifiers may be included in the JSON details for scenario-specific events.
- **Scope:** Project-wide history, with some entries describing scenario-specific work.

### `pits_records`

- **Purpose:** Stores the latest imported PITS source record for each stable PITS ID, including source fields, a source hash, and the current source revision number.
- **Key relationships:** Belongs to `projects`. Parent of `pits_record_revisions`. A new record also creates a corresponding MBOM-review candidate in `fishbone_nodes`.
- **Scope:** Project-wide source evidence.

### `pits_record_revisions`

- **Purpose:** Preserves each imported source payload revision for a PITS record so upstream changes can be reviewed without silently replacing collaborator decisions.
- **Key relationships:** Belongs to `pits_records`; deleting the parent PITS record deletes its revisions.
- **Scope:** Project-wide source history through its parent record.

### `fishbone_nodes`

- **Purpose:** Holds PITS and legacy-BOM candidate occurrences for the Manufacturing BOM review stage. It records proposed hierarchy, source evidence, review status, applicable models, and whether the upstream source changed.
- **Key relationships:** Belongs to `projects`. May reference another node through `parent_id`, but that relationship is not enforced by a database foreign key. Confirmed rows can be synchronized into `parts`; they are not the same entity as approved fishbone sections or part placements.
- **Scope:** Project-wide source/review staging.

### `project_models`

- **Purpose:** Stores official model numbers, imported PITS model attributes, estimated annual usage, source payload, and team-friendly display names and descriptions.
- **Key relationships:** Belongs to `projects`. Parent of `model_feature_values`. Referenced indirectly when displaying or interpreting part and process model applicability.
- **Scope:** Project-wide.

### `complexity_features`

- **Purpose:** Defines manufacturing-relevant product characteristics and their allowed choices, such as a door or control configuration.
- **Key relationships:** Belongs to `projects`. Parent of `model_feature_values` and `part_feature_rules`.
- **Scope:** Project-wide.

### `model_feature_values`

- **Purpose:** Assigns one selected feature value to an official model for each applicable complexity feature, forming the project complexity tree.
- **Key relationships:** Junction between `project_models` and `complexity_features`; also carries `project_id` for boundary validation.
- **Scope:** Project-wide.

### `parts`

- **Purpose:** The approved Parts Catalog, with one master record per project and official part number. It stores the part name in the legacy `description` field, revision, provenance, notes, legacy model-applicability text, and the primary CAD image path.
- **Key relationships:** Belongs to `projects`. Parent of `part_images`, `part_scenario_activity`, `part_feature_rules`, `fishbone_part_assignments`, and `process_part_options`.
- **Scope:** Project-wide master data.

### `part_scenario_activity`

- **Purpose:** Records whether a project catalog part is active in a particular planning scenario and should appear in downstream scenario views. If no row exists, current behavior treats the part as active.
- **Key relationships:** Junction between `planning_scenarios` and `parts`; also carries `project_id` for boundary validation.
- **Scope:** Scenario-specific.

### `part_images`

- **Purpose:** Stores paths and metadata for supplemental part images. The primary CAD image remains on `parts.image_path`.
- **Key relationships:** Belongs to `parts`; deleting a part deletes its supplemental image records.
- **Scope:** Project-wide through the parent part.

### `part_feature_rules`

- **Purpose:** Defines which manufacturing feature choices require a catalog part. Multiple values for one feature act as alternatives, while rules across different features combine to describe applicability.
- **Key relationships:** Junction between `parts` and `complexity_features`; also carries `project_id` for boundary validation.
- **Scope:** Project-wide.

### `assembly_sections`

- **Purpose:** Defines the station-independent assembly fishbone framework. Rows are either main-spine sections or subassemblies and include ordering, description, and active status.
- **Key relationships:** Belongs to `projects`. May reference another `assembly_sections` row as its parent. Parent of `fishbone_part_assignments`; optionally linked from `yamazumi_areas` and `process_part_groups`.
- **Scope:** Project-wide.

### `fishbone_part_assignments`

- **Purpose:** Represents one placed occurrence or use of a catalog part in a fishbone section, with occurrence quantity, use or installation description, notes, and order. One part may have multiple assignments.
- **Key relationships:** Belongs to `projects`, references `parts`, and references `assembly_sections`. Process pairing validates that selected catalog parts are available in the relevant section, but does not save the specific assignment ID.
- **Scope:** Project-wide; scenario views filter these assignments using `part_scenario_activity`.

### `yamazumi_areas`

- **Purpose:** Defines a balancing area inside a planning scenario, normally corresponding to one fishbone section and optionally carrying a takt override.
- **Key relationships:** Belongs to `projects` and `planning_scenarios`. Optionally references `assembly_sections`. Parent of `yamazumi_pitches`, `yamazumi_elements`, and `yamazumi_work_regions`.
- **Scope:** Scenario-specific.

### `yamazumi_pitches`

- **Purpose:** Stores physical pitch addresses within a Yamazumi area, including pitch name, type, status, supported model variants, and display order.
- **Key relationships:** Belongs to `yamazumi_areas` and `projects`. Referenced by `yamazumi_elements`; deleting a pitch through the supported workflow moves its work elements to Unassigned before deletion.
- **Scope:** Scenario-specific through the parent area.

### `yamazumi_elements`

- **Purpose:** Stores measurable work content for Yamazumi balancing: description, time, work type, pitch assignment, variants, work region, flags, source, order, and Process synchronization state.
- **Key relationships:** Belongs to `yamazumi_areas` and `projects`; optionally references `yamazumi_pitches`. `process_element_id` is a soft text link to `work_elements`, not an enforced foreign key. Reconciliation creates or updates the linked Process step.
- **Scope:** Scenario-specific through the parent area.

### `yamazumi_work_regions`

- **Purpose:** Defines area-specific work-region labels and colors used to categorize Yamazumi work elements.
- **Key relationships:** Belongs to `yamazumi_areas` and `projects`. Work elements store the selected region as text rather than by region ID, so rename and delete workflows must rewrite affected element values deliberately.
- **Scope:** Scenario-specific through the parent area.

### `yamazumi_flag_definitions`

- **Purpose:** Defines project-wide tags that can be applied to Yamazumi work, including protected system flags such as CTQ and Safety.
- **Key relationships:** Belongs to `projects`. Yamazumi elements store selected flag names as JSON text rather than foreign keys, so flag rename and delete workflows must rewrite affected element values deliberately.
- **Scope:** Project-wide.

### `work_elements`

- **Purpose:** Stores the ordered Process at a Glance steps for a planning scenario, including pitch, operation/work-element text, time, status, model applicability, output-assembly milestone, tool, location, unit orientation, and geometry or requirement fields. Conveyor height, platform height, and pit depth are stored directly in inches as `conveyor_height_in`, `platform_height_in`, and `pit_depth_in`.
- **Key relationships:** Belongs to `projects` and `planning_scenarios`. Soft-linked from `yamazumi_elements.process_element_id`. Parent of `process_part_groups`. Some requirement fields are retained by the schema but are not editable in the current Process dialog.
- **Scope:** Scenario-specific.

### `process_part_groups`

- **Purpose:** Defines a named material requirement for a Process at a Glance step, with a selection rule (`Use all`, `Choose one`, or `Optional`), quantity, notes, and originating fishbone section.
- **Key relationships:** Belongs to `projects` and `planning_scenarios`, references `work_elements`, optionally references `assembly_sections`, and is parent of `process_part_options`.
- **Scope:** Scenario-specific.

### `process_part_options`

- **Purpose:** Lists the catalog parts allowed or required by a process part group.
- **Key relationships:** Belongs to `process_part_groups` and references `parts`. It records the catalog part, not a specific `fishbone_part_assignments` occurrence.
- **Scope:** Scenario-specific through the parent process part group.

### `quality_requirements`

- **Purpose:** Stores the reusable Quality requirements repository, including Type, Description, Unique identifier, Pass/fail behavior, Target value, Tolerances, and Unit. Repository edits remain project reference data until an explicit push synchronizes them to linked Process requirements.
- **Key relationships:** Belongs to `projects` and is the project-wide parent of `quality_requirement_assignments` and, for requirements whose Type is Torque, the optional one-to-one `quality_requirement_torque_details` record. Unique identifiers are case-insensitively unique within a project. A repository requirement cannot be deleted while Process assignments or Torque tool details still reference it.
- **Scope:** Project-wide.

### `quality_requirement_assignments`

- **Purpose:** Attaches a published copy of a repository Quality requirement to a specific Process at a Glance step. The copied requirement values remain unchanged during an ordinary repository save and are updated only by the explicit repository push workflow.
- **Key relationships:** Belongs to `projects` and `planning_scenarios`, references `work_elements`, and references `quality_requirements`. Project and scenario boundaries are validated against the selected Process step. Deleting a Process step or scenario deletes its assignments; deleting the referenced repository requirement is restricted until its assignments are removed. Scenario cloning copies assignments and remaps them to the cloned `work_elements` records while retaining their project-wide repository links.
- **Scope:** Scenario-specific through the referenced Process at a Glance step, with published content sourced from the project-wide repository.

### `quality_requirement_torque_details`

- **Purpose:** Stores the project-wide Torque tool details for a Quality requirement whose Type is Torque, including Tool type, Tool orientation, and Screw bit type.
- **Key relationships:** Belongs to `projects` and references exactly one `quality_requirements` row through a unique `quality_requirement_id`, creating an optional one-to-one relationship. The parent requirement must belong to the same project and have Type set to Torque. Its indirect connection to the critical thread is `quality_requirements` → `quality_requirement_assignments` → `work_elements`.
- **Scope:** Project-wide, matching the parent Quality requirement. Tool type is limited to Air tool, Electric clutch tool, or DC tool. Tool orientation is limited to Fixtured, Pistol, In-line, or Right angle. Screw bit type is free-entry text with project suggestions sourced from previously saved values.
- **Deletion and type changes:** Deleting the detail record preserves the parent Quality requirement and every Process-step assignment. The parent requirement cannot be deleted or changed away from Type Torque until its detail record is removed through the confirmed workflow.

### `pfmea_entries`

- **Purpose:** Stores one scenario-specific Potential Failure Mode for a Process at a Glance step, its reviewed Classification (blank, Safety, or Critical Quality), read-only Process Function snapshots, and source fingerprints used to flag later upstream changes without replacing reviewed PFMEA evidence.
- **Key relationships:** Belongs to `projects` and `planning_scenarios`, and references one `work_elements` row. It is the parent of `pfmea_effects`, `pfmea_causes`, the structured Prevention/Detection selections, `pfmea_risk_rows`, and `pfmea_actions`. A cloned scenario receives independent PFMEA IDs and retains `source_pfmea_entry_id` lineage to the source entry.
- **Scope:** Scenario-specific. The referenced Process step must belong to the same project and scenario. A Process step with PFMEA entries cannot be deleted until those entries are removed through the confirmed PFMEA workflow.

### `pfmea_effects`

- **Purpose:** Stores one or more Potential Effects for a PFMEA entry, with a collaborator-entered whole-number Severity from 1 through 10 and sequence.
- **Key relationships:** Belongs to one `pfmea_entries` row. Deleting an Effect through the confirmed workflow also removes its derived Effect-Cause `pfmea_risk_rows` records.
- **Scope:** Scenario-specific through the parent PFMEA entry. The module does not define or persist a company Severity scale.

### `pfmea_causes`

- **Purpose:** Stores one or more Potential Causes for a PFMEA entry, with optional collaborator-entered whole-number Occurrence and Detection ratings from 1 through 10 and sequence. `control_source_review_required` marks source changes or removals for review. Detection-source changes additionally set `detection_review_required` without changing the Detection rating.
- **Key relationships:** Belongs to one `pfmea_entries` row and is parent of its structured Prevention/Detection selections, applicable `pfmea_risk_rows`, and optional cause-level `pfmea_actions`.
- **Scope:** Scenario-specific through the parent PFMEA entry. The module does not define or persist company Occurrence or Detection scales. Detection may be entered without a selected Detection control.

### `pfmea_prevention_options` and `pfmea_detection_options`

- **Purpose:** Store reusable manual phrases for Prevention and Detection controls in separate catalogs. Each row has a required Label and Active state; labels are case-insensitively unique within its project and catalog.
- **Key relationships:** Belongs to `projects` and may be referenced by the corresponding selection table. Deactivation preserves existing selections but prevents new selection. Confirmed deletion cascades only dependent selections and flags their Causes for review.
- **Scope:** Project-wide. Scenario cloning continues to reference the same manual option IDs.

### `pfmea_prevention_selections` and `pfmea_detection_selections`

- **Purpose:** Store ordered, structured Cause-level Current Process Controls. Each selection is either one published `quality_requirement_assignments` record or one manual option from the corresponding project catalog; check constraints require exactly one valid source.
- **Key relationships:** Belongs to one scenario-specific `pfmea_entries` row and `pfmea_causes` row. A Quality source must belong to the same project/scenario and linked `work_elements.id`; a manual source must belong to the same project and correct catalog. Partial unique indexes prevent duplicate Cause/source selections within one control list, while the same Quality assignment may appear once in each of the Prevention and Detection lists.
- **Scope:** Scenario-specific. Stable selection IDs and sequence preserve collaborator order. Scenario cloning creates new selection IDs, remaps PFMEA parents and Quality assignment IDs, and retains project-wide manual option IDs.
- **Source review and deletion:** `source_updated_at_snapshot` records the source version acknowledged at Save & Refresh. Live source labels are displayed; source updates set Cause review flags. A Quality unlink or catalog-option deletion removes only dependent selections transactionally, preserves Quality definitions/PFMEA ratings, and flags affected Causes. Detection-source changes also require Detection-rating review.
- **Legacy migration:** On the first PFMEA opening for a project with legacy `pfmea_controls` rows, a nonblank Current editor is required. The rows and their text are atomically discarded, affected Causes are flagged, and exactly one project-scoped PFMEA audit event records counts without recording discarded text. The obsolete table is dropped after no project retains legacy rows. Quality requirements and assignments are preserved.

### `pfmea_risk_rows`

- **Purpose:** Stores the calculated initial RPN for each Effect-Cause combination as historical save evidence. RPN is recorded as Severity × Occurrence × Detection when all three ratings exist and remains blank otherwise.
- **Key relationships:** Belongs to one PFMEA entry and references one `pfmea_effects` row and one `pfmea_causes` row. It is derived and refreshed atomically whenever the applicable flat line is saved. The separate **Recalculate RPN** action refreshes the same calculation from unsaved editor values without persistence and preserves each stable flat-line identity without appending duplicate saved rows.
- **Scope:** Scenario-specific through the parent PFMEA entry. No threshold, rating lookup, or risk classification is inferred from RPN.

### `pfmea_actions`

- **Purpose:** Stores one or more Recommended Actions for a PFMEA failure mode or a specific cause, including Responsibility, Target Completion Date, Actions Taken, Resulting Severity, Resulting Occurrence, Resulting Detection, and the persisted calculated Resulting RPN.
- **Key relationships:** Belongs to one `pfmea_entries` row and may reference one of that entry's `pfmea_causes` rows. Resulting ratings are whole-number values from 1 through 10. Resulting RPN is recalculated and overwritten on every PFMEA line-item save when all three resulting ratings exist; **Recalculate RPN** refreshes the unsaved display without persistence.
- **Scope:** Scenario-specific through the parent PFMEA entry. These actions do not automatically create future Control Method or Reaction Plan content.

## Proposed modules — pending owner review

### Pin Map

- **Proposed by:** Nicole Ervin, project owner
- **Date proposed:** August 24, 2026
- **Purpose:** Provide a scenario-specific visual representation of the production line, with linked Process at a Glance work displayed above each Yamazumi workstation or pitch.
- **Connections:** Connects the active `planning_scenarios` record to `yamazumi_areas`, `yamazumi_pitches`, `yamazumi_elements`, and `work_elements`.
- **Relationship to the critical thread:** A pitch is linked through `yamazumi_elements.pitch_id`; explicitly reconciled Process work is linked through the existing soft link from `yamazumi_elements.process_element_id` to `work_elements.id`. Every query also validates the active project and scenario boundaries.
- **Scope:** Scenario-specific. Switching scenarios changes the complete map and its linked work.
- **Storage:** No new table or field is required for the initial read-only view. It derives its layout and content from existing Yamazumi and Process at a Glance records. Any future persisted coordinates, annotations, or Pin Map-only settings require a new owner-reviewed proposal.
- **Applicable standards:** All locked standards in `DESIGN_SYSTEM.md` apply. The initial view includes the scenario boundary badge, explanatory help text, filters, filtered Excel export, and a bottom History section. Save, deletion, row-selection, and audit-write requirements do not activate because this view does not edit or persist data.
- **Approval status:** Nicole Ervin approved implementation of this read-only derived view. Persisted Pin Map data remains pending owner review.

### Functional Reviews

- **Proposed by:** Nicole Ervin, project owner
- **Date proposed:** August 21, 2026
- **Purpose:** Add project-wide navigation shells for Equipment, Ergonomics, Quality, Materials, and Safety functional reviews. Quality later received the separate, approved Quality requirements scope documented below.
- **Potential connections:** Future review records may connect to Parts, Fishbone sections, Yamazumi records, Process at a Glance steps, planning scenarios, or other approved critical-thread entities.
- **Relationship to the critical thread:** Exact relationships and foreign keys are intentionally not defined in this shell phase. The project owner approved navigation-only, non-persistent shells before those relationships are designed. No persisted review fields may be added until each relationship is approved.
- **Scope:** The Functional Reviews navigation group and its four remaining shell pages are project-wide. Quality follows the separately approved scope below. Future review content may be project-wide or scenario-specific, but every persisted record type must receive one explicit scope before implementation.
- **Storage:** No database table or field was added in this shell phase. Equipment, Ergonomics, Materials, and Safety contain only browser-session description state and an empty, schema-free table. Quality follows the separately approved storage design below. Existing tables cannot be selected or ruled out for the remaining reviews until their fields and relationships are defined.
- **Applicable standards:** All locked standards in `DESIGN_SYSTEM.md` apply, including table row selection, deletion safety, Save & Refresh, audit logging for persisted changes, History placement, Scenario Boundary badges, help text, canonical terminology, stable identifiers, and imperial units where relevant.
- **Approval status:** Nicole Ervin approved this shell-only exception. Equipment, Ergonomics, Materials, and Safety remain shells whose data model, ownership, relationships, and persisted fields are pending owner review. Quality follows the separate approval below.

### Quality requirements

- **Proposed by:** Nicole Ervin, project owner
- **Date proposed:** August 27, 2026
- **Purpose:** Add a reusable Quality requirements repository for dimensional specifications, present-and-fully-seated checks, torque specifications, vision-system validations, and other quality requirements. Allow collaborators to attach repository requirements to specific Process at a Glance steps so the published requirements support process planning, structured PFMEA control selection, and future Control Plan generation.
- **Connections:** Connects project-wide Quality requirement definitions to scenario-specific `work_elements` records. A Process step may receive one or more requirements, and the same repository definition may be attached to multiple steps, including separate screw operations that share one torque definition. A Torque requirement may also own one project-wide `quality_requirement_torque_details` record. Fishbone section or subassembly context is inherited through the selected Process step rather than stored as a separate direct Quality requirement connection.
- **Relationship to the critical thread:** Each attached requirement links directly to its Process at a Glance step through `work_elements.id`. The repository definition remains reusable project reference data, while every attachment validates the Process step's project and planning-scenario boundaries. A collaborator may explicitly select a published assignment as a Cause-level PFMEA Prevention control, Detection control, or both; nothing is auto-classified. These references do not change upstream Fishbone, Yamazumi, or Process decisions.
- **Scope:** Quality requirement definitions are project-wide and shared across planning scenarios. Attachments are associated with scenario-specific Process steps through `work_elements`, but their published requirement content remains synchronized with the shared project repository. Scenario cloning must preserve the applicable attachments for the cloned Process steps.
- **Storage:** New storage is required because one Process step may have multiple typed Quality requirements and one reusable repository definition may serve multiple Process steps; the existing `work_elements` requirement fields cannot represent that relationship. The design requires a project-wide repository table and a Process-step attachment table. Each requirement contains Type, Description, Unique identifier, Pass/fail, Target value, Tolerances, and Unit, in addition to the standard internal identifier, project relationship, and audit timestamps. Torque-only tool information is stored separately in the one-to-one `quality_requirement_torque_details` table instead of adding sparse columns to `quality_requirements`. Tool type and Tool orientation use the approved controlled choices; Screw bit type accepts free-entry text and offers previously saved project values. The implemented Quality-page interaction creates a linked Process requirement record when a collaborator attaches a saved repository requirement and removes that assignment only through the confirmed unlink workflow. Unlink discloses and transactionally removes dependent structured PFMEA selections, flags affected Causes, preserves ratings/Quality definitions, and records both Quality and PFMEA audit evidence. The separate read-only linked-requirements view shows every assignment across the active project while retaining each assignment's scenario ownership. Repository edits do not update linked Process requirements during an ordinary table save; a separate explicit push action publishes the saved repository values to every linked Process step so propagation is deliberate and predictable.
- **Applicable standards:** All locked standards in `DESIGN_SYSTEM.md` apply, including native table row selection, relationship-safe deletion confirmation, direct row entry, **Save & Refresh**, audit logging for every persisted change and synchronization action, bottom History sections, project-wide and scenario-specific boundary indicators where applicable, plain-language help text, canonical terminology, stable identifiers, and imperial storage and display for linear dimensional values. The repository's explicit push action is separate from **Save & Refresh**, must preview or explain all affected linked Process requirements, validate the complete synchronization before writing, apply it atomically, record Current editor attribution and affected rows in history, and never propagate an unsaved repository edit.
- **Approval status:** Nicole Ervin approved the documented schema and data-access implementation on August 27, 2026, and subsequently approved the project-wide editable repository page with deliberate publication to existing linked Process requirements. On August 31, 2026, Nicole Ervin approved creating and removing scenario-specific Process-step assignments and the Torque-only tool-details panel. On September 2, 2026, Nicole approved explicit use of published assignments as structured Cause-level PFMEA controls and the relationship-aware unlink cascade. The project-wide linked-requirements view remains read-only. Control Plan generation remains pending owner review.

### Process FMEA

- **Proposed by:** Nicole Ervin, project owner
- **Date approved:** August 31, 2026
- **Purpose:** Add a traditional AIAG-format Process FMEA workflow within the Quality page. The visible editor follows the approved 19-column flat line-item body of `FRM-GEA-QYS-033 PFMEA Template.xlsx`, while normalized storage continues to permit multiple Potential Effects, Potential Causes, Current Process Controls, and Recommended Actions. A separate read-only high-risk view filters saved lines when either RPN or Resulting RPN exceeds a collaborator-entered positive threshold, displays both values, and sorts by the higher value descending.
- **Connections:** Connects each `pfmea_entries` record to a scenario-specific `work_elements.id`. Item # displays the linked step's Pitch (`work_elements.station`). Process Function/Requirements displays the same Work Element label as Process at a Glance: the linked `yamazumi_elements.description` when present, otherwise `work_elements.operation`. Cause-level Prevention and Detection lists are explicit structured references to applicable published Quality assignments or project-wide manual catalog options; no source is auto-classified.
- **Relationship to the critical thread:** PFMEA enters after scenario-specific Process at a Glance. It does not rewrite Fishbone, Yamazumi, Process, or Quality decisions. Process source fingerprints surface a non-blocking upstream-change flag; only a separate confirmed review action accepts current Process source values. Quality/catalog changes show live labels and mark affected Causes for review without silently changing Detection ratings.
- **Scope:** Scenario-specific. The Quality page is Scenario-aware because the Requirements repository and manual control catalogs are project-wide while PFMEA entries and selections belong to the active scenario. Scenario cloning copies the PFMEA graph with new entry/Cause/selection IDs, remapped Work Element and Quality assignment links, reused project-wide manual options, preserved selection order/review state, and source-entry lineage.
- **Storage:** `pfmea_entries` stores the failure mode, approved Classification value, Process snapshots, and source fingerprints. `pfmea_effects` stores Effects/Severity; `pfmea_causes` stores Causes, optional Occurrence/Detection, and source/Detection review flags. `pfmea_prevention_options` and `pfmea_detection_options` store project-wide manual choices. `pfmea_prevention_selections` and `pfmea_detection_selections` store ordered scenario-specific source identities and acknowledged source versions. The 19-column flat table displays those sources as friendly multiselect tags and permits native same-column control-cell copy/paste. A paste replaces the target list, propagates across repeated flat lines backed by the same Cause, and remains staged until the shared **Undo** or **Save & Refresh** action. Applicable controls stage without interruption; incompatible step-specific Quality controls require explicit compatible-only confirmation, while inactive or unavailable manual options are omitted with an inline warning. The selected-Cause panel remains available for deliberate row-specific editing and previewed Cause-to-Cause copying. Ordinary editable cells retain native spreadsheet copy/paste. A governed duplicate-line workflow creates an independent unsaved flat line and, on save, fresh Entry, Effect, Cause, risk, Action, and control-selection IDs without persisting a source-line relationship. Same-step duplicates may reference the same applicable Quality assignment but never copy the Quality definition or assignment itself. Completion evidence and resulting ratings are cleared. Changing the duplicate's Process Function requires confirmation when step-specific Quality controls will be removed; active project-wide manual controls and the Detection rating remain. `pfmea_risk_rows` and `pfmea_actions` retain the existing RPN behavior. Internal identifiers stay hidden. The read-only high-risk view and lack of company scoring guidance, persisted threshold, or approval lifecycle remain unchanged.
- **Applicable standards:** All locked standards in `DESIGN_SYSTEM.md` apply, including native selection, direct entry, relationship-safe confirmed deletion, hidden stable IDs, filters, filtered export, Undo, **Save & Refresh**, audit logging with Editor attribution, scenario boundary explanation, canonical terminology, and one bottom History expander with Requirements and PFMEA history tabs.
- **Approval status:** Nicole Ervin approved this schema and Phase 2 editable PFMEA module on August 31, 2026, the workbook-aligned flat presentation on September 1, 2026, and the structured Cause-level Prevention/Detection selection model described here on September 2, 2026. The Quality page includes Requirements repository, PFMEA, and placeholder Control Plan tabs. Control Plan tables, generation, approval workflows, scoring definitions, and automatic action disposition remain unapproved and unimplemented.

## Known naming debt — approved for future correction, not yet changed

The following items are genuine naming debt rather than intentional stable-identifier/friendly-display-name pairs or ordinary copy variation. They are approved future corrections, but no schema, stored value, query, page, or export change is being made now.

| Current database name or stored identifier | Display label it should eventually match | Why this is real naming debt |
| --- | --- | --- |
| `work_elements.station` | **Pitch** | Process at a Glance, Yamazumi, and Pin Map use Pitch terminology for the physical work position; `station` remains the legacy persisted name. |
| `work_elements.operation` | **Work Element** | The visible Process workflow and Pin Map treat the work element as the primary concept, while `operation` remains as the legacy persisted name. |
| `parts.description` | **Part Name** | Every active workflow consistently presents this value as Part Name, with no remaining intentional alternative meaning for the catalog field. |
| `pits_records.description` | **Part Name** | Active PITS previews present the source value as Part Name; `description` is retained legacy/source terminology rather than a deliberate friendly-name pairing. Any correction remains subject to the blocked PITS-format migration. |
| `fishbone_nodes.description` | **Part Name** | MBOM-review candidates use the same part-name concept and are displayed as Part Name; the generic stored name is inherited naming debt. Any correction remains subject to the blocked PITS/MBOM-review migration. |
| `audit_log.table_name` stored values | Permanent canonical workflow display labels, including **Process at a Glance** instead of legacy values such as **Process plan** | Historical events contain free-text workflow names and Process currently applies a one-off display replacement. The permanent solution is a documented, shared display-mapping rule, not silent mutation of stored history. |

Any future database rename must update every query, page, validation path, import/export mapping, and workbook reference in one coordinated task. Historical `audit_log` values must never be rewritten. Only their display mapping may be normalized going forward so the original audit evidence remains intact.

## Dormant tables — do not modify without approval

The following tables are implemented in the schema and data layer but are not currently editable from any active application screen. Do not rename, remove, repurpose, extend, or build new UI around them without explicit project-owner approval. The scenario-owned records in this dormant model are copied during scenario cloning; project-wide manufacturing assemblies are reused by the cloned scenario rather than duplicated.

### `manufacturing_assemblies`

- **Purpose:** Intended to define made or purchased manufacturing assemblies, including assembly number, name, planning reason, parent assembly, active state, and notes.
- **Relationships and cloning:** Belongs to `projects` and may reference another manufacturing assembly as its parent. It is project-wide and is referenced by scenario policies and dormant material options. It is reused across cloned scenarios rather than copied as a new assembly record.
- **Current status — NOT YET DESIGNED:** No active screen edits this table. Future make/buy, supplier, and buffer/storage behavior is not finalized. Do not build UI, features, or duplicate logic against it without a scoping discussion and explicit project-owner approval.

### `assembly_scenario_policies`

- **Purpose:** Intended to hold scenario-specific make/buy, supplier, build-area, buffer, storage, and minimum/target/maximum quantity decisions for a manufacturing assembly.
- **Relationships and cloning:** Junction between `planning_scenarios` and `manufacturing_assemblies`; policy rows are copied when a planning scenario is cloned.
- **Current status — NOT YET DESIGNED:** No active screen edits this table. Future make/buy, supplier, and buffer/storage behavior is not finalized. Do not build UI, features, or duplicate logic against it without a scoping discussion and explicit project-owner approval.

### `work_element_material_groups`

- **Purpose:** Intended to define a material requirement directly on a Yamazumi work element, optionally identifying a target manufacturing assembly and a part-selection rule.
- **Relationships and cloning:** Belongs to `projects` and `planning_scenarios`, references `yamazumi_elements`, optionally references `manufacturing_assemblies`, and is parent of `work_element_material_options`. Rows are copied when a planning scenario is cloned.
- **Current status — LOCKED:** No active screen edits this table. The active Process at a Glance workflow instead uses `process_part_groups`. This table is frozen with no active plan to revisit it; do not modify, extend, or build new features against it. Continue carrying its rows forward during scenario cloning.

### `work_element_material_options`

- **Purpose:** Intended to list either catalog parts or manufacturing assemblies as options under a Yamazumi-level material group.
- **Relationships and cloning:** Belongs to `work_element_material_groups` and must reference exactly one of `parts` or `manufacturing_assemblies`. Rows are copied with their parent material groups when a planning scenario is cloned.
- **Current status — LOCKED:** No active screen edits this table. The active Process at a Glance workflow instead uses `process_part_options`. This table is frozen with no active plan to revisit it; do not modify, extend, or build new features against it. Continue carrying its rows forward during scenario cloning.

## Hidden review stage

`pits_records`, `pits_record_revisions`, and `fishbone_nodes` support a Manufacturing BOM confirmation stage between imported Product Architecture evidence and the approved Parts Catalog. New or changed PITS records preserve their source revisions and create or flag `fishbone_nodes` review candidates. Confirmed candidates can then be synchronized into `parts` without allowing an upstream import to silently overwrite collaborator-reviewed planning decisions.

The database and data-access functions for this review stage exist, but none of the active navigation screens currently exposes the complete review and confirmation workflow.

**Current status — BLOCKED / TBD:** This stage is intentionally on hold until the PITS spreadsheet import is migrated to a better format. Do not build an MBOM review screen or duplicate, bypass, replace, or extend this logic until that migration is complete and the project owner confirms the workflow is ready to revisit.

## Critical thread — do not break

```text
PITS / BOM evidence
    ├── PITS records + source revision history
    ├── Model definitions
    └── MBOM-review candidates (fishbone_nodes)
                    ↓ Collaborator confirmation/synchronization
Parts Catalog ── feature applicability ── model/feature architecture
      ↓
Fishbone sections + placed part occurrences
      ↓ section link
Scenario-specific Yamazumi areas → pitches → work elements
      ↓ explicit reconciliation
Scenario-specific Process at a Glance steps
      ↓
Process part groups → paired catalog parts from a fishbone section
      ↓
Scenario-specific Pin Map (derived visual view)
      ↓
Quality requirements repository -> scenario-specific assignments linked to Process steps
      ↓
Scenario-specific Process FMEA
      ↓
Future Control Plan generation (not implemented)
```
