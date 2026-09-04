# Process at a Glance

Process at a Glance (PAAG) is a local Streamlit planning application for cross-functional collaborators preparing a new-product-introduction assembly process. It keeps product definitions, source evidence, parts, assembly order, work content, workstation balance, process requirements, and open questions in one evolving project record instead of separate spreadsheets.

The application is a local prototype, not a production multi-user service. Industrial engineers, advanced quality engineers, ergonomists, materials planners, advanced manufacturing engineers, and other collaborators may all contribute to the project record.

## Documentation map

- `AGENTS.md` — Repository-wide contribution rules and required-reference routing.
- `DATA_DICTIONARY.md` — Authoritative database entities, relationships, scope, critical thread, proposals, and dormant data structures.
- `DESIGN_SYSTEM.md` — Locked table, interaction, audit, scope-indicator, help-text, units, and terminology standards.
- `PROJECT_STATUS.md` — Latest known working, incomplete, deferred, legacy, and verification status.
- `README.md` — Product overview, technology, startup, repository map, navigation, and domain glossary.

When documentation conflicts, use the authority order defined in `AGENTS.md` and resolve unresolved discrepancies with the project owner.

## Run locally

From the repository root in PowerShell, using the shared virtual environment:

```powershell
..\.venv\Scripts\streamlit.exe run streamlit_app.py
```

Then open `http://localhost:8501`. Streamlit normally reloads the app after a source file is saved.

`streamlit_app.py` calls `init_db()` at startup. Initialization creates missing tables, applies safe in-place schema upgrades used by this prototype, installs required built-in Yamazumi flags, and seeds a sample project when appropriate.

## Technology and local data

- **Language:** Python
- **Application framework:** Streamlit 1.61 or newer, below 2.0
- **Tabular data:** pandas
- **Local storage:** SQLite in `data/paag.db`, with foreign keys enabled and write-ahead logging
- **Excel:** openpyxl with pandas tabular conversion
- **Images:** Pillow validation and normalization; uploaded files under `data/uploads/`
- **Browser interactions:** Streamlit Components v2 for clipboard image paste, the interactive Fishbone, and Yamazumi drag-and-drop
- **Theme:** `.streamlit/config.toml`, including the upload-size limit

Exact package ranges are in `requirements.txt`. The shared Python virtual environment normally lives one directory above the repository at `..\.venv`.

Database writes go through the `connection()` context manager in `utils/store.py`, which commits successful operations and always closes the connection. The database, its SQLite sidecars, uploaded files, and `.streamlit/secrets.toml` are local runtime data ignored by Git. They cannot be recovered from Git, so back up the database before intentionally destructive experiments.

## Current product scope

PAAG currently supports:

- project definitions, planning assumptions, and named planning scenarios;
- official models, team-friendly names, annual usage, manufacturing features, and controlled model-to-feature mappings;
- a Parts Catalog with revision, provenance, applicability, primary and supplemental CAD images, and scenario-specific Active state;
- a project-wide Assembly grid with a protected packaged-unit row followed by Fishbone-section categories mapped to real assembly numbers by official model, with shared section controls, nested mini-BOMs, and access to the full catalog details workflow;
- ordinary BOM imports, preferred ID-based PITS imports, conservative legacy PITS imports, source revisions, and reconciliation evidence;
- a station-independent assembly Fishbone with main-spine sections, nested subassemblies, and placed part uses;
- Yamazumi balancing areas, pitch addresses, model variants, work regions, flags, takt comparison, and drag-and-drop work assignment;
- an ordered Process at a Glance plan reconciled from Yamazumi work and paired to Fishbone parts;
- process tools, locations, unit orientation, dimensional geometry, and other requirements retained by the current schema;
- a scenario-specific, derived Pin Map of pitches and reconciled Process work;
- questions, concerns, decisions, and assumptions; and
- a multi-sheet Excel snapshot with a flat `Lucid Data Link` worksheet.

See `PROJECT_STATUS.md` for the precise distinction between working, incomplete, and deferred behavior.

## Repository map

### Root

- `streamlit_app.py` — Entry point, page configuration, database initialization, active project/scenario session state, navigation, sidebar, and Current editor attribution.
- `app_pages/` — Direct Streamlit page scripts. Page bodies intentionally are not wrapped in `main()` functions.
- `utils/` — Shared business/data access, import/export, table behavior, scope UI, image handling, and custom components.
- `data/` — Ignored local database and uploaded runtime files; not application source.
- `.streamlit/config.toml` — Native Streamlit theme and upload settings.
- `requirements.txt` — Supported dependency ranges.

