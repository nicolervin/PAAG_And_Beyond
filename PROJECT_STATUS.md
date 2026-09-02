# Project status

_Reviewed September 2, 2026_

## What this project is

Process at a Glance is a local planning app for cross-functional collaborators preparing a new assembly process. It is intended to keep the product definition, parts, assembly order, work steps, timing, workstation balance, requirements, and open questions together instead of spreading them across separate spreadsheets.

The app is still a prototype. It runs on one computer, stores its records and uploaded images locally, and starts with sample data when no data file exists.

## Main screens and features

- **Overview** — Creates projects, shows headline counts, and edits the project definition. Its standard Planning scenarios table lists current and previous branches (including archived scenarios), supports filtering, direct entry and multi-row paste, external saved-row sorting, filtered Excel export, row Details, and audit history. Saving a new row clones the currently viewed scenario's scenario-owned planning data and makes the new branch the shared scenario view across pages.
- **Questions and concerns** — Keeps questions, concerns, decisions, and assumptions with owners, priority, status, and links to parts or stations.
- **Import PITS and export** — Imports ordinary Excel/CSV bills of material, the preferred ID-based PITS workbook, or older Level 1–11 PITS sheets. The ID-based route keeps source revisions and flags changed records for review. It also exports a multi-sheet Excel planning snapshot, including a flat sheet for Lucid data linking.
- **Model definitions** — Maintains official model numbers, team-friendly names, annual volumes, and active/inactive planning choices. It also defines product features and maps each model to its feature choices.
- **Parts Catalog** — Maintains the part catalog, feature-based model applicability, revision, notes, and source. Its scenario-specific Active checkbox hides inactive parts from downstream Fishbone, Process at a Glance, Pin Map-linked work, and scenario-export views while preserving their catalog records and saved links. Parts can have a main CAD image plus extra views; image controls live in Part Details and pasted Windows screenshots save immediately as the Primary CAD image. The main table supports filtering, direct row entry and multi-row paste, external sorting, selected-row actions, deletion confirmation, Excel export, and a limited history view.
- **Assemblies** — Maintains the project-wide catalog of real assembly numbers with separate Built and Installed Fishbone sections, project-wide Make / buy classification, parent nesting, explicit decimal mini-BOMs sourced from exact Fishbone uses, one-choice-per-feature AND applicability, stale-rule warnings that fail closed, primary and supplemental screenshot-capable images, full deletion impact disclosure, and standardized history. Dormant scenario-policy fields remain isolated from this workflow.
- **Parts to fishbone** — Builds the product's assembly framework, including main sections and nested subassemblies. Collaborators can place approved catalog parts into that framework, record positive decimal quantities and uses, order them, and view the result as an interactive fishbone with images and feature filtering. A lightweight section-level list opens related assembly numbers on the shared Assemblies page. Section deletion uses one combined continuity target for affected Yamazumi areas, Process at a Glance part requirements, and assembly Built/Installed references; validates Yamazumi uniqueness across scenarios; relocates mini-BOM uses for Built-section changes; and returns every other removed placement to Not placed.
- **Yamazumi** — Creates/imports pitch addresses and work elements, defines work regions and flags, compares model variants, and lets collaborators drag work between north- and south-side pitches. It also supports named planning scenarios, scenario-specific takt times, and confirmed native-toolbar deletion for pitches, work elements, work regions, and custom flags.
- **Process at a Glance** — Brings selected Yamazumi work into an ordered plan and pairs fishbone parts with the work that consumes them. Synced work and paired parts leave the upper source queues and appear in the compact pitch table, which shows Pitch, Yamazumi Pitch Name and Work Element, Paired Fishbone Parts, Models, Time, Details, Status, and Seq. A tabbed per-step dialog captures description, completed assemblies, tools, location, unit orientation, and conveyor height in inches, and also allows an incorrect part pairing to be removed so its parts return to the source queue. Orientation and conveyor height can be copied to every existing Process step tied to the same Fishbone section in the active scenario. The pairing workspace can search for similar catalog parts across every Fishbone section, choose a target section from the project when placing a part, move or add an existing use, or create a minimally complete catalog part and Fishbone placement without leaving the page. It also includes filtering, bulk edits/deletes, imperial-unit Excel export, a simple workload chart, and history.
- **Pin Map** — Presents the active scenario as a read-only line map, placing explicitly linked Process at a Glance work above each Yamazumi workstation or pitch. It supports area, pitch-status, pitch-type, and keyword filters plus a filtered Excel export.
- **Quality** — Remains a clean, non-persistent functional-review shell and is the approved future home for requirements content. The former Requirements page has been removed rather than copied into the shell.

