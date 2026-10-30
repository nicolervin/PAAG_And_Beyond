"""Static, read-only guidance displayed by the Quality Functional Review help dialog."""

TRACEABILITY_QUICK_START = """
Use **📊 Traceability Matrix** and the page-level **PAAG Sync & Unlinked Review** banners to monitor end-to-end quality coverage across your active planning scenario and keep downstream quality documents aligned when Industrial Engineering updates the Process at a Glance (PAAG).

1. **Audit 5-Pillar Coverage**: Track every PAAG step across **PAAG Step → Quality Requirement → PFMEA Risk → Control Plan → Equipment / Tooling**.
2. **Resolve Live Discrepancies**: Use the **Actionable Discrepancy Cards** at the bottom of the Traceability Matrix to align drifted specifications (`🔧 Align Spec`), link missing tooling (`🔩 Link Tooling`), or jump directly to incomplete PFMEA / Control Plan items.
3. **Reconcile Upstream PAAG Edits**: When a PAAG step is modified or moved (`⚡ Review Upstream Changes`) or deleted (`⚠️ Unlinked Review`), review the side-by-side comparison to sync, reassign, or bulk-relink your quality records without losing engineering work.
"""

TRACEABILITY_HELP_SECTIONS = (
    (
        "Cross-Functional Traceability & Discrepancy Matrix (📊 Traceability Matrix)",
        """
The **📊 Traceability Matrix** tab provides a live, single-pane health dashboard evaluating whether every manufacturing step and engineering requirement is properly analyzed and controlled:

- **KPI Scorecard**:
  - **Fully Protected %**: Percentage of active scope rows with complete chain coverage and zero warnings or gaps.
  - **Critical Gaps**: Count of rows with high-priority breaks in the quality chain (e.g., an assigned Quality Requirement with no Control Plan coverage, or a high-severity PFMEA line (`Severity ≥ 8`) with no Control Plan characteristic).
  - **Warnings & Drift**: Count of rows with specification drift, missing PFMEA analysis, missing physical tooling/equipment, or unassigned repository requirements.
  - **Protected Steps / Total Steps**: Total PAAG operations in the active scenario and how many have achieved `🟢 Fully Protected` status.
- **Interactive Filters & Excel Export**:
  - Filter the matrix by **Traceability Status** (`🔴 Critical Gap`, `🟡 Warning / Drift`, `🟢 Fully Protected`, `⚪ Unassigned / Info`), **Station / Pitch**, or **Discrepancy Type** (`Specification Drift`, `Missing Control Plan`, `Missing PFMEA`, `Tooling / Equipment Gap`, `Unassigned Requirement`).
  - Select **📥 Export Matrix (.xlsx)** to download the currently filtered traceability audit table for offline review or phase-gate signoff.
""",
    ),
    (
        "Resolving Discrepancies (Align Spec, Link Tooling & Quick Navigation)",
        """
Below the matrix table, **🔧 Resolve Discrepancies & Gaps** groups every detected issue into expandable action cards (up to 25 cards displayed at once according to your active filters):

- **Specification Drift (`🔧 Align Spec`)**:
  - **Why it happens**: A Quality Requirement's Target, Tolerance, Unit, or Pass/Fail setting was updated in the Requirements Repository and pushed to the process step *after* the Control Plan specification was already saved, causing the Control Plan text to differ from the authoritative Quality Requirement.
  - **How to resolve**: Click **🔧 Align Spec** on the card to open the **Align Control Plan Specification** modal. Review the side-by-side comparison (**Authoritative Quality Requirement** vs. **Current Control Plan Spec**) and click **✅ Align Control Plan Spec** to overwrite the outdated Control Plan specification with the current requirement spec.
- **Tooling / Equipment Gap (`🔩 Link Tooling`)**:
  - **Why it happens**: Either a **Torque** Quality Requirement is assigned to the step or a PFMEA Prevention/Detection control calls out physical equipment (such as a **Vision System**, **Barcode / Scanner**, **Fixture / Poka-Yoke**, **Gauge / Measurement Tool**, or **ESD Protection**), but no matching equipment is placed and linked at that step's Station / Pitch.
  - **How to resolve**: Click **🔩 Link Tooling** to open the **Resolve Tooling / Equipment Gap** dialog. You can either:
    1. **Link Existing Asset at Pitch**: Select an asset already placed at that Station / Pitch and attach it to the PAAG step and Quality review.
    2. **Create & Place New Asset**: Enter a new **Equipment Name**, **Tier** (`Handheld Tools`, `Station/Pitch Equipment`, `Capital Equipment`), and **Equipment Type** (`Torque tool`, `Vision system`, etc.) to create the asset, place it at the step's Pitch, and link it to the step in one action (and automatically link the Torque requirement if applicable).
- **Missing Control Plan / Missing PFMEA Quick Jumps**:
  - Use **Open in Control Plan** or **Open in PFMEA** on any card to navigate straight to the corresponding tab to classify a PFMEA failure mode or complete a Control Plan row.
""",
    ),
    (
        "Upstream PAAG Process Changes Banner & Dialog (⚡ Review Upstream Changes)",
        """
When an Industrial Engineer edits a PAAG process step that already has linked Quality Requirements or PFMEA failure modes (changing its **Station / Pitch**, **Operation**, **Location**, or **Process Description**), a warning banner appears at the top of the Quality page:

- Click **⚡ Review Upstream Changes** in the banner to open the reconciliation modal.
- **Side-by-Side Snapshot Comparison**: Each affected record displays the **Saved Snapshot** (what the PAAG step looked like when Quality last reviewed it) next to the **Current Live PAAG** values, highlighting exactly which fields changed (`Station/Pitch`, `Operation`, `Location`, `Description`).
- **Resolution Actions**:
  - **✅ Accept & Sync All Validated**: Synchronizes all eligible records on that step to the new PAAG snapshot in one click.
  - **✅ Accept** (individual row): Updates that specific Quality requirement assignment or PFMEA entry to adopt the current PAAG step wording and Pitch.
  - **🔒 PAAG Validation Gate on PFMEA Sync**: PFMEA entries can only be synchronized if the upstream PAAG step is marked **Completed & Validated** (`PAAG Validated`). If the PAAG step is still incomplete, `Accept` is locked for PFMEA rows until the step is validated in PAAG, or you can reassign the PFMEA row to a different validated step.
  - **🔀 Reassign**: If an operation was split or repurposed and your Quality requirement or PFMEA failure mode belongs on a different PAAG step, expand **🔀 Reassign**, select the target PAAG step, and click **Move**.
""",
    ),
    (
        "Unlinked Downstream Records Banner & Tab (⚠️ Unlinked Review)",
        """
When a PAAG process step is **deleted** upstream, the application never silently deletes your Quality work. Instead, affected Quality Requirement assignments, PFMEA failure modes, and Equipment step links are preserved in an unlinked state with their last known **Historical Snapshot** (`Pitch`, `Operation`, and `Description`), and the **⚠️ Unlinked Review** tab activates automatically:

- **Option 1 — Bulk Relink Entire Deleted Operation (Fastest)**:
  - Under **1. Bulk Relink by Deleted Operation Snapshot**, all orphaned records from the same deleted PAAG step are grouped together.
  - Choose a **Target Active PAAG Step** and click **🔗 Relink Entire Operation** to move all Quality requirements, PFMEA lines, and Equipment links from that deleted operation onto the replacement step in a single transaction.
- **Option 2 — Individual Record Review & Resolution**:
  - Under **2. Individual Record Review & Resolution**, switch between the **Quality Requirements**, **PFMEA Failure Modes**, and **Tooling & Equipment** sub-tabs to inspect records individually:
    - **Relink Selected**: Select one or more rows with the left-hand checkboxes, pick a replacement PAAG step, and click **🔗 Relink Selected**.
    - **Delete Selected (Unassign)**: For obsolete Quality requirement assignments or PFMEA failure modes, select the rows and click **🗑️ Delete Selected** to permanently remove them.
    - **Keep in Pitch & Clear Step Link (Equipment only)**: For Tooling & Equipment, clicking **📌 Keep in Pitch & Clear Step Link** clears the obsolete PAAG step reference while keeping the physical equipment assigned to its current Station / Pitch.
""",
    ),
    (
        "Unsaved PFMEA Draft Banner Across Tabs",
        """
If you have unsaved edits or newly staged lines in the **PFMEA** worksheet and navigate to another Quality tab, an **⚠️ Unsaved PFMEA Edits Staged** banner appears at the top of the page showing the count of modified and newly added rows:

- **💾 Save Draft**: Validates and commits your staged PFMEA changes directly from your current tab (requires a non-blank **Current editor** in the sidebar and all staged lines to have a selected **Process Function**).
- **🗑️ Discard Draft**: Clears the unsaved session draft and reverts the PFMEA table to the last saved database state.
- **✏️ Go to PFMEA**: Switches back to the PFMEA tab so you can inspect and finish editing your staged lines.
""",
    ),
)

