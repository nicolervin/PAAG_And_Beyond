from __future__ import annotations

import sqlite3
import json
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "paag.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connection():
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, program TEXT DEFAULT '',
                owner TEXT DEFAULT '', revision TEXT DEFAULT 'A', status TEXT DEFAULT 'Draft',
                takt_time_s REAL DEFAULT 60, notes TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS parts (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                part_number TEXT NOT NULL, description TEXT DEFAULT '', quantity REAL DEFAULT 1,
                revision TEXT DEFAULT '', source TEXT DEFAULT 'Manual', image_path TEXT DEFAULT '',
                model_applicability TEXT DEFAULT 'All', notes TEXT DEFAULT '', updated_at TEXT NOT NULL,
                UNIQUE(project_id, part_number)
            );
            CREATE TABLE IF NOT EXISTS work_elements (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL, station TEXT DEFAULT '', operation TEXT NOT NULL,
                description TEXT DEFAULT '', cycle_time_s REAL DEFAULT 0,
                part_number TEXT DEFAULT '', tool TEXT DEFAULT '', torque TEXT DEFAULT '',
                quality_requirement TEXT DEFAULT '', ergo_requirement TEXT DEFAULT '',
                location TEXT DEFAULT '', conveyor_height_mm REAL, platform_height_mm REAL,
                pit_depth_mm REAL, model_applicability TEXT DEFAULT 'All', status TEXT DEFAULT 'Draft',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS concerns (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                category TEXT DEFAULT 'Question', subject TEXT NOT NULL, detail TEXT DEFAULT '',
                owner TEXT DEFAULT '', priority TEXT DEFAULT 'Medium', status TEXT DEFAULT 'Open',
                related_part TEXT DEFAULT '', related_station TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fishbone_nodes (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                source_row INTEGER, sequence INTEGER NOT NULL, parent_id TEXT,
                depth INTEGER DEFAULT 1, part_number TEXT DEFAULT '', description TEXT DEFAULT '',
                quantity REAL DEFAULT 1, branch_name TEXT DEFAULT '', subsystem TEXT DEFAULT '',
                model_feature TEXT DEFAULT '', comments TEXT DEFAULT '', tracker_status TEXT DEFAULT '',
                planned_area TEXT DEFAULT '', source TEXT DEFAULT 'Manual', raw_levels TEXT DEFAULT '{}',
                review_status TEXT DEFAULT 'Confirmed',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS part_images (
                id TEXT PRIMARY KEY, part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                image_path TEXT NOT NULL, image_type TEXT DEFAULT 'Supplemental', caption TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pits_records (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                pits_id TEXT NOT NULL, part_number TEXT DEFAULT '', description TEXT DEFAULT '',
                used_bom TEXT DEFAULT '', status TEXT DEFAULT '', subsystem TEXT DEFAULT '',
                design_maturity TEXT DEFAULT '', comments TEXT DEFAULT '', workstation TEXT DEFAULT '',
                source_payload TEXT NOT NULL, source_hash TEXT NOT NULL, revision_no INTEGER DEFAULT 1,
                first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                UNIQUE(project_id, pits_id)
            );
            CREATE TABLE IF NOT EXISTS pits_record_revisions (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES pits_records(id) ON DELETE CASCADE,
                revision_no INTEGER NOT NULL, source_payload TEXT NOT NULL, imported_at TEXT NOT NULL,
                UNIQUE(record_id, revision_no)
            );
            CREATE TABLE IF NOT EXISTS project_models (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                model_number TEXT NOT NULL, item TEXT DEFAULT '', platform_size TEXT DEFAULT '',
                package_type TEXT DEFAULT '', appearance TEXT DEFAULT '', base_model TEXT DEFAULT '',
                eau REAL, dg_date TEXT, dc_date TEXT, pre_pilot_date TEXT, pilot_date TEXT,
                production_date TEXT, sku_upc TEXT DEFAULT '', evaluate_fishbone TEXT DEFAULT '',
                yamazumi TEXT DEFAULT '', bop_l1 TEXT DEFAULT '', source_payload TEXT NOT NULL,
                updated_at TEXT NOT NULL, display_name TEXT DEFAULT '', description TEXT DEFAULT '',
                active INTEGER DEFAULT 1, notes TEXT DEFAULT '', UNIQUE(project_id, model_number)
            );
            CREATE TABLE IF NOT EXISTS assembly_sections (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL, section_type TEXT NOT NULL DEFAULT 'Main spine', parent_id TEXT,
                sequence INTEGER NOT NULL DEFAULT 10, description TEXT DEFAULT '', active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(project_id, name), FOREIGN KEY(parent_id) REFERENCES assembly_sections(id)
            );
            CREATE TABLE IF NOT EXISTS fishbone_part_assignments (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                section_id TEXT NOT NULL REFERENCES assembly_sections(id), sequence INTEGER NOT NULL DEFAULT 10,
                quantity INTEGER NOT NULL DEFAULT 1, notes TEXT DEFAULT '', updated_at TEXT NOT NULL,
                UNIQUE(project_id, part_id)
            );
            """
        )
        fishbone_columns = {row[1] for row in conn.execute("PRAGMA table_info(fishbone_nodes)").fetchall()}
        if "review_status" not in fishbone_columns:
            conn.execute("ALTER TABLE fishbone_nodes ADD COLUMN review_status TEXT DEFAULT 'Confirmed'")
        for column, definition in {
            "pits_id": "TEXT DEFAULT ''",
            "applicable_models": "TEXT DEFAULT '[]'",
            "source_changed": "INTEGER DEFAULT 0",
        }.items():
            if column not in fishbone_columns:
                conn.execute(f"ALTER TABLE fishbone_nodes ADD COLUMN {column} {definition}")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_fishbone_project_pits_id ON fishbone_nodes(project_id, pits_id) WHERE pits_id IS NOT NULL AND pits_id <> ''"
        )
        model_columns = {row[1] for row in conn.execute("PRAGMA table_info(project_models)").fetchall()}
        for column, definition in {
            "display_name": "TEXT DEFAULT ''",
            "description": "TEXT DEFAULT ''",
            "active": "INTEGER DEFAULT 1",
            "notes": "TEXT DEFAULT ''",
        }.items():
            if column not in model_columns:
                conn.execute(f"ALTER TABLE project_models ADD COLUMN {column} {definition}")
        if conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0:
            timestamp = now_iso()
            project_id = str(uuid4())
            conn.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, "Sample NPI launch", "Next-generation assembly", "Industrial engineering", "A", "Draft", 60, "Replace this sample or create a new project.", timestamp, timestamp),
            )
            sample_parts = [
                ("PN-100100", "Main housing", 1, "A"),
                ("PN-100220", "Support bracket", 1, "B"),
                ("HW-M8-025", "M8 fastener", 4, ""),
            ]
            for pn, desc, qty, rev in sample_parts:
                conn.execute(
                    "INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?, 'Sample', '', 'All', '', ?)",
                    (str(uuid4()), project_id, pn, desc, qty, rev, timestamp),
                )
            sample_steps = [
                (10, "ST-010", "Load housing", "Place housing in locating fixture", 18.0, "PN-100100", "", "", "Confirm seated on all locators", "Two-hand lift review", "Main line / Zone 1", 950, 0, 0),
                (20, "ST-010", "Install bracket", "Locate bracket and hand-start four fasteners", 24.0, "PN-100220", "Nutrunner", "32 N·m ± 3", "Torque trace required", "Keep work below shoulder", "Main line / Zone 1", 950, 100, 0),
                (30, "ST-010", "Verify assembly", "Visual and torque-complete confirmation", 8.0, "HW-M8-025", "Scanner", "", "All four results pass", "", "Main line / Zone 1", 950, 100, 0),
            ]
            for row in sample_steps:
                conn.execute(
                    """INSERT INTO work_elements
                    (id, project_id, sequence, station, operation, description, cycle_time_s,
                     part_number, tool, torque, quality_requirement, ergo_requirement, location,
                     conveyor_height_mm, platform_height_mm, pit_depth_mm, model_applicability, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'All', 'Draft', ?)""",
                    (str(uuid4()), project_id, *row, timestamp),
                )


def query(sql: str, params: tuple = ()) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple = ()) -> None:
    with connection() as conn:
        conn.execute(sql, params)


def projects() -> list[dict]:
    return query("SELECT * FROM projects ORDER BY updated_at DESC")


def get_project(project_id: str) -> dict | None:
    rows = query("SELECT * FROM projects WHERE id = ?", (project_id,))
    return rows[0] if rows else None


def project_table(table: str, project_id: str, order_by: str = "updated_at DESC") -> pd.DataFrame:
    allowed = {"parts", "work_elements", "concerns", "fishbone_nodes", "assembly_sections", "fishbone_part_assignments"}
    if table not in allowed:
        raise ValueError("Unsupported table")
    return pd.DataFrame(query(f"SELECT * FROM {table} WHERE project_id = ? ORDER BY {order_by}", (project_id,)))


def create_project(name: str, program: str, owner: str, takt_time_s: float) -> str:
    project_id, timestamp = str(uuid4()), now_iso()
    execute(
        "INSERT INTO projects VALUES (?, ?, ?, ?, 'A', 'Draft', ?, '', ?, ?)",
        (project_id, name.strip(), program.strip(), owner.strip(), takt_time_s, timestamp, timestamp),
    )
    return project_id


def update_project(project_id: str, values: dict) -> None:
    fields = ["name", "program", "owner", "revision", "status", "takt_time_s", "notes"]
    execute(
        f"UPDATE projects SET {', '.join(f'{field} = ?' for field in fields)}, updated_at = ? WHERE id = ?",
        tuple(values.get(field, "") for field in fields) + (now_iso(), project_id),
    )


def normalize_model_applicability(value) -> str:
    if isinstance(value, (list, tuple, set)):
        selected = [str(item).strip() for item in value if str(item).strip()]
        if not selected or "All" in selected or "All models" in selected:
            return "All"
        return ", ".join(dict.fromkeys(selected))
    text = "" if value is None or pd.isna(value) else str(value).strip()
    return text or "All"


def upsert_part(project_id: str, values: dict, part_id: str | None = None) -> str:
    timestamp = now_iso()
    part_id = part_id or str(uuid4())
    quantity = values.get("quantity", 1)
    quantity = None if quantity is None or pd.isna(quantity) or str(quantity).strip() == "" else float(quantity)
    execute(
        """INSERT INTO parts (id, project_id, part_number, description, quantity, revision, source,
           image_path, model_applicability, notes, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(project_id, part_number) DO UPDATE SET description=excluded.description,
           quantity=excluded.quantity, revision=excluded.revision, source=excluded.source,
           model_applicability=excluded.model_applicability, notes=excluded.notes, updated_at=excluded.updated_at""",
        (part_id, project_id, values["part_number"].strip(), values.get("description", "").strip(),
         quantity, values.get("revision", "").strip(), values.get("source", "Manual"),
         values.get("image_path", ""), normalize_model_applicability(values.get("model_applicability", "All")),
         values.get("notes", "").strip(), timestamp),
    )
    rows = query("SELECT id FROM parts WHERE project_id = ? AND part_number = ?", (project_id, values["part_number"].strip()))
    return rows[0]["id"]


def update_part_rows(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "part_number", "description", "quantity", "revision", "model_applicability", "notes"}
    if not required.issubset(edited.columns):
        raise ValueError("The editable parts table is missing required columns.")
    part_numbers = edited["part_number"].fillna("").astype(str).str.strip()
    if part_numbers.eq("").any():
        raise ValueError("Every part must have a part number.")
    if part_numbers.duplicated().any():
        duplicates = ", ".join(sorted(part_numbers[part_numbers.duplicated(keep=False)].unique()))
        raise ValueError(f"Duplicate part numbers are not allowed: {duplicates}")
    def clean_text(value) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    timestamp = now_iso()
    with connection() as conn:
        for _, row in edited.iterrows():
            quantity = row.get("quantity")
            quantity = None if quantity is None or pd.isna(quantity) else float(quantity)
            conn.execute(
                """UPDATE parts SET part_number=?, description=?, quantity=?, revision=?,
                   model_applicability=?, notes=?, updated_at=? WHERE id=? AND project_id=?""",
                (str(row["part_number"]).strip(), clean_text(row.get("description")), quantity,
                 clean_text(row.get("revision")), normalize_model_applicability(row.get("model_applicability")),
                 clean_text(row.get("notes")), timestamp, str(row["id"]), project_id),
            )
    return len(edited)


def set_part_image(part_id: str, uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    target = UPLOAD_DIR / f"{part_id}{suffix}"
    target.write_bytes(uploaded_file.getvalue())
    execute("UPDATE parts SET image_path = ?, updated_at = ? WHERE id = ?", (str(target), now_iso(), part_id))
    return str(target)


def add_part_image(part_id: str, uploaded_file, image_type: str, caption: str) -> str:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    image_id = str(uuid4())
    target = UPLOAD_DIR / f"{part_id}_{image_id}{suffix}"
    target.write_bytes(uploaded_file.getvalue())
    execute(
        "INSERT INTO part_images VALUES (?, ?, ?, ?, ?, ?)",
        (image_id, part_id, str(target), image_type, caption.strip(), now_iso()),
    )
    return str(target)


def part_images(part_id: str) -> list[dict]:
    return query("SELECT * FROM part_images WHERE part_id = ? ORDER BY created_at", (part_id,))


def assembly_sections(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        "SELECT * FROM assembly_sections WHERE project_id = ? ORDER BY sequence, name",
        (project_id,),
    ))


def add_assembly_section(
    project_id: str,
    name: str,
    section_type: str,
    parent_id: str | None,
    description: str,
) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Section or subassembly name is required.")
    if section_type not in {"Main spine", "Subassembly"}:
        raise ValueError("Choose Main spine or Subassembly.")
    parent_id = parent_id or None
    if section_type == "Subassembly" and not parent_id:
        raise ValueError("A subassembly must have a parent assembly.")
    if section_type == "Main spine":
        parent_id = None
    timestamp = now_iso()
    section_id = str(uuid4())
    try:
        with connection() as conn:
            next_sequence = conn.execute(
                """SELECT COALESCE(MAX(sequence), 0) + 10 FROM assembly_sections
                   WHERE project_id=? AND parent_id IS ?""",
                (project_id, parent_id),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, parent_id, sequence, description, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (section_id, project_id, name, section_type, parent_id, next_sequence, description.strip(), timestamp, timestamp),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"A section named {name} already exists in this project.") from exc
    return section_id


def reorder_assembly_section(project_id: str, section_id: str, action: str) -> bool:
    allowed = {"Move earlier", "Move later", "Move to start", "Move to end"}
    if action not in allowed:
        raise ValueError("Unsupported framework reorder action.")
    with connection() as conn:
        target = conn.execute(
            "SELECT id, parent_id FROM assembly_sections WHERE id=? AND project_id=?",
            (section_id, project_id),
        ).fetchone()
        if not target:
            raise ValueError("The selected framework item no longer exists.")
        siblings = conn.execute(
            """SELECT id FROM assembly_sections WHERE project_id=? AND parent_id IS ?
               ORDER BY sequence, name""",
            (project_id, target["parent_id"]),
        ).fetchall()
        ordered_ids = [row["id"] for row in siblings]
        old_index = ordered_ids.index(section_id)
        new_index = old_index
        if action == "Move earlier":
            new_index = max(0, old_index - 1)
        elif action == "Move later":
            new_index = min(len(ordered_ids) - 1, old_index + 1)
        elif action == "Move to start":
            new_index = 0
        elif action == "Move to end":
            new_index = len(ordered_ids) - 1
        ordered_ids.insert(new_index, ordered_ids.pop(old_index))
        timestamp = now_iso()
        for index, sibling_id in enumerate(ordered_ids, start=1):
            conn.execute(
                "UPDATE assembly_sections SET sequence=?, updated_at=? WHERE id=?",
                (index * 10, timestamp, sibling_id),
            )
    return new_index != old_index


def update_assembly_section_rows(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "name", "section_type", "parent_id", "sequence", "description", "active"}
    if not required.issubset(edited.columns):
        raise ValueError("The assembly framework table is missing required columns.")
    records = edited.to_dict("records")
    ids = {str(row["id"]) for row in records}
    names = [str(row.get("name") or "").strip() for row in records]
    if any(not name for name in names):
        raise ValueError("Every framework row needs a name.")
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Framework names must be unique within the project.")

    parent_by_id: dict[str, str | None] = {}
    for row in records:
        section_id = str(row["id"])
        section_type = str(row.get("section_type") or "")
        parent_id = row.get("parent_id")
        parent_id = None if parent_id is None or pd.isna(parent_id) or not str(parent_id).strip() else str(parent_id)
        if section_type not in {"Main spine", "Subassembly"}:
            raise ValueError("Each framework row must be Main spine or Subassembly.")
        if section_type == "Main spine":
            parent_id = None
        elif not parent_id:
            raise ValueError(f"Subassembly {row['name']} needs a parent assembly.")
        if parent_id == section_id or (parent_id and parent_id not in ids):
            raise ValueError(f"Choose a valid parent for {row['name']}.")
        parent_by_id[section_id] = parent_id

    for section_id in ids:
        visited: set[str] = set()
        cursor = section_id
        while cursor:
            if cursor in visited:
                raise ValueError("The assembly framework cannot contain a circular parent relationship.")
            visited.add(cursor)
            cursor = parent_by_id.get(cursor)

    timestamp = now_iso()
    try:
        with connection() as conn:
            for row in records:
                section_id = str(row["id"])
                conn.execute(
                    """UPDATE assembly_sections SET name=?, section_type=?, parent_id=?, sequence=?,
                       description=?, active=?, updated_at=? WHERE id=? AND project_id=?""",
                    (
                        str(row["name"]).strip(), str(row["section_type"]), parent_by_id[section_id],
                        int(row.get("sequence") or 0), str(row.get("description") or "").strip(),
                        1 if bool(row.get("active")) else 0, timestamp, section_id, project_id,
                    ),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Framework names must be unique within the project.") from exc
    return len(records)


def fishbone_part_assignments(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT a.id, a.project_id, a.part_id, a.section_id, a.sequence, a.quantity, a.notes,
                  a.updated_at, p.part_number, p.description, p.revision, p.model_applicability,
                  s.name AS section_name
           FROM fishbone_part_assignments a
           JOIN parts p ON p.id = a.part_id
           JOIN assembly_sections s ON s.id = a.section_id
           WHERE a.project_id = ? ORDER BY s.sequence, a.sequence, p.part_number""",
        (project_id,),
    ))


def assign_parts_to_section(project_id: str, part_ids: list[str], section_id: str) -> int:
    if not part_ids:
        return 0
    timestamp = now_iso()
    count = 0
    with connection() as conn:
        section = conn.execute(
            "SELECT id FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
            (section_id, project_id),
        ).fetchone()
        if not section:
            raise ValueError("Choose an active assembly section.")
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM fishbone_part_assignments WHERE project_id=? AND section_id=?",
            (project_id, section_id),
        ).fetchone()[0]
        for part_id in dict.fromkeys(part_ids):
            part = conn.execute("SELECT quantity FROM parts WHERE id=? AND project_id=?", (part_id, project_id)).fetchone()
            if not part:
                continue
            next_sequence += 10
            quantity = max(0, int(round(part["quantity"] if part["quantity"] is not None else 1)))
            assignment_id = str(uuid4())
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, '', ?)
                   ON CONFLICT(project_id, part_id) DO UPDATE SET section_id=excluded.section_id,
                   sequence=excluded.sequence, updated_at=excluded.updated_at""",
                (assignment_id, project_id, part_id, section_id, next_sequence, quantity, timestamp),
            )
            count += 1
    return count


def replace_fishbone_part_assignments(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "part_id", "section_id", "sequence", "quantity", "notes"}
    if not required.issubset(edited.columns):
        raise ValueError("The part assignment table is missing required columns.")
    if edited["part_id"].astype(str).duplicated().any():
        raise ValueError("A part can appear only once in the current fishbone framework.")
    timestamp = now_iso()
    with connection() as conn:
        valid_parts = {row[0] for row in conn.execute("SELECT id FROM parts WHERE project_id=?", (project_id,))}
        valid_sections = {row[0] for row in conn.execute("SELECT id FROM assembly_sections WHERE project_id=?", (project_id,))}
        records = []
        for _, row in edited.iterrows():
            part_id, section_id = str(row["part_id"]), str(row["section_id"])
            if part_id not in valid_parts or section_id not in valid_sections:
                raise ValueError("Every assignment must reference a valid project part and assembly section.")
            quantity = float(row.get("quantity") or 0)
            if not quantity.is_integer():
                raise ValueError("Fishbone quantities must be whole numbers.")
            records.append((
                str(row.get("id") or uuid4()), project_id, part_id, section_id,
                int(row.get("sequence") or 0), int(quantity), str(row.get("notes") or "").strip(), timestamp,
            ))
        conn.execute("DELETE FROM fishbone_part_assignments WHERE project_id=?", (project_id,))
        conn.executemany(
            "INSERT INTO fishbone_part_assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )
    return len(records)


def replace_fishbone_nodes(project_id: str, edited: pd.DataFrame) -> None:
    fields = ["source_row", "sequence", "parent_id", "depth", "part_number", "description", "quantity",
              "branch_name", "subsystem", "model_feature", "comments", "tracker_status", "planned_area", "source", "raw_levels", "review_status",
              "pits_id", "applicable_models", "source_changed"]
    with connection() as conn:
        conn.execute("DELETE FROM fishbone_nodes WHERE project_id = ?", (project_id,))
        for idx, row in edited.iterrows():
            part_number = "" if pd.isna(row.get("part_number", "")) else str(row.get("part_number", "")).strip()
            description = "" if pd.isna(row.get("description", "")) else str(row.get("description", "")).strip()
            if not part_number and not description:
                continue
            values = []
            for field in fields:
                value = row.get(field, "")
                if field == "applicable_models" and isinstance(value, (list, tuple, set)):
                    value = json.dumps(list(value))
                if pd.isna(value):
                    value = None if field in {"source_row", "parent_id", "quantity"} else (1 if field == "depth" else (0 if field == "source_changed" else ""))
                values.append(value)
            node_id = str(row.get("id")) if row.get("id") and not pd.isna(row.get("id")) else str(uuid4())
            conn.execute(
                f"INSERT INTO fishbone_nodes (id, project_id, {', '.join(fields)}, updated_at) VALUES ({', '.join(['?'] * (len(fields) + 3))})",
                (node_id, project_id, *values, now_iso()),
            )


def import_fishbone_nodes(project_id: str, nodes: pd.DataFrame, replace: bool = True) -> int:
    timestamp = now_iso()
    with connection() as conn:
        if replace:
            conn.execute("DELETE FROM fishbone_nodes WHERE project_id = ?", (project_id,))
        id_by_sequence: dict[int, str] = {}
        for _, row in nodes.iterrows():
            node_id = str(uuid4())
            parent_sequence = row.get("parent_sequence")
            parent_id = id_by_sequence.get(int(parent_sequence)) if pd.notna(parent_sequence) else None
            sequence = int(row["sequence"])
            id_by_sequence[sequence] = node_id
            conn.execute(
                """INSERT INTO fishbone_nodes
                (id, project_id, source_row, sequence, parent_id, depth, part_number, description,
                 quantity, branch_name, subsystem, model_feature, comments, tracker_status,
                 planned_area, source, raw_levels, review_status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PITS import', ?, 'Needs review', ?)""",
                (node_id, project_id, int(row["source_row"]), sequence, parent_id, int(row["depth"]),
                 row["part_number"], row["description"], None, row["branch_name"],
                 row["subsystem"], row["model_feature"], row["comments"], row["tracker_status"],
                 row["planned_area"], json.dumps(row["raw_levels"], ensure_ascii=False), timestamp),
            )
    return len(nodes)


def project_models(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query("SELECT * FROM project_models WHERE project_id = ? ORDER BY model_number", (project_id,)))


def add_project_model(project_id: str, model_number: str, display_name: str, description: str) -> str:
    model_number = model_number.strip()
    if not model_number:
        raise ValueError("Model number is required.")
    existing = query(
        "SELECT id FROM project_models WHERE project_id = ? AND model_number = ?",
        (project_id, model_number),
    )
    timestamp = now_iso()
    if existing:
        execute(
            "UPDATE project_models SET display_name=?, description=?, active=1, updated_at=? WHERE id=?",
            (display_name.strip(), description.strip(), timestamp, existing[0]["id"]),
        )
        return existing[0]["id"]
    model_id = str(uuid4())
    execute(
        """INSERT INTO project_models
           (id, project_id, model_number, source_payload, updated_at, display_name, description, active)
           VALUES (?, ?, ?, '{}', ?, ?, ?, 1)""",
        (model_id, project_id, model_number, timestamp, display_name.strip(), description.strip()),
    )
    return model_id


def update_project_model_rows(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "display_name", "description", "active", "notes"}
    if not required.issubset(edited.columns):
        raise ValueError("The editable model table is missing required columns.")

    def clean_text(value) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    timestamp = now_iso()
    with connection() as conn:
        for _, row in edited.iterrows():
            conn.execute(
                """UPDATE project_models
                   SET display_name=?, description=?, active=?, notes=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    clean_text(row.get("display_name")),
                    clean_text(row.get("description")),
                    1 if bool(row.get("active")) else 0,
                    clean_text(row.get("notes")),
                    timestamp,
                    str(row["id"]),
                    project_id,
                ),
            )
    return len(edited)


def pits_records(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query("SELECT * FROM pits_records WHERE project_id = ? ORDER BY CAST(pits_id AS INTEGER), pits_id", (project_id,)))


def pits_revisions(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT p.pits_id, r.revision_no, r.imported_at, r.source_payload
           FROM pits_record_revisions r JOIN pits_records p ON p.id = r.record_id
           WHERE p.project_id = ? ORDER BY CAST(p.pits_id AS INTEGER), p.pits_id, r.revision_no""",
        (project_id,),
    ))


