# Process at a Glance developer guide

This file is the fast onboarding guide and working agreement for developers and AI assistants changing this repository. Read it before editing the app. `README.md` gives a shorter product summary, while `PROJECT_STATUS.md` records the latest known working and incomplete areas.

## What this application is

Process at a Glance (PAAG) is a local planning application for industrial engineers and lean/manufacturing teams preparing a new-product-introduction assembly process.

It brings information that would otherwise be spread across several spreadsheets into one evolving project record. The app covers:

- project and planning assumptions;
- official models and manufacturing-relevant product options;
- parts, revisions, source information, and CAD images;
- imported PITS and bill-of-material data;
- a station-independent assembly fishbone;
- Yamazumi work content and workstation balancing;
- an ordered process plan with tools, torque, quality, ergonomic, and workstation requirements;
- questions, concerns, decisions, and assumptions; and
- an Excel snapshot for review or Lucid data linking.

The application is currently a local prototype, not a production multi-user service. Its main users are industrial engineers, with manufacturing, lean, quality, ergonomics, design, and other cross-functional contributors supplying or reviewing information.

## Technology and how the app runs

### Main technology

- **Language:** Python.
- **Application framework:** Streamlit 1.61 or newer, but below 2.0.
- **Table/data handling:** pandas.
- **Local data storage:** SQLite in `data/paag.db`.
- **Excel import/export:** openpyxl, with pandas used for tabular conversion.
- **Images:** Pillow for validation and normalization. Uploaded images are stored under `data/uploads/` and their paths are stored in SQLite.
- **Custom browser interactions:** Streamlit Components v2 with small inline HTML, CSS, and JavaScript components. These power clipboard image paste, the interactive fishbone, and Yamazumi drag-and-drop.
- **Theme:** `.streamlit/config.toml` defines the app colors, corner radii, and a 50 MB upload limit.

The exact package ranges are in `requirements.txt`. The shared Python virtual environment normally lives one directory above this repository at `..\.venv`.

### Running the app

From the repository root in PowerShell:

```powershell
..\.venv\Scripts\streamlit.exe run streamlit_app.py
```

Then open `http://localhost:8501` in a browser. Streamlit normally reloads the app when a source file is saved.

`streamlit_app.py` calls `init_db()` on startup. The initialization code creates missing tables, applies small in-place schema upgrades used by this prototype, installs required built-in Yamazumi flags, and seeds a sample project when appropriate.

SQLite foreign-key checks are enabled and the database uses write-ahead logging. Database writes go through the `connection()` context manager in `utils/store.py`, which commits at the end of a successful block and always closes the connection.

### Local and generated data

- `data/paag.db`, its SQLite sidecar files, and `data/uploads/` are local runtime data and are ignored by Git.
- `.streamlit/secrets.toml` is ignored and must never be committed.
- Do not assume local data can be recovered from Git. Make a copy of `data/paag.db` before experiments that intentionally remove or rewrite real planning data.
- Temporary directories at the repository root are not application source. Do not build new features around them or commit them.

## Repository structure

### Root files and folders

- `streamlit_app.py` — The entry point. It configures the page, initializes the database, establishes the active project and scenario in session state, defines the page navigation, renders the sidebar, and records the browser session's Current editor name.
- `app_pages/` — Direct Streamlit page scripts. A page file renders when selected; page bodies are intentionally not wrapped in a `main()` or render function.
- `utils/` — Shared data access, import/export, table behavior, image handling, and custom visual components. Put reusable business logic here rather than copying it between pages.
- `data/` — Runtime SQLite database and uploaded files. It is not source code.
- `.streamlit/config.toml` — Native Streamlit theme and upload-size settings.
- `requirements.txt` — Python dependencies and supported version ranges.
- `README.md` — Short product description, run command, and scope overview.
- `PROJECT_STATUS.md` — Plain-English snapshot of working, incomplete, and deferred areas. Update it when a material status statement changes.
- `AGENTS.md` — This onboarding and contribution guide.
- `.gitignore` — Excludes Python caches, the local environment, secrets, the database, and uploaded images.

### Page files