TRACEABILITY_AND_SYNC_HELP = TRACEABILITY_QUICK_START + "\n\n" + "\n\n".join(
    f"### {title}\n{content}" for title, content in TRACEABILITY_HELP_SECTIONS
)


REQUIREMENTS_QUICK_START = """
Use the **Requirements repository** to maintain a master, project-wide catalog of reusable Quality checks and engineering specifications (such as dimensional checks, torque specs, leak tests, and visual standards), and assign them to specific **Process at a Glance (PAAG)** steps in the active scenario.

1. **Define Master Requirements**: Add or edit reusable requirements in the **Quality requirements** table with a **Type**, **Description**, **Pass/fail** toggle, or numeric **Target value**, **Tolerances**, and **Unit**.
2. **Assign to PAAG Steps**: Click **🔗 Assign Steps...** in the toolbar to open the multi-select assignment modal and link a requirement to one or many PAAG operations at once.
3. **Sync Updates Downstream**: When you edit a saved requirement in the repository, click **Save & Refresh**, then use **Push saved updates to linked Process steps** under **Publish saved updates** to propagate the new values to linked scenario steps.
"""

REQUIREMENTS_HELP_SECTIONS = (
    (
        "Creating & Editing Master Quality Requirements",
        """
The **Quality requirements** table stores reusable specifications across the entire project so you do not have to re-type identical drawing callouts for every station or scenario:

- **Type**: Select an active category from the project-wide Requirement Type catalog (e.g., `Torque`, `Dimensional`, `Visual`, `Functional`).
- **Description**: Enter the clear engineering check or specification name (e.g., `Rear Cover Fastener Torque` or `Flushness Gap Check`). This description flows directly into the **Control Plan** characteristic name and **Specification / Requirement** column.
- **Unique identifier**: Optional drawing bubble number, CTQ ID, or engineering reference code.
- **Pass/fail vs. Measured Specifications**:
  - **Pass/fail checked (`True`)**: Identifies an attribute or binary check (e.g., presence/absence, visual appearance). When `Pass/fail` is checked, **Target value**, **Tolerances**, and **Unit** are automatically cleared on save.
  - **Pass/fail unchecked (`False`)**: Identifies a variable measurement. Enter the **Target value** (numeric nominal, e.g., `12.5`), **Tolerances** (e.g., `± 1.5` or `+0.5 / -0.0`), and **Unit** (chosen from the allowed units configured for that Requirement Type).
- **Read-Only Status Columns**:
  - **Linked Process steps**: Shows how many PAAG operations across the project currently use this requirement.
  - **Pending linked updates**: Shows how many linked PAAG step copies still hold an older snapshot because the master requirement was edited after it was assigned.
- **Filtering & Searching**:
  - Filter the repository by **Type**, **Pass/fail** (`All`, `Pass/fail only`, `Measured only`), **Unit**, **Assignment status** (`All`, `Assigned`, `Unassigned / Needs Process Step`), or keyword search.
  - Filtering by `Unassigned / Needs Process Step` is the fastest way to verify that every drawing requirement has been mapped to at least one assembly operation.
""",
    ),
    (
        "Assigning Requirements to Process Steps (🔗 Assign Steps... Modal)",
        """
To attach a saved Quality requirement to one or more PAAG operations in the active scenario, click **🔗 Assign Steps...** in the table toolbar (or click **Assign to Process Steps**):

1. **Choose Requirement**: Select any saved requirement from the dropdown. A summary banner confirms its Type, Specification (`Target ± Tolerance Unit` or `Pass/Fail`), and how many steps it is currently assigned to in the active scenario.
2. **Filter PAAG Steps**: Narrow the step list by **Filter by Station / Pitch** or **Search Op ID, Operation, or Description** to quickly isolate a specific line section or work element.
3. **Batch Select / Deselect**:
   - Check or uncheck the **Assigned** column next to each PAAG step, or use **Select All Visible** and **Clear Visible** to batch-assign the requirement across multiple stations.
   - The live counter (`Selected: X step(s) (+Y new, -Z removed)`) previews your exact changes before saving.
4. **Proactive Torque Tooling Gap Advisory**:
   - When you assign a **Torque** requirement to one or more PAAG steps that do not yet have a `Torque tool` linked in the Quality Equipment tab, an inline **Torque Tooling Gap Advisory** appears automatically.
   - Check **Also link a Torque tool to the newly assigned step(s)** to either attach an existing Torque tool or create and place a new Torque tool across all target Pitches and steps at the same time.
5. Click **Save Step Assignments** to publish the requirement to the selected PAAG steps.
""",
    ),
    (
        "Managing Linked Process Steps & Publishing Repository Updates",
        """
Two expanders below the main table help you manage scenario links and keep published copies synchronized:

- **View Quality requirements linked to Process steps**:
  - Displays every requirement currently assigned to a PAAG step in the active scenario, ordered by physical line sequence (`Pitch`, `Operation`, `Location`, `Step description`).
  - **Upstream modified**: Checked when the PAAG step's Pitch, Operation, Location, or Description was edited in PAAG after the requirement was linked. Use the top-of-page **⚡ Review Upstream Changes** button to accept or reassign the step.
  - **Repository update pending**: Checked when the master requirement in the repository has been modified since it was published to this step.
  - **Removing Step Links**: Select one or more rows using the left-side checkboxes and click **Delete row(s)** in the table toolbar to unassign the requirement from those PAAG steps without deleting the master requirement from the repository.
- **Publish saved updates (`Push saved updates to linked Process steps`)**:
  - Editing a requirement in the repository and clicking **Save & Refresh** updates the master catalog definition only—it does not immediately overwrite published step copies.
  - Open **Publish saved updates**, review the list of requirements with pending changes, and click **Push saved updates to linked Process steps** to update all linked step copies.
  - *Note*: If a linked step already has a saved Control Plan row whose specification text was previously generated from the old requirement values, pushing an update will flag **Specification Drift** in the **📊 Traceability Matrix**, where you can review and align the Control Plan spec with one click (`🔧 Align Spec`).
""",
    ),
    (
        "Managing Quality Requirement Types & Allowed Units",
        """
Open **Manage Quality requirement types** to customize the project-wide categories and measurement units available in the Requirements Repository:

- **Type**: The category name (e.g., `Torque`, `Leak Test`, `Electrical`, `Dimensional`).
  - **Protected `Torque` Type**: The built-in `Torque` type is permanently active and cannot be renamed, deactivated, or deleted because it drives dedicated Torque Tool hardware specifications and tooling gap checks.
  - **Renaming In-Use Types**: If you rename a Type that is already used by saved requirements, a confirmation prompt summarizes the affected requirements, updates their Type label upon confirmation, and marks their linked PAAG step copies as `Repository update pending`.
- **Units available (Semicolon-Separated)**:
  - Define the allowed measurement units for each Type by separating units with semicolons (for example, `in-lbs;ft-lbs;N·m` for `Torque`, or `inch;mm;mil` for `Dimensional`).
  - These units populate the **Unit** dropdown in the Quality requirements table and are validated when saving measured requirements of that Type.
- **Active**: Uncheck `Active` to hide a Type from new requirement selections while preserving existing requirements that already use it.
- **Deleting Types**: Select unused custom Types with the left-side checkbox and click **Delete row(s)**, then click **Save & Refresh**. Types currently referenced by saved requirements cannot be deleted until those requirements are reassigned to another Type or removed.
""",
    ),
)

