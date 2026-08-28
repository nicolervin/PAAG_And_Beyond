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
- **Key relationships:** Belongs to `projects`. May reference another `assembly_sections` row as its parent. Parent of `fishbone_part_assignments`; optionally linked from `yamazumi_areas`, `process_part_groups`, and the Built and Installed fields on `manufacturing_assemblies`. Deleting a referenced section requires the combined continuity re-pointing workflow documented below.
- **Scope:** Project-wide.

### `fishbone_part_assignments`

- **Purpose:** Represents one placed occurrence or use of a catalog part in a fishbone section, with a strictly positive decimal occurrence quantity, use or installation description, notes, and order. One part may have multiple assignments.
- **Key relationships:** Belongs to `projects`, references `parts`, and references `assembly_sections`. Process pairing validates that selected catalog parts are available in the relevant section, but does not save the specific assignment ID.
- **Scope:** Project-wide; scenario views filter these assignments using `part_scenario_activity`.

### `manufacturing_assemblies`

- **Purpose:** Stores the project-wide catalog of real, pre-existing assembly numbers, including friendly name, parent assembly, Built section, Installed section, active state, notes, primary image path, and timestamps. The parked `pits_reference` and `planning_reason` fields remain hidden from the active catalog workflow.
- **Key relationships:** Belongs to `projects`; may reference another catalog assembly as its parent and references `assembly_sections` independently through Built and Installed section fields. Parent of `manufacturing_assembly_components`, `manufacturing_assembly_feature_rules`, `manufacturing_assembly_images`, and the still-dormant scenario-policy relationships.
- **Scope:** Project-wide. Active catalog reads and writes are isolated from `assembly_scenario_policies` and never accept `scenario_id`.

### `manufacturing_assembly_components`

- **Purpose:** Stores one explicit, independently quantified mini-BOM component for an assembly number by referencing an exact Fishbone use. Quantities are positive decimals and do not stay synchronized with the Fishbone quantity after creation.
- **Key relationships:** Belongs to `manufacturing_assemblies` and references `fishbone_part_assignments`; deleting the assembly or Fishbone use cascades to the component row.
- **Scope:** Project-wide.

### `manufacturing_assembly_feature_rules`

- **Purpose:** Stores precise assembly applicability with at most one choice per feature and AND logic across features. Stale rows are retained, visibly flagged, and fail closed until deliberately corrected or removed.
- **Key relationships:** Belongs to `manufacturing_assemblies` and references `complexity_features` with `ON DELETE RESTRICT`; values are validated against the feature's current JSON `allowed_values`.
- **Scope:** Project-wide.

### `manufacturing_assembly_images`

- **Purpose:** Stores unlimited supplemental assembly-image paths and optional captions. The primary image remains on `manufacturing_assemblies.image_path`.
- **Key relationships:** Belongs to `manufacturing_assemblies`; deleting the assembly deletes its image rows and owned upload files through the supported workflow.
- **Scope:** Project-wide.

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

## Module proposals and decision records

### Assemblies catalog (real, pre-existing assembly numbers)

