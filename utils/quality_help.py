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