REQUIREMENTS_REPOSITORY_HELP = REQUIREMENTS_QUICK_START + "\n\n" + "\n\n".join(
    f"### {title}\n{content}" for title, content in REQUIREMENTS_HELP_SECTIONS
)


PFMEA_QUICK_START = """
Use **PFMEA** to perform scenario-specific Process Failure Mode and Effects Analysis on validated **Process at a Glance (PAAG)** steps, manage reusable failure mode patterns and manual control catalogs, and flag critical controls that require **Control Plan** coverage.

1. **PAAG Validation Gate**: Ensure the target PAAG step is marked **Completed & Validated** in Process at a Glance (`🔒 PAAG Validation Gate`).
2. **Stage New Lines or Patterns**: Use the **⚡ PFMEA Line Staging & Pattern Bar** above the worksheet to apply a reusable failure mode pattern (single step or batch multi-step) or stage custom blank PFMEA lines.
3. **Analyze Failure Modes & Controls**: Complete the Failure Mode, Effects, Severity (`1–10`), Classification (`CL`), Causes, Occurrence (`1–10`), Prevention/Detection Controls, and Detection (`1–10`).
4. **Assign Actions & Save**: Select a **Responsibility** owner and **Target Completion Date**, use **Recalculate RPN** to preview risk scores, and click **Save & Refresh** to commit the draft.
"""