- **Proposed by:** Nicole Ervin, project owner
- **Date proposed:** August 27, 2026
- **Review status:** **Approved and implemented on `Nicole_Assemblies_Addition`, August 27, 2026.**
- **Purpose:** Add a project-wide catalog of real, pre-existing assembly numbers. A Fishbone section and an assembly number remain separate entities: one section may be the built or installed location for many assembly numbers, and each assembly number owns an authoritative, explicitly edited mini-BOM rather than a BOM computed from feature rules.
- **Connections:** Reuse `manufacturing_assemblies` as the authoritative assembly-number record. Every catalog assembly has a built-section reference and an installed-section reference to `assembly_sections`; the two references may be identical. Mini-BOM rows reference exact `fishbone_part_assignments` occurrences and reach Parts Catalog records through those occurrences. Assembly feature rules reference `complexity_features` and are compared with `model_feature_values`; they do not reuse or modify `part_feature_rules`. The locked `work_element_material_groups` and `work_element_material_options` tables are not used. Existing free-text Process output-assembly fields and all Process selection behavior remain out of scope.
- **Relationship to the critical thread:** The catalog forms an explicit project-wide bridge from Model definitions and approved Fishbone structure toward future Process planning: `complexity_features` / `model_feature_values` -> assembly feature rules -> `manufacturing_assemblies`, and `parts` -> `fishbone_part_assignments` -> assembly mini-BOM components -> `manufacturing_assemblies` -> built/installed `assembly_sections`. A future Process task may offer an assembly only to steps tied to its installed section; this phase stores the required distinction but does not add that Process UI or relationship.
- **Scope:** Project-wide, matching Parts Catalog, Fishbone structure, and `part_feature_rules`. No new catalog, mini-BOM, feature-rule, or image row carries `scenario_id`. The new Assemblies page must use the **Project-wide** scope badge. The lightweight assembly list on the Scenario-aware Parts to fishbone page still reads project-wide assembly data.
- **Reuse and isolation:** Extend and reuse `manufacturing_assemblies`; do not create a second assembly master. Add normalized child tables for mini-BOM components, feature rules, and supplemental images. New catalog reads and writes must use isolated project-only store functions that do not accept `scenario_id`, join `assembly_scenario_policies`, or write scenario policies. The existing dormant `manufacturing_assemblies(project_id, scenario_id)`, `replace_manufacturing_assemblies(...)`, `bulk_update_assembly_policy(...)`, and scenario-cloning policy logic remain untouched and unreferenced by the new page. Existing `pits_reference` and `planning_reason` values remain stored but hidden and are not written by the new workflow; their meaning remains parked with the future make/buy discussion.

#### Extended `manufacturing_assemblies`

Retain every existing column and add the following catalog fields:

| Column | Definition | Purpose |
| --- | --- | --- |
| `built_section_id` | `TEXT REFERENCES assembly_sections(id) ON DELETE RESTRICT` | Identifies the section where the assembly is built and whose placed Fishbone uses are eligible for its mini-BOM. Nullable at the database level for compatibility with the dormant writer, but required by every new isolated catalog save. |
| `installed_section_id` | `TEXT REFERENCES assembly_sections(id) ON DELETE RESTRICT` | Identifies the section where the completed assembly is installed and supports future Process-step eligibility. Nullable at the database level for compatibility with the dormant writer, but required by every new isolated catalog save. |
| `image_path` | `TEXT DEFAULT ''` | Stores the primary assembly-image path, mirroring the primary-image-on-master-record pattern used by Parts Catalog. |
| `created_at` | `TEXT` | Stores the UTC creation timestamp. Existing rows are backfilled from `updated_at`; new isolated catalog writes always supply it. |

`assembly_number` remains the stable, required real-world identifier and stays unique within a project. The app never generates an assembly number. `name` remains its editable friendly name. `parent_id` continues to represent assembly-number nesting independently of Fishbone section nesting. New saves validate same-project parents, reject self-parenting and cycles, and show the approved soft warning when a child's installed section differs from its parent's built section. Skipping an assembly-number tier requires no flag: it is represented simply by having no assembly record at that Fishbone tier.

#### New `manufacturing_assembly_components`

| Column | Definition | Purpose |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | Stable string UUID for editing, deletion, and audit details. |
| `project_id` | `TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE` | Carries and validates the project boundary. |
| `assembly_id` | `TEXT NOT NULL REFERENCES manufacturing_assemblies(id) ON DELETE CASCADE` | Identifies the assembly whose authoritative mini-BOM owns the row. |
| `fishbone_assignment_id` | `TEXT NOT NULL REFERENCES fishbone_part_assignments(id) ON DELETE CASCADE` | References one exact placed Fishbone part-use. Deleting that use automatically removes this component row. |
| `quantity` | `REAL NOT NULL CHECK(quantity > 0)` | Stores the explicit positive component quantity for this assembly. |
| `created_at` | `TEXT NOT NULL` | UTC creation timestamp. |
| `updated_at` | `TEXT NOT NULL` | UTC latest-change timestamp. |

