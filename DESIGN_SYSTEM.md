# Process at a Glance design system

This file defines locked interaction and interface standards for Process at a Glance. New UI work must follow these standards. Existing screens may require separate, explicitly scoped retrofit work.

## Universal Deletion Standard

Every editable table in this app must follow this exact deletion pattern, with no exceptions:

1. Do not display a trash-can icon, Delete button, per-row delete control, or other deletion affordance inside or beside an editable table.
2. Native row selection may be used for non-destructive bulk actions such as bulk editing, but it must not expose or imply a table-deletion action.
3. A new table-deletion workflow may be added only after explicit project-owner approval and must be designed as a separate, confirmed workflow rather than an incidental table control.
4. Any approved destructive workflow must state what will be deleted and what related data will be affected or unassigned. Its final confirmation button is the red destructive action and must not require typing a confirmation word.
5. This standard applies to every table in the app without exception, including low-stakes tables like Questions and concerns.

This standard is **locked** and replaces prior inconsistent patterns, including Yamazumi's typed-`CLEAR` dialogs, Process at a Glance's single-click **Remove pairing** action, and delete-on-save behavior in Questions and concerns and Feature definitions.

Retrofitting existing screens to this standard is a separate future task and is not part of this documentation update. Do not modify screen code as part of documenting this standard.

## Universal Table Row Selection Standard

Every data table in this app must show Streamlit's native row-selection checkboxes on the far left. The unlabeled checkbox in the upper-left corner must select or clear all rows currently visible in the table with one click.

Selection is a transient, non-destructive table action. It must not be stored as a data edit, trigger a write by itself, or expose a native trash-can or row-deletion control. Filters define which rows are currently visible and therefore which rows the upper-left checkbox selects.

Use the shared table conventions in `utils/table_ui.py`: read-only tables use `selectable_dataframe()` and editable tables use native editor selection with `num_rows="delete"`, while the native deletion toolbar is hidden. Do not add a named checkbox column or a separate **Select all** control to imitate this behavior. Where a business workflow can act on only one row, the screen may require exactly one selected row before enabling that action, but the native selectors and upper-left select-all control must remain available.

This standard is **locked** and applies to every existing and future data table, including Questions and concerns, Fishbone assembly hierarchy tables, previews, and History tables.

## Universal Save Action Standard

Every editable table or screen in this app must use the exact label **Save & refresh** for its primary save action button, regardless of what is being saved. Do not use screen-specific variants such as **Save concerns**, **Save model definitions**, **Save features**, **Save complexity tree**, **Save project**, or **Save scenario details**.

The button must follow the existing shared header pattern implemented in `utils/table_ui.py`: the title, orange **Unsaved changes** indicator, **Undo**, and the blue **Save & refresh** button must appear on one line.

This standard is **locked** and replaces all screen-specific save button labels identified during the current-state audit, including those on Overview, Questions and concerns, all three Model definitions subsections, and Parts to fishbone.

Retrofitting existing screens to this standard is a separate future task. Do not modify screen code as part of documenting this standard.

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
2. **Scenario: [active scenario name]** — Data here belongs only to the currently active planning scenario. Changes do not affect other scenarios.
3. **Project-wide (scenario-aware)** — The underlying data is shared across all scenarios, but some fields or visibility on this screen change depending on which scenario is currently active.

Assign each active screen its correct badge state based on the scope definitions in `DATA_DICTIONARY.md`:

- **Project-wide:** Overview project-identity fields, Questions and concerns, Import PITS and export, Model definitions, and Fishbone framework/structure.
- **Scenario: [active scenario name]:** Overview active-scenario fields, Yamazumi, Process at a Glance, and Requirements.
- **Project-wide (scenario-aware):** Parts Catalog, where the catalog is project-wide but Active status is scenario-specific; and Parts to fishbone, where the structure is project-wide but visible and active parts depend on the scenario.

Because Overview contains both project-wide identity fields and scenario-specific active-scenario fields, display the applicable badge next to each corresponding section heading as well as maintaining the standard page-title placement, so neither scope is presented ambiguously.

Every badge state must include hover/tooltip text explaining its meaning:

1. **Project-wide** badge tooltip: "Changes on this page affect every planning scenario in this project."
2. **Scenario: [active scenario name]** badge tooltip: "Changes on this page only affect the [scenario name] scenario. Other scenarios are not affected."
3. **Project-wide (scenario-aware)** badge tooltip: Write this specifically for each screen where it appears, clearly explaining exactly which data is shared across all scenarios and which part is scenario-dependent. Do not use one generic sentence for this badge state across multiple screens.

For Parts Catalog specifically, use: "The parts catalog itself is shared across every scenario. Whether a part is marked Active applies only to the currently selected scenario."

The badge must use consistent colors, wording, and placement on every screen with no exceptions. This standard is locked. Retrofitting this badge onto every existing screen is a separate future task.

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

This update is documentation-only and does not modify screen code. The glossary itself remains active, locked, and binding policy for all future UI work.