PFMEA_HELP_SECTIONS = (
    (
        "PAAG Validation Gate & Staging New PFMEA Lines (Pattern Quick-Apply vs. Blank Lines)",
        """
- **🔒 PAAG Validation Gate**:
  - Only PAAG steps that have been marked **Completed & Validated** by Industrial Engineering can be selected when creating new PFMEA failure modes or synchronizing upstream PAAG changes.
  - The caption above the worksheet displays the live count of eligible validated steps (`Only Completed & Validated PAAG steps (X/Y) can be selected for new PFMEA failure modes`).
- **⚡ PFMEA Line Staging & Pattern Bar**:
  - Located directly above the PFMEA worksheet, this bar lets you add PFMEA rows in two ways:
  - **Mode 1 — ⚡ Pattern Quick-Apply**:
    - Select an active reusable pattern from **1. Select Failure Mode Pattern** (if your project has no patterns yet, click **🌱 Seed Standard Starter Patterns** to automatically generate three industry-standard templates: *Torque Fastener Assembly*, *Press Fit Component Assembly*, and *Visual Quality Inspection*).
    - Choose **Single Step** (pick one PAAG step and click **⚡ Apply Pattern**) or **Batch Multi-Step** (check multiple PAAG steps—or click `Select All Steps`—and click **⚡ Apply to X Step(s)**).
    - Staging a pattern appends a complete, independent failure mode graph (Failure Mode, Suggested Classification, Effects, Causes, Recommended Actions, and active Prevention/Detection controls) to your current unsaved PFMEA draft.
  - **Mode 2 — ➕ Add Custom Blank Line(s)**:
    - Select one or more validated PAAG steps in **Select Process Function(s) to stage blank PFMEA lines** and click **➕ Stage Blank Line(s)** (or add a row at the bottom of the grid).
""",
    ),
    (
        "PFMEA Worksheet Columns, Shared-Record Sync & Inline Editing",
        """
The **PFMEA line items** table presents the multi-level PFMEA hierarchy (`Failure Mode → Effects / Causes → Controls & Recommended Actions`) in a flat, spreadsheet-friendly worksheet:

- **Item # & Process Function**:
  - **Item #** is read-only and displays the selected PAAG step's current **Station / Pitch**.
  - **Process Function** shows the derived `Op ID — Work Element`. Once a PFMEA line is saved for the first time, its `Process Function` locks to preserve historical traceability (to move a saved PFMEA line to a different operation, use the upstream change reassignment workflow).
- **Failure Mode, Effects, Causes & Shared-Record Synchronization**:
  - When a single Failure Mode has multiple Effects, Causes, or Recommended Actions, the flat table displays one row per combination.
  - Editing a shared field (such as the **Potential Failure Mode** text, **Classification**, an **Effect**, a **Severity** rating, or a **Cause**) automatically synchronizes across all flat rows backed by that same record upon **Save & Refresh**.
  - Press `Shift+Enter` to insert multi-line text inside a cell, or use separate PFMEA lines when different Failure Modes or Causes require distinct ratings or controls.
- **Filtering & Sorting**:
  - Filter the worksheet by keyword, **Item #** (Pitch), or **Classification**, and sort saved rows by `Saved order`, `Item #`, `Process Function`, `Potential Failure Mode`, `Severity`, `Classification`, `Occurrence`, `Detection`, `RPN`, or `Resulting RPN` (ascending or descending).
""",
    ),
    (
        "Ratings, RPN Calculation, and Classification (CL) Codes",
        """
- **Severity, Occurrence, and Detection (`1–10`)**:
  - Enter whole numbers from `1` to `10`.
  - **Initial RPN** is calculated automatically as $\\text{Severity} \\times \\text{Occurrence} \\times \\text{Detection}$ once all three ratings are entered.
  - **Resulting RPN** is calculated from $\\text{Resulting Severity} \\times \\text{Resulting Occurrence} \\times \\text{Resulting Detection}$ after corrective actions are taken.
  - Click **Recalculate RPN** in the toolbar at any time to preview updated Initial and Resulting RPN values on unsaved draft edits before saving.
- **Classification (`CL`) & Control Plan Eligibility**:
  - Selecting a **Classification** code marks the PFMEA line as requiring downstream **Control Plan** management and automatically generates corresponding Control Plan row(s) once saved. Leave `Classification` blank if the failure mode is not classified.
  - Click the **PFMEA Classification legend** expander above the table at any time to reference the company classification definitions:

| Code | Meaning |
| --- | --- |
| **S** | Safety (Critical to Product Safety) |
| **R** | Regulatory |
| **E** | Engineering CTQ |
| **P** | Process CTQ |
| **C** | Critical Characteristic |
| **H** | High Impact / High RPN |
| **K** | Key Characteristic |
| **F** | Fit / Function |
| **V** | Verification / Visual |
| **L** | Low Impact / Minor |
""",
    ),
    (
        "Current Process Controls (Prevention & Detection) & Control Plan Coverage Flag",
        """
PFMEA **Prevention** and **Detection** controls represent your process-level safeguards (such as fixtures, poka-yokes, gauges, automated sensors, and visual checks). Quality drawing specifications live in the Requirements Repository and flow directly to the Control Plan, keeping PFMEA controls focused on process prevention and detection methods:

- **Two Ways to Assign Controls**:
  1. **Direct In-Grid Multiselect**: Double-click the **Current Process Controls — Prevention** or **Current Process Controls — Detection** cell directly in the PFMEA table to pick or remove active catalog controls.
  2. **Select Current Process Controls Panel (Below the Worksheet)**: Select a saved or draft **Cause to edit** to manage its Prevention and Detection controls with full ordering, **Copy Prevention / Copy Detection / Copy both**, and **Paste to selected Cause** across rows.
- **Creating New Custom Controls Inline**:
  - Inside **Select Current Process Controls**, expand **➕ Create custom manual prevention/detection option**, enter the **Option label**, choose `Prevention` or `Detection`, and click **Add & Select Option** to add it to the project catalog and immediately select it on the current Cause.
- **Requires Control Plan Flag & Coverage Warning Banner**:
  - Not every PFMEA control belongs in the Control Plan (for example, simple visual checks or operator awareness may not warrant a formal Control Plan entry, whereas gauges, fixtures, and automated measurements do).
  - When creating or editing a control in the catalog, check **Requires Control Plan (flag if missing from Control Plan)** for critical controls that must be governed on the shop floor.
  - **⚠️ Control Plan Coverage Flag Banner**: If any PFMEA line uses a control marked `Requires Control Plan`, the application checks whether:
    1. The PFMEA line has a **Classification (`CL`)** assigned so it flows into the Control Plan, and
    2. That control has been selected in the **Control method** dropdown on at least one Control Plan row for that PAAG step.
  - If either condition is missing, a warning banner (**⚠️ Control Plan Coverage Flag**) appears at the top of both the **PFMEA** and **Control Plan** tabs with an expandable table (**View PFMEA Controls Missing from Control Plan**) detailing the exact `Item #`, `Process Function`, `Control Type`, `Control Label`, and `Action Needed`.
""",
    ),
    (
        "Recommended Actions, Assignees (👥 Manage Assignees) & Target Dates",
        """
When a Cause requires risk reduction beyond current controls, document the corrective action plan in the right-hand columns of the PFMEA worksheet:

- **Recommended Action**: Describe the engineering or process improvement action to reduce Severity, Occurrence, or Detection. Multiple Recommended Actions can be tracked for the same Cause.
- **Responsibility & Target Completion Date**:
  - **Responsibility** and **Target Completion Date** are managed in dedicated columns in the worksheet (and automatically combined into the standard `Responsibility & Target Completion Date` column when exporting the Company Template).
  - Choose the owner from the **Responsibility** dropdown and select a date in **Target Completion Date** (`YYYY-MM-DD` calendar picker).
- **👥 Manage Assignees Popover**:
  - Click **👥 Manage Assignees** in the PFMEA toolbar to manage the project's responsible personnel list:
    - **➕ Add New Assignee**: Add a team member's name to make them selectable in the `Responsibility` column.
    - **Active Assignees & Mark Inactive**: Mark departing or rotated personnel as inactive so they no longer clutter new dropdown selections, while preserving their name on historical completed actions.
    - **🔄 Reassign Tasks**: Bulk-transfer all PFMEA action rows currently assigned to one person (e.g., an inactive engineer) to another active team member in one click.
- **Actions Taken & Resulting Ratings**:
  - Once the action is implemented, record the verification details and completion date in **Actions Taken** and enter **Resulting Severity**, **Resulting Occurrence**, and **Resulting Detection** to compute the **Resulting RPN**.
""",
    ),
    (
        "Manual Control Catalog Overview & Editor (📊 Control Catalog)",
        """
Open **📊 Manual Prevention & Detection Control Catalog Overview** below the worksheet to audit and maintain your project's reusable Prevention and Detection control libraries:

- **Catalog KPIs & Quick-Add**:
  - View counts of **Active Prevention Options**, **Active Detection Options**, and **PFMEA Lines Using Controls**.
  - Use **➕ Quick-Add Custom Control Option** to create a new Prevention or Detection control and optionally mark **Requires Control Plan**.
- **📊 Side-by-Side Review Chart**:
  - Displays a clean side-by-side summary of all Prevention and Detection controls, their `Status` (`Active` / `Inactive`), whether `Ctrl Plan Req.` is checked (`🚩 Yes` / `No`), and how many PFMEA lines (`Used in Lines`) currently reference each option.
- **✏️ Edit Prevention Catalog & ✏️ Edit Detection Catalog Tabs**:
  - Filter by keyword or active status, export the catalog to Excel, rename options, toggle **Requires Control Plan** or **Active** checkboxes directly in the table, or select unused rows and click **Delete row(s)**, then click **Save Prevention Catalog** / **Save Detection Catalog**.
  - Deleting an option that is currently used on saved PFMEA lines prompts a confirmation disclosing how many Causes are affected and flags those Causes for review. Options referenced by a saved PFMEA Pattern cannot be deleted until removed from the pattern.
""",
    ),
    (
        "Creating, Capturing & Managing Reusable PFMEA Patterns",
        """
A **PFMEA Pattern** is a project-wide template for recurring manufacturing processes (such as fastening, pressing, adhesive dispensing, or inspection). Applying a pattern creates an independent copy in the active scenario without linking saved PFMEA rows back to the template:

- **Manage PFMEA patterns Expander**:
  - Filter existing patterns by keyword, `Active` state, or `Suggested Classification`, or export the pattern catalog to Excel.
  - Under **Pattern to edit**, choose **Create new pattern** or select an existing pattern to update its **Label**, **Notes**, **Potential Failure Mode**, **Suggested Classification**, **Active** checkbox, ordered **Effects**, ordered **Causes**, and each Cause's **Recommended Actions**, **Prevention suggestions**, and **Detection suggestions**.
- **Save a PFMEA line as a pattern**:
  - Inside **Manage PFMEA patterns**, you can turn any well-written saved PFMEA line into a reusable project pattern.
  - Save or undo any current PFMEA table draft first, select one **Saved PFMEA line**, enter a unique **New pattern label** and optional notes, review the capture preview, and click **Save selected PFMEA line as pattern**.
  - *Note*: Patterns intentionally strip scenario-specific ratings (`S`, `O`, `D`, `RPN`), assignees, target dates, and `Actions Taken` so engineers perform a fresh risk evaluation each time the pattern is applied to a new operation.
""",
    ),
    (
        "Duplicating Lines, Completion Assistant, RPN Charts & Exports",
        """
- **Duplicate PFMEA line Expander**:
  - Unlike raw spreadsheet copy-paste (which only copies visible text cells), **Duplicate selected PFMEA line** clones the entire underlying PFMEA graph—including its active Prevention and Detection controls, Effects, Causes, Classification, initial ratings, and Recommended Actions—into a new unsaved draft line while clearing `Actions Taken` and resulting ratings.
- **PFMEA completion assistant**:
  - Automatically audits all saved PFMEA lines for missing fields (missing Failure Mode, Effect, Cause, Severity/Occurrence/Detection ratings, Classification, Prevention/Detection controls, or Recommended Action).
  - Click **Next incomplete line** to filter the main PFMEA worksheet to a single incomplete line at a time, and click **Show all lines** to restore the full view.
- **Saved RPN by PFMEA line & High-risk PFMEA lines**:
  - Visualizes saved RPN values in a horizontal bar chart and filters high-risk lines where Initial RPN or Resulting RPN exceeds your configurable **RPN review threshold** (default `100`).
- **Process source review**:
  - Lists PFMEA lines whose linked PAAG step changed upstream (`Pitch`, `Operation`, `Location`, or `Description`) or whose controls require review after a catalog deletion. Select rows and click **Mark selected PFMEA sources reviewed** (gated by PAAG step validation).
- **Three Export Formats**:
  - **Export filtered rows**: Standard multi-column Excel (`.xlsx`) export of the current filtered view.
  - **Export Company Template (FRM-GEA-QYS-033)**: Populates the official formatted company PFMEA Excel template (`FRM-GEA-QYS-033`), preserving official header styling, worksheet formulas, and combined `Responsibility & Target Completion Date` formatting.
  - **Export filtered rows (.csv)**: Lightweight CSV export for external data analysis.
""",
    ),
)