Enforce `UNIQUE(assembly_id, fishbone_assignment_id)`. Store validation must confirm that the assembly and assignment belong to `project_id` and that, when the component is added or edited, the assignment is currently placed in the assembly's built section. A newly added component defaults to the Fishbone use's current quantity at that moment. Its saved quantity then becomes independent: later Fishbone quantity changes do not update the mini-BOM, and mini-BOM quantity changes do not update Fishbone. The same Fishbone use may appear in any number of different assembly mini-BOMs with a different quantity in each.

If an assembly's own `built_section_id` is changed, every Fishbone use referenced by that assembly's current mini-BOM is moved to the new section in the same atomic transaction. This relocation is unconditional, including when another assembly also references the same use. Parts in the old section that are not in this assembly's mini-BOM remain untouched. Any other assembly whose shared mini-BOM reference no longer matches its built section retains the component row and receives a visible mismatch warning for deliberate review; the row is not silently changed or removed. The same mismatch detection applies if a collaborator separately moves a referenced Fishbone use.

Deleting one or more Fishbone uses must first show exactly which assembly numbers and mini-BOM component rows will be affected. Confirmation proceeds without blocking, and `ON DELETE CASCADE` removes those component rows while leaving the assembly records intact. Section-deletion impact calculations must likewise include mini-BOM rows that will disappear when uses inside the deleted section are removed.

#### Completed existing quantity change

`fishbone_part_assignments.quantity` was safely converted from `INTEGER` to `REAL NOT NULL DEFAULT 1 CHECK(quantity > 0)` after the project owner approved the usage audit. Fishbone and mini-BOM quantities now accept positive decimal values such as `1.5` inches of tape or `0.02` pints of lubricant; zero, negative, nonnumeric, NaN, and infinite values are rejected by the store layer. Fishbone and Process displays use shared clean-number formatting, and history change detection rounds to nine decimal places to avoid false changes from floating-point noise.

#### New `manufacturing_assembly_feature_rules`

| Column | Definition | Purpose |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | Stable string UUID for editing, deletion, warning resolution, and audit details. |
| `project_id` | `TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE` | Carries and validates the project boundary. |
| `assembly_id` | `TEXT NOT NULL REFERENCES manufacturing_assemblies(id) ON DELETE CASCADE` | Identifies the assembly-number owner. |
| `feature_id` | `TEXT NOT NULL REFERENCES complexity_features(id) ON DELETE RESTRICT` | References one generic Model definitions feature and prevents silent feature deletion while a rule exists. |
| `value` | `TEXT NOT NULL` | Stores one choice from the referenced feature's `allowed_values`; the store layer validates it because choices are JSON values rather than foreign-key rows. |
| `created_at` | `TEXT NOT NULL` | UTC creation timestamp. |
| `updated_at` | `TEXT NOT NULL` | UTC latest-change timestamp. |

Enforce `UNIQUE(assembly_id, feature_id)`, so an assembly can have at most one choice for each feature. Rules across features combine with **AND**. An assembly with no rules applies to all models; otherwise, a model matches only when every assembly rule matches its corresponding `model_feature_values` value.

New or changed rules must use a currently active feature and one of its current allowed choices. Deactivating a referenced feature or removing a referenced choice must retain the saved rule and visibly flag it, for example, **Warning: references a removed choice — review and update**. A stale rule evaluates **fail closed** and the assembly matches no model until the rule is corrected or removed. This higher-safety behavior is intentional because assembly applicability will eventually gate whether an authoritative assembly can be selected in Process at a Glance.

This creates two deliberate differences from existing mechanisms:

1. `part_feature_rules` permits multiple alternative choices for one feature and automatically deletes rules whose feature or choice is removed; assembly feature rules permit exactly one choice per feature and never silently auto-delete a stale rule.
2. Stale assembly rules fail closed. The withdrawn section-level qualifying-condition proposal was designed to fail open because it affected only a visual Fishbone filter and should not hide real parts; assembly rules will eventually control higher-stakes Process selectability, so unresolved applicability must not qualify an assembly.

#### New `manufacturing_assembly_images`

