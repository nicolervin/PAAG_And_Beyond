"""Static guidance displayed by the Import/Export Projects page help dialog."""

EXCHANGE_HELP_SECTIONS = (
    (
        "Overview",
        """
The **Import/Export Projects** page lets you backup, share, or restore complete PAAG projects between environments or local installations.

- **Export Project** creates a single portable `.paagproject` archive file containing all project settings, planning scenarios, database records, and uploaded files/photos.
- **Import Project** lets you load a `.paagproject` archive file to create a brand new project or replace an existing project.
""",
    ),
    (
        "How to Export a Project",
        """
1. Navigate to **Import/Export Projects**.
2. Click the **Export Project** button.
3. Once prepared, click **Download project package** to save the `.paagproject` file to your computer.
""",
    ),
    (
        "How to Import a Project (Step-by-Step)",
        """
Follow these 4 simple steps to import a `.paagproject` file:

### Step 1: Upload the Package
- Drag and drop or browse for your `.paagproject` file in the **PAAG project package** file uploader.
- Once uploaded, PAAG validates the package integrity and displays preview summary tables:
  - **Included scenarios**: Planning scenarios contained in the file.
  - **Per-table record counts**: Database tables and row counts.
  - **Included uploads**: File attachments and photos.

> [!NOTE]
> All scenarios, database records, and uploads listed in the package previews will be imported into your new project. The preview tables are for review only; you do **not** need to select individual rows inside the tables.

---

### Step 2: Select Your Target Operation (Required)
> [!IMPORTANT]
> **You MUST select a Target Operation below the preview tables to proceed!**
> The **Continue** button will remain disabled until you make a selection.

Scroll down below the preview tables to **Target operation** and select your choice:
- Click **Create new** (Recommended) to import the dataset as a brand-new project.
- Click **Replace an existing project** if you intentionally want to overwrite an existing project's data (and select the target project from the dropdown).

---

### Step 3: Click Continue
- Once **Target operation** is selected, the **Continue** (`→ Continue`) button at the bottom of the card becomes active.
- Click **Continue**.

---

### Step 4: Finalize in the Confirmation Modal
- A pop-up dialog will appear titled **Create imported project?** (or **Replace existing project?**).
- Click **Create new project** (or **Replace project**) inside the pop-up modal to execute the import.
- All internal IDs will be automatically remapped, and PAAG will automatically switch your active workspace session to the newly imported project!
""",
    ),
)

EXCHANGE_HELP = "\n\n".join(
    f"### {title}\n{content}" for title, content in EXCHANGE_HELP_SECTIONS
)

