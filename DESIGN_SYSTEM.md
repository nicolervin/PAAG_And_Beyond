# Process at a Glance design system

This file defines locked interaction and interface standards for Process at a Glance. New UI work must follow these standards. Existing screens may require separate, explicitly scoped retrofit work.

## Universal Deletion Standard

Every editable table in this app must follow this exact deletion pattern, with no exceptions:

1. On a table with an approved deletion workflow, selecting one or more rows must reveal Streamlit's native **Delete row(s)** action in the table's upper-right toolbar.
2. Clicking the native action initiates deletion but must not persist it immediately. Open a confirmation dialog that lists or summarizes the selected records and explains related records that will be deleted, preserved, unassigned, or otherwise affected.
3. Cancel must restore the selected rows by resetting the editor state. The final confirmed action performs the database write, records history, resets the editor, shows a toast, and reruns.
4. Do not add a second trash-can button, separate Delete button beside the table, per-row delete control, or Delete `ButtonColumn`. The native toolbar action is the single table-level entry point.
5. Tables without an approved, relationship-safe deletion workflow must keep the native Delete action hidden. Adding such a workflow still requires explicit project-owner approval.
6. The final confirmation button is the red destructive action and must not require typing a confirmation word.
7. This standard applies to every table in the app, including low-stakes tables like Questions and concerns.

Every approved destructive confirmation or standalone destructive action must use a stable Streamlit widget key beginning with `destructive_`. The entry point uses this prefix to render destructive actions red without styling Cancel actions.

This standard is **locked** and replaces prior inconsistent patterns, including globally hiding Streamlit's native deletion action, Yamazumi's typed-`CLEAR` dialogs, Process at a Glance's single-click **Remove pairing** action, and delete-on-save behavior in Questions and concerns and Feature definitions.

Retrofitting existing screens to this standard is a separate future task and is not part of this documentation update. Do not modify screen code as part of documenting this standard.

## Universal Table Row Selection Standard

Every data table in this app must show Streamlit's native row-selection checkboxes on the far left. The unlabeled checkbox in the upper-left corner must select or clear all rows currently visible in the table with one click.

Selection is transient and does not write data by itself. On tables with an approved deletion workflow, the native Delete action converts the current selection into a pending confirmed deletion. On other tables, selection remains available only for non-destructive actions and the Delete action stays hidden. Filters define which rows are currently visible and therefore which rows the upper-left checkbox selects.

Use the shared table conventions in `utils/table_ui.py`: read-only tables use `selectable_dataframe()` and editable tables use native editor selection through `num_rows="dynamic"` or `num_rows="delete"`. Show the native Delete toolbar action only when the editor is connected to an approved confirmation workflow. Do not add a named checkbox column or a separate **Select all** control to imitate selection. Where a business workflow can act on only one row, the screen may require exactly one selected row before enabling that action, but the native selectors and upper-left select-all control must remain available.

This standard is **locked** and applies to every existing and future data table, including Questions and concerns, Fishbone assembly hierarchy tables, previews, and History tables.

## Universal Save Action Standard

Every editable table in this app must use the exact label **Save & Refresh** for its primary save action button, regardless of what is being saved. Do not use table-specific variants such as **Save concerns**, **Save model definitions**, **Save features**, or **Save complexity tree**.

Keep the section title, filters, and sorting controls above the table. Immediately below the table, use the shared footer pattern implemented in `utils/table_ui.py`: the orange **Unsaved changes** indicator, **Undo**, and the blue **Save & Refresh** button with the save icon must appear together in a right-aligned row.

This standard is **locked** and replaces all screen-specific save button labels identified during the current-state audit, including those on Overview, Questions and concerns, all three Model definitions subsections, and Parts to fishbone.

Retrofitting existing screens to this standard is a separate future task. Do not modify screen code as part of documenting this standard.

## Universal Row Creation Standard

Editable tables that permit new records must allow contributors to type or paste one or many spreadsheet rows directly into Streamlit's native blank entry row. Do not expose a separate **Add row** button. Use `direct_entry_editor_rows(..., editor_key=...)` immediately before `st.data_editor(..., num_rows="dynamic")`.

Because Streamlit disables native header sorting when an editor permits row creation, the shared helper supplies external **Sort rows by** and **Descending** controls. Apply sorting before editing; once the editor contains draft changes, pasted rows, or native row selections, the sort controls must remain locked until the contributor saves, undoes, or clears the selection. Approved new-row defaults belong in `st.column_config`. Saving or undoing must clear the editor draft while retaining the chosen saved-row sort. Apply this standard to every existing and future editable table that permits row creation.