| Column | Definition | Purpose |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | Stable supplemental-image UUID. |
| `project_id` | `TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE` | Carries and validates the project boundary. |
| `assembly_id` | `TEXT NOT NULL REFERENCES manufacturing_assemblies(id) ON DELETE CASCADE` | Attaches the image to exactly one assembly number. |
| `image_path` | `TEXT NOT NULL` | Stores the validated uploaded-file path. |
| `caption` | `TEXT DEFAULT ''` | Optional free-text caption; it is not a named image slot or image type. |
| `created_at` | `TEXT NOT NULL` | UTC creation timestamp and stable display ordering. |

The master row's `image_path` holds one primary image; this child table holds unlimited supplemental images. Both primary and supplemental images support validated PNG, JPG/JPEG, and WEBP uploads plus direct screenshot paste. No `image_type`, exploded-view slot, finished-view slot, grouping-level image, or other labeled slot is introduced. Parts Catalog's current image implementation remains unchanged. Deleting an image or assembly removes its owned upload files using the same safe upload-directory checks as Parts Catalog.

#### Section references, replacement, and assembly nesting/deletion

- Fishbone section deletion evaluates the selected sections and every descendant included in the deletion. If none has a linked `yamazumi_areas` row, `process_part_groups` row, or `manufacturing_assemblies` Built/Installed reference, the standard disclosure and confirmed deletion proceed without a continuity target. If any of those references exists, one required same-project target section outside the deletion set applies to every affected Yamazumi, Process at a Glance, and assembly reference. The dialog discloses each category count and keeps **Delete sections** disabled until a valid target is selected.
- Target validation preserves the one-Yamazumi-area-per-section rule across every affected planning scenario. Re-pointing is rejected when the target already owns a Yamazumi area in a scenario that also has an affected source area, or when multiple affected source areas in one scenario would converge on the same target. The dialog reports the active-scenario conflict first and identifies another scenario when applicable. It never merges Yamazumi areas; resolving pitches, work elements, regions, and area settings remains a separate future design.
- Confirmed deletion performs one atomic transaction: re-point affected `yamazumi_areas.section_id` and `process_part_groups.section_id`; generate Built/Installed replacements from `assembly_section_reference_impact()`; call `repoint_assembly_section_references()`; delete remaining Fishbone uses in the deleted sections; and delete the sections and descendants. A Built-section assembly re-point retains Task 04 behavior by relocating every Fishbone use referenced by that assembly's mini-BOM before remaining uses are removed. Those relocated uses survive under the target; every other removed placement returns its Parts Catalog record to **Not placed**.
- Parent-nesting validation compares a child's installed section with its parent's built section. A mismatch opens one save-time warning dialog describing every mismatch. It is never a validation block: dismissing or declining the warning leaves the selected parent valid and the save may proceed with that choice.
- Direct assembly deletion uses the Universal Deletion Standard and one upfront dialog showing the complete affected descendant tree. For each child depth/level, the contributor selects one action for that whole level: **Move to grandparent**, **Delete entirely**, or **Become unassigned**. Every level is shown in the same dialog, including levels below a group marked Delete entirely; each deeper level still receives its own explicit destination choice rather than inheriting an unseen cascade decision.
- **Move to grandparent** assigns that level's surviving assemblies to the next surviving parent level while retaining their built section, installed section, mini-BOM, rules, and images. **Become unassigned** clears `parent_id`, `built_section_id`, and `installed_section_id`, removing the assemblies from catalog nesting and Fishbone built/installed lists without deleting their records; their retained mini-BOM rows are visibly mismatched until deliberately reassigned. **Delete entirely** removes the chosen assembly rows and their owned mini-BOM rows, feature rules, images, and uploaded files after all deeper-level choices have been validated.
- The upfront dialog must disclose all affected catalog records, mini-BOM rows, rule rows, image rows/files, child levels, and existing dormant `assembly_scenario_policies`, `work_element_material_options`, and target-assembly links. Dormant references remain uneditable in this phase, but their actual foreign-key cascade or unassignment effects must never be omitted from the confirmation. The complete multi-level action validates before one atomic database write; no sequential per-level pop-ups or partial application is allowed.

#### Store-layer functions

Add isolated, project-bound store functions with no scenario-policy coupling:

