"""Static, read-only guidance displayed by the Quality page help dialog."""

REQUIREMENTS_REPOSITORY_HELP = """
Use the **Requirements repository** to maintain reusable Quality checks and
specifications for the project.

- **Type** chooses an active value from the project-wide Quality requirement
  Type catalog. **Pass/fail** identifies a check recorded as a binary result;
  leave it off for a measured-value requirement.
- **Target value** is the desired numeric result, **Tolerances** describes the
  permitted variation, and **Unit** identifies how the result is measured.
- **Linked Process steps** is the number of published copies currently attached
  to Process at a Glance steps. Select the count to open the read-only list of
  those steps.
- **Pending linked updates** counts linked copies that still contain older
  published values after the repository definition has changed.
- **Save & Refresh** saves repository edits only. It does not change published
  copies. Review the pending count, then use **Push saved updates to linked
  Process steps** when the new saved values are ready to replace those copies.
- For a shared Pass/fail change, open **Bulk edit Pass/fail**, select saved
  requirements in its read-only list, choose the setting, and use **Apply to
  selected**. Save or undo ordinary repository edits first.

Torque requirements can also use **Quality → Equipment → Torque requirement
specifications**.
Requirement Types are maintained separately under **Manage Quality requirement
types**.
"""


EQUIPMENT_HELP = """
Use **Equipment** to maintain physical equipment used by the Quality review.

- **All equipment** shows every shared equipment record attached to Quality.
  Each applicable Equipment Type also has its own chart.
- Shared fields—Equipment name, Equipment Type, Description, Manufacturer,
  Model, and Notes—stay synchronized when the same equipment is attached to
  another Functional Review.
- Select equipment to manage its primary image and its placement for the active
  scenario. A placement may be **Unassigned** or use one Station / Pitch.
- Process Function links are optional and must belong to the saved Station /
  Pitch. If upstream Process Functions move, use the displayed reconciliation
  guidance rather than creating a duplicate equipment record.
- In the **Torque tool** chart, installed tools can link to several saved Torque
  Quality requirements. Published target, tolerance, unit, tool type,
  orientation, and screw-bit values remain read-only source information.
- **Torque requirement specifications** maintains the requirement-level tool
  details formerly shown in Requirements repository. It does not create a
  physical installed tool automatically.
- Use **Add existing equipment** to attach a shared project record to Quality.
  Removing it from Quality removes only that association; permanent deletion is
  available from the top-level Equipment page.

Equipment changes use Current editor attribution and appear in Equipment
History. Viewing, filtering, and exporting do not write data.
"""


PFMEA_QUICK_START = """
Use **PFMEA** to document scenario-specific failure analysis for Process at a
Glance work.

1. Choose a **Process Function** for each new PFMEA line.
2. Enter the Failure Mode, Effects, Causes, and initial ratings.
3. Choose a Classification and applicable Prevention and Detection controls.
4. Add Recommended Actions, responsibility, completion evidence, and resulting
   ratings when they become available.
5. Use **Recalculate RPN** to refresh the unsaved calculations, then use the
   shared **Save & Refresh** action to persist the complete draft.

Only Process Function is required to save. The completion assistant identifies
recommended follow-up without blocking incomplete work.
"""


