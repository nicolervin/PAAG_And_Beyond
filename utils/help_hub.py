"""Universal Help, Global Search, Workflow Guide, and Bug/Feature Tracker Hub."""

from __future__ import annotations

import hashlib
import html
from pathlib import Path
import re
from typing import Any

import pandas as pd
import streamlit as st

from utils.clipboard_image import clipboard_image, decode_clipboard_image
from utils.db_core import ROOT, UPLOAD_DIR, format_eastern_timestamp
from utils.gcp_storage import resolve_upload_path
from utils.quality_help import (
    CONTROL_PLAN_HELP,
    EQUIPMENT_HELP,
    PFMEA_HELP,
    REQUIREMENTS_REPOSITORY_HELP,
)

QUALITY_TAB_HELP_GUIDES: dict[str, dict[str, str]] = {
    "Requirements repository": {
        "title": "Requirements repository",
        "body": REQUIREMENTS_REPOSITORY_HELP.strip(),
    },
    "Equipment": {
        "title": "Quality Equipment & Torque Specs",
        "body": EQUIPMENT_HELP.strip(),
    },
    "PFMEA": {
        "title": "PFMEA & Reusable Patterns",
        "body": PFMEA_HELP.strip(),
    },
    "Control Plan": {
        "title": "Manufacturing Control Plan (MCP)",
        "body": CONTROL_PLAN_HELP.strip(),
    },
}
from utils.store import (
    FEEDBACK_SEVERITIES,
    FEEDBACK_STATUSES,
    FEEDBACK_TYPES,
    audit_history,
    bulk_update_app_feedback_status,
    create_app_feedback,
    critical_thread_status_counts,
    delete_app_feedback,
    global_project_search,
    list_app_feedback,
    open_app_feedback_count,
    save_bulk_app_feedback,
    save_feedback_screenshot,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    request_table_editor_reset,
)
from utils.table_ui import (
    has_active_unsaved_changes,
    request_unsaved_page_navigation,
    selectable_dataframe,
)
from utils.yamazumi_naming import parse_yamazumi_pitch_address