- `assembly_catalog_rows(project_id)`
- `save_assembly_catalog_rows(project_id, rows)`
- `assembly_catalog_delete_impact(project_id, assembly_ids)`
- `delete_assembly_catalog_rows(project_id, assembly_ids, level_actions)`
- `assembly_bom_components(project_id, assembly_id)`
- `save_assembly_bom_components(project_id, assembly_id, rows)`
- `assembly_feature_rules(project_id, assembly_id)`
- `save_assembly_feature_rules(project_id, assembly_id, rows)`
- `assembly_model_applicability(project_id, assembly_id)`
- `assembly_images(project_id, assembly_id)`
- `set_assembly_image(project_id, assembly_id, uploaded_file)`
- `add_assembly_image(project_id, assembly_id, uploaded_file, caption='')`
- `delete_assembly_images(project_id, assembly_id, image_ids)`
- `assemblies_for_section(project_id, section_id)`
- `fishbone_assignment_assembly_impact(project_id, assignment_ids)`
- `assembly_section_reference_impact(project_id, section_ids)`
- `repoint_assembly_section_references(project_id, replacements, connection=None)`
- `assembly_section_delete_impact(project_id, section_ids)`
- `assembly_section_delete_target_validation(project_id, section_ids, target_section_id, active_scenario_id=None)`
- `delete_assembly_sections(project_id, section_ids, target_section_id=None, active_scenario_id=None)`

All writes validate project ownership, complete input sets, required fields, uniqueness, parent cycles, positive quantities, section/component consistency, file types, and stale-rule restrictions before changing data. Multi-table operations use one connection so catalog changes, mini-BOM relocation, re-pointing, and deletion remain atomic. Expected failures raise user-readable `ValueError` messages.

#### UI and applicable standards

- Add a new **Assemblies** page and navigation item under Product structure. The page provides the full editor for catalog fields, built/installed sections, parent nesting, mini-BOM, feature rules, primary/supplemental images, and the warning/deletion workflows above. `pits_reference`, `planning_reason`, and every scenario-policy field stay hidden.
- The main catalog table shows Assembly number, Assembly name, Built section, Installed section, Parent assembly, Active, Notes, and Details. It supports filters, direct blank-row entry and multi-row paste, external sorting, native row selection, filtered export, validation, Undo, and the standard **Save & Refresh** footer.
- The selected assembly's mini-BOM editor offers only exact Fishbone uses currently in its built section for new rows, displays clear part-number/use context, and stores its independent decimal quantity. The feature-rule editor uses controlled feature/choice options, shows an AND-based plain-language summary, and retains visible stale rows and warnings. Image controls support upload and screenshot paste for both primary and supplemental images.
- Parts to fishbone shows only a lightweight read-only list for the selected section. An assembly appears for both relationships, labeled **Built here** and/or **Installed here**; when both references point to the selected section, both relationships are shown. Each row displays the assembly number and a Details action that navigates to the shared Assemblies page and selects that same underlying record. No assembly editing is added to Fishbone.
- Follow every locked `DESIGN_SYSTEM.md` standard: `page_title_with_scope()` with a Project-wide badge and standard hover text; native table selection/select-all; native confirmed deletion; direct row creation; filters and sorting above tables; orange Unsaved changes, Undo, and blue **Save & Refresh** immediately below each editable table; editor resets and reruns; Current editor attribution; `record_audit_event()` for every save, deletion, image action, re-pointing, and bulk action; and a bottom History expander with tabs when multiple assembly workflow categories are shown. Use stable UUIDs internally, friendly assembly/section labels in the UI, plain-language help for built versus installed sections, Material Symbols, native bordered containers, and no new general CSS.

- **Out of scope:** Process at a Glance assembly selection, output-assembly-milestone linking, handling/sub-touch chains, exploded-BOM comparison, make/buy and scenario-policy behavior, and multi-touch/sub-touch support. Do not modify or build UI against `assembly_scenario_policies`, `work_element_material_groups`, or `work_element_material_options` except to disclose their existing foreign-key effects during an approved assembly deletion.

### Section-level qualifying-condition feature rules (OR across features) — Withdrawn