def import_pits_id_snapshot(project_id: str, records: list[dict], models: list[dict]) -> dict[str, int]:
    timestamp = now_iso()
    summary = {"new": 0, "changed": 0, "unchanged": 0, "models": 0}
    with connection() as conn:
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM fishbone_nodes WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        for record in records:
            pits_id = str(record["pits_id"]).strip()
            payload = json.dumps(record["source_payload"], sort_keys=True, ensure_ascii=False, default=str)
            source_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            existing = conn.execute(
                "SELECT * FROM pits_records WHERE project_id = ? AND pits_id = ?", (project_id, pits_id)
            ).fetchone()
            if existing is None:
                record_id = str(uuid4())
                revision = 1
                conn.execute(
                    """INSERT INTO pits_records
                    (id, project_id, pits_id, part_number, description, used_bom, status, subsystem,
                     design_maturity, comments, workstation, source_payload, source_hash, revision_no,
                     first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (record_id, project_id, pits_id, record["part_number"], record["description"], record["used_bom"],
                     record["status"], record["subsystem"], record["design_maturity"], record["comments"],
                     record["workstation"], payload, source_hash, revision, timestamp, timestamp),
                )
                conn.execute(
                    "INSERT INTO pits_record_revisions VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), record_id, revision, payload, timestamp),
                )
                next_sequence += 1
                conn.execute(
                    """INSERT INTO fishbone_nodes
                    (id, project_id, source_row, sequence, parent_id, depth, part_number, description, quantity,
                     branch_name, subsystem, model_feature, comments, tracker_status, planned_area, source,
                     raw_levels, review_status, updated_at, pits_id, applicable_models, source_changed)
                    VALUES (?, ?, ?, ?, NULL, 1, ?, ?, NULL, '', ?, '', ?, ?, ?, 'PITS tracker', ?, 'Needs review', ?, ?, '[]', 0)""",
                    (str(uuid4()), project_id, record["source_row"], next_sequence, record["part_number"],
                     record["description"], record["subsystem"], record["comments"], record["status"],
                     record["workstation"], payload, timestamp, pits_id),
                )
                summary["new"] += 1
            elif existing["source_hash"] != source_hash:
                revision = int(existing["revision_no"]) + 1
                conn.execute(
                    """UPDATE pits_records SET part_number=?, description=?, used_bom=?, status=?, subsystem=?,
                       design_maturity=?, comments=?, workstation=?, source_payload=?, source_hash=?, revision_no=?,
                       last_seen_at=? WHERE id=?""",
                    (record["part_number"], record["description"], record["used_bom"], record["status"],
                     record["subsystem"], record["design_maturity"], record["comments"], record["workstation"],
                     payload, source_hash, revision, timestamp, existing["id"]),
                )
                conn.execute(
                    "INSERT INTO pits_record_revisions VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), existing["id"], revision, payload, timestamp),
                )
                conn.execute(
                    "UPDATE fishbone_nodes SET source_changed=1, updated_at=? WHERE project_id=? AND pits_id=?",
                    (timestamp, project_id, pits_id),
                )
                summary["changed"] += 1
            else:
                conn.execute("UPDATE pits_records SET last_seen_at=? WHERE id=?", (timestamp, existing["id"]))
                summary["unchanged"] += 1

        for model in models:
            payload = json.dumps(model["source_payload"], sort_keys=True, ensure_ascii=False, default=str)
            existing = conn.execute(
                "SELECT id FROM project_models WHERE project_id=? AND model_number=?",
                (project_id, model["model_number"]),
            ).fetchone()
            model_id = existing["id"] if existing else str(uuid4())
            conn.execute(
                """INSERT INTO project_models
                (id, project_id, model_number, item, platform_size, package_type, appearance, base_model,
                 eau, dg_date, dc_date, pre_pilot_date, pilot_date, production_date, sku_upc,
                 evaluate_fishbone, yamazumi, bop_l1, source_payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, model_number) DO UPDATE SET item=excluded.item,
                 platform_size=excluded.platform_size, package_type=excluded.package_type,
                 appearance=excluded.appearance, base_model=excluded.base_model, eau=excluded.eau,
                 dg_date=excluded.dg_date, dc_date=excluded.dc_date, pre_pilot_date=excluded.pre_pilot_date,
                 pilot_date=excluded.pilot_date, production_date=excluded.production_date,
                 sku_upc=excluded.sku_upc, evaluate_fishbone=excluded.evaluate_fishbone,
                 yamazumi=excluded.yamazumi, bop_l1=excluded.bop_l1,
                 source_payload=excluded.source_payload, updated_at=excluded.updated_at""",
                (model_id, project_id, model["model_number"], model["item"], model["platform_size"],
                 model["package_type"], model["appearance"], model["base_model"], model["eau"],
                 model["dg_date"], model["dc_date"], model["pre_pilot_date"], model["pilot_date"],
                 model["production_date"], model["sku_upc"], model["evaluate_fishbone"],
                 model["yamazumi"], model["bop_l1"], payload, timestamp),
            )
            summary["models"] += 1
    return summary


def apply_pits_updates(project_id: str, pits_ids: list[str]) -> int:
    if not pits_ids:
        return 0
    placeholders = ",".join("?" for _ in pits_ids)
    timestamp = now_iso()
    with connection() as conn:
        cursor = conn.execute(
            f"""UPDATE fishbone_nodes
                SET part_number=(SELECT part_number FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    description=(SELECT description FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    subsystem=(SELECT subsystem FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    comments=(SELECT comments FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    planned_area=(SELECT workstation FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    raw_levels=(SELECT source_payload FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    source_changed=0, review_status='Needs review', updated_at=?
                WHERE project_id=? AND pits_id IN ({placeholders})""",
            (timestamp, project_id, *pits_ids),
        )
        return cursor.rowcount


def set_mbom_review_status(project_id: str, node_ids: list[str], status: str) -> int:
    allowed = {"Needs review", "Confirmed", "Excluded"}
    if status not in allowed:
        raise ValueError("Unsupported MBOM review status")
    if not node_ids:
        return 0
    placeholders = ",".join("?" for _ in node_ids)
    with connection() as conn:
        cursor = conn.execute(
            f"UPDATE fishbone_nodes SET review_status=?, updated_at=? WHERE project_id=? AND id IN ({placeholders})",
            (status, now_iso(), project_id, *node_ids),
        )
        return cursor.rowcount


def sync_confirmed_mbom_parts(project_id: str) -> int:
    confirmed = query(
        """SELECT part_number, MAX(description) AS description, MAX(quantity) AS quantity,
                  MAX(applicable_models) AS applicable_models, MAX(comments) AS comments
           FROM fishbone_nodes
           WHERE project_id = ? AND review_status = 'Confirmed' AND TRIM(part_number) <> ''
           GROUP BY part_number""",
        (project_id,),
    )
    for row in confirmed:
        try:
            assigned_models = json.loads(row["applicable_models"] or "[]")
        except (TypeError, json.JSONDecodeError):
            assigned_models = []
        upsert_part(
            project_id,
            {
                "part_number": row["part_number"],
                "description": row["description"] or "",
                "quantity": row["quantity"],
                "source": "Confirmed MBOM",
                "model_applicability": ", ".join(assigned_models) if assigned_models else "All",
                "notes": row["comments"] or "",
            },
        )
    return len(confirmed)


def replace_work_elements(project_id: str, edited: pd.DataFrame) -> None:
    fields = ["sequence", "station", "operation", "description", "cycle_time_s", "part_number", "tool", "torque",
              "quality_requirement", "ergo_requirement", "location", "conveyor_height_mm", "platform_height_mm",
              "pit_depth_mm", "model_applicability", "status"]
    with connection() as conn:
        conn.execute("DELETE FROM work_elements WHERE project_id = ?", (project_id,))
        for idx, row in edited.iterrows():
            if not str(row.get("operation", "")).strip():
                continue
            values = []
            for field in fields:
                value = row.get(field, "")
                if pd.isna(value):
                    value = None if field.endswith("_mm") else (0 if field in {"sequence", "cycle_time_s"} else "")
                values.append(value)
            conn.execute(
                f"INSERT INTO work_elements (id, project_id, {', '.join(fields)}, updated_at) VALUES ({', '.join(['?'] * (len(fields) + 3))})",
                (str(row.get("id")) if row.get("id") and not pd.isna(row.get("id")) else str(uuid4()), project_id, *values, now_iso()),
            )


def replace_concerns(project_id: str, edited: pd.DataFrame) -> None:
    fields = ["category", "subject", "detail", "owner", "priority", "status", "related_part", "related_station"]
    with connection() as conn:
        conn.execute("DELETE FROM concerns WHERE project_id = ?", (project_id,))
        for _, row in edited.iterrows():
            if not str(row.get("subject", "")).strip():
                continue
            timestamp = now_iso()
            values = ["" if pd.isna(row.get(field, "")) else row.get(field, "") for field in fields]
            conn.execute(
                f"INSERT INTO concerns (id, project_id, {', '.join(fields)}, created_at, updated_at) VALUES ({', '.join(['?'] * (len(fields) + 4))})",
                (str(row.get("id")) if row.get("id") and not pd.isna(row.get("id")) else str(uuid4()), project_id, *values,
                 str(row.get("created_at")) if row.get("created_at") and not pd.isna(row.get("created_at")) else timestamp, timestamp),
            )