PAGE_MANUALS: dict[str, dict[str, Any]] = {
    "overview": {
        "title": "Overview",
        "icon": ":material/dashboard:",
        "scope": "All scenarios + Active scenario sections",
        "summary": (
            "Project command center for creating projects, managing project-wide metadata "
            "(2-character Line Code, takt time, building location), and managing planning scenarios."
        ),
        "workflows": [
            "**Create or edit a project**: Set the project name, product line, 2-character Yamazumi line code (e.g. `M1`), default takt time, and owner.",
            "**Manage planning scenarios**: Create working scenarios, clone an existing scenario (including Yamazumi, Process at a Glance, Quality assignments, PFMEA, Control Plan, Equipment placements, Ergonomics, and Safety), or compare scenario readiness.",
            "**Delete with safety net**: Deleted projects and scenarios are archived in the 30-day Recycle Bin and can be restored with all child data.",
        ],
        "connections": (
            "Root of all project-wide tables (`All scenarios`) and scenario-specific planning (`Active scenario`)."
        ),
        "tips": [
            "Set your **2-character Line Code** (such as `M1` or `L1`) early—Yamazumi pitch addresses and Process at a Glance Op IDs use it automatically.",
            "Enter your name in **Current editor** in the left sidebar so every save, import, and deletion is attributed in table history.",
        ],
    },
    "concerns": {
        "title": "Questions and concerns",
        "icon": ":material/forum:",
        "scope": "All scenarios",
        "summary": (
            "Project-wide issue, question, and risk log for cross-functional collaborators, "
            "linked to parts, stations, and BOM reconciliation escalations."
        ),
        "workflows": [
            "**Log a question or concern**: Add a row with Category (`Question`, `Concern`, `Risk`, `Action`), Subject, Detail, Owner, Priority, and optional Related Part or Station.",
            "**Review BOM escalations**: Changed or missing PITS BOM occurrences escalated from the BOM page appear here automatically.",
            "**Update & close items**: Filter by status or priority, edit inline, and click **Save & Refresh**.",
        ],
        "connections": (
            "Connects to **BOM** (escalated source changes), **Parts Catalog**, and **Process at a Glance** stations."
        ),
        "tips": [
            "While you have unsaved edits in the table, filter/sort controls lock so your edits are never lost. Click **Save & Refresh** or **Undo** to unlock them.",
        ],
    },
    "exchange": {
        "title": "Import/Export Projects",
        "icon": ":material/sync_alt:",
        "scope": "All projects",
        "summary": (
            "Export complete portable project packages (`.zip` with database records and media uploads) "
            "or import a project package from another collaborator."
        ),
        "workflows": [
            "**Export a project**: Choose the project, generate the portable archive, and download the `.zip` package.",
            "**Import a project**: Upload a `.zip` package, preview the manifest and conflict checks, and import as a new or updated project.",
            "**Export Excel workbooks**: Generate multi-sheet Excel snapshots for external spreadsheet or Lucid consumers.",
        ],
        "connections": (
            "Transfers complete project graphs across local prototype instances while preserving UUID relationships and media files."
        ),
        "tips": [
            "Always preview import conflict summaries before confirming an import.",
        ],
    },
    "pits_exchange": {
        "title": "Import PITs",
        "icon": ":material/sync_alt:",
        "scope": "All scenarios",
        "summary": (
            "Step 1 of the Critical Thread: Import Product Architecture / PITS tracker workbooks "
            "as source evidence without silently overwriting reviewed planning decisions."
        ),
        "workflows": [
            "**Upload PITS workbook**: Select your PITS `.xlsx` workbook to preview part tracker records and Level 1–11 BOM structure.",
            "**Review revision diffs**: Inspect new, changed, and missing PITS tracker records before applying the import.",
            "**Seed Parts & BOM occurrences**: Importing updates `pits_records` and stages `pits_bom_occurrences` for review on the **BOM** page.",
        ],
        "connections": (
            "Feeds **BOM** (`pits_bom_occurrences`) and **Parts Catalog** (`parts`)."
        ),
        "tips": [
            "PITS is treated as **source evidence**, never automatic approval. Collaborator-reviewed Fishbone placements and MBOM decisions are protected.",
        ],
    },
    "models": {
        "title": "Complexity Trees",
        "icon": ":material/view_in_ar:",
        "scope": "All scenarios",
        "summary": (
            "Step 2 of the Critical Thread: Define product models, EAU volumes, milestone dates, "
            "complexity features, and model-to-feature matrix mappings."
        ),
        "workflows": [
            "**Define Models**: Add or import product models (`model_number`, `display_name`, `platform_size`, `eau`, milestone dates).",
            "**Define Complexity Features**: Create differentiating features (e.g. `Control Type`, `Color`, `Fuel Type`) and their allowed values.",
            "**Map Model Feature Values**: Assign each model's feature values in the matrix so downstream part and assembly rules can resolve model applicability.",
        ],
        "connections": (
            "Used by **Parts Catalog** and **Fishbone Assembly Grid** to compute which models use each part or manufacturing assembly."
        ),
        "tips": [
            "Multi-table operations on Complexity Trees support **Undo** to restore the previous saved snapshot if needed.",
        ],
    },
    "bom_tree": {
        "title": "BOM",
        "icon": ":material/account_tree:",
        "scope": "All scenarios",
        "summary": (
            "Step 3 of the Critical Thread: Inspect interactive CAD-style Model Tree BOMs by official model, "
            "author Level 1–11 BOM structures from scratch, and reconcile parts against the Parts Catalog and Fishbone."
        ),
        "workflows": [
            "**🌲 View BOM & Reconcile Gaps**: Select `All models (Master BOM)` or a specific official model, filter by `Missing from Fishbone` or `Missing from Parts Catalog`, inspect part properties in the right-hand panel, and add/assign parts to the Parts Catalog or Fishbone sections.",
            "**✏️ Build / Author BOM from Scratch**: Use the side-by-side **BOM Spreadsheet Editor** (Level 1–11, Part # / Group #, Description, Qty) and **Live Visual Tree** (`🌳 Live Hierarchy` and `🌲 CAD Browser Tree`) to build or edit a model's BOM.",
            "**Import, Copy, or Predict BOMs**: Use **📥 Download Template**, **📤 Import File** (or **📋 Paste from Excel**), **👥 Copy from Model**, or **✨ Predict from Features** (using Complexity Trees rules) to populate a model BOM rapidly.",
            "**Group Number Conflict Resolution**: When saving a shared group/drawing number whose child parts or quantities differ from other models, PAAG alerts you and lets you sync the updated group structure across models or confirm a model variation.",
        ],
        "connections": (
            "Bridges **Import PITs** & **Complexity Trees** -> **BOM** -> **Parts Catalog** -> **Fishbone** (`fishbone_part_assignments`)."
        ),
        "tips": [
            "Use **Undo last edit** and **Redo last edit** in the BOM Spreadsheet Editor to step backward or forward through individual cell changes before clicking **Save BOM Structure**.",
            "Keep **Auto-add new parts to Parts Catalog** checked so any new part numbers typed in the BOM Editor are automatically registered in the Parts Catalog on save.",
        ],
    },
    "parts": {
        "title": "Parts Catalog",
        "icon": ":material/category:",
        "scope": "All scenarios + Scenario active toggle",
        "summary": (
            "Step 4 of the Critical Thread: Maintain the project-wide part master, engineering/ME ownership, "
            "annotated reference photos, complexity rules, and scenario-specific active status."
        ),
        "workflows": [
            "**Edit catalog attributes**: Update descriptions, factory nicknames, make/buy, part code, weight, and engineering owners, then click **Save & Refresh**.",
            "**Freeze / Pin columns**: Use the **Freeze left columns** selector above the Parts Catalog table to pin `Part number`, `Factory nickname`, or any other columns while scrolling horizontally.",
            "**Attach & annotate photos**: Upload or paste (`Ctrl+V`) part photos and use **Annotate / Add Shapes** to draw editable vector arrows, boxes, and callouts.",
            "**Toggle Active in scenario**: Mark parts active or inactive for the active planning scenario without deleting them from other scenarios.",
        ],
        "connections": (
            "Supplies parts to **Fishbone** placements, **Yamazumi** material groups, and **Process at a Glance** part handling/consumption."
        ),
        "tips": [
            "You can paste multiple rows directly from Excel into the Parts Catalog editor!",
        ],
    },
    "fishbone": {
        "title": "Fishbone",
        "icon": ":material/device_hub:",
        "scope": "All scenarios",
        "summary": (
            "Step 5 of the Critical Thread: Design the assembly section flow (Main Line, Subassemblies, "
            "Parallel branches), place parts into sections, and configure the Manufacturing Assembly Grid."
        ),
        "workflows": [
            "**Build Section Flow**: Create assembly sections and connect them (`series`, `parallel`, `subassembly`) on the visual Fishbone diagram.",
            "**Assign Parts to Sections**: Place catalog parts into sections with step numbers, quantities, and use descriptions.",
            "**Manufacturing Assemblies & Grid**: Group parts into subassemblies/kits (`ASM`) and map them across product models.",
        ],
        "connections": (
            "Feeds **Yamazumi** areas (1-to-1 with Fishbone sections) and constrains which parts can be assigned in **Yamazumi** and **Process at a Glance**."
        ),
        "tips": [
            "Each active Fishbone section automatically creates a corresponding Yamazumi area and can be selected directly on the **Yamazumi** and **Process at a Glance** pages.",
        ],
    },
    "yamazumi": {
        "title": "Yamazumi",
        "icon": ":material/view_column:",
        "scope": "Active scenario",
        "summary": (
            "Step 6 of the Critical Thread: Scenario-specific line balancing across areas, pitches "
            "(Pitch, Waterspider, Subassembly, Kitter, Repacker), and operator work elements against takt time."
        ),
        "workflows": [
            "**Create Areas & Pitches or Import Files**: Link Yamazumi areas to Fishbone sections, create pitches with guided addresses (e.g. `M1S1b.01`), or upload one or more Excel/PDF Yamazumi files, assign specific pitches or pitch ranges (with `Pitch Type` and assigned features shown in the `Feature` column) to one or more Yamazumi areas (pitches already placed are removed from the preview while unplaced pitches stay loaded until all pitches are placed or the **Import Yamazumi File** expander is minimized), and map detected model variants to `All models` or official project features in the import preview.",
            "**Interactive Yamazumi Tab**: Select one or more Yamazumi areas in the top **Yamazumi Area** selector, review top summary metrics (including **Actual Operators**, the count of pitches containing work elements), drag and drop work elements between paired North/South pitches (odd and even workstation pairs aligned directly across the assembly flow line) or `Unassigned` on the interactive balancing board to balance operator cycle time against the red Takt Time line, and add or edit work elements per model-variant stack so edits in one model variant only update that specific model variant's work element (assigning or changing a work element's model variant automatically adds any missing model variant to its pitch).",
            "**Yamazumi Tables Tab**: Review and edit each Yamazumi area's **Area Takt Time** (initialized to the current rev takt time when the area is set up) and **Conveyor Type** (`1-sided` or `2-sided`) in the **Yamazumi Area** table, view, filter, and bulk-edit **Pitch Addresses** (including `Pitch Type` and `Feeds Into Pitch`, which stay synchronized with **Edit Pitch** on the Interactive Yamazumi board) and **Yamazumi Work Elements** across all Yamazumi areas in the scenario, select pitches in the **Pitch Addresses** table and click **Delete Pitches**, **Copy Pitches** (to copy them to another planning scenario), or **Move Pitches** (to move them to another Yamazumi area), and select work elements in the **Yamazumi Work Elements** table and click **Delete Work Element** or **Copy Work Element** (to duplicate each selected work element immediately beneath itself).",
            "**Assign Material Groups**: Link Fishbone part placements to Yamazumi elements (`Use all` or `Choose one`).",
            "**Push to Process at a Glance**: Sync balanced pitch stacks into **Process at a Glance** steps.",
        ],
        "connections": (
            "Links **Fishbone** sections -> **Yamazumi** pitches & elements -> **Process at a Glance** (`work_elements`)."
        ),
        "tips": [
            "Pitches marked `Open` or `Blocked` reject work-element drops on the Yamazumi board to prevent accidental assignment.",
            "Feeder pitches (`Subassembly`, `Kitter`) must specify which main-line pitch they feed into.",
        ],
    },
    "process": {
        "title": "Process at a Glance",
        "icon": ":material/account_tree:",
        "scope": "Active scenario",
        "summary": (
            "Step 7 of the Critical Thread: Authoritative scenario Process plan with deterministic Op IDs, "
            "part Handle/Consume assignments, pitch visual aids, and functional review summaries."
        ),
        "workflows": [
            "**Manage Process steps**: Edit sequence, pitch (`station`), description, cycle time, resource type (`Human`, `Cobots`, `Automation`), and workstation heights.",
            "**Deterministic Op IDs**: Operation IDs (e.g. `M1S1b.01-ML1-004.4`) are formatted from Pitch Address + Flow Prefix + Sequence.",
            "**Part Pairing (`Handle` vs `Consume`)**: Pair Fishbone parts with Process steps and mark whether the step first **Consumes** the part or **Handles** an already-consumed part.",
            "**Pitch Visual Aids**: Upload or paste images, videos, CAD renders, or links for each pitch and tag relevant Process steps.",
        ],
        "connections": (
            "Drives the **Pin Map** and anchors all **Functional Reviews** (Equipment, Ergonomics, Quality, Materials, Safety)."
        ),
        "tips": [
            "Open **Process at a Glance** and **Yamazumi** (or **Quality**) together in **Split Screen** using the split icon in the left sidebar!",
        ],
    },
    "pin_map": {
        "title": "Pin Map",
        "icon": ":material/map:",
        "scope": "Active scenario (derived view) + Layout Canvas",
        "summary": (
            "Step 8 of the Critical Thread: Visual station-by-station Pin Map derived from Process at a Glance, "
            "Yamazumi pitches, Quality/Torque, Ergonomics, Safety, and interactive 2D Plant Layout."
        ),
        "workflows": [
            "**Derived Pin Map Table**: Inspect every pitch and Process step with its aggregated Quality, Torque, Ergonomics, Safety, and Equipment indicators.",
            "**Interactive Layout Canvas**: Arrange station footprints, conveyor zones, and custom stencils on a 2D floorplan revision.",
        ],
        "connections": (
            "Synthesizes **Yamazumi**, **Process at a Glance**, and all **Functional Reviews**."
        ),
        "tips": [
            "The Pin Map table is derived from live scenario records—update the underlying Process or Functional Review pages to change Pin Map indicators.",
        ],
    },
    "functional_equipment": {
        "title": "Equipment",
        "icon": ":material/precision_manufacturing:",
        "scope": "All scenarios (Catalog) + Active scenario (Placements & Links)",
        "summary": (
            "Shared Equipment Catalog (Handheld Tools, Station/Pitch Equipment, Capital Equipment), "
            "scenario pitch placements, Process step links, and Conveyor Zone calculators."
        ),
        "workflows": [
            "**Equipment Catalog**: Define shared equipment types and assets (`All scenarios`) with manufacturer, model, and reference photos.",
            "**Scenario Placements & Links**: Place equipment assets at Yamazumi pitches in the active scenario and link them to Process steps and Torque requirements.",
            "**Conveyor Zones**: Configure conveyor zones across pitch ranges to calculate total line lengths and monument spacing.",
        ],
        "connections": (
            "Links to **Yamazumi** pitches, **Process at a Glance** steps, and **Quality** torque requirements."
        ),
        "tips": [
            "Deleting a Process step preserves its Equipment link as an unlinked snapshot so you can relink it without losing engineering work.",
        ],
    },
    "functional_ergonomics": {
        "title": "Ergonomics",
        "icon": ":material/accessibility_new:",
        "scope": "Active scenario",
        "summary": (
            "Scenario-specific Ergonomics reviews linked to Process steps and part options, "
            "with controlled risk classifications (`Green`, `Favorable Green`, `Favorable Red`, `Red`) and visual media."
        ),
        "workflows": [
            "**Create & update Ergonomics reviews**: Link reviews to Process steps, select ergonomic hazards, assign a reviewer and due date, and set the risk classification.",
            "**Attach visual media**: Upload or paste posture photos and videos with annotated callouts.",
        ],
        "connections": (
            "Links to **Process at a Glance** (`work_elements`) and feeds **Pin Map** ergonomic risk indicators."
        ),
        "tips": [
            "If a linked Process step is deleted, the Ergonomics review is preserved with its legacy description so assessment history is never lost.",
        ],
    },
    "functional_quality": {
        "title": "Quality",
        "icon": ":material/verified:",
        "scope": "All scenarios (Repository & Catalogs) + Active scenario (Assignments, PFMEA, Control Plan)",
        "summary": (
            "Comprehensive Quality Engineering workspace covering the shared Quality Requirements repository, "
            "Torque specifications, scenario Process step assignments, PFMEA, and Control Plan."
        ),
        "workflows": [
            "**Quality Overview**: Monitor scenario readiness, out-of-sync requirement assignments, and unlinked snapshots.",
            "**Requirements & Torque**: Author project-wide quality requirements (`QR-001`) and torque tool details, then assign/push them to scenario Process steps.",
            "**PFMEA**: Build Failure Mode and Effects Analysis rows linked to Process steps and Quality requirements, with automatic Action Priority (`H`/`M`/`L`) calculation and Reusable Failure Patterns.",
            "**Control Plan**: Generate and maintain Control Plan rows synchronized with PFMEA causes/controls and Quality requirements.",
        ],
        "connections": (
            "Connects **Process at a Glance** steps -> **Quality Requirements & Torque** -> **PFMEA** -> **Control Plan** -> **Pin Map**."
        ),
        "tips": [
            "Scenario assignments keep a published snapshot of each Quality requirement. When you update a shared requirement, use **Push updates** to sync scenario assignments deliberately.",
        ],
    },
    "functional_materials": {
        "title": "Materials",
        "icon": ":material/inventory_2:",
        "scope": "Active scenario",
        "summary": (
            "Materials planning review workspace for line-side presentation, replenishment, "
            "and kitting/waterspider alignment."
        ),
        "workflows": [
            "**Review material presentation**: Inspect how catalog parts and manufacturing assemblies are grouped and delivered to pitches in the active scenario.",
        ],
        "connections": (
            "Connects **Parts Catalog**, **Fishbone** manufacturing assemblies, and **Yamazumi / Process** material groups."
        ),
        "tips": [
            "Use **Split Screen** to view **Materials** alongside **Parts Catalog** or **Yamazumi**.",
        ],
    },
    "functional_safety": {
        "title": "Safety",
        "icon": ":material/health_and_safety:",
        "scope": "Active scenario",
        "summary": (
            "Scenario-specific Safety requirements and Personal Protective Equipment (PPE) "
            "linked to Process at a Glance steps."
        ),
        "workflows": [
            "**Add Safety requirements**: Select a Process step, specify the safety requirement description and required PPE, and click **Save & Refresh**.",
            "**Edit or deactivate requirements**: Update inline in the Safety table and save.",
        ],
        "connections": (
            "Links to **Process at a Glance** (`work_elements`) and feeds **Pin Map** safety indicators."
        ),
        "tips": [
            "Every persisted change is recorded in the **History** expander at the bottom of the page.",
        ],
    },
    "recycle_bin": {
        "title": "Recycle Bin",
        "icon": ":material/delete:",
        "scope": "All projects / Active project",
        "summary": (
            "App-wide 30-day safety net for deleted projects, scenarios, parts, Process steps, "
            "Fishbone sections, functional reviews, and feedback items."
        ),
        "workflows": [
            "**Filter by scope**: Toggle between `Active project` and `All projects` (which displays both `Project` and `Scenario` columns).",
            "**Restore selected**: Select one or more deleted items and click **Restore selected** to atomically restore the record, its cascaded children, and its preserved media files.",
            "**Delete permanently**: Select specific items and confirm permanent deletion if they should be purged before their 30-day expiration date.",
        ],
        "connections": (
            "Captures deletions across all project-wide, scenario-specific, and app-feedback tables."
        ),
        "tips": [
            "Items automatically expire 30 days after deletion. If you deleted a child record and later deleted its parent project, select both to restore them together!",
        ],
    },
}

# Map unlisted URL aliases to their canonical manual keys
_MANUAL_KEY_ALIASES: dict[str, str] = {
    "__default__": "overview",
    "": "overview",
    "Equipment": "functional_equipment",
    "Ergonomics": "functional_ergonomics",
    "Quality": "functional_quality",
    "Materials": "functional_materials",
    "Safety": "functional_safety",
}