PFMEA_HELP_SECTIONS = (
    (
        "Process Function and table entry",
        """
- **Process Function** shows the current derived Op ID followed by the Process
  at a Glance Work Element. The stable internal Process relationship stays
  hidden. Complete choices follow Fishbone and Yamazumi physical order;
  incomplete Op IDs remain selectable afterward.
- **Item #** is read-only and shows the selected Process Function's current
  Pitch. It is not a separately entered identifier.
- Process Function locks after the line's first **Save & Refresh**. On an
  unsaved draft, changing it recalculates Item # and requires confirmation
  before incompatible Quality-backed controls are removed.
- Ordinary editable cells support native spreadsheet copy and paste. Shared
  Failure Mode, Effect, Cause, rating, or Action values synchronize across
  repeated flat rows backed by the same PFMEA record.
- Shift+Enter line breaks remain in saved text, but the closed grid cell may
  display them as spaces. Use separate PFMEA lines when Failure Modes or Effects
  need different ratings, controls, Causes, or Actions.
""",
    ),
    (
        "Ratings, RPN, and Classification",
        """
- **Severity**, **Occurrence**, and **Detection** accept whole-number ratings
  from 1 through 10. The application does not define company scoring guidance.
- Initial **RPN** is Severity x Occurrence x Detection. Resulting RPN uses the
  three Resulting ratings. A calculation remains blank until all three inputs
  exist.
- **Recalculate RPN** updates the current unsaved display without writing.
  **Save & Refresh** recalculates and persists the values atomically.

| Code | Meaning |
| --- | --- |
| S | Critical to Product Safety |
| R | Regulatory |
| E | Engineering CTQ |
| P | Process CTQ |
| P- | Process CTQ done at qualification |
| Q | Quality Specific |
| E- | Engineering CTQ at qualification |
| M | Maintain Control |
| PM | Preventative Maintenance |

Leave Classification blank when the line has not yet been classified.
""",
    ),
    (
        "Current Process Controls",
        """
- Prevention and Detection tags in the grid are read-only summaries. Edit them
  in **Select Current Process Controls** by choosing the saved or draft Cause.
- Choices combine published Quality requirements linked to that exact Process
  Function with active project-wide manual Prevention or Detection options.
- Use **Copy Prevention**, **Copy Detection**, or **Copy both**, select another
  Cause, and use **Paste to selected Cause**. Paste replaces only the copied
  list or lists while preserving source order.
- Same-step Quality controls and active manual options apply directly.
  Cross-Process Quality controls require compatible-only confirmation;
  inactive or unavailable sources are disclosed and omitted.
- A Detection-control change preserves the Detection rating and marks it for
  review. All control edits stay in the PFMEA draft until Save & Refresh.
""",
    ),
    (
        "PFMEA pattern overview",
        """
A PFMEA pattern is a reviewed, project-wide starting point for analysis that is
expected to recur. Applying one to a Process Function creates a new,
scenario-specific PFMEA graph; it does not connect the saved PFMEA back to the
pattern.

A pattern can retain:

- A Potential Failure Mode and optional Suggested Classification.
- Ordered Effects and Causes.
- Cause-specific Recommended Actions.
- Ordered Prevention and Detection control suggestions.

A pattern never retains Severity, Occurrence, Detection, RPN, Responsibility &
Target Completion Date, Actions Taken, resulting ratings, or Resulting RPN.
Those values require a fresh review for the selected Process Function. Later
pattern edits, deactivation, or deletion never modify PFMEA graphs that were
already created from it.
""",
    ),
    (
        "Create or edit a pattern",
        """
Open **Manage PFMEA patterns** below the PFMEA line-items table.

1. Use the pattern filters to search Label or Potential Failure Mode and filter
   by Active state or Suggested Classification. **Export filtered patterns**
   downloads the filtered catalog without hidden identifiers.
2. Under **Pattern to edit**, choose **Create new pattern** or an existing
   pattern.
3. Complete the pattern header:
   - **Label** is required and must be unique within the project, ignoring
     capitalization.
   - **Notes** optionally explain when or why the pattern should be used.
   - **Potential Failure Mode** is required and becomes the staged Failure Mode.
   - **Suggested Classification** may be Unclassified or one of the approved
     PFMEA Classification codes. It is a starting suggestion, not an approval.
   - **Active** controls whether the pattern is available under **Add PFMEA
     lines**. An inactive pattern remains stored and can still be reviewed or
     edited in the manager.
4. Enter **Effects** and **Causes**, with one entry per line. Blank lines
   are ignored, and the displayed top-to-bottom order becomes the saved order.
5. Each Cause creates its own bordered section. Enter **Recommended Actions**,
   with one entry per line, then choose its ordered **Prevention suggestions** and
   **Detection suggestions**. Suggestions can reference project-wide Quality
   requirement definitions or the corresponding manual control catalog.
6. **Undo** reloads the saved pattern values. Enter a nonblank **Current editor**
   and select **Save & Refresh** to save the complete pattern graph atomically
   and record one PFMEA History event.

The pattern table itself is a read-only catalog and deletion-selection surface;
use **Pattern to edit** for content changes rather than typing into the catalog
rows.
""",
    ),
    (
        "Create a pattern from a saved PFMEA line",
        """
Use **Save a PFMEA line as a pattern** inside **Manage PFMEA patterns** when a
saved PFMEA graph is a useful reusable starting point.

1. First use the PFMEA table's **Save & Refresh** or **Undo**, and clear any
   native deletion selection. Capture is disabled while the PFMEA table has an
   unsaved draft or selected deletion rows.
2. Choose exactly one **Saved PFMEA line**.
3. Enter a required, project-unique **New pattern label** and optional **New
   pattern notes**.
4. Review the capture preview for Failure Mode, Effect, Cause, Recommended
   Action, control-suggestion, and Classification counts.
5. Enter a nonblank **Current editor** and select **Save selected PFMEA line as
   pattern**.

Capture copies the reusable Failure Mode graph, Suggested Classification, and
eligible control sources. Quality selections are converted to their reusable
project-wide Quality requirement definitions; the scenario assignment and
Process Function are not copied. Inactive or unavailable controls are omitted
and disclosed. Ratings, RPN, responsibility, completion evidence, Actions
Taken, and resulting values are never stored in the new pattern.
""",
    ),
    (
        "Apply a pattern to PFMEA lines",
        """
Open **Add PFMEA lines** above **Select Current Process Controls** and the PFMEA
line-items table.

1. Select one or more **Process Functions**. Choices follow the established
   live Op ID order, and selecting them does not stage or save data.
2. For each Process Function, choose **Blank PFMEA line** or an active pattern.
3. Review the preview. It shows Item #, Process Function, pattern, Failure Mode,
   Effect/Cause/Action counts, compatible Prevention and Detection suggestions,
   and any source that will be omitted.
4. Select **Stage PFMEA lines**. Each choice creates a fresh, independent
   session-only PFMEA graph and appends it to the existing PFMEA draft. The flat
   table can show several rows when the graph contains several Effects, Causes,
   or Cause-specific Actions.
5. Review the staged analysis, enter fresh Severity, Occurrence, and Detection
   ratings, and adjust operation-specific text or controls as needed.
6. Use the PFMEA table's **Save & Refresh** to validate and persist the complete
   draft. Use the PFMEA table's **Undo** to discard the staged graphs.

**Stage PFMEA lines** performs no database write and creates no History event.
Only the normal PFMEA **Save & Refresh** persists the generated graphs and
records the save. Generated PFMEA entries keep no stored pattern lineage.
""",
    ),
    (
        "How pattern controls are handled",
        """
- A Quality requirement is copied into the PFMEA only when it has already been
  published to the selected Process Function in the current scenario. Applying
  a pattern never creates, publishes, or moves a Quality requirement.
- A manual control is copied only when it is **Active** and is in the correct
  Prevention or Detection list. An inactive control already saved in a pattern
  stays visible so you can remove it, but it is not copied into new PFMEA lines.
- The preview lists any controls that cannot be used. Those controls are left
  out. This means the same pattern may copy different controls to different
  Process Functions.
- If a Quality requirement or manual control is used by a pattern, remove it
  from the pattern and save before deleting that requirement or control.
- To delete a pattern, select it in the pattern list and use **Delete row(s)**.
  Confirming deletes the pattern only. PFMEA lines previously created from it
  are not deleted or changed.
- Creating, changing, activating, deactivating, or deleting a pattern is
  recorded in PFMEA History with the Current editor. Previewing or staging a
  pattern is not recorded because nothing has been saved yet.
""",
    ),
    (
        "Duplicate PFMEA lines",
        """
- **Duplicate selected PFMEA line** creates an independent unsaved line next to
  the source. It copies approved analysis, initial ratings, Classification,
  Actions, and compatible active controls while clearing Actions Taken and all
  resulting ratings/RPN values.
- Duplication is different from a pattern: it copies one current line inside
  the active scenario and can retain its initial ratings, while patterns are
  project-wide reusable guidance and always leave ratings blank.
""",
    ),
    (
        "Review tools",
        """
- The read-only **PFMEA completion assistant** lists missing Failure Mode,
  Effect, Cause, ratings, Classification, controls, and Recommended Action. Use
  **Next incomplete line** to focus one result and **Show all lines** to clear
  that focus.
- **Saved RPN by PFMEA line** charts persisted Effect-Cause risk lines. It does
  not apply approval thresholds or company risk colors.
- **High-risk PFMEA lines** shows a line when either RPN or Resulting RPN is
  greater than the entered threshold, ordered by the highest current value.
  The threshold is a read-only view filter, not a stored approval limit.
- **Process source review** appears when current Process information differs
  from the reviewed PFMEA snapshot. Accepting current sources preserves the
  PFMEA analysis and records the review in History.
""",
    ),
    (
        "Saving, deletion, export, and History",
        """
- **Undo** discards staged table, control, duplication, and pattern-generated
  changes. **Save & Refresh** validates and saves the complete PFMEA draft in
  one transaction with Current editor attribution.
- **Export filtered rows** creates an Excel file from the current filtered
  view with friendly control labels and no internal IDs.
- Select saved rows with the native left-side checkboxes and use the native
  **Delete row(s)** toolbar action. The confirmation explains that child
  Effects, Causes, controls, risk rows, Actions, and dependent Control Plan
  working-draft items will be removed; Process and Quality records remain.
- Persistent saves, deletions, source reviews, pattern changes, and manual
  control-catalog changes appear in the existing PFMEA History group. Filters,
  previews, completion guidance, and other draft-only actions create no event.
""",
    ),
    (
        "Manage reusable options",
        """
- **Manage PFMEA control options** maintains the project-wide Prevention and
  Detection manual catalogs. Options can be added, renamed, deactivated,
  filtered, exported, saved, and relationship-safely deleted.
- Deactivation preserves existing selections but prevents new use. Confirmed
  deletion discloses affected selections and marks affected Causes for review.
  An option referenced by a pattern cannot be deleted until that reference is
  removed.
""",
    ),
)