- `app_pages/overview.py` — Project creation and definition, headline counts, default takt, and active-scenario name, revision, takt, and change summary.
- `app_pages/concerns.py` — Editable questions, concerns, decisions, and assumptions.
- `app_pages/exchange.py` — Ordinary BOM import, preferred ID-based PITS import, legacy Level 1–11 PITS import, previews/mapping, and Excel snapshot export.
- `app_pages/models.py` — Official model catalog, team-friendly model definitions, estimated annual usage, feature definitions, and the model-to-feature complexity tree.
- `app_pages/parts.py` — Part catalog, feature applicability, primary and supplemental images, direct Windows screenshot paste, filters, bulk actions, export, and history.
- `app_pages/fishbone.py` — Assembly framework, nested subassemblies, catalog-part placement, occurrence ordering, and the interactive fishbone visualization.
- `app_pages/yamazumi.py` — Planning-scenario branching, Yamazumi import/reset, assembly areas, pitch generation, work regions, flags, model variants, the interactive balancing board, and editable pitch/work-element tables.
- `app_pages/process.py` — Pairs fishbone parts to Yamazumi work, reconciles selected work into the process plan, captures process requirements, supports bulk actions and export, and shows a simple workload-by-pitch chart.
- `app_pages/requirements.py` — Read-only review of tooling, torque, quality, ergonomics, material, location, and geometry requirements by process step.
- `app_pages/assembly_sequence.py` — Older assembly-fishbone page retained in the repository but not linked from the current navigation. Treat it as legacy code; do not add features to it unless the user explicitly asks to revive it.

### Shared utility files

- `utils/store.py` — SQLite schema, startup initialization, seed data, queries, validation, CRUD operations, scenario cloning, snapshots/restore operations, history recording, and file storage. This is the main business/data layer.
- `utils/excel_io.py` — Reads ordinary BOM files, recognizes and parses current and legacy PITS formats, suggests column mappings, and builds the multi-sheet Excel export.
- `utils/table_ui.py` — Shared editable-table header, unsaved-change detection, native selected-row interpretation, required-field checks, details-button configuration, and filtered-table Excel export.
- `utils/table_filters.py` — Keyword/dropdown filters, multi-value filtering, merging filtered edits back into the full table, and reliable editor-reset helpers.
- `utils/yamazumi_board.py` — Components v2 Yamazumi board. It displays odd pitch addresses on the north/top side, even addresses on the south/bottom side, variant stacks, timed work blocks, flags, and drag/edit/add events.
- `utils/fishbone_visual.py` — Components v2 interactive assembly fishbone with pan, zoom, full-screen view, part cards, thumbnails, and hover details.
- `utils/clipboard_image.py` — Components v2 clipboard capture plus server-side image validation and conversion into an upload-like object.
- `utils/__init__.py` — Marks `utils` as a Python package.

## Navigation and screens

The current navigation is defined only in `streamlit_app.py` and is grouped as follows.

### Project

#### Overview

Creates a new NPI project and edits the active project's identity, program/product, product line, lead industrial engineer, baseline revision, status, default takt, and notes. It shows counts for parts, work elements, draft cycle time versus takt, and open concerns. It also edits the active planning scenario without changing other scenarios.

#### Questions & concerns

Tracks cross-functional questions, concerns, decisions, and assumptions with subject, detail, owner, priority, status, related part, related station, and creation time.

### Product structure

#### Import PITS & export

Supports three import routes:

1. The preferred PITS workbook with `part_tracker` and `models` sheets. `ID Number` is treated as the stable source key. Reimporting an unchanged ID does not overwrite IE decisions; changed source content creates a source revision and a reconciliation item.
2. Legacy PITS sheets with repeated Level 1–11 columns. These rows are conservative review candidates; the Level values are not guessed to be quantities, sequences, or model codes.
3. Ordinary Excel, CSV, TSV, or text BOM data with user-confirmed column mapping.

The page also creates a one-way Excel snapshot. Its sheets cover the project, active scenario, parts, work elements, concerns, MBOM review, fishbone, PITS history, models, and a flattened `Lucid Data Link` view.

#### Model definitions