GLOSSARY_TERMS: list[dict[str, str]] = [
    {
        "term": "Critical Thread",
        "category": "Architecture",
        "definition": (
            "The authoritative end-to-end engineering data spine in PAAG: "
            "Product Architecture / PITS evidence -> Complexity Trees -> BOM -> Parts Catalog -> "
            "Fishbone -> scenario-specific Yamazumi -> scenario-specific Process at a Glance -> "
            "derived Pin Map & Functional Reviews."
        ),
    },
    {
        "term": "Project-Wide vs. Scenario Scope",
        "category": "Scope & Governance",
        "definition": (
            "Project-wide data (`All scenarios` badge) is shared across the entire project—such as "
            "Parts Catalog, Complexity Trees, BOM, Fishbone structure, shared Quality Requirements, "
            "and Equipment Assets. Scenario-specific data (`Active scenario` badge) belongs to a single "
            "planning scenario—such as Yamazumi areas/pitches/elements, Process at a Glance steps, "
            "PFMEA, Control Plan, Ergonomics, and Safety."
        ),
    },
    {
        "term": "PITS (Product Issue Tracking System)",
        "category": "Product Structure",
        "definition": (
            "Upstream Product Architecture workbook containing part tracker rows and Level 1–11 EBOM "
            "hierarchy. Imported as source evidence that enters reconciliation rather than overwriting "
            "collaborator-reviewed planning data."
        ),
    },
    {
        "term": "EBOM vs. MBOM",
        "category": "Product Structure",
        "definition": (
            "Engineering Bill of Materials (EBOM) reflects how product engineering groups parts in CAD/Windchill; "
            "Manufacturing Bill of Materials (MBOM) reflects how the factory actually builds subassemblies and "
            "consumes parts across Fishbone sections and Process steps."
        ),
    },
    {
        "term": "Fishbone Section",
        "category": "Product Structure",
        "definition": (
            "A logical zone of assembly flow (Main Line, Subassembly, or Parallel branch) on the Fishbone diagram "
            "where parts and manufacturing assemblies are placed."
        ),
    },
    {
        "term": "Manufacturing Assembly (ASM)",
        "category": "Product Structure",
        "definition": (
            "A factory-defined subassembly or kit built in one Fishbone section (`built_section_id`) and "
            "installed in a downstream section (`installed_section_id`)."
        ),
    },
    {
        "term": "Takt Time",
        "category": "Process Planning",
        "definition": (
            "Available production time divided by customer demand per shift. Serves as the target pace "
            "ceiling for balancing operator work elements across Yamazumi pitches."
        ),
    },
    {
        "term": "Yamazumi Pitch & Pitch Address",
        "category": "Process Planning",
        "definition": (
            "A physical or logical operator workstation/zone in a Yamazumi area. Uses a structured 3-part Pitch Address "
            "such as `01-ML1-004` (`01` = 2-char Line/Subline code, `ML1` = 3-char Section/Flow code, `004` = Pitch sequence number)."
        ),
    },
    {
        "term": "Pitch Types (Pitch, Waterspider, Subassembly, Kitter, Repacker)",
        "category": "Process Planning",
        "definition": (
            "`Pitch` is a main-line assembly pitch; `Subassembly` and `Kitter` are feeder pitches that must "
            "specify which downstream pitch they feed into (`feeds_into_pitch_id`); `Waterspider` and `Repacker` "
            "represent material presentation and repack roles."
        ),
    },
    {
        "term": "Operation ID (Op ID)",
        "category": "Process Planning",
        "definition": (
            "Deterministic Process step identifier in Process at a Glance (for example, `M1S1b.01-ML1-004.4`), "
            "combining the Fishbone Hierarchy Prefix (`M1S1b`), the Yamazumi Pitch Address (`01-ML1-004`), "
            "and the element's stack position inside that pitch (`.4`)."
        ),
    },
    {
        "term": "Handle vs. Consume (Part Pairing)",
        "category": "Process Planning",
        "definition": (
            "In Process at a Glance, `Consume` marks the step where a Fishbone part placement is first installed/consumed "
            "into the build; `Handle` marks a step that touches, positions, or inspects a part that was already consumed."
        ),
    },
    {
        "term": "PFMEA Action Priority (AP)",
        "category": "Quality",
        "definition": (
            "AIAG-VDA risk prioritization (`High`, `Medium`, `Low`) computed automatically from Severity (S), "
            "Occurrence (O), and Detection (D) ratings on each PFMEA risk row."
        ),
    },
    {
        "term": "Recycle Bin (30-Day Retention)",
        "category": "Scope & Governance",
        "definition": (
            "App-wide safety net that snapshots deleted records, cascaded child records, and uploaded media "
            "for 30 days so accidental deletions can be restored atomically."
        ),
    },
]

TROUBLESHOOTING_FAQS: list[dict[str, str]] = [
    {
        "question": "Why is the 'Save & Refresh' button disabled on a table?",
        "answer": (
            "**Save & Refresh** is only enabled when the table has pending unsaved edits (added, modified, or "
            "checked rows). Note: if you type inside a cell, press **Enter** or **Tab** (or click outside the cell) "
            "so Streamlit commits the cell value to the editor state and enables **Save & Refresh**."
        ),
    },
    {
        "question": "Why are the search, sort, and filter controls locked above a table?",
        "answer": (
            "When a table has unsaved edits, changing sort order or filter criteria would cause the browser "
            "editor to lose your in-progress rows. PAAG automatically locks sort/filter/column controls while "
            "edits are pending—click **Save & Refresh** to commit your changes or **Undo** to discard them and unlock filtering."
        ),
    },
    {
        "question": "How do I view two pages at once (Split Screen or Pop-out window)?",
        "answer": (
            "In the left sidebar under **Application**, click the **Split screen** icon on the right side of any page row "
            "to open that page in a second pane! By default, Split Screen stacks **Top & Bottom** at 100% monitor width "
            "so wide tables never get squished, and you can toggle to **Side-by-side**, **Swap Panes**, or click **Pop out** "
            "to open the second page in a separate browser window."
        ),
    },
    {
        "question": "How do I paste multiple rows from Excel or paste screenshots from my clipboard?",
        "answer": (
            "- **Excel paste**: Copy cells in Excel (`Ctrl+C`), click a target cell in any editable PAAG table (or the empty `+` add-row at the bottom), and press `Ctrl+V`.\n"
            "- **Screenshot paste**: Take a snip with `Win+Shift+S` (or `Cmd+Ctrl+Shift+4` on Mac), then click **📋 Paste screenshot** or click the dashed paste box and press `Ctrl+V`."
        ),
    },
    {
        "question": "How do I freeze/pin columns on wide tables like the Parts Catalog?",
        "answer": (
            "On the **Parts Catalog**, use the **Freeze left columns** multiselect right next to **Visible columns** "
            "to choose which columns stay pinned to the left edge while scrolling horizontally (`Part number` is pinned by default)."
        ),
    },
    {
        "question": "How do I recover something that was accidentally deleted?",
        "answer": (
            "Click **Recycle bin** at the bottom-left of the sidebar. Every deleted project, scenario, part, "
            "Process step, Fishbone section, and Functional Review is kept for **30 days** along with its child records "
            "and uploaded images. Check the item and click **Restore selected**."
        ),
    },
]


def resolve_manual_key(active_page_key: str | None) -> str:
    raw = str(active_page_key or "").strip()
    mapped = _MANUAL_KEY_ALIASES.get(raw, raw)
    if mapped in PAGE_MANUALS:
        return mapped
    return "overview"


def navigate_to_page_from_hub(target_url_path: str, page_title: str = "") -> None:
    """Navigate to a target page from inside the Help Hub dialog, respecting unsaved edits."""
    clean_target = str(target_url_path or "").strip()
    if not clean_target:
        return
    if clean_target == "__feedback_tab__":
        st.session_state["help_hub_requested_tab"] = "feedback"
        st.rerun()
        return
    if clean_target == "exchange":
        clean_target = "__default__"

    current_url_path = str(st.session_state.get("current_url_path") or "__default__")
    if clean_target == current_url_path:
        st.toast(f"You are already on {page_title or clean_target}.", icon=":material/info:")
        return

    if has_active_unsaved_changes():
        request_unsaved_page_navigation(
            clean_target,
            label=page_title or clean_target,
        )
        st.rerun()
        return

    st.session_state["split_workspace_pending_navigation"] = clean_target
    st.rerun()


def _explain_fishbone_prefix(prefix: str) -> str:
    clean = str(prefix or "").strip()
    m_sub = re.match(
        r"^(?P<main>M\d+(?:\+M\d+\.?)?)S(?P<lineage>\d+)(?P<depth>[a-z]+)(?P<branch>\d*)$",
        clean,
        re.IGNORECASE,
    )
    if m_sub:
        main_tag = m_sub.group("main").rstrip(".")
        lineage = m_sub.group("lineage")
        depth_letters = m_sub.group("depth").lower()
        branch = m_sub.group("branch")
        depth_num = ord(depth_letters[0]) - ord("a") + 1
        branch_note = f", sibling branch #{branch}" if branch else ""
        return (
            f"Fishbone Subassembly feeding {main_tag} · Lineage S{lineage} · "
            f"Subassembly nesting depth {depth_num} ('{depth_letters}'{branch_note})."
        )
    m_main = re.match(r"^M(?P<num>\d+)$", clean, re.IGNORECASE)
    if m_main:
        return f"Main Line / Root Assembly section #{m_main.group('num')} on the Fishbone."
    m_so = re.match(r"^SO(?P<num>\d+)$", clean, re.IGNORECASE)
    if m_so:
        return f"Support Operations section #{m_so.group('num')} on the Fishbone."
    return f"Fishbone hierarchy section prefix ('{clean}')."


def decode_operation_or_pitch_id(raw_value: str) -> dict[str, Any]:
    """Decode a PAAG Pitch Address (e.g. 01-ML1-004) or Operation ID (e.g. M1S1b.01-ML1-004.4)."""
    text = str(raw_value or "").strip()
    if not text:
        return {"valid": False, "error": "Enter a Pitch Address or Operation ID to decode."}

    flow_descriptions = {
        "ML": "Main Line assembly area",
        "SUB": "Subassembly feeder area",
        "WS": "Waterspider material delivery area",
        "KIT": "Kitter preparation area",
        "RPK": "Repacker area",
    }

    fishbone_prefix = ""
    stack_position = ""
    pitch_candidate = text

    # Check if input is a full Op ID: <fishbone_prefix>.<pitch_address>.<stack_position>
    # Note that <fishbone_prefix> can contain a dot if shared across mainlines (e.g. M1+M2.S1a.01-ML1-004.4)
    full_op_match = re.match(
        r"^(?P<fb>[A-Za-z0-9+.]+?)\.(?P<pitch>[A-Za-z0-9]+-[A-Za-z0-9&]+-\d+)\.(?P<pos>\d+)$",
        text,
    )
    if full_op_match:
        fishbone_prefix = full_op_match.group("fb")
        pitch_candidate = full_op_match.group("pitch")
        stack_position = full_op_match.group("pos")
    elif "." in text and "-" in text:
        first_dot = text.find(".")
        last_dot = text.rfind(".")
        if first_dot < last_dot:
            fishbone_prefix = text[:first_dot]
            pitch_candidate = text[first_dot + 1 : last_dot]
            stack_position = text[last_dot + 1 :]
        else:
            fishbone_prefix = text[:first_dot]
            pitch_candidate = text[first_dot + 1 :]

    segments: list[dict[str, str]] = []
    if fishbone_prefix:
        segments.append(
            {
                "segment": fishbone_prefix,
                "label": "Fishbone Hierarchy",
                "meaning": _explain_fishbone_prefix(fishbone_prefix),
            }
        )

    parsed_pitch = parse_yamazumi_pitch_address(pitch_candidate)
    if parsed_pitch is not None:
        sec_code = parsed_pitch.section_code
        flow_match = re.match(r"^([A-Z]+)(\d*)$", sec_code)
        if flow_match:
            prefix_letters = flow_match.group(1)
            prefix_num = flow_match.group(2)
            base_desc = flow_descriptions.get(
                prefix_letters, f"Section code '{sec_code}'"
            )
            sec_meaning = (
                f"{base_desc} #{prefix_num}" if prefix_num else base_desc
            )
        else:
            sec_meaning = f"Fishbone section code '{sec_code}'."

        segments.append(
            {
                "segment": parsed_pitch.line_code,
                "label": "Line / Subline Code",
                "meaning": f"2-character line/subline code ('{parsed_pitch.line_code}').",
            }
        )
        segments.append(
            {
                "segment": parsed_pitch.section_code,
                "label": "Section / Area Code",
                "meaning": sec_meaning,
            }
        )
        segments.append(
            {
                "segment": f"{parsed_pitch.number:03d}",
                "label": "Pitch Sequence",
                "meaning": f"Pitch #{parsed_pitch.number} inside {parsed_pitch.line_code}-{parsed_pitch.section_code}.",
            }
        )
    else:
        parts = pitch_candidate.split("-")
        for idx, token in enumerate(parts):
            clean_tok = token.strip()
            if not clean_tok:
                continue
            if idx == 0:
                segments.append(
                    {
                        "segment": clean_tok,
                        "label": "Line / Station Prefix",
                        "meaning": f"Station or line prefix ('{clean_tok}').",
                    }
                )
            elif idx == 1:
                segments.append(
                    {
                        "segment": clean_tok,
                        "label": "Section / Flow Token",
                        "meaning": f"Work area or section token ('{clean_tok}').",
                    }
                )
            else:
                segments.append(
                    {
                        "segment": clean_tok,
                        "label": "Sequence Token",
                        "meaning": f"Sequence identifier ('{clean_tok}').",
                    }
                )

    if stack_position:
        segments.append(
            {
                "segment": f".{stack_position}",
                "label": "Pitch Stack Position",
                "meaning": f"Work element #{stack_position} stacked inside pitch {pitch_candidate}.",
            }
        )

    return {
        "valid": True,
        "input": text,
        "is_guided_pitch": parsed_pitch is not None,
        "is_full_op_id": bool(fishbone_prefix and stack_position),
        "segments": segments,
    }