# Backward-compatible combined content for read-only consumers outside the
# dialog. The dialog itself renders the quick start and collapsed sections.
PFMEA_HELP = PFMEA_QUICK_START + "\n\n" + "\n\n".join(
    f"### {title}\n{content}" for title, content in PFMEA_HELP_SECTIONS
)


CONTROL_PLAN_HELP = """
Use **Control Plan** for the scenario-specific Manufacturing Control Plan
working draft. It is not an issued or approved document.

- A classified PFMEA entry creates a Control Plan operation. Published Quality
  requirements explicitly selected as that PFMEA entry's Prevention or
  Detection controls create separate characteristic lines. When no published
  Quality control qualifies, the classified PFMEA entry appears as an
  incomplete PFMEA-only line.
- Read-only pulls include **Station / Pitch**, **Operation**, **Product / Part
  characteristic**, **Process characteristic**, **CL**, **Specification /
  Requirement**, **Measurement / Evaluation**, and **Source review required**.
  Review warnings identify upstream information that needs collaborator review.
- Directly editable MCP fields are **Pr. Nº**, **Machine / fixture**,
  **Characteristic suffix**, **Characteristic type**, **Sample size**, **Sample
  frequency**, **Who**, **Control method**, and **Decision rule / corrective
  action and reference documents**.
- **Pr. Nº** is a collaborator-curated document number for a Process operation.
  It is repeated in storage for that operation but displayed only on the first
  visible characteristic line. It does not identify, link, sort, or change the
  underlying Process step.
- **Characteristic Nº** is the displayed combination of Pr. Nº and a
  characteristic suffix. Leave **Characteristic suffix** blank for automatic
  numbering, or enter a positive whole-number override. The resulting number is
  a document label only and does not control relationships or row order.
- **Characteristic type** places the derived characteristic in the **Product /
  Part characteristic** or **Process characteristic** column. **Not assigned**
  keeps the line visible and flags it for completion.
- Lines from the same Process operation are grouped together. Repeated Pr. Nº
  and Operation values are visually blanked after the first visible line;
  Station / Pitch remains visible on every line. Identical repeated Machine /
  fixture values may also be visually blanked without clearing saved data.

Use the Control Plan's shared **Undo** and **Save & Refresh** controls to manage
the working draft. Derived source fields remain read-only and never write back
to PFMEA, Quality requirements, or Process at a Glance.
"""