Maintains source model numbers and the names/descriptions familiar to the IE team. Models can be activated or hidden from planning choices. The page also defines manufacturing-relevant features and allowed choices, then maps each official model to one choice for every active feature.

#### Parts

Maintains one catalog record per official part number. It records description, revision, provenance/source, notes, and feature-based model applicability. It supports a primary CAD image, additional image views, file upload, and direct Windows screenshot paste. New parts are created in the blank table row; persisted parts then receive photos and detailed actions.

#### Parts to fishbone

Builds the assembly framework before workstation balancing. Main-spine sections establish the product's assembly order; subassemblies attach to a parent section or another subassembly. Approved part-catalog entries can have one or more placed uses, each with quantity, use description, notes, section, and order. The interactive visual can be filtered by feature choice.

### Process planning

#### Yamazumi & balancing

Creates or imports balancing areas, pitch addresses, and work elements inside the active planning scenario. Users can:

- branch the current plan with Save as scenario;
- reset selected or all Yamazumi data with confirmation;
- create areas from fishbone sections;
- generate ranges of odd, even, or all pitch addresses;
- define area-specific work regions and project-wide flags;
- enable model-variant stacks on pitches;
- add and edit pitches or work elements;
- drag work between active pitches on the visual board; and
- edit the same records directly in tables.

#### Process plan

Starts from Yamazumi work rather than creating unrelated duplicate work. The upper workspace selects a fishbone section, one Yamazumi work element, and one or more part uses, then records whether all parts are used, one alternative is chosen, or the parts are optional. The main table orders the work by pitch and captures time, output-assembly milestones, tools, torque, quality, ergonomics, location, conveyor/platform height, pit depth, model applicability, and status.

#### Requirements

Provides a read-only, pitch-filtered review of the requirements already entered in Process plan. Process plan remains the source for edits.

## Glossary

- **NPI** — New product introduction: the work required to prepare a product and its manufacturing process for production.
- **IE** — Industrial engineer. The primary user and decision owner in this prototype.
- **BOM** — Bill of material: a list of parts or assemblies required for a product.
- **MBOM** — Manufacturing bill of material: the manufacturing-reviewed product structure. Imported PITS candidates are not automatically accepted as approved MBOM content.
- **PITS** — The upstream product-information/workbook format used by this project. The preferred format has a stable `ID Number` in `part_tracker` and model definitions in `models`. Older Level 1–11 files are also recognized but intentionally interpreted conservatively.
- **PITS record/revision** — The latest imported source row for a stable PITS ID and its saved earlier source versions. Source revisions preserve what changed without silently rewriting IE-authored planning decisions.
- **Part catalog** — The project's approved list of part numbers, descriptions, revisions, images, provenance, and applicability rules.
- **Fishbone** — A station-independent view of assembly order. Its main spine is the product flow; fins/branches represent subassemblies and placed part uses. Build this before assigning physical work locations.
- **Framework section** — A named assembly stage on the fishbone. A Main spine section is part of the main product flow. A Subassembly attaches to a parent.
- **Part use/occurrence** — One placement or installation of a catalog part in the fishbone. The same catalog part can appear more than once for different uses.
- **Yamazumi** — A visual workload-balancing method. Work elements are stacked by pitch and compared with takt time. Colors distinguish cycle, periodic, and fluctuation work.
- **Yamazumi area** — The balancing scope, usually tied to a fishbone section, within one planning scenario.
- **Pitch** — A physical work position/address along the line. In the visual board, addresses ending in odd numbers appear north/top and even numbers south/bottom.
- **Pitch type** — The role of a pitch: Pitch, Waterspider, Subassembly, Kitter, or Repacker.
- **Pitch status** — Active pitches can receive work. Open and Blocked pitches remain visible but cannot receive work until activated.
- **Takt time** — The target number of seconds available per completed unit, based on demand. Workload is compared with takt to show whether a pitch is over or under the target.
- **Planning scenario** — A named branch of Yamazumi and Process plan data with its own revision label, takt, and lineage. Save as scenario copies the current plan so alternatives can be explored without mixing their work records.
- **Model** — An official product/model number imported from PITS or entered manually. A team-friendly display name can be added without replacing the official identifier.
- **Feature / complexity feature** — A manufacturing-relevant product characteristic, such as a door or control configuration, with a controlled list of choices.
- **Model variant** — A Yamazumi stack representing Base work or a specific feature choice. Base applies to every model; feature variants show additional or different work.
- **Model applicability** — The rule that determines which model configurations need a part or process step. Parts use feature rules; older records may still contain legacy model-number text.
- **Work element** — One measurable piece of work with a description, time, type, region, flags, variant, and optional pitch assignment.
- **Cycle / Periodic / Fluctuation work** — Cycle work happens each unit; periodic work happens at a planned interval; fluctuation work varies with product mix or conditions.
- **Work region** — An area-specific category used to group or color the nature/location of Yamazumi work.
- **Flag** — A visible work-element tag. CTQ and Safety are system flags; projects can add custom flags. CTQ means critical to quality.
- **Process plan** — The ordered, scenario-specific manufacturing steps by pitch, enriched with parts and detailed execution requirements.
- **Part requirement / selection rule** — A group of parts paired to a process step. Use all means every listed part is consumed, Choose one means alternatives, and Optional means the group may not apply.
- **Output assembly milestone** — The exact process step at which a new made assembly becomes complete. Purchased assemblies remain ordinary catalog parts.
- **Current editor** — The name entered in the sidebar for the browser session. Standardized table history records it; this is attribution, not authentication.
- **Lucid Data Link** — A flat worksheet intended for linking the exported snapshot into Lucid. It is not a live two-way connection.