## What is working now

- The main app opens, finds the current projects and scenarios, and renders the Overview screen without an error.
- All active screens display the locked Scenario Boundary badge and hover explanation. The concise **Scenario-specific** and **Scenario-aware** badges leave the active scenario name and revision to the adjacent synchronized dropdown. Overview also labels its project-definition and active-scenario sections separately. The dropdown selection persists across page navigation for the browser session and drives downstream scenario views. Every scenario-specific page also places the shared blue Save as scenario action beside that dropdown, allowing Yamazumi, Process at a Glance, Pin Map, and future scenario-specific screens to create branches that appear in Overview's Planning scenarios table.
- The navigation contains 15 screens: Overview, Questions and concerns, Import PITS and export, Model definitions, Parts Catalog, Assemblies, Parts to fishbone, Yamazumi, Process at a Glance, Pin Map, and the five non-persistent Functional Reviews shells. The established screens and Process at a Glance detail dialog have passed prior smoke checks; Assemblies has empty and populated AppTest coverage, and Pin Map is covered by its own smoke check.
- All Python files pass a syntax/import compilation check with the installed packages.
- The committed `unittest` suite currently passes 43 tests covering planning-scenario behavior, scope selectors, shared direct-entry sorting and deletion-target interpretation, decimal Fishbone quantity migration and export, Assemblies catalog isolation/mini-BOM/rule/re-pointing/deletion behavior, combined Fishbone section continuity re-pointing, saved-state Undo, cross-scenario Yamazumi conflict prevention, dual Built/Installed Fishbone listing, duplicate-feature-rule rejection, and Pin Map data derivation.
- The current project data file is populated, rather than being only an empty demonstration. Across the file it currently contains 2 projects, 2 planning scenarios, 17 model records, 20 parts, 172 current PITS records with 172 saved source revisions, 808 PITS/MBOM review rows, 6 fishbone sections, 9 placed part uses, 3 process-plan work elements, and 2 pitch addresses.
- Excel snapshot generation works against the current data. The test workbook was produced successfully with 13 sheets covering the project, scenario, parts, work, concerns, MBOM review, fishbone, PITS history, models, and Lucid data link.
- The app already has meaningful safeguards in its newer tables: required-field checks, preservation of rows hidden by filters, undo for unsaved edits, confirmation for supported bulk deletes, and editor/timestamp history for selected workflows.
- Row-creating tables accept direct typing and spreadsheet-style multi-row paste through the native blank entry row. Their shared external sort controls preserve saved-row ordering and lock while drafts or row selections are present so positions cannot shift underneath unsaved work.
- Tables with approved deletion workflows expose Streamlit's native **Delete row(s)** action after one or more rows are selected. The action opens a relationship-aware confirmation dialog; Cancel restores the rows and confirmation records the deletion in history.
- Editable tables place their orange unsaved warning, Undo control, and blue **Save & Refresh** action together in a right-aligned footer immediately below the table, leaving filters and sorting controls above it.

These checks confirm that the screens can load and that export can be generated. They do not prove every button, drag-and-drop action, upload format, or multi-step editing path end to end.

## Confirmed designs pending implementation

### Task 09 — Grid-based assembly-to-model mapping

The project owner confirmed the schema and interaction design on September 2, 2026; implementation has not started and still requires an explicit go-ahead. The existing Assemblies infrastructure remains intact, but `app_pages/assemblies.py` will become a project-wide, section-selected grid as the primary entry point. Each row will be a persisted EBOM category with official and plain-English names, a shared root number, row order, and one authoritative Installed section. Each active-model cell will map that category directly to one real `manufacturing_assemblies` record. Components remain that mapped assembly's existing `manufacturing_assembly_components` rows, and `manufacturing_assembly_feature_rules` remains independent.