## Shared Editable-Table Implementation Checklist

Use `utils/table_ui.py` and `utils/table_filters.py` for every new or modernized data table. These helpers implement the locked standards above and must not be recreated independently in page code.

- Put keyword and relevant dropdown filters above every table with `filter_table()`.
- Put the section title above the filters with `editable_table_heading()`. Put the orange **Unsaved changes** indicator, **Undo**, and blue **Save & Refresh** action immediately below the table with `editable_table_footer()`.
- Use `selectable_dataframe()` for read-only tables. Editable tables use Streamlit's native selection state through the shared editor pattern; never add a named `CheckboxColumn` or separate Select all control.
- Read selected persisted rows with `native_selected_rows()`. Treat selection as transient UI state and exclude it from change detection with `table_has_unsaved_changes(..., native_row_selection=True)` where applicable.
- Refuse a normal save while persisted rows remain selected; selection is reserved for validated bulk actions.
- Keep native Sort ascending and Sort descending on read-only tables and editable tables that do not create rows. For `num_rows="dynamic"`, call `direct_entry_editor_rows(..., editor_key=...)` immediately before `st.data_editor()` and use its locked external sort controls.
- When saving a filtered editor, use `merge_filtered_edits()` so rows hidden by filters are preserved. Filters affect only the visible and exported view; they must never delete or overwrite hidden records.
- Mark required fields in `st.column_config` and validate them again with `required_field_errors()` or store-layer validation.
- Convert multi-value database fields to lists for `MultiselectColumn`, then convert them back to their persisted representation before saving. Use `universal_values` in `filter_table()` for values such as All models that match every specific choice.
- Keep stable identifiers separate from friendly display values. Hide internal IDs visually while retaining them for callback and write resolution; remove genuinely sensitive values before data reaches the browser.
- Validate an entire bulk operation before writing. Never partially apply a bulk change because one selected record is invalid.
- Provide bulk editing for meaningful shared fields, subject to the Universal Deletion Standard.
- Use the shared Details/Edit action configuration, and do not change established column sizing unless a request specifically calls for it.
- Export the currently filtered table with `dataframe_to_excel()`.
- Do not impose Draft/In review/Approved as a universal status model. Status values are specific to each business table.

Use this normal save sequence:

1. Read the filtered editor output and native selection.
2. Refuse a normal save if persisted rows remain selected.
3. Validate required fields and business rules.
4. Merge filtered edits into the complete unfiltered data.
5. Convert display labels back to stored identifiers or codes.
6. Call one named store-layer save function.
7. Record the audit event with Current editor attribution and the timestamp returned by the store layer.
8. Request an editor reset, show a success toast, and rerun.

### Editor state and reset behavior

Treat `st.session_state` as browser-session state, not permanent storage. Apply `apply_pending_table_editor_reset(editor_key)` before constructing an editor whose prior state may need clearing. After a successful save or approved destructive action, call `request_table_editor_reset(editor_key)` before rerunning so stale edits and selections cannot replay.

Unsaved-change Undo normally clears the editor's session-state entry and reruns. A complex multi-table workflow may retain a pre-save snapshot in session state when it genuinely needs saved-state Undo; follow the existing Model definitions and Fishbone patterns. Session-state Undo remains limited to the current browser session and is not an audit or version-control mechanism.

## Deferred decisions

Multi-step Undo/Redo (spreadsheet-style, multiple sequential steps backward/forward through edits): considered and intentionally deferred. A feasibility review found it technically possible but high-risk in Streamlit, requiring a new shared edit-history subsystem across all tables. The core problem it was meant to solve — protection against accidental data loss — is instead addressed in part by the Universal Deletion Standard, which removes deletion affordances from editable tables unless a separate workflow is explicitly approved. Revisit multi-step Undo/Redo only as a deliberate future project, not as an incidental addition to any single-screen task.

This is a documentation-only decision. Do not modify screen code as part of documenting it.

## Universal Audit Trail Standard

Every persisted change in this app — every save, delete, and bulk action, on every screen, with no exceptions — must write an entry to `audit_log`. This applies even to screens currently considered low-stakes, such as Questions and concerns, and screens that currently record nothing, including Overview, imports, normal Model definitions saves, Feature and Complexity-tree saves, and most Parts to fishbone changes.

Each `audit_log` entry must follow the existing pattern used by compliant screens such as Parts, Process at a Glance, and most of Yamazumi. It must record:

- a logical table or workflow name;
- the action taken;
- the affected row count;
- free-text Current editor attribution;
- JSON details describing what changed; and
- a timestamp.