## Coding and design conventions

### General Python and page structure

- Follow the existing Python style: `snake_case` for functions, variables, widget keys, and modules; `UPPER_SNAKE_CASE` for constants; and short descriptive helper names.
- Use string UUIDs for persisted record IDs (`str(uuid4())`). Do not invent sequential database IDs.
- Store timestamps as UTC ISO strings using `now_iso()`.
- Keep Streamlit page files as direct scripts. Do not add `if __name__ == "__main__"` or wrap a page in a `main()` function.
- Keep page code focused on presentation and user interaction. Put reusable data rules, validation, transactions, and transformations in `utils/`.
- Read `project_id` and, where relevant, `scenario_id` from `st.session_state`. Stop early when required context is missing. Confirm that the selected scenario still exists before using it.
- Give repeated or dynamic widgets stable, descriptive keys. Include the relevant project, scenario, area, section, or record ID when the same control can exist in different scopes.
- Use `st.rerun()` after a successful write when the displayed data must be reloaded. Use a scoped rerun only where an existing fragment/dialog pattern requires it.
- Prefer native Streamlit elements. Use Components v2 only for interactions native Streamlit cannot provide, as with clipboard capture and the two interactive visuals.
- Use Material Symbols (`:material/...:`), sentence-case labels, native bordered containers, and the project theme. Do not add general CSS styling unless a custom component truly needs its own encapsulated styles.
- Use `width="stretch"` or `width="content"`; do not introduce deprecated `use_container_width`.

### Data access and database changes

- All normal reads and writes belong in `utils/store.py`; pages should call named store functions instead of opening SQLite directly.
- Use parameterized SQL for values. Never build SQL by inserting user-entered text into the statement.
- Keep foreign-key behavior explicit and preserve project/scenario boundaries in every query.
- A planning scenario owns its Yamazumi areas and Process plan work. Do not query or update scenario-specific records using project ID alone when that could mix scenarios.
- Validate before writing. Store functions should raise `ValueError` with a user-readable message for expected validation failures; pages should catch it and show `st.error` or a warning.
- For multi-table operations, use one `connection()` block so the change commits together.
- This prototype currently performs schema creation and small upgrades inside `init_db()` rather than using a separate migration tool. New schema changes must be safe to run repeatedly and must preserve existing local data.
- Return tabular results as pandas DataFrames when pages need table operations.
- **Always give empty editable DataFrames explicit dtypes.** A cleared table must still declare text columns as `string`, booleans as `bool`, and numeric columns as appropriate. `pd.DataFrame(columns=[...])` or `reindex()` alone can infer empty columns as floats and make `st.data_editor` reject a `TextColumn`. The Yamazumi work-region loader is the reference fix for this case.
- Uploaded files must remain under `data/uploads/`. Validate file type/size, generate safe unique filenames, and store paths rather than binary image contents in SQLite.