def _render_page_manual_tab(active_page_key: str) -> None:
    default_manual_key = resolve_manual_key(active_page_key)
    manual_keys = list(PAGE_MANUALS.keys())
    default_idx = (
        manual_keys.index(default_manual_key)
        if default_manual_key in manual_keys
        else 0
    )

    top_c1, top_c2 = st.columns([3, 2])
    with top_c1:
        selected_key = st.selectbox(
            "Select module guide (defaults to your active tab)",
            options=manual_keys,
            index=default_idx,
            format_func=lambda k: (
                f"{PAGE_MANUALS[k]['title']}  (Current tab)"
                if k == default_manual_key
                else PAGE_MANUALS[k]["title"]
            ),
            key=f"help_hub_manual_selector_{default_manual_key}",
        )
    with top_c2:
        manual_search = st.text_input(
            "Filter guides by keyword",
            placeholder="e.g. torque, freeze columns, takt, BOM...",
            key="help_hub_manual_keyword_filter",
        ).strip()

    if manual_search:
        tokens = [t.lower() for t in manual_search.split() if t.strip()]
        matching_keys = []
        for k, m in PAGE_MANUALS.items():
            haystack = " ".join(
                [
                    m["title"],
                    m["scope"],
                    m["summary"],
                    " ".join(m["workflows"]),
                    m["connections"],
                    " ".join(m["tips"]),
                ]
            ).lower()
            if all(tok in haystack for tok in tokens):
                matching_keys.append(k)
        st.caption(
            f"Found **{len(matching_keys)}** module guide{'s' if len(matching_keys) != 1 else ''} matching `{manual_search}`:"
        )
        for mk in matching_keys:
            m = PAGE_MANUALS[mk]
            with st.expander(f"{m['icon']} **{m['title']}** · `{m['scope']}`", expanded=(mk == selected_key)):
                st.markdown(m["summary"])
                st.markdown("**Key workflows:**")
                for wf in m["workflows"]:
                    st.markdown(f"- {wf}")
                st.caption(f"**Critical thread connection:** {m['connections']}")
                if st.button(
                    f"Open {m['title']}",
                    icon=m["icon"],
                    key=f"help_hub_filter_jump_{mk}",
                ):
                    navigate_to_page_from_hub(mk, m["title"])
        st.divider()

    manual = PAGE_MANUALS[selected_key]
    with st.container(border=True):
        hdr_c1, hdr_c2 = st.columns([4, 1], vertical_alignment="center")
        with hdr_c1:
            st.markdown(f"### {manual['icon']} {manual['title']}")
            st.caption(f"**Scope:** `{manual['scope']}`")
        with hdr_c2:
            if selected_key != default_manual_key:
                if st.button(
                    f"Open {manual['title']}",
                    icon=":material/open_in_new:",
                    width="stretch",
                    key=f"help_hub_open_manual_page_{selected_key}",
                ):
                    navigate_to_page_from_hub(selected_key, manual["title"])
            else:
                st.caption(":material/location_on: **Current tab**")

        st.markdown(manual["summary"])
        st.markdown("#### Step-by-step workflows")
        for wf in manual["workflows"]:
            st.markdown(f"- {wf}")

        st.markdown("#### Critical Thread connection")
        st.info(manual["connections"], icon=":material/account_tree:")

        if manual.get("tips"):
            st.markdown("#### Tips & best practices")
            for tip in manual["tips"]:
                st.markdown(f"- :material/lightbulb: {tip}")

    if selected_key == "functional_quality":
        st.markdown("#### Detailed Quality tab guides")
        q_tabs = list(QUALITY_TAB_HELP_GUIDES.keys())
        chosen_q_tab = st.segmented_control(
            "Quality sub-module",
            options=q_tabs,
            default=q_tabs[0],
            key="help_hub_quality_subtab_selector",
        ) or q_tabs[0]
        q_guide = QUALITY_TAB_HELP_GUIDES[chosen_q_tab]
        with st.container(border=True):
            st.markdown(f"**{q_guide['title']}**")
            st.markdown(q_guide["body"])


def _render_global_search_tab(
    project_id: str | None,
    scenario_id: str | None,
) -> None:
    if not project_id:
        st.info(
            "Select or create an active project on **Overview** to search project records. "
            "You can still search App Feedback items below.",
            icon=":material/info:",
        )

    sc1, sc2, sc3 = st.columns([3, 1.4, 1.6], vertical_alignment="bottom")
    with sc1:
        query = st.text_input(
            "Keyword search across project & scenario data",
            placeholder="Search part numbers, descriptions, Op IDs, pitches, failure modes, concerns...",
            key="help_hub_global_search_query",
        ).strip()
    with sc2:
        scope_mode = st.selectbox(
            "Scenario scope",
            options=["Active scenario", "All scenarios"],
            index=0,
            key="help_hub_global_search_scope",
            help="Choose whether scenario-owned tables (Yamazumi, Process, PFMEA, Ergo, Safety) filter to the active scenario or search all scenarios in the project.",
        )
    with sc3:
        category_filter = st.selectbox(
            "Category filter",
            options=[
                "All categories",
                "Parts Catalog",
                "Fishbone",
                "Complexity Trees",
                "BOM",
                "Yamazumi",
                "Process at a Glance",
                "Equipment",
                "Quality",
                "Quality (PFMEA)",
                "Ergonomics",
                "Safety",
                "Questions & Concerns",
                "App Feedback",
            ],
            index=0,
            key="help_hub_global_search_category",
        )

    if not query:
        st.caption(
            "Type one or more keywords above to search across **Parts Catalog**, **Fishbone**, "
            "**Complexity Trees**, **BOM**, **Yamazumi**, **Process at a Glance**, **Equipment**, "
            "**Quality & PFMEA**, **Ergonomics**, **Safety**, **Questions & Concerns**, and **App Feedback**."
        )
        return

    results_df = global_project_search(
        project_id,
        scenario_id,
        query,
        include_all_scenarios=(scope_mode == "All scenarios"),
        limit_per_category=30,
    )
    if category_filter != "All categories" and not results_df.empty:
        results_df = results_df[results_df["category"] == category_filter].reset_index(
            drop=True
        )

    if results_df.empty:
        st.warning(
            f"No records matched `{query}` in the selected scope. Try broadening your search or switching **Scenario scope** to `All scenarios`.",
            icon=":material/search_off:",
        )
        return

    st.caption(
        f"Found **{len(results_df)}** matching record{'s' if len(results_df) != 1 else ''} across "
        f"**{results_df['category'].nunique()}** module{'s' if results_df['category'].nunique() != 1 else ''}. "
        "Click **Open page** on any result to jump directly to that screen."
    )

    for idx, row in results_df.iterrows():
        with st.container(border=True):
            rc1, rc2 = st.columns([4.2, 1.3], vertical_alignment="center")
            with rc1:
                st.markdown(
                    f"**{row['item_label']}** &nbsp;·&nbsp; `{row['category']}` &nbsp;·&nbsp; `{row['scope']}`"
                )
                if str(row["detail"] or "").strip():
                    st.caption(str(row["detail"]))
            with rc2:
                if st.button(
                    f"Open {row['page_title']}",
                    icon=":material/arrow_forward:",
                    width="stretch",
                    key=f"help_hub_search_go_{idx}_{row['record_id']}",
                ):
                    navigate_to_page_from_hub(
                        str(row["page_url_path"]),
                        str(row["page_title"]),
                    )


def _default_critical_thread_steps() -> list[dict[str, Any]]:
    """Fallback step metadata when no project is selected yet."""
    return [
        {
            "step_number": 1,
            "title": "Import PITs (Source Evidence)",
            "scope": "All scenarios",
            "page_url_path": "pits_exchange",
            "page_title": "Import PITs",
            "metric_summary": "0 PITS records · 0 BOM workbook imports",
            "populated": False,
            "description": (
                "Import Product Architecture / PITS tracker workbooks as source evidence. "
                "Changed records enter reconciliation without silently overwriting reviewed planning decisions."
            ),
        },
        {
            "step_number": 2,
            "title": "Complexity Trees (Models & Features)",
            "scope": "All scenarios",
            "page_url_path": "models",
            "page_title": "Complexity Trees",
            "metric_summary": "0 models · 0 complexity features",
            "populated": False,
            "description": (
                "Define product models, platform sizes, and differentiating complexity features "
                "so parts and assemblies can be mapped to model applicability rules."
            ),
        },
        {
            "step_number": 3,
            "title": "BOM (Tree, Authoring & Reconciliation)",
            "scope": "All scenarios",
            "page_url_path": "bom_tree",
            "page_title": "BOM",
            "metric_summary": "0 approved / 0 total BOM occurrences",
            "populated": False,
            "description": (
                "Inspect CAD-style Model Tree BOMs, author Level 1–11 model BOMs from scratch "
                "(or predict from Complexity Trees features), and reconcile parts into Fishbone sections."
            ),
        },
        {
            "step_number": 4,
            "title": "Parts Catalog",
            "scope": "All scenarios + scenario active flags",
            "page_url_path": "parts",
            "page_title": "Parts Catalog",
            "metric_summary": "0 catalog parts",
            "populated": False,
            "description": (
                "Maintain the project-wide part master, reference images, annotated callouts, "
                "feature applicability rules, and scenario-specific Active status."
            ),
        },
        {
            "step_number": 5,
            "title": "Fishbone Assembly Structure",
            "scope": "All scenarios",
            "page_url_path": "fishbone",
            "page_title": "Fishbone",
            "metric_summary": "0 sections · 0 part placements",
            "populated": False,
            "description": (
                "Structure main-line, subassembly, and feeder sections, sequence part placements, "
                "and define manufacturing assemblies across the assembly grid."
            ),
        },
        {
            "step_number": 6,
            "title": "Yamazumi Line Balancing",
            "scope": "Active scenario",
            "page_url_path": "yamazumi",
            "page_title": "Yamazumi",
            "metric_summary": "0 areas · 0 pitches · 0 work elements",
            "populated": False,
            "description": (
                "Balance operator work elements against scenario takt time across pitches, "
                "assign material groups from Fishbone placements, and push reviewed stacks to Process at a Glance."
            ),
        },
        {
            "step_number": 7,
            "title": "Process at a Glance",
            "scope": "Active scenario",
            "page_url_path": "process",
            "page_title": "Process at a Glance",
            "metric_summary": "0 Process steps",
            "populated": False,
            "description": (
                "Maintain the authoritative scenario Process plan with deterministic Op IDs, "
                "part handling/consumption groups, visual aids, and functional review links."
            ),
        },
        {
            "step_number": 8,
            "title": "Pin Map & Functional Reviews",
            "scope": "Active scenario + shared repositories",
            "page_url_path": "pin_map",
            "page_title": "Pin Map",
            "metric_summary": "0 Quality reqs · 0 Equipment · 0 Ergo · 0 Safety",
            "populated": False,
            "functional_counts": {
                "equipment": 0,
                "quality": 0,
                "ergonomics": 0,
                "safety": 0,
            },
            "description": (
                "Review the derived Pin Map and complete functional reviews across Equipment, "
                "Ergonomics, Quality (Requirements, Torque, PFMEA, Control Plan), Materials, and Safety."
            ),
        },
    ]