### Active page files

- `app_pages/overview.py` — Project definition, headline counts, default takt, and active-scenario metadata.
- `app_pages/concerns.py` — Questions, concerns, decisions, and assumptions.
- `app_pages/exchange.py` — Ordinary BOM and PITS imports, preview/mapping, and Excel snapshot export.
- `app_pages/models.py` — Model catalog, common names, usage, manufacturing features, and the model-feature complexity tree.
- `app_pages/parts.py` — Parts Catalog, applicability, images, filters, bulk actions, export, and history.
- `app_pages/assemblies.py` — Project-wide multi-section assembly-to-model grid plus the shared full assembly catalog, operational mini-BOM nesting, image, deletion, and history workflows.
- `utils/assembly_grid.py` — Components v2 category/model grid renderer and its narrow interaction event contract.
- `app_pages/fishbone.py` — Assembly framework, nested subassemblies, part placement, occurrence ordering, and the interactive Fishbone.
- `app_pages/yamazumi.py` — Scenario branching, balancing areas, pitches, regions, flags, model variants, visual board, and work tables.
- `app_pages/process.py` — Yamazumi reconciliation, Fishbone part pairing, ordered process requirements, bulk actions, export, and workload chart.
- `app_pages/pin_map.py` — Scenario-specific read-only line visualization of pitches and explicitly linked Process work.
- `app_pages/functional_*.py` — Non-persistent Equipment, Ergonomics, Quality, Materials, and Safety review shells.
- `app_pages/assembly_sequence.py` — Legacy, unlinked assembly-Fishbone implementation; do not extend unless explicitly revived.

### Shared utility files

- `utils/store.py` — Schema, initialization, validation, CRUD, scenario cloning, snapshots, history, and file storage.
- `utils/excel_io.py` — BOM/PITS parsing, column mapping, and multi-sheet export.
- `utils/table_ui.py` — Shared table headers, selection interpretation, change detection, required-field checks, row actions, resets, and export helpers.
- `utils/table_filters.py` — Keyword/dropdown filters, filtered-edit merging, multi-value filters, and editor reset behavior.
- `utils/scope_ui.py` — Scenario Boundary titles, section headings, scenario selectors, and Save as scenario controls.
- `utils/yamazumi_board.py` — Components v2 balancing board.
- `utils/fishbone_visual.py` — Components v2 interactive assembly Fishbone.
- `utils/clipboard_image.py` — Components v2 clipboard capture and server-side image normalization.
- `utils/functional_review_ui.py` — Shared shell for the five Functional Reviews pages.

## Navigation and screens

Navigation is defined in `streamlit_app.py`.

### Project

- **Overview** creates and edits the project identity and active planning scenario, and shows project-level counts and takt comparisons.
- **Questions and concerns** tracks cross-functional questions, concerns, decisions, and assumptions with ownership, priority, status, and related context.

### Product structure

- **Import PITS and export** accepts ordinary BOM data, the preferred `part_tracker` plus `models` PITS format, and legacy Level 1–11 PITS data. Preferred imports use `ID Number` as the stable source key; changed source content creates a revision and reconciliation item instead of overwriting reviewed planning decisions. The page also creates the one-way Excel snapshot.
- **Model definitions** maintains official model numbers, common names, descriptions, annual usage, manufacturing features, allowed feature choices, and model-to-feature mappings.
- **Parts Catalog** maintains one approved record per official part number. Catalog data is project-wide while Active state is scenario-specific. Completed manufacturing assemblies are linked catalog parts so a built subassembly can be placed on the Fishbone and handled again downstream; their model applicability comes from Assembly grid mappings. The page supports primary and supplemental images, including direct Windows screenshot paste.
- **Assembly grid** begins with one protected Top-level packaged unit row immediately below the active feature headers, followed by one or more selected Fishbone sections as labeled grid groups. The top row maps one final warehouse-handoff assembly per active official model, has a selectable final Built section and optional Installed section, and can nest completed subassemblies from every active Fishbone section. Section categories map their own real assembly numbers per model. Creating an assembly creates or reuses its linked completed-subassembly Parts Catalog row in the same save. Quantity-bearing mini-BOM links use automatic Fishbone-use placement, model-coverage validation, and cycle prevention. Category section values continuously synchronize mapped assemblies. Changing a saved cell to another same-category assembly's existing number opens a confirmed merge that redirects the old mappings, reuses the target mini-BOM and catalog part, and deletes the disclosed superseded assembly. Details opens with Images first, Mini-BOM second, and retains catalog editing for Make / buy, optional legacy parent grouping, and full deletion. Legacy assembly feature rules are not shown or evaluated.
- **Parts to fishbone** defines the station-independent assembly sequence through ordered main-spine sections, nested subassemblies, and one or more placed uses of approved catalog parts.