### Streamlit state and undo

- Streamlit reruns the full active page after most interactions. Treat `st.session_state` as browser-session state, not permanent storage.
- Apply `apply_pending_table_editor_reset(editor_key)` before constructing an editor whose prior state may need clearing.
- After a successful save or delete, call `request_table_editor_reset(editor_key)` and rerun so stale row edits and selections do not replay.
- Unsaved-change Undo normally clears the editor's session-state entry and reruns.
- Some complex screens keep a pre-save snapshot in session state so the last saved change can be restored. Follow the existing model/fishbone snapshot pattern when a multi-table operation genuinely needs saved-state Undo.
- Session-state Undo is intentionally limited to the current browser session. It is not a durable audit or version-control system.
- Do not let a one-shot custom-component click replay on later page reruns. Consume or clear its trigger state as the Yamazumi dialogs do.

### Editable table standard

Use `utils/table_ui.py` and `utils/table_filters.py` for every new editable table or tab. Match this interaction pattern:

- Put the section title, orange unsaved-changes indicator, Undo control, and blue **Save & refresh** button on one line at the top. Use `editable_table_header()` unless there is a documented reason it cannot fit.
- Support direct cell editing and direct row creation whenever the data model permits it.
- Use Streamlit's native selected/deleted-row state through `num_rows="dynamic"` or `num_rows="delete"`. The unlabeled square in the upper-left must select all currently visible rows, matching Order assigned parts.
- Do not add a named `CheckboxColumn` or a separate Select all control to simulate selection.
- Read selected persisted rows with `native_selected_rows()`. Treat selection as transient UI state, not an unsaved business-data edit. Use `table_has_unsaved_changes(..., native_row_selection=True)` where selection must be excluded from change detection.
- Prevent a normal save while persisted rows remain selected; selection is reserved for bulk actions.
- Put keyword and relevant dropdown filters above every table with `filter_table()`.
- When saving a filtered table, use `merge_filtered_edits()` so rows hidden by the current filters are preserved.
- Do not change existing column sizing unless the user specifically asks for it.
- Mark required fields in `st.column_config` and validate them again with `required_field_errors()` or store-layer validation before writing.
- Validate the complete bulk operation before making any write. Do not partially apply a bulk change when one selected record is invalid.
- Provide bulk editing for meaningful shared fields and bulk deletion for persisted selected rows.
- Require a confirmation dialog before bulk deletion. State what related data will also be removed or unassigned.
- Keep a convenient individual-row Delete action where appropriate. Use a `ButtonColumn` callback and block it when unrelated unsaved edits would make the target ambiguous.
- Use the shared Details/Edit button configuration for consistent row actions.
- Include an Excel export of the currently filtered table using `dataframe_to_excel()`.
- After a successful save, bulk edit, or delete: write the data, record history, request an editor reset, show a toast, and rerun.
- Record standardized saves, bulk edits, and bulk deletions with `record_audit_event()`. Include the timestamp supplied by the store layer and `st.session_state.get("current_editor", "")`. Expose a nearby history expander or toggle using `audit_history()`.
- Do not impose Draft/In review/Approved statuses as a universal standard. Status options are specific to the business table.

A typical save flow is:

1. Read the filtered editor output and native selection.
2. Refuse a normal save if persisted rows remain selected.
3. Validate required fields and business rules.
4. Merge filtered edits into the full unfiltered DataFrame.
5. Convert display labels back to stored identifiers or codes.
6. Call one store-layer save function.
7. Record the audit event with Current editor.
8. Request the editor reset, show a success toast, and rerun.

### Filtering and display values

- Keep stored identifiers stable and separate from friendly labels. For example, store official model numbers but display team-friendly names when helpful.
- Convert multi-value database fields into lists before giving them to `MultiselectColumn`, then convert them back to the stored representation before saving.
- Use the `universal_values` option in `filter_table()` for values such as All models that should match every specific choice.
- Filters must affect the visible/exported view only. They must not delete or overwrite filtered-out records on save.
- Hide internal IDs in the UI but retain them in the DataFrame used to resolve callbacks and writes. Remember that hiding a column is visual only; remove truly sensitive fields before sending data to the browser.

