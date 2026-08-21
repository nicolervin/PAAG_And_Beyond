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

## Proposed modules — pending owner review

### Functional Reviews

- **Proposed by:** Nicole Ervin, project owner
- **Date proposed:** August 21, 2026
- **Purpose:** Add project-wide navigation shells for Equipment, Ergonomics, Quality, Materials, and Safety functional reviews.
- **Potential connections:** Future review records may connect to Parts, Fishbone sections, Yamazumi records, Process at a Glance steps, planning scenarios, or other approved critical-thread entities.
- **Relationship to the critical thread:** Exact relationships and foreign keys are intentionally not defined in this shell phase. The project owner approved navigation-only, non-persistent shells before those relationships are designed. No persisted review fields may be added until each relationship is approved.
- **Scope:** The Functional Reviews navigation group and its five shell pages are project-wide. Future review content may be project-wide or scenario-specific, but every persisted record type must receive one explicit scope before implementation.
- **Storage:** No database table or field is added in this phase. Each shell contains only browser-session description state and an empty, schema-free table. Existing tables cannot be selected or ruled out until the review fields and relationships are defined.
- **Applicable standards:** All locked standards in `DESIGN_SYSTEM.md` apply, including table row selection, deletion safety, Save & refresh, audit logging for persisted changes, History placement, Scenario Boundary badges, help text, canonical terminology, stable identifiers, and imperial units where relevant.
- **Approval status:** Nicole Ervin approved this shell-only exception. The data model, ownership, relationships, and persisted fields remain pending owner review.

## Known naming debt — approved for future correction, not yet changed

The following items are genuine naming debt rather than intentional stable-identifier/friendly-display-name pairs or ordinary copy variation. They are approved future corrections, but no schema, stored value, query, page, or export change is being made now.

| Current database name or stored identifier | Display label it should eventually match | Why this is real naming debt |
| --- | --- | --- |
| `work_elements.station` | **Pitch** | Process at a Glance and Yamazumi use Pitch terminology for the physical work position; only legacy/internal code and the Requirements station filter retain Station. |
| `work_elements.operation` | **Work Element** | The visible Process workflow now treats the Yamazumi-derived work element as the primary concept, while `operation` remains as the legacy persisted name and Requirements heading source. |
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
- **Current status:** No active screen edits this table.

### `assembly_scenario_policies`

- **Purpose:** Intended to hold scenario-specific make/buy, supplier, build-area, buffer, storage, and minimum/target/maximum quantity decisions for a manufacturing assembly.
- **Relationships and cloning:** Junction between `planning_scenarios` and `manufacturing_assemblies`; policy rows are copied when a planning scenario is cloned.
- **Current status:** No active screen edits this table.

### `work_element_material_groups`

- **Purpose:** Intended to define a material requirement directly on a Yamazumi work element, optionally identifying a target manufacturing assembly and a part-selection rule.
- **Relationships and cloning:** Belongs to `projects` and `planning_scenarios`, references `yamazumi_elements`, optionally references `manufacturing_assemblies`, and is parent of `work_element_material_options`. Rows are copied when a planning scenario is cloned.
- **Current status:** No active screen edits this table. The active Process at a Glance workflow instead uses `process_part_groups`.

### `work_element_material_options`

- **Purpose:** Intended to list either catalog parts or manufacturing assemblies as options under a Yamazumi-level material group.
- **Relationships and cloning:** Belongs to `work_element_material_groups` and must reference exactly one of `parts` or `manufacturing_assemblies`. Rows are copied with their parent material groups when a planning scenario is cloned.
- **Current status:** No active screen edits this table. The active Process at a Glance workflow instead uses `process_part_options`.

## Hidden review stage

`pits_records`, `pits_record_revisions`, and `fishbone_nodes` support a Manufacturing BOM confirmation stage between imported Product Architecture evidence and the approved Parts Catalog. New or changed PITS records preserve their source revisions and create or flag `fishbone_nodes` review candidates. Confirmed candidates can then be synchronized into `parts` without allowing an upstream import to silently overwrite collaborator-reviewed planning decisions.

The database and data-access functions for this review stage exist, but none of the active navigation screens currently exposes the complete review and confirmation workflow. New UI work must not duplicate, bypass, or create a competing MBOM review path without first checking with the project owner and determining whether the existing hidden workflow should be restored or replaced.

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
Read-only Requirements view
```