### Process planning

- **Yamazumi** creates or imports areas, pitch addresses, and measurable work inside the active planning scenario. It supports scenario branching, takt, work regions, flags, model-variant stacks, and visual work balancing.
- **Process at a Glance** starts from reconciled Yamazumi work, pairs it to Fishbone parts, orders it by pitch, and captures detailed execution requirements and output-assembly milestones.
- **Pin Map** derives a scenario-specific read-only line view from existing pitches, Yamazumi elements, and explicitly linked Process work. It stores no separate layout data.

### Functional Reviews

**Equipment**, **Ergonomics**, **Quality**, **Materials**, and **Safety** are project-wide, non-persistent shells. Quality is the approved future home for requirements-review content. Persisted relationships, ownership, scope, and storage require proposal and owner review before implementation.

## Domain glossary

- **NPI** — New product introduction: preparing a product and its manufacturing process for production.
- **IE** — Industrial engineer, one of several functional roles contributing to PAAG.
- **BOM** — Bill of material: a list of parts or assemblies required for a product.
- **MBOM** — Manufacturing bill of material: the collaborator-reviewed manufacturing product structure. Imported candidates are not automatically approved MBOM content.
- **PITS** — The upstream product-information workbook. The preferred format has stable `ID Number` values in `part_tracker` and definitions in `models`; older Level 1–11 formats are interpreted conservatively.
- **PITS record/revision** — The latest imported source row for a stable PITS ID and its preserved earlier source versions.
- **Parts Catalog** — The approved project-wide list of part numbers, names, revisions, images, provenance, and applicability.
- **Assembly grid** — The project-wide category-by-model mapping view whose cells reference real assembly records and whose nested rows reuse each assembly's explicit mini-BOM.
- **Assemblies catalog** — The authoritative project-wide list of real assembly numbers and their explicit mini-BOMs, built and installed sections, optional parent grouping, applicability, and images, retained as the grid's full Details workflow. Quantity-bearing operational nesting comes from completed subassemblies used in those mini-BOMs.
- **Fishbone** — The station-independent assembly-order view whose main spine represents product flow and whose branches represent subassemblies and placed parts.
- **Fishbone section** — A named assembly stage, either on the main spine or attached as a subassembly.
- **Fishbone use** — One placement or installation occurrence of a catalog part. The same part may have multiple uses.
- **Yamazumi** — A workload-balancing method that stacks timed work by pitch and compares it with takt.
- **Yamazumi area** — A balancing scope, usually connected to a Fishbone section, within one scenario.
- **Pitch** — A physical work position or address. Odd addresses render north/top and even addresses south/bottom on the visual board.
- **Pitch type** — Pitch, Waterspider, Subassembly, Kitter, or Repacker.
- **Pitch status** — Active pitches accept work; Open and Blocked pitches remain visible but cannot receive work.
- **Takt time** — Target seconds available per completed unit based on demand.
- **Planning scenario** — A named branch of Yamazumi and Process data with its own revision, takt, and lineage.
- **Model** — An official product/model number. A separate common name can change without replacing the stable identifier.
- **Complexity feature** — A manufacturing-relevant product characteristic with controlled choices.
- **Model variant** — A Yamazumi stack for Base work or a specific feature choice.
- **Model applicability** — The rule identifying which configurations require a part or Process step.
- **Work element** — One measurable item of work with description, time, type, region, flags, variant, and optional pitch.
- **Cycle / Periodic / Fluctuation work** — Work performed per unit, at a planned interval, or variably according to mix or conditions.
- **Work region** — An area-specific category grouping the nature or location of Yamazumi work.
- **Flag** — A visible Yamazumi tag; CTQ and Safety are built-in system flags.
- **Process at a Glance** — The ordered scenario-specific manufacturing plan enriched with parts and execution requirements.
- **Part requirement** — A group of parts paired to a Process step using `Use all`, `Choose one`, or `Optional` selection behavior.
- **Output assembly milestone** — The exact Process step where a new made assembly becomes complete.
- **Current editor** — Free-text browser-session attribution recorded in standardized history; it is not authentication.
- **Lucid Data Link** — A flat exported worksheet intended for Lucid linking, not live two-way synchronization.

For exact UI labels, use the locked Canonical Terminology Glossary in `DESIGN_SYSTEM.md`.