Use `record_audit_event()` for standardized saves, approved destructive actions, and bulk edits. Include the timestamp supplied by the store layer and `st.session_state.get("current_editor", "")`. Keep action names consistent with the visible workflow, such as `Save & Refresh` or `Bulk edit`; do not create near-duplicate action labels for equivalent events.

This standard is **locked**. Bringing all existing screens into compliance is a separate future retrofit task and is not part of this documentation update. Any new screen or feature built from this point forward must include audit logging from the start. Audit logging is not optional and must not be treated as an item to add later.

This is a documentation-only standard. Do not modify screen code as part of documenting it.

## Universal History Display Standard

Every screen or tab in this app must display a **History** section at the bottom of the page showing that screen's own `audit_log` entries in a consistent, shared layout. Reuse the existing history-display pattern implemented on Parts Catalog and Process at a Glance.

This standard pairs directly with the Universal Audit Trail Standard: if a screen logs events, it must also display them. No screen is exempt, including currently history-less screens such as Overview, Questions and concerns, Model definitions, Parts to fishbone, and Pin Map.

The History section must show, at minimum:

- what changed;
- who made the change, using the free-text Current editor attribution; and
- when the change occurred.

It must use the same visual placement and format on every screen so users always know where to look.

Use `audit_history()` in a bottom expander. When a page has multiple history categories, group them into tabs inside that expander rather than scattering separate History sections through the page.

This standard is **locked**. Retrofitting all existing screens to include this History section is a separate future task and is not part of this documentation update. Any new screen or feature built from this point forward must include a History section from the start.

This is a documentation-only standard. Do not modify screen code as part of documenting it.

## Stable Identifier vs. Friendly Display Name Standard

This app intentionally keeps certain stable identifiers separate from editable friendly display names. This is not an inconsistency — it is a deliberate pattern that allows the friendly label to be renamed or clarified over time without altering the permanent underlying identifier.

Confirmed examples of this intentional pattern from the naming audit include:

- `project_models.model_number` versus `project_models.display_name`;
- `assembly_sections.parent_id` versus its displayed **Parent assembly** name;
- `fishbone_part_assignments.section_id` versus its displayed section name; and
- `pits_records.pits_id` as a fixed source key.

Do not "fix" these pairs by renaming the database identifier to match the friendly label, or vice versa. When building new features, follow this same pattern for any new stable identifier that needs a human-friendly label.

This standard is locked.

This is a documentation-only standard. Do not modify code as part of documenting it.

## Imperial Units Standard

At this stage of the project, all linear dimensional measurements (e.g., height, width, depth, length, distance) are stored AND displayed in imperial units (inches), with no internal metric conversion layer. This replaces the prior pattern of storing values in millimeters and converting to inches for display, which was removed when `work_elements.conveyor_height_mm`, `platform_height_mm`, and `pit_depth_mm` were renamed to `conveyor_height_in`, `platform_height_in`, and `pit_depth_in`.

This standard does not apply to non-dimensional measurements such as time, torque, weight, temperature, or pressure. Those measurements retain their own appropriate units and are unaffected by this standard.

Rule: any new linear dimensional field added to this app must store and display in inches by default. Do not introduce a metric storage column unless explicitly approved by the project owner.

This standard is locked. It may be revisited in the future if the project requires metric-native data sources or equipment specs; until then, it remains imperial-only.

## Scenario Boundary Indicator Standard

Every screen must display a small, consistently placed badge next to the page title indicating the scope of the data shown, using exactly one of these three states:

1. **Project-wide** — Data here is shared across every planning scenario in the project. Changes affect all scenarios.
2. **Scenario-specific** — Data here belongs only to the currently active planning scenario. Changes do not affect other scenarios.
3. **Scenario-aware** — The underlying data is shared across all scenarios, but some fields or visibility on this screen change depending on which scenario is currently active.

Assign each active screen its correct badge state based on the scope definitions in `DATA_DICTIONARY.md`:

- **Project-wide:** Overview project-identity fields, Questions and concerns, Import PITS and export, Model definitions, and Fishbone framework/structure.
- **Scenario-specific:** Overview active-scenario fields, Yamazumi, Process at a Glance, and Pin Map.
- **Scenario-aware:** Parts Catalog, where the catalog is project-wide but Active status is scenario-specific; and Parts to fishbone, where the structure is project-wide but visible and active parts depend on the scenario.

Because Overview contains both project-wide identity fields and scenario-specific active-scenario fields, display the applicable badge next to each corresponding section heading as well as maintaining the standard page-title placement, so neither scope is presented ambiguously.

Every badge state must include hover/tooltip text explaining its meaning:

