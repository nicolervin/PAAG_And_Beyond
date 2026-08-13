# PAAG development conventions

## Editable tables

Use `utils/table_ui.py` for every new editable table or tab.

- Place the section title, orange unsaved-changes indicator, Undo control, and blue **Save & refresh** button on one line at the top of the section.
- Support direct cell editing and direct row creation whenever the data model permits it.
- Include a **Select** checkbox column and bulk actions for editing shared fields and deleting selected persisted rows.
- Do not treat transient selection-checkbox changes as unsaved business-data changes.
- Retain a convenient individual-row delete action when appropriate.
- Put keyword and relevant dropdown filters above every table.
- Validate bulk operations before writing, preserve filtered-out rows, and reset/refresh the editor after successful writes.
- Keep column sizing unchanged unless the user specifically requests sizing changes.
- Require confirmation before bulk deletion.
- Use Streamlit's native row selector (`num_rows="delete"` or `"dynamic"`) so the unlabeled square in the table's upper-left corner selects all visible rows, matching **Order assigned parts**. Do not simulate selection with a named `CheckboxColumn` and do not add a separate Select all control. Treat the native selected/deleted-row state as bulk-action selection, require confirmation before actual deletion, and prevent a normal save while rows remain selected.
- Include an Excel export of the currently filtered table.
- Use consistent **Details** or **Edit** row actions from the shared helpers.
- Mark required fields in column configuration and validate them again before database writes.
- Record standardized saves, bulk edits, and bulk deletions with timestamp and the session's Current editor name, and expose a history view.
- Do not impose Draft/In review/Approved workflow statuses as a general table standard.
