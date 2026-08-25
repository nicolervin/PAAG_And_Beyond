# Project status

_Reviewed August 25, 2026_

## What this project is

Process at a Glance is a local planning app for cross-functional collaborators preparing a new assembly process. It is intended to keep the product definition, parts, assembly order, work steps, timing, workstation balance, requirements, and open questions together instead of spreading them across separate spreadsheets.

The app is still a prototype. It runs on one computer, stores its records and uploaded images locally, and starts with sample data when no data file exists.

## Main screens and features

- **Overview** — Creates projects, shows headline counts, and edits the project definition. Its standard Planning scenarios table lists current and previous branches (including archived scenarios), supports filtering, direct entry and multi-row paste, external saved-row sorting, filtered Excel export, row Details, and audit history. Saving a new row clones the currently viewed scenario's scenario-owned planning data and makes the new branch the shared scenario view across pages.
- **Questions and concerns** — Keeps questions, concerns, decisions, and assumptions with owners, priority, status, and links to parts or stations.
- **Import PITS and export** — Imports ordinary Excel/CSV bills of material, the preferred ID-based PITS workbook, or older Level 1–11 PITS sheets. The ID-based route keeps source revisions and flags changed records for review. It also exports a multi-sheet Excel planning snapshot, including a flat sheet for Lucid data linking.
- **Model definitions** — Maintains official model numbers, team-friendly names, annual volumes, and active/inactive planning choices. It also defines product features and maps each model to its feature choices.
- **Parts Catalog** — Maintains the part catalog, feature-based model applicability, revision, notes, and source. Its scenario-specific Active checkbox hides inactive parts from downstream Fishbone, Process at a Glance, Pin Map-linked work, and scenario-export views while preserving their catalog records and saved links. Parts can have a main CAD image plus extra views; image controls live in Part Details and pasted Windows screenshots save immediately as the Primary CAD image. The main table supports filtering, direct row entry and multi-row paste, external sorting, selected-row actions, deletion confirmation, Excel export, and a limited history view.
- **Parts to fishbone** — Builds the product's assembly framework, including main sections and nested subassemblies. Collaborators can place approved catalog parts into that framework, record quantities and uses, order them, and view the result as an interactive fishbone with images and feature filtering.
- **Yamazumi** — Creates/imports pitch addresses and work elements, defines work regions and flags, compares model variants, and lets collaborators drag work between north- and south-side pitches. It also supports named planning scenarios, scenario-specific takt times, and confirmed native-toolbar deletion for pitches, work elements, work regions, and custom flags.
- **Process at a Glance** — Brings selected Yamazumi work into an ordered plan and pairs fishbone parts with the work that consumes them. Synced work and paired parts leave the upper source queues and appear in the compact pitch table, which shows Pitch, Yamazumi Pitch Name and Work Element, Paired Fishbone Parts, Models, Time, Details, Status, and Seq. A tabbed per-step dialog captures description, completed assemblies, tools, location, unit orientation, and conveyor height in inches, and also allows an incorrect part pairing to be removed so its parts return to the source queue. Orientation and conveyor height can be copied to every existing Process step tied to the same Fishbone section in the active scenario. The pairing workspace can search for similar catalog parts across every Fishbone section, choose a target section from the project when placing a part, move or add an existing use, or create a minimally complete catalog part and Fishbone placement without leaving the page. It also includes filtering, bulk edits/deletes, imperial-unit Excel export, a simple workload chart, and history.
- **Pin Map** — Presents the active scenario as a read-only line map, placing explicitly linked Process at a Glance work above each Yamazumi workstation or pitch. It supports area, pitch-status, pitch-type, and keyword filters plus a filtered Excel export.
- **Quality** — Remains a clean, non-persistent functional-review shell and is the approved future home for requirements content. The former Requirements page has been removed rather than copied into the shell.

## What is working now

- The main app opens, finds the current projects and scenarios, and renders the Overview screen without an error.
- All active screens display the locked Scenario Boundary badge and hover explanation. The concise **Scenario-specific** and **Scenario-aware** badges leave the active scenario name and revision to the adjacent synchronized dropdown. Overview also labels its project-definition and active-scenario sections separately. The dropdown selection persists across page navigation for the browser session and drives downstream scenario views. Every scenario-specific page also places the shared blue Save as scenario action beside that dropdown, allowing Yamazumi, Process at a Glance, Pin Map, and future scenario-specific screens to create branches that appear in Overview's Planning scenarios table.
- The navigation contains 14 screens: Overview, Questions and concerns, Import PITS and export, Model definitions, Parts Catalog, Parts to fishbone, Yamazumi, Process at a Glance, Pin Map, and the five non-persistent Functional Reviews shells. The established screens and Process at a Glance detail dialog have passed prior smoke checks; Pin Map is covered by its own smoke check.
- All Python files pass a syntax/import compilation check with the installed packages.
- The committed `unittest` suite currently passes 18 tests covering planning-scenario behavior, scope selectors, shared direct-entry sorting and deletion-target interpretation, and Pin Map data derivation.
- The current project data file is populated, rather than being only an empty demonstration. Across the file it currently contains 2 projects, 2 planning scenarios, 17 model records, 20 parts, 172 current PITS records with 172 saved source revisions, 808 PITS/MBOM review rows, 6 fishbone sections, 9 placed part uses, 3 process-plan work elements, and 2 pitch addresses.
- Excel snapshot generation works against the current data. The test workbook was produced successfully with 13 sheets covering the project, scenario, parts, work, concerns, MBOM review, fishbone, PITS history, models, and Lucid data link.
- The app already has meaningful safeguards in its newer tables: required-field checks, preservation of rows hidden by filters, undo for unsaved edits, confirmation for supported bulk deletes, and editor/timestamp history for selected workflows.
- Row-creating tables accept direct typing and spreadsheet-style multi-row paste through the native blank entry row. Their shared external sort controls preserve saved-row ordering and lock while drafts or row selections are present so positions cannot shift underneath unsaved work.
- Tables with approved deletion workflows expose Streamlit's native **Delete row(s)** action after one or more rows are selected. The action opens a relationship-aware confirmation dialog; Cancel restores the rows and confirmation records the deletion in history.
- Editable tables place their orange unsaved warning, Undo control, and blue **Save & Refresh** action together in a right-aligned footer immediately below the table, leaving filters and sorting controls above it.

These checks confirm that the screens can load and that export can be generated. They do not prove every button, drag-and-drop action, upload format, or multi-step editing path end to end.

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
