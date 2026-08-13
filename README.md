# Process at a Glance

A local Streamlit prototype for industrial engineers planning new-product-introduction assembly processes. It brings parts and CAD images, ordered work elements, draft cycle times, tooling and torque, quality and ergonomic requirements, workstation geometry, and open concerns into one evolving project record.

## Run locally

From this directory, using the shared virtual environment:

```powershell
..\.venv\Scripts\streamlit.exe run streamlit_app.py
```

Then open `http://localhost:8501`.

The app creates `data/paag.db` on first run and seeds a small sample project. Uploaded images are stored in `data/uploads/`. Both are ignored by Git.

## Current scope

- Create and revise NPI projects
- Maintain a part catalog with CAD screenshots and BOM provenance
- Paste Windows screenshots directly from the clipboard without saving an intermediate image file
- Import draft BOMs from Excel or CSV with column mapping
- Detect PITS-style Level 1–11 sheets and send their repeated occurrences to an IE review queue without treating them as approved MBOM content
- Prefer the ID-based `part_tracker` + `models` PITS workbook: synchronize source records by stable ID Number, retain revision history, and flag changed IDs for IE reconciliation
- Import or manually define the project model catalog, add team-familiar names and descriptions, and activate the models used for planning
- Assign parts and MBOM occurrences to all models or a controlled multi-select of specific models
- Develop an editable Manufacturing BOM, explicitly confirming or excluding every rough PITS candidate
- Build a station-independent assembly fishbone from confirmed MBOM content before balancing work into physical pitches
- Work through one continuous IE workspace: selectable PITS list, live fishbone visual, then editable MBOM order
- Build an ordered, editable work-element plan and draft Yamazumi station view
- Capture tools, torques, quality, ergonomics, locations, conveyor/platform heights, and pit depths
- Track questions, concerns, decisions, assumptions, owners, and status
- Export a multi-sheet Excel workbook with a flat `Lucid Data Link` sheet

The preferred PITS workbook uses `ID Number` as the immutable source key. Re-importing an unchanged ID leaves the IE-authored MBOM untouched; changed source content creates a revision and enters the PITS updates reconciliation view. Model definitions come from the `models` tab, while part-to-model applicability remains an IE decision. Legacy Level 1–11 PITS files remain supported as an intentionally conservative fallback. Multi-user authentication, a full audit trail for IE edits, threaded comments, packaging/routing plans, PFMEA, control plans, and work instructions are intentionally left for later increments.
# Editable table standard

New editable tables and tabs should use the shared helpers in `utils/table_ui.py` and follow this interaction pattern:

- Put the section title, orange unsaved-changes warning, Undo, and blue **Save & refresh** button on one line at the top of the section.
- Support direct cell editing and direct row creation where the underlying data allows it.
- Add a **Select** checkbox column for bulk actions. Selection alone is transient and does not count as an unsaved data change.
- Provide bulk editing for the table's meaningful shared fields and bulk deletion for persisted selected rows.
- Keep a clear individual-row delete action when users may need to remove one row quickly.
- Keep keyword and relevant dropdown filters above the table.
- Validate bulk changes before writing and refresh the editor after a successful save or deletion.
- Confirm bulk deletion, support selecting all filtered rows from Streamlit's native upper-left table selector, and export the filtered table to Excel.
- Use consistent Details/Edit actions, required-field validation, editor attribution, automatic timestamps, and table history.
- Workflow status values are table-specific rather than a global Draft/In review/Approved standard.