### History and attribution

- `audit_log` is the standardized lightweight history store. It records table/workflow name, action, row count, Current editor, optional JSON details, and timestamp.
- Keep action names consistent, such as `Save & refresh`, `Bulk edit`, `Bulk delete`, `Delete`, `Pair parts`, or `Remove pairing`.
- Current editor is free text scoped to the browser session. Never describe it as authenticated identity.
- Audit coverage is still incomplete. When modernizing an older editable table, add standardized history rather than inventing a second history mechanism.

### Import/export behavior

- Treat PITS as source evidence, not automatic approval. Changed source records must enter reconciliation without silently overwriting IE-authored MBOM/fishbone decisions.
- Preserve the stable PITS ID and revision history for the preferred workbook format.
- Keep legacy Level 1–11 parsing conservative. Do not infer business meaning that the source does not state.
- Preview and validate imports before applying them. Ordinary BOM imports require an explicit part-number mapping.
- Export uses the active project and active scenario. Preserve stable, flat sheet names expected by downstream spreadsheet/Lucid users unless a requested change explicitly coordinates the break.

### Custom components

- The custom component code lives beside its Python wrapper in `utils/clipboard_image.py`, `utils/fishbone_visual.py`, or `utils/yamazumi_board.py`.
- Keep component input data JSON-serializable and callbacks narrow. Persist actual business changes through store functions in the Python page callback, not directly in browser JavaScript.
- Escape user-provided text before inserting it into component HTML.
- When a front-end component change needs clients to reload a new component definition, follow the existing versioned component-name pattern.
- Test both empty and populated component inputs. The board must retain an Unassigned destination and must not allow work to be dropped onto Open or Blocked pitches.

### Verification expectations

- There is currently no committed automated test suite. Use checks proportional to the change.
- At minimum, compile changed Python files with the shared environment.
- For page/data changes, run Streamlit `AppTest` smoke checks where supported, using a real project/scenario context and checking `a.exception`.
- For database changes, test empty and populated results without rewriting the user's real data. Prefer a temporary database or a read-only query for diagnostics.
- For Excel changes, generate a workbook in memory and open it with openpyxl to confirm the expected sheets.
- Clipboard, upload, drag-and-drop, full-screen fishbone, and other browser-only behavior require a manual browser check because `AppTest` cannot fully exercise them.
- Preserve unrelated working-tree changes. Do not reset, overwrite, or reformat files outside the requested scope.

## Known incomplete or intentionally deferred areas

### Incomplete current workflows

- Bulk deletion of pitch addresses is not complete. Reassignment rules must be finalized before selected pitches can be safely removed.
- Bulk deletion of Yamazumi work elements is not complete. Individual deletion exists, but the selected-row workflow remains forthcoming.
- The Lucid export is a one-way workbook snapshot. There is no controlled live/two-way synchronization or final identifier strategy.
- Standard history is partial. Parts, Process plan, and several Yamazumi operations use it, but not every editable screen or individual engineering change does.
- The editable-table standard is not yet applied consistently to older screens. Questions & concerns is the clearest gap; model and fishbone tables also contain mixed-generation patterns.
- `app_pages/assembly_sequence.py` is legacy/unlinked code.

### Deferred product capabilities

- User accounts, sign-in, roles, and permissions
- Safe simultaneous editing by multiple people
- A complete, immutable audit trail for every IE change
- Threaded comments and notifications
- Packaging and routing plans
- PFMEA
- Control plans
- Work instructions
- A production deployment and shared server-backed database
- Controlled Lucid synchronization

### Testing gaps

- No repository test suite currently guards save, delete, clone, import, or reconciliation behavior.
- The repository does not contain a maintained set of representative ordinary BOM, current PITS, and legacy PITS fixtures.
- The three custom browser components do not have automated browser tests.

When implementing deferred work, preserve the current rule that imported source data informs planning but does not silently replace an industrial engineer's reviewed decisions.