def _build_critical_thread_flowchart_html(
    steps: list[dict[str, Any]],
    active_manual_key: str,
) -> str:
    """Build an interactive-looking visual SVG/HTML flowchart of the PAAG Critical Thread."""
    step_map = {int(s["step_number"]): s for s in steps}
    populated_steps = sum(1 for s in steps if s.get("populated"))
    total_steps = max(len(steps), 1)
    pct = int(round((populated_steps / total_steps) * 100))

    def _node_card_html(
        step_num: int,
        short_title: str,
        subtitle: str,
        scope_kind: str = "project",
    ) -> str:
        s = step_map.get(step_num, {})
        is_pop = bool(s.get("populated"))
        url_path = str(s.get("page_url_path") or "")
        is_current = bool(url_path and url_path == active_manual_key)
        metric = html.escape(str(s.get("metric_summary") or ""))
        scope_label = "All scenarios" if scope_kind == "project" else "Active scenario"
        scope_cls = "paag-fc-scope-project" if scope_kind == "project" else "paag-fc-scope-scenario"
        status_cls = "paag-fc-node-pop" if is_pop else "paag-fc-node-empty"
        current_cls = " paag-fc-node-current" if is_current else ""
        status_badge = (
            '<span class="paag-fc-status paag-fc-status-ok">✓ Populated</span>'
            if is_pop
            else '<span class="paag-fc-status paag-fc-status-pending">○ Pending</span>'
        )
        here_badge = (
            '<span class="paag-fc-here-badge">★ You are here</span>' if is_current else ""
        )
        return f"""
        <div class="paag-fc-node {status_cls}{current_cls}">
            <div class="paag-fc-node-top">
                <span class="paag-fc-step-num">STEP {step_num}</span>
                <span class="paag-fc-scope {scope_cls}">{scope_label}</span>
                {here_badge}
                {status_badge}
            </div>
            <div class="paag-fc-node-title">{html.escape(short_title)}</div>
            <div class="paag-fc-node-sub">{html.escape(subtitle)}</div>
            <div class="paag-fc-node-metric">{metric}</div>
        </div>
        """

    s8 = step_map.get(8, {})
    func_counts = s8.get("functional_counts") or {}
    eq_cnt = int(func_counts.get("equipment", 0))
    q_cnt = int(func_counts.get("quality", 0))
    er_cnt = int(func_counts.get("ergonomics", 0))
    sf_cnt = int(func_counts.get("safety", 0))
    s4_pop = bool(step_map.get(4, {}).get("populated"))
    s5_pop = bool(step_map.get(5, {}).get("populated"))

    func_branches = [
        (
            "functional_equipment",
            "Equipment",
            "Catalog · Placements · Conveyors",
            f"{eq_cnt} assets",
            eq_cnt > 0,
        ),
        (
            "functional_quality",
            "Quality",
            "QR Repo · Torque · PFMEA · CP",
            f"{q_cnt} requirements",
            q_cnt > 0,
        ),
        (
            "functional_ergonomics",
            "Ergonomics",
            "Posture · Risk Class (Green/Red)",
            f"{er_cnt} reviews",
            er_cnt > 0,
        ),
        (
            "functional_materials",
            "Materials",
            "Line-side · Kitting · Delivery",
            "Synced with Parts & ASM" if (s4_pop or s5_pop) else "Awaiting parts",
            s4_pop or s5_pop,
        ),
        (
            "functional_safety",
            "Safety",
            "Hazards & Required PPE",
            f"{sf_cnt} requirements",
            sf_cnt > 0,
        ),
    ]

    func_cards_html = []
    for f_key, f_title, f_sub, f_metric, f_pop in func_branches:
        f_curr = f_key == active_manual_key
        f_cls = "paag-fc-mini-pop" if f_pop else "paag-fc-mini-empty"
        if f_curr:
            f_cls += " paag-fc-node-current"
        f_dot = "●" if f_pop else "○"
        f_here = '<span class="paag-fc-here-mini">★ Here</span>' if f_curr else ""
        func_cards_html.append(
            f"""
            <div class="paag-fc-mini-node {f_cls}">
                <div class="paag-fc-mini-header">
                    <span class="paag-fc-mini-dot">{f_dot}</span>
                    <span class="paag-fc-mini-title">{html.escape(f_title)}</span>
                    {f_here}
                </div>
                <div class="paag-fc-mini-sub">{html.escape(f_sub)}</div>
                <div class="paag-fc-mini-metric">{html.escape(f_metric)}</div>
            </div>
            """
        )

    return f"""
    <style>
    .paag-fc-wrap {{
        font-family: "Source Sans Pro", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #1e293b;
        background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
        border: 1px solid #cbd5e1;
        border-radius: 14px;
        padding: 16px 18px 20px 18px;
        margin-bottom: 12px;
    }}
    .paag-fc-topbar {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 14px;
        padding-bottom: 10px;
        border-bottom: 1px solid #e2e8f0;
    }}
    .paag-fc-progress-wrap {{
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 0.85rem;
        font-weight: 600;
        color: #0f172a;
    }}
    .paag-fc-progress-track {{
        width: 140px;
        height: 8px;
        background: #e2e8f0;
        border-radius: 999px;
        overflow: hidden;
    }}
    .paag-fc-progress-fill {{
        height: 100%;
        width: {pct}%;
        background: linear-gradient(90deg, #0f766e, #10b981);
        border-radius: 999px;
    }}
    .paag-fc-legend {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        font-size: 0.76rem;
        color: #475569;
    }}
    .paag-fc-legend-item {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 999px;
        padding: 2px 9px;
    }}
    .paag-fc-lane {{
        border-radius: 12px;
        padding: 12px 14px 14px 14px;
        position: relative;
    }}
    .paag-fc-lane-project {{
        background: rgba(238, 242, 255, 0.65);
        border: 1.5px dashed #818cf8;
    }}
    .paag-fc-lane-scenario {{
        background: rgba(240, 253, 250, 0.75);
        border: 1.5px dashed #14b8a6;
    }}
    .paag-fc-lane-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 6px;
        margin-bottom: 10px;
        font-size: 0.78rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}
    .paag-fc-lane-project .paag-fc-lane-header {{
        color: #3730a3;
    }}
    .paag-fc-lane-scenario .paag-fc-lane-header {{
        color: #0f766e;
    }}
    .paag-fc-grid-2 {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 16px;
        align-items: stretch;
    }}
    .paag-fc-grid-pair-sync {{
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        gap: 10px;
        align-items: center;
    }}
    .paag-fc-sync-bridge {{
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        font-size: 0.72rem;
        font-weight: 700;
        color: #4338ca;
        background: #e0e7ff;
        border: 1px solid #a5b4fc;
        border-radius: 8px;
        padding: 6px 8px;
        min-width: 92px;
        line-height: 1.2;
    }}
    .paag-fc-center-row {{
        display: flex;
        justify-content: center;
    }}
    .paag-fc-center-row > .paag-fc-node {{
        width: min(100%, 560px);
    }}
    .paag-fc-node {{
        background: #ffffff;
        border-radius: 10px;
        padding: 10px 13px;
        box-shadow: 0 2px 5px rgba(15, 23, 42, 0.06);
        transition: transform 0.12s ease, box-shadow 0.12s ease;
    }}
    .paag-fc-node-pop {{
        border: 1.5px solid #10b981;
        border-left: 5px solid #059669;
    }}
    .paag-fc-node-empty {{
        border: 1.5px solid #cbd5e1;
        border-left: 5px solid #94a3b8;
    }}
    .paag-fc-node-current {{
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.28), 0 4px 12px rgba(37, 99, 235, 0.16) !important;
        border-color: #2563eb !important;
    }}
    .paag-fc-node-top {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 6px;
        margin-bottom: 5px;
    }}
    .paag-fc-step-num {{
        font-size: 0.7rem;
        font-weight: 800;
        letter-spacing: 0.05em;
        background: #0f172a;
        color: #ffffff;
        padding: 2px 7px;
        border-radius: 5px;
    }}
    .paag-fc-scope {{
        font-size: 0.69rem;
        font-weight: 700;
        padding: 2px 7px;
        border-radius: 999px;
    }}
    .paag-fc-scope-project {{
        background: #e0e7ff;
        color: #3730a3;
    }}
    .paag-fc-scope-scenario {{
        background: #ccfbf1;
        color: #115e59;
    }}
    .paag-fc-status {{
        margin-left: auto;
        font-size: 0.71rem;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 999px;
    }}
    .paag-fc-status-ok {{
        background: #d1fae5;
        color: #065f46;
    }}
    .paag-fc-status-pending {{
        background: #f1f5f9;
        color: #64748b;
    }}
    .paag-fc-here-badge {{
        font-size: 0.69rem;
        font-weight: 800;
        background: #dbeafe;
        color: #1d4ed8;
        border: 1px solid #93c5fd;
        padding: 1px 7px;
        border-radius: 999px;
    }}
    .paag-fc-node-title {{
        font-size: 0.96rem;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 2px;
    }}
    .paag-fc-node-sub {{
        font-size: 0.79rem;
        color: #475569;
        margin-bottom: 6px;
        line-height: 1.3;
    }}
    .paag-fc-node-metric {{
        font-size: 0.76rem;
        font-weight: 600;
        color: #0f766e;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 3px 8px;
        display: inline-block;
    }}
    .paag-fc-connector-row {{
        display: flex;
        justify-content: space-around;
        align-items: center;
        padding: 4px 0;
        color: #475569;
        font-size: 0.74rem;
        font-weight: 600;
    }}
    .paag-fc-arrow-pill {{
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 999px;
        padding: 2px 10px;
        color: #334155;
        font-size: 0.73rem;
        font-weight: 600;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }}
    .paag-fc-funnel {{
        display: flex;
        flex-direction: column;
        align-items: center;
        margin: 6px 0;
    }}
    .paag-fc-funnel-bracket {{
        width: 56%;
        height: 10px;
        border-left: 2px solid #64748b;
        border-right: 2px solid #64748b;
        border-bottom: 2px solid #64748b;
        border-radius: 0 0 8px 8px;
    }}
    .paag-fc-fanout-bracket {{
        width: 82%;
        height: 10px;
        border-left: 2px solid #0d9488;
        border-right: 2px solid #0d9488;
        border-top: 2px solid #0d9488;
        border-radius: 8px 8px 0 0;
    }}
    .paag-fc-fanin-bracket {{
        width: 82%;
        height: 10px;
        border-left: 2px solid #0d9488;
        border-right: 2px solid #0d9488;
        border-bottom: 2px solid #0d9488;
        border-radius: 0 0 8px 8px;
    }}
    .paag-fc-boundary-gate {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        margin: 10px 0;
    }}
    .paag-fc-boundary-line {{
        flex: 1;
        height: 2px;
        background: linear-gradient(90deg, transparent, #64748b, transparent);
    }}
    .paag-fc-boundary-badge {{
        background: #0f172a;
        color: #f8fafc;
        font-size: 0.74rem;
        font-weight: 700;
        padding: 4px 14px;
        border-radius: 999px;
        letter-spacing: 0.03em;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.15);
    }}
    .paag-fc-grid-5 {{
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 8px;
    }}
    .paag-fc-mini-node {{
        background: #ffffff;
        border-radius: 8px;
        padding: 8px 9px;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
    }}
    .paag-fc-mini-pop {{
        border: 1.5px solid #10b981;
        border-top: 3.5px solid #059669;
    }}
    .paag-fc-mini-empty {{
        border: 1.5px solid #cbd5e1;
        border-top: 3.5px solid #94a3b8;
    }}
    .paag-fc-mini-header {{
        display: flex;
        align-items: center;
        gap: 4px;
        margin-bottom: 3px;
    }}
    .paag-fc-mini-dot {{
        font-size: 0.75rem;
        color: #059669;
    }}
    .paag-fc-mini-empty .paag-fc-mini-dot {{
        color: #94a3b8;
    }}
    .paag-fc-mini-title {{
        font-size: 0.82rem;
        font-weight: 700;
        color: #0f172a;
    }}
    .paag-fc-here-mini {{
        margin-left: auto;
        font-size: 0.64rem;
        font-weight: 800;
        background: #dbeafe;
        color: #1d4ed8;
        padding: 1px 5px;
        border-radius: 999px;
    }}
    .paag-fc-mini-sub {{
        font-size: 0.7rem;
        color: #64748b;
        margin-bottom: 4px;
        line-height: 1.25;
    }}
    .paag-fc-mini-metric {{
        font-size: 0.7rem;
        font-weight: 600;
        color: #0f766e;
    }}
    @media (max-width: 900px) {{
        .paag-fc-grid-2,
        .paag-fc-grid-pair-sync,
        .paag-fc-grid-5 {{
            grid-template-columns: 1fr;
        }}
    }}
    </style>

    <div class="paag-fc-wrap">
        <div class="paag-fc-topbar">
            <div class="paag-fc-progress-wrap">
                <span>Critical Thread Readiness: {populated_steps} / {len(steps)} stages populated ({pct}%)</span>
                <div class="paag-fc-progress-track"><div class="paag-fc-progress-fill"></div></div>
            </div>
            <div class="paag-fc-legend">
                <span class="paag-fc-legend-item"><strong style="color:#059669;">●</strong> Populated</span>
                <span class="paag-fc-legend-item"><strong style="color:#94a3b8;">○</strong> Pending</span>
                <span class="paag-fc-legend-item"><strong style="color:#2563eb;">★</strong> Current page</span>
            </div>
        </div>

        <!-- PHASE 1: PROJECT-WIDE SWIMLANE -->
        <div class="paag-fc-lane paag-fc-lane-project">
            <div class="paag-fc-lane-header">
                <span>Phase 1 · Project-Wide Product Architecture &amp; MBOM Spine</span>
                <span>Scope: All scenarios (shared across project)</span>
            </div>

            <!-- Row 1: Parallel Upstream Inputs (Step 1 & Step 2) -->
            <div class="paag-fc-grid-2">
                {_node_card_html(1, "Import PITs (Source Evidence)", "Upstream Product Architecture & Level 1–11 EBOM workbooks", "project")}
                {_node_card_html(2, "Complexity Trees (Models & Features)", "Product models, EAU volumes, milestone dates & feature matrix", "project")}
            </div>

            <!-- Connectors from Row 1 to Row 2 -->
            <div class="paag-fc-connector-row">
                <span class="paag-fc-arrow-pill">▼ Stages EBOM occurrences &amp; tracker rows</span>
                <span class="paag-fc-arrow-pill">▼ Supplies model &amp; feature applicability rules</span>
            </div>

            <!-- Row 2: BOM Reconciliation <-> Parts Catalog (Step 3 & Step 4) -->
            <div class="paag-fc-grid-pair-sync">
                {_node_card_html(3, "BOM (Tree, Authoring & Reconciliation)", "View CAD tree, author Level 1–11 model BOMs & sync Fishbone placements", "project")}
                <div class="paag-fc-sync-bridge">
                    <span>◄────►</span>
                    <span>Syncs Parts &amp; Placements</span>
                </div>
                {_node_card_html(4, "Parts Catalog", "Master part attributes, annotated photos & scenario active flags", "project")}
            </div>

            <!-- Converging Funnel into Step 5 (Fishbone) -->
            <div class="paag-fc-funnel">
                <div class="paag-fc-funnel-bracket"></div>
                <span class="paag-fc-arrow-pill" style="margin-top:3px;">▼ Approved MBOM placements &amp; active catalog parts converge</span>
            </div>

            <!-- Row 3: Fishbone Assembly Structure (Step 5) -->
            <div class="paag-fc-center-row">
                {_node_card_html(5, "Fishbone Assembly Structure", "Main line, subassembly & parallel sections · Part placements · Manufacturing Assembly Grid (ASM)", "project")}
            </div>
        </div>

        <!-- SCOPE BOUNDARY CROSSING -->
        <div class="paag-fc-boundary-gate">
            <div class="paag-fc-boundary-line"></div>
            <div class="paag-fc-boundary-badge">
                ▼ SCOPE BOUNDARY: Fishbone Sections map 1-to-1 into Scenario Yamazumi Areas &amp; Material Groups ▼
            </div>
            <div class="paag-fc-boundary-line"></div>
        </div>

        <!-- PHASE 2: SCENARIO-SPECIFIC SWIMLANE -->
        <div class="paag-fc-lane paag-fc-lane-scenario">
            <div class="paag-fc-lane-header">
                <span>Phase 2 · Scenario Line Balancing, Process Plan &amp; Functional Reviews</span>
                <span>Scope: Active scenario (isolated per scenario)</span>
            </div>

            <!-- Row 4: Yamazumi Line Balancing (Step 6) -->
            <div class="paag-fc-center-row">
                {_node_card_html(6, "Yamazumi Line Balancing", "Scenario areas, guided pitch addresses (Pitch / Subassembly / Kitter / Waterspider) & operator elements vs. Takt Time", "scenario")}
            </div>

            <!-- Connector from Step 6 to Step 7 -->
            <div class="paag-fc-funnel">
                <span class="paag-fc-arrow-pill">▼ Push balanced pitch stacks &amp; material groups into Process steps</span>
            </div>

            <!-- Row 5: Process at a Glance (Step 7) -->
            <div class="paag-fc-center-row">
                {_node_card_html(7, "Process at a Glance (Authoritative Scenario Plan)", "Deterministic Op IDs (M1S1b.01-ML1-004.4) · Part Handle vs. Consume pairings · Pitch visual aids", "scenario")}
            </div>

            <!-- Fan-Out from Step 7 to 5 Functional Reviews -->
            <div class="paag-fc-funnel">
                <span class="paag-fc-arrow-pill" style="margin-bottom:3px;">▼ Process steps anchor all 5 Cross-Functional Engineering Reviews ▼</span>
                <div class="paag-fc-fanout-bracket"></div>
            </div>

            <!-- Row 6: 5 Parallel Functional Review Branches -->
            <div class="paag-fc-grid-5">
                {"".join(func_cards_html)}
            </div>

            <!-- Fan-In from Functional Reviews into Step 8 (Pin Map) -->
            <div class="paag-fc-funnel">
                <div class="paag-fc-fanin-bracket"></div>
                <span class="paag-fc-arrow-pill" style="margin-top:3px;">▼ Synthesizes station-by-station risk, torque, tool &amp; PPE indicators ▼</span>
            </div>

            <!-- Row 7: Pin Map & 2D Layout (Step 8) -->
            <div class="paag-fc-center-row">
                {_node_card_html(8, "Pin Map & 2D Plant Layout", "Derived station-by-station indicator matrix + interactive 2D floorplan & conveyor layout canvas", "scenario")}
            </div>
        </div>
    </div>
    """


