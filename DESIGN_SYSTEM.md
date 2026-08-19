# Process at a Glance design system

This file defines locked interaction and interface standards for Process at a Glance. New UI work must follow these standards. Existing screens may require separate, explicitly scoped retrofit work.

## Universal Deletion Standard

Every editable table in this app must follow this exact deletion pattern, with no exceptions:

1. A multi-select column on the far left (checkboxes) is the only mechanism for marking rows for deletion. Do not add a per-row trash icon or any single-click delete affordance.
2. When one or more rows are selected, display a bulk-action menu in the upper-right area of the table (trash can icon for delete; reserve room for future bulk actions like bulk edit).
3. Clicking the trash icon opens a confirmation dialog. The dialog must state what will be deleted and name any related/dependent data that will also be affected or unassigned.
4. The confirmation dialog's Delete button is a simple click — do not require typing a confirmation word (for example, `CLEAR`) under any circumstance.
5. This standard applies to every table in the app without exception, including low-stakes tables like Questions and concerns.

This standard is **locked** and replaces prior inconsistent patterns, including Yamazumi's typed-`CLEAR` dialogs, Process at a Glance's single-click **Remove pairing** action, and delete-on-save behavior in Questions and concerns and Feature definitions.

Retrofitting existing screens to this standard is a separate future task and is not part of this documentation update. Do not modify screen code as part of documenting this standard.

## Universal Save Action Standard

Every editable table or screen in this app must use the exact label **Save & refresh** for its primary save action button, regardless of what is being saved. Do not use screen-specific variants such as **Save concerns**, **Save model definitions**, **Save features**, **Save complexity tree**, **Save project**, or **Save scenario details**.

The button must follow the existing shared header pattern implemented in `utils/table_ui.py`: the title, orange **Unsaved changes** indicator, **Undo**, and the blue **Save & refresh** button must appear on one line.

This standard is **locked** and replaces all screen-specific save button labels identified during the current-state audit, including those on Overview, Questions and concerns, all three Model definitions subsections, and Parts to fishbone.

Retrofitting existing screens to this standard is a separate future task. Do not modify screen code as part of documenting this standard.

## Deferred decisions

Multi-step Undo/Redo (spreadsheet-style, multiple sequential steps backward/forward through edits): considered and intentionally deferred. A feasibility review found it technically possible but high-risk in Streamlit, requiring a new shared edit-history subsystem across all tables. The core problem it was meant to solve — protection against accidental data loss — is instead addressed by the Universal Deletion Standard (multi-select, red delete action, confirmation dialog) already documented above. Revisit multi-step Undo/Redo only as a deliberate future project, not as an incidental addition to any single-screen task.

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

This standard is **locked**. Bringing all existing screens into compliance is a separate future retrofit task and is not part of this documentation update. Any new screen or feature built from this point forward must include audit logging from the start. Audit logging is not optional and must not be treated as an item to add later.

This is a documentation-only standard. Do not modify screen code as part of documenting it.

## Universal History Display Standard

Every screen or tab in this app must display a **History** section at the bottom of the page showing that screen's own `audit_log` entries in a consistent, shared layout. Reuse the existing history-display pattern implemented on Parts Catalog and Process at a Glance.

This standard pairs directly with the Universal Audit Trail Standard: if a screen logs events, it must also display them. No screen is exempt, including currently history-less screens such as Overview, Questions and concerns, Model definitions, Parts to fishbone, and Requirements.

The History section must show, at minimum:

- what changed;
- who made the change, using the free-text Current editor attribution; and
- when the change occurred.

It must use the same visual placement and format on every screen so users always know where to look.

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

This is a documentation-only standard. Do not modify code as part of documenting it.

## Canonical Terminology Glossary

Before adding any new label, caption, dialog, or button text, check this glossary first. If a new UI label describes a concept already listed here, use the canonical label exactly as written below.

| Concept | Canonical label | Applies to |
| --- | --- | --- |
| Questions page | **Questions and concerns** | Navigation and page title |
| Import/export page | **Import PITS and export** | Navigation and page title |
| Fishbone page | **Parts to fishbone** | Navigation and page title |
| Requirements page | **Requirements** | Navigation and page title |
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

This is a documentation-only glossary. Do not modify screen code as part of documenting it.
