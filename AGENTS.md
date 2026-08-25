# Process at a Glance developer guide

This file contains the repository-wide working agreement for developers and AI assistants. Keep it focused on instructions that apply broadly; descriptive product material belongs in the supporting documents below.

## Required references and authority

Read this file before changing the application. Then read the applicable authoritative references in full before acting:

- **Database schema, persisted fields, relationships, scope, or a new screen/module:** read `DATA_DICTIONARY.md`.
- **Tables, forms, page layout, deletion, save behavior, audit/history, scenario badges, help text, or UI terminology:** read `DESIGN_SYSTEM.md`.
- **Incomplete, deferred, dormant, blocked, or legacy behavior:** read `PROJECT_STATUS.md` and the applicable `DATA_DICTIONARY.md` section.
- **Product scope, navigation, repository map, technology, startup, or domain terminology:** read `README.md`.

When a task crosses categories, read every applicable reference. `DATA_DICTIONARY.md` controls the data model and scope; `DESIGN_SYSTEM.md` controls locked UI behavior; `PROJECT_STATUS.md` records current implementation status; `README.md` is descriptive. If code or documentation conflicts with an authoritative reference, stop and resolve the discrepancy with the project owner before extending it.

Read `DATA_DICTIONARY.md` and `DESIGN_SYSTEM.md` in full before creating any new table, persisted field, screen, or module.

## Collaborator roles and ownership

This project is maintained by multiple functions: Industrial Engineer (IE), Advanced Quality Engineer (AQE), Ergonomist, Materials Planner, Advanced Manufacturing Engineer, and other cross-functional collaborators.

- Treat general-task uses of "IE" or "industrial engineer" in older documentation, comments, or UI copy as "collaborator" or "contributor" when the work is not role-specific.
- Preserve genuinely role-specific ownership. For example, future Quality/AQE ownership of torque and quality specifications must not be generalized to every collaborator.
- Adding a role name to the contributor roster is lightweight and needs only a name plus a one-line description here.
- Assigning a role ownership or exclusive control of a data type, table, or module is a critical-thread decision requiring project-owner approval. Never infer or self-assign it.

If it is unclear whether a rule is general or role-specific, or whether a change affects only the roster versus data ownership, ask the project owner.

## Critical product invariants

- PAAG is currently a local prototype, not a production multi-user service. Current editor is free-text attribution, not authentication.
- Preserve the critical thread documented in `DATA_DICTIONARY.md`: Product Architecture/PITS evidence -> Parts Catalog -> Fishbone -> scenario-specific Yamazumi -> scenario-specific Process at a Glance -> derived Pin Map. Imported evidence must never silently replace collaborator-reviewed planning decisions.
- A planning scenario owns its Yamazumi areas and Process plan work. Never read or write scenario-owned records by project ID alone where that could mix scenarios.
- The Parts Catalog and Fishbone structure are project-wide, with scenario-dependent downstream visibility documented in `DATA_DICTIONARY.md`.
- The five Functional Reviews pages are approved non-persistent shells. Do not add persisted fields, relationships, ownership, or storage until the applicable proposal passes the New Module Proposal Gate.
- `app_pages/assembly_sequence.py` is legacy and unlinked. Do not add features to it unless the requester explicitly asks to revive it.
- Dormant and hidden tables have distinct restrictions in `DATA_DICTIONARY.md`. Do not modify or build against them without the documented approval.

## New Module Proposal Gate

If a request describes a new page, module, table, persisted field, or feature not already covered by `DATA_DICTIONARY.md`, do not begin implementation. Ask the requester and wait for answers to all five questions:

1. What existing entity or entities does the module connect to, such as a Part, Process step, Fishbone section, Model, or Scenario?
2. What exact relationship or foreign key links the data to the critical thread (Product Architecture -> Parts -> Fishbone -> Yamazumi -> Process at a Glance)?
3. Is the module project-wide or scenario-specific under the scope rules in `DATA_DICTIONARY.md`?
4. Does it require a new table, or can an existing table serve it? If new, what fields are required and why is an existing table insufficient?
5. Which `DESIGN_SYSTEM.md` standards apply, including deletion, save action, audit logging, history, scenario badges, and help text?

After answers are supplied, add or update the `Proposed modules — pending owner review` section in `DATA_DICTIONARY.md` with the module name, answers, proposer, and date. Then implementation may proceed in the requester's branch. Do not skip this gate. If questions 1–3 cannot be answered, stop and direct the proposal to the project owner.

## Python and page structure

- Follow the existing Python style: `snake_case` for functions, variables, widget keys, and modules; `UPPER_SNAKE_CASE` for constants; and short descriptive helper names.
- Use string UUIDs for persisted record IDs (`str(uuid4())`); do not introduce sequential database IDs.
- Store timestamps as UTC ISO strings using `now_iso()`.
- Keep Streamlit page files as direct scripts. Do not add `if __name__ == "__main__"` or wrap a page in `main()`.
- Keep pages focused on presentation and interaction. Put reusable business rules, validation, transactions, and transformations in `utils/`.
- Read `project_id` and, where relevant, `scenario_id` from `st.session_state`. Stop early when required context is absent and confirm the selected scenario still exists.
- Give repeated or dynamic widgets stable descriptive keys containing the relevant project, scenario, area, section, or record ID.
- Use `st.rerun()` after a successful write when displayed data must reload; use scoped reruns only for an established fragment/dialog pattern.
- Prefer native Streamlit. Use Components v2 only when native Streamlit cannot provide the interaction.
- Use Material Symbols (`:material/...:`), sentence-case labels, native bordered containers, and the project theme. Avoid general CSS unless a custom component needs encapsulated styles.
- Use `page_title_with_scope()` for every active page title and `section_heading_with_scope()` for Overview's project-wide and active-scenario sections.
- Use `width="stretch"` or `width="content"`; do not introduce deprecated `use_container_width`.