def _render_workflow_guide_tab(
    project_id: str | None,
    scenario_id: str | None,
    active_page_key: str = "",
) -> None:
    st.markdown(
        "The **Critical Thread** is the visual engineering flowchart of Process at a Glance. "
        "Upstream product architecture evidence flows through project-wide BOM & Fishbone structures "
        "into scenario-specific Yamazumi line balancing, Process steps, Functional Reviews, and the derived Pin Map."
    )
    if not project_id:
        st.info(
            "Select or create a project on **Overview** to populate live record counts inside the flowchart below.",
            icon=":material/info:",
        )
        steps = _default_critical_thread_steps()
    else:
        steps = critical_thread_status_counts(project_id, scenario_id) or _default_critical_thread_steps()

    active_manual_key = resolve_manual_key(active_page_key)
    st.html(_build_critical_thread_flowchart_html(steps, active_manual_key))

    st.markdown("##### :material/ads_click: Click any flowchart node to open that workspace")
    row1_cols = st.columns(4)
    for col, step in zip(row1_cols, steps[:4]):
        with col:
            is_pop = bool(step.get("populated"))
            btn_icon = ":material/check_circle:" if is_pop else ":material/open_in_new:"
            if st.button(
                f"{step['step_number']}. {step['page_title']}",
                icon=btn_icon,
                width="stretch",
                key=f"help_hub_thread_go_{step['step_number']}",
                help=f"{step['title']} ({step['metric_summary']})",
            ):
                navigate_to_page_from_hub(step["page_url_path"], step["page_title"])

    row2_cols = st.columns(4)
    for col, step in zip(row2_cols, steps[4:8]):
        with col:
            is_pop = bool(step.get("populated"))
            btn_icon = ":material/check_circle:" if is_pop else ":material/open_in_new:"
            if st.button(
                f"{step['step_number']}. {step['page_title']}",
                icon=btn_icon,
                width="stretch",
                key=f"help_hub_thread_go_{step['step_number']}",
                help=f"{step['title']} ({step['metric_summary']})",
            ):
                navigate_to_page_from_hub(step["page_url_path"], step["page_title"])

    func_nav = [
        ("functional_equipment", "Equipment", ":material/precision_manufacturing:"),
        ("functional_quality", "Quality", ":material/verified:"),
        ("functional_ergonomics", "Ergonomics", ":material/accessibility_new:"),
        ("functional_materials", "Materials", ":material/inventory_2:"),
        ("functional_safety", "Safety", ":material/health_and_safety:"),
    ]
    func_cols = st.columns(5)
    for col, (f_url, f_label, f_icon) in zip(func_cols, func_nav):
        with col:
            if st.button(
                f_label,
                icon=f_icon,
                width="stretch",
                key=f"help_hub_thread_func_{f_url}",
                help=f"Open {f_label} functional review workspace",
            ):
                navigate_to_page_from_hub(f_url, f_label)

    with st.expander(":material/list_alt: View detailed stage-by-stage descriptions", expanded=False):
        for step in steps:
            is_pop = bool(step.get("populated"))
            status_icon = ":material/check_circle:" if is_pop else ":material/radio_button_unchecked:"
            status_label = "Populated" if is_pop else "Not yet populated"
            st.markdown(
                f"**Step {step['step_number']}: {step['title']}** (`{step['scope']}`) — "
                f"{status_icon} *{status_label}* ({step['metric_summary']})\n\n"
                f"{step['description']}"
            )