- **Status:** **Withdrawn — reverted before merge by project owner decision, August 27, 2026.** This section is retained only as a decision record. The table, store behavior, Fishbone UI, filter integration, and feature-specific tests described below are not part of the active application or schema and must not be restored without a new approved proposal.
- **Proposed by:** Nicole Ervin, project owner
- **Date proposed:** August 25, 2026
- **Purpose:** Add a separate, additive set of qualifying conditions to a Fishbone section. Each condition is exactly one manufacturing feature plus one allowed choice. Multiple conditions attached to the same section combine with OR. Existing `part_feature_rules` remain unchanged and continue using their current same-feature-alternatives/different-features-AND behavior.
- **Connections:** Conditions belong to `assembly_sections` and reference `complexity_features`. The Phase 1 Fishbone filter compares the selected feature/choice identity directly with section conditions and existing part rules; it does not require resolving a complete official model through `model_feature_values`. A condition affects only `fishbone_part_assignments` whose `section_id` directly references that exact section. Conditions do not flow from parent sections into nested subassemblies, and this feature must not query, modify, or evaluate the blocked `fishbone_nodes` MBOM-review staging table.
- **Relationship to the critical thread:** The new rows sit between project-wide Model definitions and the project-wide Fishbone framework: `complexity_features` -> `assembly_section_feature_conditions` -> `assembly_sections` -> `fishbone_part_assignments` -> `parts` / existing `part_feature_rules`. Conditions are evaluated dynamically rather than copied into each Fishbone-use row, so every directly placed use inherits its section's current rule without per-use tagging or duplicated persisted applicability.
- **Scope:** Project-wide. The Parts to fishbone page remains Scenario-aware because scenario-specific part activity controls which uses are visible, but the inline qualifying-condition subsection must carry its own **Project-wide** scope indicator. Changes affect the section in every scenario.
- **Storage:** Add the normalized table `assembly_section_feature_conditions`. A separate table is required because one section can own zero or more independently editable feature/choice pairs and because reusing `part_feature_rules` would mix two different owners and logical operators. Do not add a JSON condition column to `assembly_sections` and do not modify the schema or interpretation of `part_feature_rules`.

  | Column | Definition | Purpose |
  | --- | --- | --- |
  | `id` | `TEXT PRIMARY KEY` | Stable string UUID for editing, deletion, and audit details. |
  | `project_id` | `TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE` | Carries and validates the project boundary. |
  | `section_id` | `TEXT NOT NULL REFERENCES assembly_sections(id) ON DELETE CASCADE` | Makes one exact Fishbone section the condition owner. Deleting that section deletes its condition rows. |
  | `feature_id` | `TEXT NOT NULL REFERENCES complexity_features(id) ON DELETE RESTRICT` | References a generic Model definitions feature. `ON DELETE RESTRICT` is an intentional, owner-approved deviation from the original cascade proposal: a referenced feature cannot be deleted until its saved section conditions are deliberately resolved, preventing silent deletion or hiding of condition data. |
  | `value` | `TEXT NOT NULL` | Stores one choice from the referenced feature's current `allowed_values`. Choices are currently JSON values on `complexity_features`, so the store layer must validate this value rather than relying on a choice-table foreign key. |
  | `created_at` | `TEXT NOT NULL` | UTC creation timestamp. |
  | `updated_at` | `TEXT NOT NULL` | UTC latest-change timestamp. |

  Enforce `UNIQUE(section_id, feature_id, value)` so the same condition cannot be attached to one section twice. Store-layer validation must confirm that the section and feature belong to `project_id`. New or edited conditions must use a currently available feature/choice pair.
