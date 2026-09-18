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

Torque requirements can also use the project-wide **Torque tool details** area.
Requirement Types are maintained separately under **Manage Quality requirement
types**.
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
        "Patterns, duplication, and faster entry",
        """
- **Add PFMEA lines** can stage blank or patterned graphs for one or several
  Process Functions. Its preview shows Item #, Process context, analysis counts,
  compatible controls, and any omitted sources before staging.
- A project-wide PFMEA pattern can suggest Failure Mode, Effects, Causes,
  Recommended Actions, Classification, and ordered control sources. It never
  supplies ratings, RPN, responsibility, completion evidence, or resulting
  values, and generated PFMEA rows retain no pattern lineage.
- **Duplicate selected PFMEA line** creates an independent unsaved line next to
  the source. It copies approved analysis, initial ratings, Classification,
  Actions, and compatible active controls while clearing Actions Taken and all
  resulting ratings/RPN values.
- **Save selected PFMEA line as pattern** captures one saved graph after a
  preview. It excludes ratings, completion evidence, resulting values, and
  inactive controls.
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
- **Manage PFMEA patterns** maintains reusable pattern headers, Effects,
  Causes, Recommended Actions, Classification suggestions, and ordered control
  suggestions. It provides filtering, export, Undo, Save & Refresh, and
  confirmed deletion. Deleting a pattern never deletes PFMEA rows previously
  created from it.
""",
    ),
)


PFMEA_HELP = """
Use **PFMEA** to document scenario-specific failure analysis for Process at a
Glance work.

- For a new line, choose **Process Function** from the active scenario's Work
  Elements. The friendly choice shows the current derived Op ID followed by
  the Work Element; the internal relationship stays hidden. Complete choices
  follow the curated Fishbone and Yamazumi physical order, while incomplete
  Op IDs remain selectable at the end. After the first **Save & Refresh**, the
  Process Function is locked in the normal editor.
- **Item #** is read-only. It automatically shows the selected Process
  Function's current Pitch; it is not a separately entered identifier.
- Enter **Severity**, **Occurrence**, and **Detection** as ratings from 1 through
  10. **RPN** is Severity × Occurrence × Detection. Resulting RPN uses the three
  Resulting ratings. A calculation stays blank until all three inputs exist.
- **Recalculate RPN** refreshes Initial and Resulting RPN from the current
  unsaved ratings without saving the PFMEA. **Save & Refresh** also recalculates
  and persists the current results.
- **Current Process Controls — Prevention** and **Current Process Controls —
  Detection** combine published Quality requirements linked to that Process
  step with active choices from the corresponding project-wide manual control
  catalog. The selections remain staged with the PFMEA draft until **Save &
  Refresh**.
- **High-risk PFMEA lines** is read-only. It shows a line when either RPN or
  Resulting RPN is greater than the entered review threshold and lists the
  highest current risk first. The threshold is a view filter, not an approval
  limit and not a stored scoring rule.

### Classification codes

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
"""

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