def _render_glossary_and_troubleshooting_tab() -> None:
    st.markdown("#### :material/qr_code_scanner: Interactive Op ID & Pitch Address Decoder")
    st.caption(
        "Paste any Yamazumi Pitch Address (e.g. `M1S1b.01`) or Process at a Glance Operation ID "
        "(e.g. `M1S1b.01-ML1-004.4`) to see what each segment means."
    )
    sample_op = st.text_input(
        "Pitch Address or Operation ID",
        value="M1S1b.01-ML1-004.4",
        key="help_hub_op_id_decoder_input",
    )
    decoded = decode_operation_or_pitch_id(sample_op)
    if decoded.get("valid"):
        seg_cols = st.columns(len(decoded["segments"]))
        for col, seg in zip(seg_cols, decoded["segments"]):
            with col:
                with st.container(border=True):
                    st.markdown(f"### `{seg['segment']}`")
                    st.markdown(f"**{seg['label']}**")
                    st.caption(seg["meaning"])
    else:
        st.caption(decoded.get("error", ""))

    st.divider()
    st.markdown("#### :material/quiz: Troubleshooting & Pro-Tips")
    for faq in TROUBLESHOOTING_FAQS:
        with st.expander(f"**{faq['question']}**", expanded=False):
            st.markdown(faq["answer"])

    st.divider()
    st.markdown("#### :material/dictionary: Canonical PAAG Glossary")
    glossary_query = st.text_input(
        "Filter glossary terms",
        placeholder="Search terms (e.g. MBOM, Takt, Waterspider, Consume, AP)...",
        key="help_hub_glossary_search",
    ).strip().lower()

    filtered_terms = [
        item
        for item in GLOSSARY_TERMS
        if not glossary_query
        or glossary_query in item["term"].lower()
        or glossary_query in item["category"].lower()
        or glossary_query in item["definition"].lower()
    ]
    for item in filtered_terms:
        with st.container(border=True):
            st.markdown(f"**{item['term']}** &nbsp;·&nbsp; `{item['category']}`")
            st.caption(item["definition"])