The confirmed new project-wide tables are `assembly_grid_categories`, `assembly_grid_model_mappings`, and `assembly_grid_feature_visibility`. Active features appear by default; inactive features never render. Model filtering is browser-session state only. Root-plus-suffix entry and full-number override are unsaved conveniences; only the final assembly relationship is persisted. The Components v2 grid has a documented screen-specific selection/deletion exception, but Python retains every non-dismissible confirmation, relationship disclosure, validation, atomic write, audit, reset, toast, and rerun requirement.

Category Installed section uses continuous synchronization. Changing it through **Save & Refresh** atomically updates every distinct currently mapped assembly, while a conflicting existing assembly is blocked from being mapped silently. A mapped assembly's Installed section is managed by its category; after the final mapping is removed, the assembly retains its last value and becomes independently editable. One real assembly may serve multiple models only inside one category. Project-wide validation blocks any final state that maps one `manufacturing_assemblies.id` to more than one distinct category, while allowing a complete atomic move between categories.

After implementation approval, the local database will be backed up and existing prototype assembly records and their dependents will be cleared through the documented validated reset. No reset has occurred yet.

### Task 03 continuity extension required by Task 09

The current implemented Fishbone section-deletion workflow detects four continuity reference types: Yamazumi areas, Process at a Glance part requirements, assembly Built sections, and assembly Installed sections. Task 09 must extend it before the new grid becomes active to include category Built sections and category Installed sections under the same one-target picker.

The confirmed pending work extends `assembly_section_delete_impact()`, target validation, `delete_assembly_sections()`, and the combined disclosure dialog. The target validator will retain cross-scenario Yamazumi protection and reject category collisions on trimmed, case-insensitive official EBOM category name or Display name. Every rejection will identify the target section, incoming category, exact colliding field and value, and conflicting target or incoming category, then instruct the contributor to choose a different target. No inline rename flow is planned.

The six reference types will be re-pointed in one transaction. Source-section feature-visibility preferences will be disclosed and removed rather than merged into the target. Fishbone saved-state Undo will be repaired by adding Task 09 categories, mappings, and preferences to `fishbone_plan_snapshot()` and `restore_fishbone_plan_snapshot()`, preserving stable identifiers and avoiding `ON DELETE RESTRICT` failures or lost grid data.

## Unfinished or broken

### Incomplete workflows

- The export to Lucid is a one-way snapshot only. There is no controlled ongoing synchronization or settled Lucid identifier strategy yet.
- Change history is partial rather than complete. Parts, process-planning, and several Yamazumi actions record standardized history, but not every editable screen and not every individual engineering change does so.
- Some older editable sections still do not provide the same bulk tools or audit coverage, even though their save-action placement now follows the shared table-footer pattern.
- `app_pages/assembly_sequence.py` is an older assembly-fishbone page that is no longer linked in the app navigation. It appears to be leftover code alongside the newer Parts to fishbone screen.

### Product areas deliberately left for later

- User accounts, sign-in, permissions, and safe simultaneous editing by multiple people
- A complete audit trail for all collaborator edits
- Threaded comments and collaboration
- Packaging and routing plans
- PFMEA, control plans, and work instructions
- A production deployment and shared server-backed data store

### Verification gaps

- The automated suite remains small and does not exercise most editing, confirmation, save, deletion, or audit workflows. Compilation and page smoke checks therefore remain necessary, and browser-only behavior can still regress without being caught automatically.
- Import parsing was inspected but not tested with a set of saved example workbooks in the repository. Ordinary BOM, current PITS, and legacy PITS variations therefore depend heavily on real-file testing.
- Image upload, clipboard paste, the interactive fishbone, and Yamazumi drag-and-drop need browser-level tests; the available smoke check cannot fully exercise them.

## Overall assessment

The project has grown beyond a simple mock-up: the core product structure, model/part planning, fishbone, Process at a Glance workflow, scenario-specific Pin Map, local persistence, revision-aware PITS import, scenario branching, and Excel export are substantially present. Quality is the approved future home for requirements review. The highest-value remaining work is to bring the remaining editable screens up to the shared table standard and add repeatable tests around imports and the major save and deletion paths.