# Backward-compatible combined content for read-only consumers outside the dialog.
PFMEA_HELP = PFMEA_QUICK_START + "\n\n" + "\n\n".join(
    f"### {title}\n{content}" for title, content in PFMEA_HELP_SECTIONS
)


CONTROL_PLAN_QUICK_START = """
Use **Control Plan** to manage the scenario-specific Manufacturing Control Plan (MCP) working draft and inspect the visual **Process flow map**.

1. **Understand Automatic Row Generation**: Control Plan rows are automatically generated and pre-populated from **classified PFMEA failure modes** (where `Classification` is not blank) combined with **published Quality requirements** assigned to that PAAG step.
2. **Resolve PFMEA Control Coverage Flags**: Review the **⚠️ PFMEA Control Coverage Flag** banner at the top of the tab and select flagged PFMEA controls in the **Control method** dropdown so every critical gauge, fixture, or poka-yoke is accounted for.
3. **Complete Control Plan Details**: Set the **Characteristic type** (`Product` or `Process`), verify the auto-populated **Specification / Requirement**, and enter the **Measurement technique**, **Sample Size**, **Sample Frequency**, **Control method**, and **Reaction Plan**, then click **Save & Refresh**.
"""

CONTROL_PLAN_HELP_SECTIONS = (
    (
        "How Control Plan Rows Are Pre-Populated (Why Blank Rows Cannot Be Added Manually)",
        """
The **Control Plan** is strictly driven by upstream engineering linkages rather than freeform manual row insertion. This guarantees 100% traceability back to the PAAG, Requirements Repository, and PFMEA:

- **Step 1 — PFMEA Classification Gate**:
  - A PAAG process step enters the Control Plan **only when it has at least one saved PFMEA failure mode with a non-blank Classification (`CL`)** (such as `S`, `R`, `E`, `P`, `C`, `H`, `K`, `F`, `V`, or `L`).
  - Unclassified PFMEA lines do not generate Control Plan rows; they are listed in the **Review excluded and source-ineligible items** expander at the bottom of the tab so you can easily see why a step is not yet in the Control Plan.
- **Step 2 — Pairing with Published Quality Requirements**:
  - Once a PAAG step has a classified PFMEA entry, the Control Plan checks all **published Quality requirements** linked to that same PAAG step in the **Requirements repository**:
    - **If the PAAG step has 1 or more published Quality requirements**: The Control Plan automatically generates **one row per published Quality requirement** on that step (for example, if a step has 3 assigned Quality requirements, 3 Control Plan rows appear for that operation).
    - **If the PAAG step has 0 published Quality requirements**: The Control Plan generates **one PFMEA-only row** for that step using the PFMEA Failure Mode as the characteristic label.
- **How to Add Another Characteristic Row to the Control Plan**:
  - To add a new characteristic row for an operation, go to the **Requirements repository** tab, create or select the Quality requirement, and assign it to that PAAG step via **🔗 Assign Steps...** (and ensure the step has a classified PFMEA line). The new row will automatically appear in the Control Plan!
""",
    ),
    (
        "PFMEA Control Coverage Flag Banner & Control Method Dropdown Link",
        """
When a PFMEA Prevention or Detection control is marked **Requires Control Plan** in the PFMEA catalog (used for critical controls like gauges, fixtures, torque monitoring, or automated sensors), the Control Plan actively tracks whether that control has been assigned on the shop floor:

- **⚠️ PFMEA Control Coverage Flag Banner**:
  - Appears at the top of the Control Plan tab whenever a PFMEA line uses a control marked `Requires Control Plan`, but either:
    1. The PFMEA line is still unclassified (`CL` is blank), preventing the step from appearing in the Control Plan, or
    2. The control has not yet been selected in the **Control method** column on any Control Plan row for that PAAG step.
  - Expand **View PFMEA Controls Missing from Control Plan** inside the banner to see the exact `Item # (Pitch)`, `Process Function`, `Failure Mode`, `Cause`, `Control Type`, `Control Label`, and `Action Needed`.
- **Automatic Sync to the Control Method Dropdown**:
  - Every active PFMEA control marked **Requires Control Plan** automatically appears as a selectable option in the Control Plan's **Control method** dropdown menu.
  - Simply select that control in the **Control method** column for the corresponding row and click **Save & Refresh** to link the control and clear the warning banner.
""",
    ),
    (
        "Managing Custom Control Methods (➕ Manage Custom Control Methods)",
        """
Open the **➕ Manage Custom Control Methods** expander above the Control Plan table to manage the dropdown options available in the **Control method** column:

- **Add New Control Method**:
  - Enter a **Method Name** (e.g., `SPC X-bar & R Chart`, `100% Automated Torque Monitoring`, `First Piece Check Sheet`), choose the **Scope**:
    - **Current Project Only**: Available only within the active project.
    - **Global (All Projects)**: Available across all projects in the application.
  - Click **Add Method** to add it to the dropdown catalog immediately.
- **Usage Audit & Cleanup**:
  - The catalog table displays every available Control Method alongside its **Scope** (`Global`, `Project`, `PFMEA (Requires Control Plan)`, or `In Use (Legacy)`), **Rows Using** count in the current Control Plan, and **Created By** attribution.
  - Select any custom `Global` or `Project` method using the left-side checkbox and click **🗑️ Delete Selected Method(s)** to remove it from the catalog (existing saved Control Plan cells retain their text value until changed). Methods originating from PFMEA (`Requires Control Plan`) are managed directly via the PFMEA Control Catalog.
""",
    ),
    (
        "Numbering (Pr. Nº & Renumbering), Characteristic Types & Specifications",
        """
- **Pr. Nº (Process Number) & Visual Grouping**:
  - All Control Plan rows belonging to the same PAAG step share a single **Pr. Nº** (automatically initialized as `10.0`, `20.0`, `30.0`, etc.).
  - For clean document readability, repeated `Pr. Nº` values are visually blanked on secondary rows of the same PAAG step while `Station / Pitch` and `Op ID` remain visible. Editing `Pr. Nº` on any row of a step updates the group number for that entire step.
- **Renumber Pr. Nº by Op ID**:
  - If PAAG operations are reordered or inserted upstream so that `Pr. Nº` values are no longer in ascending order relative to live `Op ID` sequence, a notice appears above the table with a **Renumber Pr. Nº by Op ID** button. Click it to automatically re-sequence all operations as `1.0`, `2.0`, `3.0`, etc. in exact `Op ID` order.
- **Machine/Fixt. & Operation**:
  - Combines any physical equipment/tooling linked to the PAAG step with the PAAG Operation name (`Equipment — Operation`). You can also override the `Machine / fixture` text for the operation directly in the table.
- **Characteristic Type (`Product` vs. `Process`) & Auto-Numbering (`10.1`, `10.2`)**:
  - Choose `Product` or `Process` in **Characteristic type** (rows default to `Not assigned` until reviewed).
  - Selecting `Product` places the numbered characteristic (`10.1 Description`) into **Product / Part characteristic**; selecting `Process` places it into **Process characteristic**. Within each operation, suffixes (`1`, `2`, `3`...) are automatically numbered in display order.
- **CL (Classification)**:
  - Read-only column showing the highest-priority PFMEA Classification code (`S > R > E > P > C > H > K > F > V > L`) among classified PFMEA lines for that PAAG step.
- **Specification / Requirement & Specification Drift**:
  - Automatically populated from the linked Quality Requirement (`Description: Target (±Tolerance) Unit` or `Description: Pass/Fail`).
  - You can double-click **Specification / Requirement** to customize the text or append shop-floor notes. If the underlying Quality Requirement is later modified in the Requirements Repository, the **📊 Traceability Matrix** will flag **Specification Drift** (`🔧 Align Spec`) so you can inspect and re-align it when ready.
- **Measurement Technique, Sampling, Control Method & Reaction Plan**:
  - Complete **Measurement technique**, **Sample Size**, **Sample Frequency**, **Control method** (dropdown), and **Reaction Plan**, then click **Save & Refresh**.
""",
    ),
    (
        "Interactive Process Flow Map Sub-Tab",
        """
Switch from **Characteristics table** to the **Process flow map** sub-tab at the top of the Control Plan to view an interactive, visual manufacturing flow diagram of your Control Plan:

- **Fishbone & Pitch Architecture**:
  - Operations are organized into lanes by Fishbone assembly section (**Main Line**, **Sub-Assemblies**, **Monument**, and **Offline**) and grouped inside **Station / Pitch** cards showing the `Pr. Nº`, `Op ID`, and operation title.
  - **Sequence** arrows (`#2563eb`) connect consecutive steps along a line, while dashed **Feed** arrows (`#e65100`) show sub-assemblies feeding into downstream main-line operations.
- **Color-Coded Characteristic Ovals**:
  - Inside each operation box, clickable ovals represent individual Control Plan characteristics:
    - **Green Oval**: **Product** characteristic (`Product / Part characteristic`).
    - **Blue Oval**: **Process** characteristic (`Process characteristic`).
    - **Gray Oval**: **Unassigned** characteristic (`Characteristic type` is still `Not assigned`).
- **Interactive Filtering & Click-to-Inspect Modal**:
  - Filter the diagram by **Characteristic Type**, **Fishbone Group**, **Classification (CL)**, or **Control Method** to highlight matching ovals and dim non-matching steps.
  - **Click any characteristic oval** in the diagram to open the **Control Plan Characteristic Details** modal dialog, displaying its full specification, classification badge, measurement technique, sampling plan, control method, reaction plan, and upstream review status.
""",
    ),
    (
        "Supporting Expanders (PFMEA Evidence, Excluded Items & History)",
        """
At the bottom of the **Characteristics table** sub-tab, three expanders provide complete audit visibility:

- **View PFMEA control and action evidence**:
  - Read-only reference table showing every classified PFMEA line feeding the Control Plan, including its Prevention/Detection controls, Recommended Actions, Responsibility & Target Completion Date, Actions Taken, and Initial vs. Resulting RPN.
- **Review excluded and source-ineligible items**:
  - Explains why specific PFMEA lines or Quality requirements are not currently generating Control Plan rows (e.g., `Unclassified PFMEA entry` where `CL` is blank, or upstream source review flags).
- **History**:
  - Displays the timestamped audit log of Control Plan creations, edits, and deletions attributed to the **Current editor**.
""",
    ),
)