def _render_feedback_tracker_tab(
    project_id: str | None,
    scenario_id: str | None,
    active_page_title: str,
    editor_name: str,
) -> None:
    st.markdown(
        "Report software bugs, suggest new features or UX improvements, and track resolution status. "
        "Deleted items are protected for **30 days** in the Recycle Bin."
    )

    staged_ss_key = "help_hub_staged_feedback_screenshot"
    last_paste_hash_key = "help_hub_last_paste_hash"
    last_upload_hash_key = "help_hub_last_upload_hash"
    reset_form_key = "help_hub_reset_new_fb_form"

    if st.session_state.pop(reset_form_key, False):
        st.session_state["help_hub_new_fb_title"] = ""
        st.session_state["help_hub_new_fb_desc"] = ""
        st.session_state["help_hub_new_fb_steps"] = ""
        st.session_state.pop(staged_ss_key, None)
        st.session_state.pop(last_paste_hash_key, None)
        st.session_state.pop(last_upload_hash_key, None)

    if not st.session_state.get("help_hub_stage_unable_ids"):
        st.session_state.pop("help_hub_unable_reason_input", None)

    with st.expander(
        ":material/add_circle: **Report a bug or suggest an improvement**",
        expanded=True,
    ):
        st.caption(
            f"**Captured context:** Page: `{active_page_title or 'Overview'}` · "
            f"Submitted by: `{editor_name or 'Unspecified editor'}`"
        )
        fc1, fc2, fc3 = st.columns([1.4, 1.2, 2.4])
        with fc1:
            fb_type = st.selectbox(
                "Type",
                options=list(FEEDBACK_TYPES),
                index=0,
                key="help_hub_new_fb_type",
            )
        with fc2:
            fb_severity = st.selectbox(
                "Severity / Priority",
                options=list(FEEDBACK_SEVERITIES),
                index=1,
                key="help_hub_new_fb_severity",
            )
        with fc3:
            fb_title = st.text_input(
                "Concise summary / title",
                placeholder="e.g. Yamazumi board scroll jumps when dragging long descriptions",
                key="help_hub_new_fb_title",
            )

        dc1, dc2 = st.columns(2)
        with dc1:
            fb_desc = st.text_area(
                "Description / Expected vs. actual behavior",
                placeholder="Describe what happened or how the suggested feature would help your workflow...",
                height=95,
                key="help_hub_new_fb_desc",
            )
        with dc2:
            fb_steps = st.text_area(
                "Steps to reproduce / Use case (optional)",
                placeholder="1. Open Yamazumi\n2. Filter by section...\n3. Click Save & Refresh",
                height=95,
                key="help_hub_new_fb_steps",
            )

        st.markdown("**Attach screenshot (optional — upload file or paste with `Ctrl+V`)**")
        up_col, paste_col = st.columns([1.3, 1.7], vertical_alignment="center")
        with up_col:
            uploaded_ss = st.file_uploader(
                "Upload screenshot (PNG, JPG, WEBP · max 10 MB)",
                type=["png", "jpg", "jpeg", "webp"],
                key="help_hub_fb_file_uploader",
            )
        with paste_col:
            pasted_ss = clipboard_image(key="help_hub_fb_clipboard")

        pasted_payload = getattr(pasted_ss, "image", None)
        if pasted_payload:
            try:
                decoded_img = decode_clipboard_image(pasted_payload)
                raw_bytes = decoded_img["bytes"]
                paste_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
                if st.session_state.get(last_paste_hash_key) != paste_hash:
                    st.session_state[last_paste_hash_key] = paste_hash
                    st.session_state[staged_ss_key] = {
                        "bytes": raw_bytes,
                        "filename": decoded_img.get("name") or "clipboard.png",
                        "source": "clipboard",
                    }
            except ValueError as exc:
                st.error(str(exc))

        if uploaded_ss is not None:
            raw_up = uploaded_ss.getvalue()
            up_hash = hashlib.sha256(raw_up).hexdigest()[:16]
            if st.session_state.get(last_upload_hash_key) != up_hash:
                st.session_state[last_upload_hash_key] = up_hash
                st.session_state[staged_ss_key] = {
                    "bytes": raw_up,
                    "filename": uploaded_ss.name or "screenshot.png",
                    "source": "upload",
                }

        staged_ss = st.session_state.get(staged_ss_key)
        if isinstance(staged_ss, dict) and staged_ss.get("bytes"):
            prev_c1, prev_c2 = st.columns([1, 3], vertical_alignment="center")
            with prev_c1:
                st.image(staged_ss["bytes"], width="stretch")
            with prev_c2:
                st.caption(
                    f":material/image: Attached screenshot: `{staged_ss.get('filename', 'screenshot.png')}`"
                )
                if st.button(
                    "Remove attached screenshot",
                    icon=":material/close:",
                    key="help_hub_remove_staged_ss_btn",
                ):
                    st.session_state.pop(staged_ss_key, None)
                    st.rerun(scope="fragment")

        if st.button(
            "Submit feedback",
            icon=":material/send:",
            type="primary",
            key="help_hub_submit_feedback_btn",
        ):
            try:
                saved_ss_path = ""
                if isinstance(staged_ss, dict) and staged_ss.get("bytes"):
                    saved_ss_path = save_feedback_screenshot(
                        staged_ss["bytes"],
                        staged_ss.get("filename") or "feedback.png",
                    )
                create_app_feedback(
                    title=fb_title,
                    feedback_type=fb_type,
                    severity=fb_severity,
                    description=fb_desc,
                    steps_to_reproduce=fb_steps,
                    page_context=active_page_title or "Overview",
                    project_id=project_id,
                    scenario_id=scenario_id,
                    screenshot_path=saved_ss_path,
                    submitted_by=editor_name,
                )
                st.session_state.pop(staged_ss_key, None)
                st.session_state[reset_form_key] = True
                st.toast("Feedback submitted—thank you!", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.divider()
    st.markdown("#### :material/list_alt: Submitted Bug Reports & Feature Suggestions")

    flt_c1, flt_c2, flt_c3, flt_c4 = st.columns([1.3, 1.3, 1.4, 2.0])
    with flt_c1:
        fb_scope = st.selectbox(
            "Project filter",
            options=["All projects", "Active project only"],
            index=0,
            key="help_hub_fb_list_scope",
        )
    with flt_c2:
        status_filter_options = [
            "All except Completed",
            "All (including Completed)",
            *FEEDBACK_STATUSES,
        ]
        if (
            "help_hub_fb_list_status" in st.session_state
            and st.session_state["help_hub_fb_list_status"] not in status_filter_options
        ):
            st.session_state["help_hub_fb_list_status"] = "All except Completed"
        fb_status_flt = st.selectbox(
            "Status",
            options=status_filter_options,
            index=0,
            key="help_hub_fb_list_status",
            help="Defaults to hiding Completed items. Choose 'All (including Completed)' or 'Completed' to view completed items.",
        )
    with flt_c3:
        fb_type_flt = st.selectbox(
            "Type",
            options=["All", *FEEDBACK_TYPES],
            index=0,
            key="help_hub_fb_list_type",
        )
    with flt_c4:
        fb_search = st.text_input(
            "Filter feedback",
            placeholder="Search title, description, page, or submitter...",
            key="help_hub_fb_list_search",
        ).strip().lower()

    fb_df = list_app_feedback(
        project_id=project_id,
        include_all_projects=(fb_scope == "All projects"),
        status_filter=fb_status_flt,
        feedback_type_filter=fb_type_flt,
    )

    if fb_search and not fb_df.empty:
        mask = (
            fb_df["title"].fillna("").str.lower().str.contains(fb_search, regex=False)
            | fb_df["description"].fillna("").str.lower().str.contains(fb_search, regex=False)
            | fb_df["page_context"].fillna("").str.lower().str.contains(fb_search, regex=False)
            | fb_df["submitted_by"].fillna("").str.lower().str.contains(fb_search, regex=False)
            | fb_df["resolution_notes"].fillna("").str.lower().str.contains(fb_search, regex=False)
        )
        fb_df = fb_df[mask].reset_index(drop=True)

    if fb_df.empty:
        if fb_status_flt == "All except Completed":
            st.caption(
                "No active feedback items match the current filters. "
                "Select **All (including Completed)** or **Completed** in the Status filter to view completed items."
            )
        else:
            st.caption("No feedback items match the current filters.")
    else:
        editor_key = "help_hub_feedback_table_editor"
        apply_pending_table_editor_reset(editor_key)

        display_df = fb_df.copy()
        display_df.insert(0, "_delete", False)
        display_df["created_at_display"] = display_df["created_at"].map(
            lambda v: format_eastern_timestamp(v)
        )
        display_df["has_screenshot"] = display_df["screenshot_path"].map(
            lambda p: "📷 Yes" if str(p or "").strip() else "—"
        )

        visible_cols = [
            "_delete",
            "status",
            "severity",
            "feedback_type",
            "title",
            "page_context",
            "description",
            "steps_to_reproduce",
            "resolution_notes",
            "submitted_by",
            "project_name",
            "has_screenshot",
            "created_at_display",
            "id",
        ]

        edited_df = st.data_editor(
            display_df[visible_cols],
            key=editor_key,
            hide_index=True,
            width="stretch",
            num_rows="fixed",
            column_order=[c for c in visible_cols if c != "id"],
            disabled=[
                "page_context",
                "submitted_by",
                "project_name",
                "has_screenshot",
                "created_at_display",
                "id",
            ],
            column_config={
                "_delete": st.column_config.CheckboxColumn(
                    "Select",
                    help="Select feedback items to move to a resolution stage (Working, Completed, Tagged for Future Development, Unable to complete, Open) or delete.",
                    default=False,
                    width="small",
                ),
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    options=list(FEEDBACK_STATUSES),
                    required=True,
                    width="medium",
                ),
                "severity": st.column_config.SelectboxColumn(
                    "Severity",
                    options=list(FEEDBACK_SEVERITIES),
                    required=True,
                    width="small",
                ),
                "feedback_type": st.column_config.SelectboxColumn(
                    "Type",
                    options=list(FEEDBACK_TYPES),
                    required=True,
                    width="medium",
                ),
                "title": st.column_config.TextColumn(
                    "Title",
                    required=True,
                    width="medium",
                ),
                "page_context": st.column_config.TextColumn(
                    "Page / Tab",
                    width="small",
                ),
                "description": st.column_config.TextColumn(
                    "Description",
                    width="large",
                ),
                "steps_to_reproduce": st.column_config.TextColumn(
                    "Steps / Use case",
                    width="medium",
                ),
                "resolution_notes": st.column_config.TextColumn(
                    "Resolution notes / Reason",
                    help="Resolution notes, or the required reason when Status is 'Unable to complete'.",
                    width="medium",
                ),
                "submitted_by": st.column_config.TextColumn(
                    "Submitted by",
                    width="small",
                ),
                "project_name": st.column_config.TextColumn(
                    "Project",
                    width="small",
                ),
                "has_screenshot": st.column_config.TextColumn(
                    "Screenshot",
                    width="small",
                ),
                "created_at_display": st.column_config.TextColumn(
                    "Submitted (ET)",
                    width="small",
                ),
            },
        )

        selected_for_delete = (
            edited_df[edited_df["_delete"].fillna(False).astype(bool)]["id"]
            .astype(str)
            .tolist()
        )
        compare_cols = [
            "status",
            "severity",
            "feedback_type",
            "title",
            "description",
            "steps_to_reproduce",
            "resolution_notes",
        ]
        has_inline_edits = not (
            edited_df[compare_cols]
            .fillna("")
            .astype(str)
            .equals(display_df[compare_cols].fillna("").astype(str))
        )

        selected_count = len(selected_for_delete)
        count_suffix = f" ({selected_count})" if selected_count else ""

        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(
                f"**Move selected{count_suffix} to stage:**"
                if selected_count
                else "**Select rows above to move to a resolution stage:**"
            )
            stage_actions = [
                ("Working", ":material/engineering:", "help_hub_stage_working_btn"),
                ("Completed", ":material/check_circle:", "help_hub_stage_completed_btn"),
                (
                    "Tagged for Future Development",
                    ":material/bookmark_added:",
                    "help_hub_stage_future_dev_btn",
                ),
                ("Open", ":material/restart_alt:", "help_hub_stage_open_btn"),
            ]
            for target_stage, stage_icon, stage_key in stage_actions:
                if st.button(
                    f"{target_stage}{count_suffix}",
                    icon=stage_icon,
                    disabled=not selected_for_delete,
                    width="content",
                    key=stage_key,
                ):
                    try:
                        moved = bulk_update_app_feedback_status(
                            selected_for_delete,
                            target_stage,
                            active_project_id=project_id,
                            editor_name=editor_name,
                        )
                        request_table_editor_reset(editor_key)
                        st.session_state.pop("help_hub_confirm_fb_delete_ids", None)
                        st.session_state.pop("help_hub_stage_unable_ids", None)
                        st.toast(
                            f"Moved {moved} item{'s' if moved != 1 else ''} to '{target_stage}'.",
                            icon=stage_icon,
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            if st.button(
                f"Unable to complete{count_suffix}",
                icon=":material/block:",
                disabled=not selected_for_delete,
                width="content",
                key="help_hub_stage_unable_btn",
            ):
                st.session_state["help_hub_stage_unable_ids"] = selected_for_delete
                st.session_state.pop("help_hub_confirm_fb_delete_ids", None)

        staged_unable_ids = st.session_state.get("help_hub_stage_unable_ids") or []
        if staged_unable_ids:
            with st.container(border=True):
                st.markdown(
                    f":material/block: **Mark {len(staged_unable_ids)} selected item{'s' if len(staged_unable_ids) != 1 else ''} as 'Unable to complete'**"
                )
                unable_reason = st.text_input(
                    "Reason unable to complete (required)",
                    placeholder="Enter the reason why this bug report or feature suggestion cannot be completed...",
                    key="help_hub_unable_reason_input",
                )
                with st.container(horizontal=True, vertical_alignment="center"):
                    if st.button(
                        "Confirm 'Unable to complete'",
                        icon=":material/block:",
                        type="primary",
                        width="content",
                        key="help_hub_confirm_unable_btn",
                    ):
                        try:
                            moved = bulk_update_app_feedback_status(
                                staged_unable_ids,
                                "Unable to complete",
                                resolution_notes=unable_reason,
                                active_project_id=project_id,
                                editor_name=editor_name,
                            )
                            st.session_state.pop("help_hub_stage_unable_ids", None)
                            request_table_editor_reset(editor_key)
                            st.toast(
                                f"Marked {moved} item{'s' if moved != 1 else ''} as 'Unable to complete'.",
                                icon=":material/block:",
                            )
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                    if st.button(
                        "Cancel",
                        icon=":material/close:",
                        width="content",
                        key="help_hub_cancel_unable_btn",
                    ):
                        st.session_state.pop("help_hub_stage_unable_ids", None)
                        st.rerun()

        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button(
                "Save & Refresh",
                icon=":material/save:",
                type="primary",
                disabled=not has_inline_edits,
                width="content",
                key="help_hub_fb_save_btn",
            ):
                try:
                    updated = save_bulk_app_feedback(
                        edited_df,
                        active_project_id=project_id,
                        editor_name=editor_name,
                    )
                    request_table_editor_reset(editor_key)
                    st.toast(
                        f"Saved {updated} feedback update{'s' if updated != 1 else ''}.",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if st.button(
                "Undo",
                icon=":material/undo:",
                disabled=not (has_inline_edits or bool(selected_for_delete)),
                width="content",
                key="help_hub_fb_undo_btn",
            ):
                request_table_editor_reset(editor_key)
                st.session_state.pop("help_hub_confirm_fb_delete_ids", None)
                st.session_state.pop("help_hub_stage_unable_ids", None)
                st.rerun()
            if st.button(
                f"Delete selected ({len(selected_for_delete)})"
                if selected_for_delete
                else "Delete selected",
                icon=":material/delete:",
                disabled=not selected_for_delete,
                width="content",
                key="destructive_help_hub_stage_fb_delete_btn",
            ):
                st.session_state["help_hub_confirm_fb_delete_ids"] = selected_for_delete
                st.session_state.pop("help_hub_stage_unable_ids", None)

        staged_delete_ids = st.session_state.get("help_hub_confirm_fb_delete_ids") or []
        if staged_delete_ids:
            with st.container(border=True):
                st.warning(
                    f"Move **{len(staged_delete_ids)}** selected feedback item{'s' if len(staged_delete_ids) != 1 else ''} "
                    "to the **Recycle Bin** (restorable for 30 days)?",
                    icon=":material/warning:",
                )
                cf1, cf2 = st.columns(2)
                with cf1:
                    if st.button(
                        "Confirm delete",
                        icon=":material/delete_forever:",
                        width="stretch",
                        key="destructive_help_hub_confirm_fb_delete_btn",
                    ):
                        try:
                            deleted = delete_app_feedback(
                                staged_delete_ids,
                                active_project_id=project_id,
                                editor_name=editor_name,
                            )
                            st.session_state.pop("help_hub_confirm_fb_delete_ids", None)
                            request_table_editor_reset(editor_key)
                            st.toast(
                                f"Moved {deleted} feedback item{'s' if deleted != 1 else ''} to the Recycle Bin.",
                                icon=":material/delete:",
                            )
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                with cf2:
                    if st.button(
                        "Cancel",
                        icon=":material/close:",
                        width="stretch",
                        key="help_hub_cancel_fb_delete_btn",
                    ):
                        st.session_state.pop("help_hub_confirm_fb_delete_ids", None)
                        st.rerun()

        # Optional screenshot viewer for rows that have screenshots
        rows_with_ss = fb_df[fb_df["screenshot_path"].fillna("").str.strip() != ""]
        if not rows_with_ss.empty:
            with st.expander(
                f":material/photo_library: View attached feedback screenshots ({len(rows_with_ss)})",
                expanded=False,
            ):
                for _, srow in rows_with_ss.iterrows():
                    raw_path = str(srow["screenshot_path"] or "").strip()
                    resolved = resolve_upload_path(raw_path, UPLOAD_DIR)
                    with st.container(border=True):
                        st.markdown(
                            f"**{srow['title']}** (`{srow['feedback_type']}` · `{srow['status']}`)"
                        )
                        if resolved is not None and resolved.is_file():
                            st.image(str(resolved), width="stretch")
                        else:
                            st.caption(f"Screenshot file not found locally (`{raw_path}`).")

    if project_id:
        with st.expander("History", icon=":material/history:"):
            history = audit_history(project_id, "App feedback", limit=50)
            if history.empty:
                st.caption("No App feedback history has been recorded for this project yet.")
            else:
                selectable_dataframe(
                    history.drop(columns=["details"], errors="ignore"),
                    key=f"app_feedback_history_table_{project_id}",
                    hide_index=True,
                    column_config={
                        "action": "Action",
                        "row_count": "Rows",
                        "editor_name": "Editor",
                        "created_at": st.column_config.DatetimeColumn(
                            "When", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
                        ),
                    },
                )


@st.dialog("Universal Help, Global Search & Feedback Hub", width="large")
def open_universal_help_dialog(
    *,
    active_page_key: str,
    active_page_title: str,
    project_id: str | None,
    scenario_id: str | None,
    editor_name: str = "",
) -> None:
    """Render the 5-tab Universal Help, Search & Feedback Hub modal."""
    tab_options = [
        ":material/menu_book: Page Manual",
        ":material/search: Global Search",
        ":material/account_tree: Workflow Guide",
        ":material/help_center: Glossary & Pro-Tips",
        ":material/bug_report: Bug Reports & Ideas",
    ]
    requested = st.session_state.pop("help_hub_requested_tab", "")
    if requested == "feedback":
        st.session_state["help_hub_active_tab_control"] = tab_options[4]
    elif requested == "search":
        st.session_state["help_hub_active_tab_control"] = tab_options[1]

    tab_manual, tab_search, tab_workflow, tab_glossary, tab_feedback = st.tabs(
        tab_options
    )

    with tab_manual:
        _render_page_manual_tab(active_page_key)

    with tab_search:
        _render_global_search_tab(project_id, scenario_id)

    with tab_workflow:
        _render_workflow_guide_tab(
            project_id,
            scenario_id,
            active_page_key=active_page_key,
        )

    with tab_glossary:
        _render_glossary_and_troubleshooting_tab()

    with tab_feedback:
        _render_feedback_tracker_tab(
            project_id=project_id,
            scenario_id=scenario_id,
            active_page_title=active_page_title,
            editor_name=editor_name,
        )


def render_floating_help_button(
    *,
    active_page_key: str,
    active_page_title: str,
    project_id: str | None,
    scenario_id: str | None,
    editor_name: str = "",
) -> None:
    """Render the persistent bottom-right floating Help & Search trigger button."""
    st.html(
        """
        <style>
        /* Reserve safe bottom space so the floating Help button never overlaps Save & Refresh or History */
        .main .block-container {
            padding-bottom: 5rem !important;
        }
        div.st-key-floating_help_hub_container {
            position: fixed !important;
            bottom: 18px !important;
            right: 24px !important;
            z-index: 999990 !important;
            width: auto !important;
        }
        div.st-key-floating_help_hub_container div[data-testid="stButton"] > button {
            border-radius: 999px !important;
            padding: 0.5rem 1.05rem !important;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.22) !important;
            font-weight: 600 !important;
            border: 1px solid rgba(255, 255, 255, 0.25) !important;
        }
        </style>
        """
    )
    open_count = open_app_feedback_count(project_id)
    badge_suffix = f" ({open_count})" if open_count > 0 else ""
    with st.container(key="floating_help_hub_container"):
        if st.button(
            f"Help & search{badge_suffix}",
            icon=":material/help:",
            type="primary",
            key="floating_help_hub_trigger_btn",
            help=(
                f"Open Help Manual for '{active_page_title}', Global Project Search, "
                "Critical Thread Guide, Op ID Decoder, and Bug / Feature Tracker."
            ),
        ):
            open_universal_help_dialog(
                active_page_key=active_page_key,
                active_page_title=active_page_title,
                project_id=project_id,
                scenario_id=scenario_id,
                editor_name=editor_name,
            )