## Data access and persistence

- Put normal reads and writes in `utils/store.py`; pages call named store functions rather than opening SQLite directly.
- Use parameterized SQL. Never interpolate user-entered values into SQL statements.
- Keep foreign-key behavior explicit and enforce project and scenario boundaries in every query.
- Validate before writing. Store functions raise user-readable `ValueError` exceptions for expected failures; pages catch and display them.
- Use one `connection()` block for a multi-table operation so the transaction commits atomically.
- Schema creation and safe, repeatable in-place upgrades live in `init_db()`. Preserve existing local data.
- Return pandas DataFrames for tabular page data.
- Give empty editable DataFrames explicit dtypes: text as `string`, booleans as `bool`, and numeric columns as appropriate. A cleared table must remain compatible with its `st.column_config`.
- Store validated uploads beneath `data/uploads/` with safe unique filenames; persist paths, not image binaries.

## Streamlit tables, state, and audit

Read and follow `DESIGN_SYSTEM.md` before changing any table or UI. Reuse `utils/table_ui.py`, `utils/table_filters.py`, and `utils/scope_ui.py`; do not recreate their behavior locally.

- Treat `st.session_state` as browser-session state, not durable storage.
- Apply `apply_pending_table_editor_reset(editor_key)` before constructing an editor that may need clearing. After a successful write, call `request_table_editor_reset(editor_key)` and rerun so stale edits or selections do not replay.
- Unsaved-change Undo normally clears the editor state and reruns. Use the existing model/fishbone snapshot pattern only when a multi-table operation genuinely needs saved-state Undo.
- Consume one-shot custom-component triggers so they cannot replay on later reruns.
- Preserve rows hidden by filters with `merge_filtered_edits()` and retain hidden internal IDs for callback/write resolution. Remove truly sensitive fields before sending data to the browser.
- Validate a complete bulk operation before writing; never partially apply it.
- Record every persisted change with `record_audit_event()` and Current editor attribution, then expose the relevant `audit_history()` at the bottom of the screen as required by `DESIGN_SYSTEM.md`.
- Do not invent universal business statuses. Status values are specific to their table.

## Import and export

- Treat PITS as source evidence, not automatic approval. Changed source records enter reconciliation without overwriting collaborator-authored MBOM or Fishbone decisions.
- Preserve stable PITS IDs and revision history for the preferred workbook format.
- Parse legacy Level 1–11 data conservatively; do not infer business meaning absent from the source.
- Preview and validate imports before applying them. Ordinary BOM imports require explicit part-number mapping.
- Exports use the active project and active scenario. Preserve stable flat sheet names expected by spreadsheet and Lucid consumers unless a requested change explicitly coordinates a breaking change.

## Custom components

- Component code lives beside its Python wrapper in `utils/clipboard_image.py`, `utils/fishbone_visual.py`, or `utils/yamazumi_board.py`.
- Keep inputs JSON-serializable and callbacks narrow. Persist business changes through store functions in Python, never directly from browser JavaScript.
- Escape user-provided text before inserting it into component HTML.
- Follow the existing versioned component-name pattern when clients must load a new definition.
- Test empty and populated inputs. The Yamazumi board must retain an Unassigned destination and reject drops onto Open or Blocked pitches.

## Local data and repository safety

- `data/paag.db`, SQLite sidecars, `data/uploads/`, and `.streamlit/secrets.toml` are local and ignored by Git. Never commit them.
- Local data cannot be recovered from Git. Back up `data/paag.db` before an experiment that intentionally removes or rewrites real planning data.
- Temporary root directories are not application source; do not depend on or commit them.
- Preserve unrelated worktree changes. Never reset, overwrite, or reformat files outside the requested scope.

## Verification

Use checks proportional to the change:

- Compile changed Python files with the shared environment at minimum.
- For page/data changes, run supported Streamlit `AppTest` smoke checks with a real project/scenario context and inspect `a.exception`.
- For database changes, test empty and populated results without rewriting the user's real data; prefer a temporary database or read-only diagnostics.
- For Excel changes, create the workbook in memory and open it with openpyxl to verify its sheets.
- Manually check clipboard, upload, drag-and-drop, full-screen Fishbone, and other browser-only behavior that `AppTest` cannot exercise.

The repository has a small committed `unittest` suite covering selected scenario, scope, table-helper, and Pin Map behavior, but it does not cover all save, deletion, import, or browser-component paths. Representative import fixtures are not maintained. See `PROJECT_STATUS.md` for current verification gaps and incomplete behavior.