1. **Project-wide** badge tooltip: "Changes on this page affect every planning scenario in this project."
2. **Scenario-specific** badge tooltip: "Changes on this page only affect the [scenario name] scenario. Other scenarios are not affected."
3. **Scenario-aware** badge tooltip: Write this specifically for each screen where it appears, clearly explaining exactly which data is shared across all scenarios and which part is scenario-dependent. Do not use one generic sentence for this badge state across multiple screens.

For Parts Catalog specifically, use: "The parts catalog itself is shared across every scenario. Whether a part is marked Active applies only to the currently selected scenario."

The badge must use consistent colors, wording, and placement on every screen with no exceptions. This standard is locked. Use the shared helpers in `utils/scope_ui.py` for every page title and for Overview's two scoped section headings.

Every **Scenario-specific** and **Scenario-aware** page title must also show the active scenario's revision and name in a dropdown beside the badge. The badge itself stays concise and does not repeat the active scenario name or revision. Changing that dropdown changes the browser session's single active scenario, synchronizes the sidebar selector, and controls the scenario data shown on every subsequent page until the contributor changes it again. When no valid scenario has been selected, default to the newest non-archived scenario returned by the standard scenario ordering.

Every scenario-specific page title must also place a blue **Save as scenario** button immediately beside that scenario dropdown. The shared page-title helper owns this control so new scenario-specific screens receive it automatically. It creates a complete branch from the scenario shown in the adjacent dropdown, makes the new branch the browser session's active scenario, and exposes it immediately in Overview's Planning scenarios table. Scenario-aware and project-wide pages do not receive this button.

## Help Text (Hover) Standard

Any field, column header, section, or control that a collaborator judges as potentially confusing may include an optional help icon (a "?" symbol) placed immediately to the right of its label. This is discretionary — not every field requires one — and any contributor may add one wherever they see fit, without requiring special approval beyond the normal weekly branch review process.

The help icon must use the same hover/tooltip display mechanism as the Scenario Boundary Indicator badges (see above), so all hover help in the app looks and behaves identically regardless of where it appears.

Content rules for help text:

- One to three sentences maximum
- Plain, non-technical language — avoid engineering jargon and internal database terminology
- Explain what the field/control means and, if relevant, why it matters or how it's used downstream
- Do not restate the field's label; add real explanatory value

## Canonical Terminology Glossary

Before adding any new label, caption, dialog, or button text, check this glossary first. If a new UI label describes a concept already listed here, use the canonical label exactly as written below.

This glossary is active, locked policy, not merely informational, and must be checked before adding new UI labels.

| Concept | Canonical label | Applies to |
| --- | --- | --- |
| Questions page | **Questions and concerns** | Navigation and page title |
| Import/export page | **Import PITS and export** | Navigation and page title |
| Fishbone page | **Parts to fishbone** | Navigation and page title |
| Pin Map page | **Pin Map** | Navigation and page title |
| Parts master | **Parts Catalog** | Page title, captions, help text, dialogs, and cross-page references |
| Fishbone framework | **Fishbone framework** | Section headings and explanatory copy |
| Fishbone section | **Fishbone section** | Filters, selectors, table columns, captions, and help text |
| Placed part occurrence | **Fishbone use** | Table headings, actions, confirmation dialogs, and history display |
| Friendly model label | **Common name** | Model definitions, fallback text, captions, and help |
| Stable model label | **Official model number** | Model tables and explanatory copy |
| Scenario revision | **Scenario revision** | Editable field labels and explanatory text; compact value summaries may still abbreviate it as **Rev** |
| Yamazumi area | **Yamazumi area** | Selectors, tables, captions, and help text |
| Process material group | **Part requirement** | Forms, captions, dialog content, and history display |
| Fishbone occurrence quantity | **Fishbone quantity** | Forms, tables, and dialogs |
| Part-use description | **Use / installation location** | Forms, tables, search results, and help text |
| Generic enabled-state wording | **Active** | Boolean columns and filters where the value genuinely means enabled or disabled |
| History attribution | **Editor** | Sidebar field and History column; supporting help must continue stating that this is free-text attribution |

The following terms remain contextual exceptions rather than globally unified labels:

- **Subassembly** remains a valid Fishbone section type.
- **Common name** and **Official model number** remain separate fields.
- Compact scenario summaries may use **Rev** even though the editable field label is **Scenario revision**.
- **Active** must not replace a genuinely different status such as **Draft**, **Open**, **Blocked**, or **Released**.

This update is documentation-only and does not modify screen code. The glossary itself remains active, locked, and binding policy for all future UI work.
