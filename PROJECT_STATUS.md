# Project status

_Reviewed August 17, 2026_

## What this project is

Process at a Glance is a local planning app for industrial engineers preparing a new assembly process. It is intended to keep the product definition, parts, assembly order, work steps, timing, workstation balance, requirements, and open questions together instead of spreading them across separate spreadsheets.

The app is still a prototype. It runs on one computer, stores its records and uploaded images locally, and starts with sample data when no data file exists.

## Main screens and features

- **Overview** — Creates projects, shows headline counts, edits the project definition, and manages the active planning scenario and its takt time. A scenario can be copied so an engineer can try a different balance without overwriting the earlier one.
- **Questions and concerns** — Keeps questions, concerns, decisions, and assumptions with owners, priority, status, and links to parts or stations.
- **Import PITS & export** — Imports ordinary Excel/CSV bills of material, the preferred ID-based PITS workbook, or older Level 1–11 PITS sheets. The ID-based route keeps source revisions and flags changed records for review. It also exports a multi-sheet Excel planning snapshot, including a flat sheet for Lucid data linking.
- **Model definitions** — Maintains official model numbers, team-friendly names, annual volumes, and active/inactive planning choices. It also defines product features and maps each model to its feature choices.
- **Parts** — Maintains the part catalog, feature-based model applicability, revision, notes, and source. Parts can have a main CAD image plus extra views; Windows screenshots can be pasted directly. The main table supports filtering, editing, adding rows, selected-row actions, deletion confirmation, Excel export, and a limited history view.
- **Parts to fishbone** — Builds the product's assembly framework, including main sections and nested subassemblies. Engineers can place approved catalog parts into that framework, record quantities and uses, order them, and view the result as an interactive fishbone with images and feature filtering.
- **Yamazumi & workstation balancing** — Creates/imports pitch addresses and work elements, defines work regions and flags, compares model variants, and lets engineers drag work between north- and south-side pitches. It also supports named planning scenarios and scenario-specific takt times.
- **Process plan** — Brings selected Yamazumi work into an ordered plan, pairs fishbone parts with the work that consumes them, records the step that completes a made assembly, and captures time, tools, torque, quality, ergonomics, location, heights, pit depth, model coverage, and status. It includes filtering, bulk edits/deletes, Excel export, a simple workload chart, and history.
- **Requirements** — Presents the process-plan details as a read-only requirements review, grouped by work element and filterable by pitch.

## What is working now

- The main app opens, finds the current projects and scenarios, and renders the Overview screen without an error.
- All nine navigated screens rendered successfully in automated smoke checks against the current local data: Overview, Questions and concerns, Import and export, Model definitions, Parts, Parts to fishbone, Yamazumi, Process plan, and Requirements.
- All Python files pass a syntax/import compilation check with the installed packages.
- The current project data file is populated, rather than being only an empty demonstration. Across the file it currently contains 2 projects, 2 planning scenarios, 17 model records, 20 parts, 172 current PITS records with 172 saved source revisions, 808 PITS/MBOM review rows, 6 fishbone sections, 9 placed part uses, 3 process-plan work elements, and 2 pitch addresses.
- Excel snapshot generation works against the current data. The test workbook was produced successfully with 13 sheets covering the project, scenario, parts, work, concerns, MBOM review, fishbone, PITS history, models, and Lucid data link.
- The app already has meaningful safeguards in its newer tables: required-field checks, preservation of rows hidden by filters, undo for unsaved edits, confirmation for supported bulk deletes, and editor/timestamp history for selected workflows.

These checks confirm that the screens can load and that export can be generated. They do not prove every button, drag-and-drop action, upload format, or multi-step editing path end to end.

## Unfinished or broken

### Incomplete workflows

- Bulk deletion of pitch addresses is not finished. Selecting pitches and saving shows a message that deletion will be added after work-reassignment rules are settled.
- Bulk deletion of Yamazumi work elements is also not finished. Individual deletion exists, but the selected-row workflow is still described in the app as forthcoming.
- The export to Lucid is a one-way snapshot only. There is no controlled ongoing synchronization or settled Lucid identifier strategy yet.
- Change history is partial rather than complete. Parts, process-planning, and several Yamazumi actions record standardized history, but not every editable screen and not every individual engineering change does so.
- The editable-table experience is inconsistent across older screens. For example, Questions and concerns lacks the newer shared header, Excel export, selected-row bulk tools, deletion confirmation, editor attribution, and history. Model and fishbone tables also use a mixture of older and newer patterns.
- `app_pages/assembly_sequence.py` is an older assembly-fishbone page that is no longer linked in the app navigation. It appears to be leftover code alongside the newer Parts to fishbone screen.

### Product areas deliberately left for later

- User accounts, sign-in, permissions, and safe simultaneous editing by multiple people
- A complete audit trail for all industrial-engineering edits
- Threaded comments and collaboration
- Packaging and routing plans
- PFMEA, control plans, and work instructions
- A production deployment and shared server-backed data store

### Verification gaps

- There is no automated test suite in the repository. The current review used compilation checks and screen smoke checks, so future changes can still break editing or saving behavior without being caught automatically.
- Import parsing was inspected but not tested with a set of saved example workbooks in the repository. Ordinary BOM, current PITS, and legacy PITS variations therefore depend heavily on real-file testing.
- Image upload, clipboard paste, the interactive fishbone, and Yamazumi drag-and-drop need browser-level tests; the available smoke check cannot fully exercise them.

## Overall assessment

The project has grown beyond a simple mock-up: the core product structure, model/part planning, fishbone, process plan, requirements review, local persistence, revision-aware PITS import, scenario branching, and Excel export are substantially present. The highest-value remaining work is to finish safe Yamazumi bulk deletion, bring the remaining editable screens up to the shared table standard, and add repeatable tests around imports and the major save/delete paths.