CONTROL_PLAN_HELP = CONTROL_PLAN_QUICK_START + "\n\n" + "\n\n".join(
    f"### {title}\n{content}" for title, content in CONTROL_PLAN_HELP_SECTIONS
)


EQUIPMENT_QUICK_START = """
Use the **Equipment** tab in the Quality Functional Review to manage inspection devices, gauges, fixtures, vision systems, barcode scanners, and torque tools used to verify quality in the active scenario.

1. **Maintain Shared or New Assets**: Add new equipment rows directly in **All equipment** (or type-specific sub-tabs), or use **Add existing equipment** to attach a shared project asset to Quality without duplicating it.
2. **Assign Scenario Placement & Photos**: Under **Equipment details**, upload a photo or paste a screenshot (`Ctrl+V`), assign the equipment to a **Station / Pitch**, and link it to one or more **Process Functions** at that Pitch.
3. **Configure Torque Tools & Audit Coverage**: Link saved `Torque` requirements to `Torque tool` assets, define tool hardware details in **Torque requirement specifications**, and check the **Equipment Needs vs. Placements Audit Matrix** at the bottom of the tab.
"""

EQUIPMENT_HELP_SECTIONS = (
    (
        "Equipment Tiers, Types & Shared Project Catalog",
        """
Equipment records in PAAG & Beyond use a shared project identity with scenario-specific placement:

- **Three Equipment Tiers**:
  - **Handheld Tools**: Portable tools and hand gauges (e.g., click wrenches, cordless DC nutrunners, calipers, handheld barcode scanners).
  - **Station/Pitch Equipment**: Fixed station hardware, test stands, vision cameras, or checking fixtures anchored to a Pitch (can optionally mark the Station / Pitch as blocked/dedicated).
  - **Capital Equipment**: Major machinery, automated cells, or monument test systems.
- **All Equipment & Type-Specific Sub-Tabs**:
  - **All equipment** displays every equipment asset attached to the Quality review. Each active **Equipment Type** (such as `Torque tool`, `Vision system`, `Fixture`, etc.) also gets its own dedicated sub-tab filtered to that type.
  - Shared catalog attributes (**Equipment name**, **Tier**, **Equipment Type**, **Description**, **Manufacturer**, **Model**, **Notes**, and **Primary image**) stay synchronized if the same piece of equipment is also attached to another Functional Review (such as Ergonomics, Safety, or Materials) or the top-level Equipment page.
- **Add Existing Equipment vs. Removing from Quality**:
  - Open **Add existing equipment** to attach an existing project asset to the Quality review.
  - Selecting a row in the Quality Equipment table and clicking **Delete row(s)** removes its association with the **Quality** review only; the shared asset remains in the project catalog (permanent project-wide deletion is handled on the top-level **Equipment** page).
""",
    ),
    (
        "Equipment Details, Clipboard Image Paste & Scenario Placement",
        """
Below the equipment table, open **Equipment details** and choose an asset in **Equipment to manage** to configure its visual documentation and floor placement for the active planning scenario:

- **Primary Image (Upload, Camera, or Clipboard Paste)**:
  - Upload a `.png`, `.jpg`, or `.webp` image file, capture a live photo using **Take a picture**, or use **📋 Or paste screenshot from clipboard (`Win+Shift+S` then `Ctrl+V`)** to paste a snipped image directly from your clipboard, then click **Save pasted image**.
- **Scenario Placement (`Station / Pitch` & `Linked Process Functions`)**:
  - Choose a **Station / Pitch** (or leave as `Unassigned` if not yet placed on the line).
  - In **Linked Process Functions**, select one or more PAAG operations located at that Station / Pitch.
  - **🚧 Tag Station / Pitch as Blocked (Dedicated to this equipment)**: Available when `Tier` is set to `Station/Pitch Equipment`. Checking this box flags the Station / Pitch as dedicated to this equipment in line planning views.
  - Click **Save placement** to persist the Pitch and step links for the active scenario.
""",
    ),
    (
        "Reconciling Disconnected or Moved PAAG Steps",
        """
When Industrial Engineering rebalances the line or deletes a PAAG operation in Process at a Glance, the Equipment tab protects your placed hardware and guides you through reconciliation:

- **Disconnected process step links (Deleted PAAG Steps)**:
  - If a linked PAAG step is deleted upstream, the physical equipment **remains anchored in its assigned Station / Pitch** so your floor layout is not lost.
  - Open the **Disconnected process step links** expander to see the deleted step's historical snapshot (`Op ID`, `Pitch`, `Operation`, `Description`). You can either select a **Replacement step in Pitch** and click **Relink to step**, or click **Clear obsolete links** to remove the dead step reference while keeping the equipment in its Pitch.
- **Equipment placement review (Moved PAAG Steps)**:
  - If a linked PAAG step is moved to a different Station / Pitch during line balancing, the **Equipment placement review** expander appears with two clear choices depending on how the steps moved:
    1. **Move equipment to current Pitch**: Available when *all* linked PAAG steps for that equipment moved together to the same single destination Pitch. Updates the equipment's placement to follow the operation to the new Pitch.
    2. **Unlink moved steps (keep equipment anchored)**: Keeps the physical equipment at its original Station / Pitch and detaches the steps that moved away (so those moved steps will appropriately flag as needing equipment at their new Pitch).
""",
    ),
    (
        "Torque Tool Linking & Torque Requirement Specifications",
        """
The Quality Equipment tab provides specialized management for **Torque** requirements and **Torque tools**:

- **Torque requirement specifications Expander**:
  - Defines the one-to-one hardware specification required by each saved `Torque` requirement from the Requirements Repository (**Description**, **Target value**, **Tolerances**, **Unit**):
    - **Tool type**: Choose `Air tool`, `Electric clutch tool`, `Pulse tool`, `DC tool`, or `Click wrench`.
    - **Tool orientation**: Choose `Right angle`, `In-line`, or `Pistol`.
    - **Screw bit type**: Select an existing bit type or use **New screw bit type** + **Add screw bit type** to add a reusable bit specification (e.g., `T25 Torx`, `8mm Hex Socket`, `#2 Phillips`) to the project catalog.
  - *Note*: Defining a Torque requirement specification documents what kind of tool is needed; you still place and link physical **Torque tool** assets in the Equipment table.
- **Linking Torque Requirements to an Installed Torque Tool**:
  - When you select an asset whose **Equipment Type** is `Torque tool` inside **Equipment details** (or on the **Torque tool** sub-tab), a **Linked Torque requirements** section appears.
  - Select one or more saved `Torque` requirements in **Torque requirements for selected tool** and click **Save Torque links**.
  - The read-only **Published Torque specifications** table displays every linked PAAG step (`Op ID`), its published `Target value`, `Tolerances`, `Unit`, `Tool type`, `Tool orientation`, and `Screw bit type`, and warns you if a Torque requirement is linked to the tool but has not yet been published to the PAAG step(s) where the tool is used.
""",
    ),
    (
        "Equipment Needs vs. Placements Audit Matrix",
        """
At the bottom of the Quality Equipment tab, open **Equipment Needs vs. Placements Audit Matrix** to verify that every tooling requirement called out in your engineering documents is backed by placed physical hardware:

- **How Needs Are Detected**:
  - **Drawing Requirements (`Requirements Repository`)**: Automatically detects `Torque` requirements assigned to PAAG steps and checks for a placed `Torque tool` at that step's Pitch.
  - **PFMEA Process Controls (`PFMEA`)**: Scans active PFMEA Prevention and Detection controls on each step for hardware keywords—including **Vision Systems** (`vision`, `camera`), **Barcode / Scanners** (`scanner`, `barcode`, `rfid`), **Fixtures / Poka-Yoke** (`fixture`, `jig`, `poka`), **Gauges / Measurement Tools** (`gauge`, `gage`, `caliper`, `micrometer`, `leak`), and **ESD Protection** (`esd`, `ground`)—and checks whether matching equipment is placed at that step's Pitch.
- **Audit Filters & Summary KPIs**:
  - View counts of **Total Identified Equipment Needs**, **Satisfied (Equipment Placed)**, and **Gaps (Missing Placement)**.
  - Filter the audit table by **Coverage Status** (`All`, `Missing Equipment Only`, `Satisfied Only`) or **Source Stage** (`All`, `Drawing Requirement Only`, `PFMEA Control Only`) to quickly close any hardware gaps before launch.
""",
    ),
)

EQUIPMENT_HELP = EQUIPMENT_QUICK_START + "\n\n" + "\n\n".join(
    f"### {title}\n{content}" for title, content in EQUIPMENT_HELP_SECTIONS
)