- **Evaluation logic:** The existing **View fishbone for features** control remains a simple feature/choice membership lookup and does not require selecting or resolving a complete official model. For each selected feature/choice, a section passes when it has no conditions or any saved condition references the selected pair. A part passes when it has no part-level rule or its existing rule set references the selected pair. A Fishbone use appears only when both the section lookup and part lookup pass. Multiple selected filter choices retain the control's existing any-selected membership behavior. Existing `part_feature_rules` storage and full model-applicability behavior must not be modified, replaced, or reinterpreted. Only the Parts to fishbone visual and its existing feature filter consume the combined lookup in this phase; Excel export and every other project-wide or downstream view are deferred.
- **Stale-condition preservation and evaluation:** Deactivating a referenced feature or removing a referenced choice must not delete or hide its saved condition. The store layer and inline UI must retain it and visibly flag it in the summary, for example, **Warning: references a removed choice — review and update**. While unresolved, that individual stale condition evaluates **fail open** and imposes no model restriction. Because section conditions combine with OR, the presence of a stale condition keeps the section gate open for every model until a collaborator corrects or removes it. The warning is the only signal: stale conditions do not block filtering, stop other model matching, or stall unrelated page work. This follows the approved default-open convention and prevents stale references from silently hiding real Fishbone uses.
- **UI:** On Parts to fishbone, selecting a Fishbone section reveals an inline condition editor beneath that section. Its approved horizontal builder presents a Feature dropdown, a dependent Choice dropdown containing only that feature's current allowed values, and **Add condition**. Additions remain unsaved until the resulting condition list's standard **Save & Refresh** action. The editor shows a live plain-language summary from the unsaved draft, such as **This section applies to models where: Brand = Acme OR Product Line = Commercial**. No standalone rules-management screen or per-row dialog is added. Any collaborator may edit these conditions; this is not IE-exclusive ownership.
- **Applicable standards:** Follow every locked table standard in `DESIGN_SYSTEM.md`: direct entry where supported, native row selection, external sorting when row creation disables native sorting, orange unsaved warning, Undo, and the blue **Save & Refresh** footer; validation before atomic store-layer writes; editor reset and rerun; Current editor attribution; `record_audit_event()` for saves and deletions; and the page's bottom History expander. Native deletion must use a confirmed workflow. The section-deletion confirmation must disclose the exact number of qualifying-condition rows that will be cascade-deleted with the section.
- **Phase boundary:** This phase does not modify or build against the dormant Phase 2 Assemblies catalog (`manufacturing_assemblies` or `assembly_scenario_policies`) and does not extend effective applicability into Phase 3 Process at a Glance integration, exports, or other screens.
- **Decision history:** Nicole Ervin approved Phase 1 implementation on August 26, 2026, then withdrew it before merge on August 27, 2026. The independent preservation of the original **View fishbone for features** behavior and the separate Fishbone section-deletion Yamazumi/Process re-pointing correction are not part of this withdrawal.

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
- **Purpose:** Add project-wide navigation shells for Equipment, Ergonomics, Quality, Materials, and Safety functional reviews.
- **Potential connections:** Future review records may connect to Parts, Fishbone sections, Yamazumi records, Process at a Glance steps, planning scenarios, or other approved critical-thread entities.
- **Relationship to the critical thread:** Exact relationships and foreign keys are intentionally not defined in this shell phase. The project owner approved navigation-only, non-persistent shells before those relationships are designed. No persisted review fields may be added until each relationship is approved.
- **Scope:** The Functional Reviews navigation group and its five shell pages are project-wide. Future review content may be project-wide or scenario-specific, but every persisted record type must receive one explicit scope before implementation.
- **Storage:** No database table or field is added in this phase. Each shell contains only browser-session description state and an empty, schema-free table. Existing tables cannot be selected or ruled out until the review fields and relationships are defined.
- **Applicable standards:** All locked standards in `DESIGN_SYSTEM.md` apply, including table row selection, deletion safety, Save & Refresh, audit logging for persisted changes, History placement, Scenario Boundary badges, help text, canonical terminology, stable identifiers, and imperial units where relevant.
- **Approval status:** Nicole Ervin approved this shell-only exception. The data model, ownership, relationships, and persisted fields remain pending owner review.

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

`manufacturing_assemblies` is now an active catalog table documented above. Its `pits_reference` and `planning_reason` fields, the legacy scenario-coupled reader/writer, and every make/buy or policy behavior remain parked and must not be exposed or modified by the active Assemblies workflow.

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
      ├── explicit project-wide assembly mini-BOMs + assembly applicability
      ↓ section link
Scenario-specific Yamazumi areas → pitches → work elements
      ↓ explicit reconciliation
Scenario-specific Process at a Glance steps
      ↓
Process part groups → paired catalog parts from a fishbone section
      ↓
Scenario-specific Pin Map (derived visual view)
      ↓
Quality functional review (future home for requirements; persisted design pending)
```
