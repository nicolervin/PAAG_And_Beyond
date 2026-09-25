"""Build portable, project-complete PAAG export packages."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from utils import store


PACKAGE_VERSION = 1
PACKAGE_EXTENSION = ".paagproject"
AUDIT_CATEGORY = "Project transfer"


@dataclass(frozen=True)
class TransferTable:
    name: str
    parent_table: str | None = None
    foreign_key: str | None = None
    parent_key: str = "id"


# Topological registry. Tables with project_id are scoped directly; the four
# child-only tables use their declared ownership edge.
PROJECT_TRANSFER_TABLES = (
    TransferTable("projects"), TransferTable("planning_scenarios"),
    TransferTable("parts"), TransferTable("part_scenario_activity"),
    TransferTable("work_elements"), TransferTable("concerns"),
    TransferTable("fishbone_nodes"),
    TransferTable("pits_bom_imports"),
    TransferTable("part_images", "parts", "part_id"),
    TransferTable("pits_records"),
    TransferTable("pits_record_revisions", "pits_records", "record_id"),
    TransferTable("project_models"), TransferTable("complexity_features"),
    TransferTable("model_feature_values"), TransferTable("part_feature_rules"),
    TransferTable("assembly_sections"), TransferTable("fishbone_part_assignments"),
    TransferTable("pits_bom_occurrences"),
    TransferTable(
        "pits_bom_occurrence_revisions", "pits_bom_occurrences", "occurrence_id"
    ),
    TransferTable("pits_bom_occurrence_concerns"),
    TransferTable("audit_log"), TransferTable("yamazumi_areas"),
    TransferTable("yamazumi_pitches"), TransferTable("yamazumi_elements"),
    TransferTable("yamazumi_work_regions"),
    TransferTable("manufacturing_assemblies"),
    TransferTable("manufacturing_assembly_components"),
    TransferTable("manufacturing_assembly_feature_rules"),
    TransferTable("manufacturing_assembly_images"),
    TransferTable("assembly_grid_categories"),
    TransferTable("assembly_grid_model_mappings"),
    TransferTable("assembly_grid_feature_visibility"),
    TransferTable("assembly_scenario_policies"),
    TransferTable("work_element_material_groups"),
    TransferTable("work_element_material_options", "work_element_material_groups", "group_id"),
    TransferTable("process_part_groups"),
    TransferTable("process_part_options", "process_part_groups", "group_id"),
    TransferTable("ergonomic_hazard_options"), TransferTable("ergonomics_reviews"),
    TransferTable("ergonomics_review_hazard_selections"),
    TransferTable("quality_requirements"), TransferTable("quality_requirement_assignments"),
    TransferTable("quality_requirement_torque_details"), TransferTable("quality_requirement_types"),
    TransferTable("pfmea_entries"), TransferTable("pfmea_effects"),
    TransferTable("pfmea_causes"), TransferTable("pfmea_risk_rows"),
    TransferTable("pfmea_actions"), TransferTable("pfmea_prevention_options"),
    TransferTable("pfmea_detection_options"), TransferTable("pfmea_prevention_selections"),
    TransferTable("pfmea_detection_selections"), TransferTable("control_plan_items"),
    TransferTable("project_transfer_events"),
)


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _registered_rows(
    conn: sqlite3.Connection, project_id: str
) -> tuple[dict[str, list[dict]], dict[str, int]]:
    existing = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    registered = {item.name for item in PROJECT_TRANSFER_TABLES}
    unregistered = existing - registered
    missing = {
        table
        for table in unregistered
        if conn.execute(f'SELECT EXISTS(SELECT 1 FROM "{table}" LIMIT 1)').fetchone()[0]
    }
    unavailable = registered - existing
    if missing:
        raise ValueError(
            "The project package registry is incomplete for these tables: "
            + ", ".join(sorted(missing))
        )
    if unavailable:
        raise ValueError(
            "The local database is missing registered project tables: "
            + ", ".join(sorted(unavailable))
        )

    tables: dict[str, list[dict]] = {}
    for item in PROJECT_TRANSFER_TABLES:
        columns = _table_columns(conn, item.name)
        if item.name == "projects":
            rows = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchall()
        elif "project_id" in columns:
            rows = conn.execute(
                f'SELECT * FROM "{item.name}" WHERE project_id=?', (project_id,)
            ).fetchall()
        else:
            parent_rows = tables.get(str(item.parent_table), [])
            parent_values = {
                row.get(item.parent_key) for row in parent_rows if row.get(item.parent_key) is not None
            }
            if not parent_values:
                rows = []
            else:
                placeholders = ",".join("?" for _ in parent_values)
                rows = conn.execute(
                    f'SELECT * FROM "{item.name}" WHERE "{item.foreign_key}" IN ({placeholders})',
                    tuple(parent_values),
                ).fetchall()
        tables[item.name] = [dict(row) for row in rows]
    if not tables["projects"]:
        raise ValueError("The current project no longer exists.")
    return tables, {name: len(rows) for name, rows in tables.items()}


def _upload_manifest(tables: dict[str, list[dict]]) -> list[dict]:
    upload_root = store.UPLOAD_DIR.resolve()
    uploads: dict[str, dict] = {}
    for rows in tables.values():
        for row in rows:
            for column, value in row.items():
                if not column.endswith("_path") or not str(value or "").strip():
                    continue
                path = Path(str(value)).resolve()
                if not path.is_file() or upload_root not in path.parents:
                    continue
                relative = path.relative_to(upload_root).as_posix()
                content = path.read_bytes()
                uploads[str(path)] = {
                    "database_path": str(value),
                    "archive_path": f"uploads/{relative}",
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "source_path": path,
                }
    return list(uploads.values())


def export_project_package(project_id: str, editor_name: str = "") -> dict:
    """Create a complete archive and atomically record both export audit rows."""
    with store.connection() as conn:
        tables, record_counts = _registered_rows(conn, project_id)
        project = tables["projects"][0]
        uploads = _upload_manifest(tables)
        manifest = {
            "format": "PAAG project package",
            "package_version": PACKAGE_VERSION,
            "created_at": store.now_iso(),
            "source_project": {"id": project_id, "name": str(project.get("name") or "")},
            "record_counts": record_counts,
            "uploads": [
                {key: value for key, value in upload.items() if key != "source_path"}
                for upload in uploads
            ],
        }
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
            archive.writestr(
                "records.json", json.dumps(tables, ensure_ascii=False, separators=(",", ":"))
            )
            for upload in uploads:
                archive.write(upload["source_path"], upload["archive_path"])

        conn.execute(
            """INSERT INTO project_transfer_events
               (id, project_id, operation, package_version, manifest_json,
                source_project_id, source_project_name, target_project_id,
                target_project_name, record_counts_json, conflicts_json,
                editor_name, created_at)
               VALUES (?, ?, 'Export', ?, ?, ?, ?, NULL, '', ?, '[]', ?, ?)""",
            (
                str(uuid4()), project_id, PACKAGE_VERSION,
                json.dumps(manifest, ensure_ascii=False), project_id,
                str(project.get("name") or ""), json.dumps(record_counts),
                str(editor_name or "").strip(), manifest["created_at"],
            ),
        )
        store.record_audit_event(
            project_id, AUDIT_CATEGORY, "Export Project", sum(record_counts.values()),
            editor_name,
            {"package_version": PACKAGE_VERSION, "record_counts": record_counts,
             "upload_count": len(uploads)},
            _conn=conn,
        )

    safe_name = "".join(
        char if char.isalnum() or char in "-_" else "_"
        for char in str(project.get("name") or "project")
    ).strip("_") or "project"
    return {
        "data": buffer.getvalue(),
        "file_name": f"{safe_name}{PACKAGE_EXTENSION}",
        "manifest": manifest,
    }


def preview_project_package(package_data: bytes) -> dict:
    """Validate an exported package completely without writing local state."""
    if not package_data:
        raise ValueError("Choose a non-empty PAAG project package.")
    try:
        with ZipFile(BytesIO(package_data)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("The project package contains duplicate archive entries.")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("The project package contains an unsafe archive path.")
            if "manifest.json" not in names or "records.json" not in names:
                raise ValueError("The project package is missing its manifest or records file.")
            try:
                manifest = json.loads(archive.read("manifest.json"))
                tables = json.loads(archive.read("records.json"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError("The project package manifest or records file is invalid.") from exc

            if not isinstance(manifest, dict) or manifest.get("format") != "PAAG project package":
                raise ValueError("This file is not a PAAG project package.")
            if manifest.get("package_version") != PACKAGE_VERSION:
                raise ValueError(
                    f"Package version {manifest.get('package_version')} is not supported. "
                    f"This installation supports version {PACKAGE_VERSION}."
                )
            if not isinstance(tables, dict):
                raise ValueError("The project package records must be grouped by table.")
            registered = {item.name for item in PROJECT_TRANSFER_TABLES}
            if set(tables) != registered:
                missing = registered - set(tables)
                extra = set(tables) - registered
                details = []
                if missing:
                    details.append("missing " + ", ".join(sorted(missing)))
                if extra:
                    details.append("unregistered " + ", ".join(sorted(extra)))
                raise ValueError("The project package table registry is invalid: " + "; ".join(details))

            with store.connection() as conn:
                for item in PROJECT_TRANSFER_TABLES:
                    rows = tables[item.name]
                    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                        raise ValueError(f"Table {item.name} does not contain a valid row list.")
                    expected_columns = set(_table_columns(conn, item.name))
                    for row in rows:
                        if set(row) != expected_columns:
                            raise ValueError(
                                f"Table {item.name} does not match the registered local schema."
                            )

            record_counts = manifest.get("record_counts")
            actual_counts = {name: len(rows) for name, rows in tables.items()}
            if not isinstance(record_counts, dict) or record_counts != actual_counts:
                raise ValueError("The project package record counts do not match its contents.")
            source_project = manifest.get("source_project")
            if not isinstance(source_project, dict) or not str(source_project.get("id") or ""):
                raise ValueError("The project package source-project identity is missing.")
            project_rows = tables["projects"]
            if len(project_rows) != 1 or str(project_rows[0].get("id")) != str(source_project["id"]):
                raise ValueError("The project package must contain exactly its declared source project.")
            source_id = str(source_project["id"])
            for name, rows in tables.items():
                for row in rows:
                    if "project_id" in row and str(row["project_id"]) != source_id:
                        raise ValueError(f"Table {name} contains records from another project.")

            uploads = manifest.get("uploads")
            if not isinstance(uploads, list) or any(not isinstance(item, dict) for item in uploads):
                raise ValueError("The project package upload manifest is invalid.")
            expected_archive_names = {"manifest.json", "records.json"}
            for upload in uploads:
                archive_path = str(upload.get("archive_path") or "")
                path = PurePosixPath(archive_path)
                if not archive_path or path.is_absolute() or ".." in path.parts or path.parts[0] != "uploads":
                    raise ValueError("The project package contains an unsafe upload path.")
                if archive_path not in names:
                    raise ValueError(f"The project package is missing upload {archive_path}.")
                content = archive.read(archive_path)
                if len(content) != upload.get("size_bytes"):
                    raise ValueError(f"Upload {archive_path} has an invalid size.")
                if hashlib.sha256(content).hexdigest() != upload.get("sha256"):
                    raise ValueError(f"Upload {archive_path} failed its integrity check.")
                if not str(upload.get("database_path") or "").strip():
                    raise ValueError(f"Upload {archive_path} is missing its database path.")
                expected_archive_names.add(archive_path)
            if set(names) != expected_archive_names:
                raise ValueError("The project package contains files not declared by its manifest.")
    except BadZipFile as exc:
        raise ValueError("This file is not a valid PAAG project package archive.") from exc

    scenarios = [
        {
            "Scenario revision": str(row.get("revision_label") or ""),
            "Scenario name": str(row.get("name") or ""),
            "Status": str(row.get("status") or ""),
        }
        for row in tables["planning_scenarios"]
    ]
    return {
        "manifest": manifest,
        "record_counts": actual_counts,
        "scenarios": scenarios,
        "uploads": uploads,
    }


def _remapped_tables(
    conn: sqlite3.Connection,
    tables: dict[str, list[dict]],
    source_project_id: str,
    new_project_id: str,
    upload_paths: dict[str, str],
) -> dict[str, list[dict]]:
    id_maps: dict[str, dict[str, str]] = {}
    for item in PROJECT_TRANSFER_TABLES:
        rows = tables[item.name]
        if rows and "id" in rows[0]:
            id_maps[item.name] = {
                str(row["id"]): (
                    new_project_id if item.name == "projects" else str(uuid4())
                )
                for row in rows
            }

    remapped: dict[str, list[dict]] = {}
    for item in PROJECT_TRANSFER_TABLES:
        foreign_keys = {
            str(row[3]): (str(row[2]), str(row[4]))
            for row in conn.execute(f'PRAGMA foreign_key_list("{item.name}")')
        }
        output_rows = []
        for source_row in tables[item.name]:
            row = dict(source_row)
            if "id" in row:
                row["id"] = id_maps[item.name][str(source_row["id"])]
            if "project_id" in row:
                row["project_id"] = new_project_id
            for column, (parent_table, parent_column) in foreign_keys.items():
                value = source_row.get(column)
                if value is None or parent_column != "id" or parent_table == "projects":
                    continue
                mapping = id_maps.get(parent_table, {})
                if str(value) in mapping:
                    row[column] = mapping[str(value)]
            if item.name == "fishbone_nodes" and source_row.get("parent_id"):
                row["parent_id"] = id_maps["fishbone_nodes"].get(
                    str(source_row["parent_id"])
                )
            if item.name == "yamazumi_elements" and source_row.get("process_element_id"):
                row["process_element_id"] = id_maps["work_elements"].get(
                    str(source_row["process_element_id"])
                )
            if item.name == "project_transfer_events":
                for column in ("source_project_id", "target_project_id"):
                    if str(source_row.get(column) or "") == source_project_id:
                        row[column] = new_project_id
            for column, value in source_row.items():
                if column.endswith("_path") and str(value) in upload_paths:
                    row[column] = upload_paths[str(value)]
            output_rows.append(row)
        remapped[item.name] = output_rows
    return remapped


def _insert_remapped_tables(
    conn: sqlite3.Connection, tables: dict[str, list[dict]]
) -> None:
    for item in PROJECT_TRANSFER_TABLES:
        for row in tables[item.name]:
            columns = list(row)
            column_sql = ", ".join(f'"{column}"' for column in columns)
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f'INSERT INTO "{item.name}" ({column_sql}) VALUES ({placeholders})',
                tuple(row[column] for column in columns),
            )


def import_project_package(
    package_data: bytes,
    operation: str,
    editor_name: str = "",
    *,
    replace_project_id: str | None = None,
    current_project_id: str | None = None,
    allow_current_replace: bool = False,
) -> dict:
    """Revalidate and atomically create or replace one complete project graph."""
    preview = preview_project_package(package_data)
    if operation not in {"Create new", "Replace an existing project"}:
        raise ValueError("Choose Create new or Replace an existing project.")
    if operation == "Replace an existing project" and not replace_project_id:
        raise ValueError("Choose the existing project to replace.")
    if (
        operation == "Replace an existing project"
        and str(replace_project_id) == str(current_project_id)
        and not allow_current_replace
    ):
        raise ValueError(
            "Enable the additional current-project replacement step before continuing."
        )

    with ZipFile(BytesIO(package_data)) as archive:
        tables = json.loads(archive.read("records.json"))
        upload_contents = {
            upload["database_path"]: archive.read(upload["archive_path"])
            for upload in preview["uploads"]
        }

    manifest = preview["manifest"]
    source_project = manifest["source_project"]
    new_project_id = str(uuid4())
    created_files: list[Path] = []
    replaced_files: list[Path] = []
    target_name = ""
    upload_paths: dict[str, str] = {}
    store.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with store.connection() as conn:
            conn.execute("PRAGMA defer_foreign_keys=ON")
            if operation == "Replace an existing project":
                target = conn.execute(
                    "SELECT id, name FROM projects WHERE id=?", (replace_project_id,)
                ).fetchone()
                if target is None:
                    raise ValueError("The selected replacement project no longer exists.")
                target_name = str(target["name"] or "")
                target_tables, _ = _registered_rows(conn, str(replace_project_id))
                replaced_files = [
                    Path(str(item["source_path"])) for item in _upload_manifest(target_tables)
                ]
                conn.execute("DELETE FROM projects WHERE id=?", (replace_project_id,))

            for database_path, content in upload_contents.items():
                suffix = Path(str(database_path)).suffix.lower()
                target_path = (
                    store.UPLOAD_DIR
                    / f"project_transfer_{new_project_id}_{uuid4()}{suffix}"
                )
                target_path.write_bytes(content)
                created_files.append(target_path)
                upload_paths[str(database_path)] = str(target_path)

            remapped = _remapped_tables(
                conn, tables, str(source_project["id"]), new_project_id, upload_paths
            )
            _insert_remapped_tables(conn, remapped)
            timestamp = store.now_iso()
            conflicts = (
                [{"type": "replace_target", "project_id": replace_project_id,
                  "project_name": target_name}]
                if operation == "Replace an existing project" else []
            )
            conn.execute(
                """INSERT INTO project_transfer_events
                   (id, project_id, operation, package_version, manifest_json,
                    source_project_id, source_project_name, target_project_id,
                    target_project_name, record_counts_json, conflicts_json,
                    editor_name, created_at)
                   VALUES (?, ?, 'Import', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), new_project_id, PACKAGE_VERSION,
                    json.dumps(manifest, ensure_ascii=False), str(source_project["id"]),
                    str(source_project.get("name") or ""), replace_project_id,
                    target_name, json.dumps(preview["record_counts"]),
                    json.dumps(conflicts), str(editor_name or "").strip(), timestamp,
                ),
            )
            store.record_audit_event(
                new_project_id, AUDIT_CATEGORY, "Import Project",
                sum(preview["record_counts"].values()), editor_name,
                {"operation": operation, "package_version": PACKAGE_VERSION,
                 "source_project": source_project, "replaced_project_id": replace_project_id,
                 "replaced_project_name": target_name,
                 "record_counts": preview["record_counts"],
                 "upload_count": len(upload_contents)},
                _conn=conn,
            )
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise ValueError("The imported project contains invalid relationships.")
    except Exception:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise

    created_resolved = {path.resolve() for path in created_files}
    upload_root = store.UPLOAD_DIR.resolve()
    for path in replaced_files:
        try:
            resolved = path.resolve()
            if (
                resolved not in created_resolved
                and resolved.is_file()
                and upload_root in resolved.parents
            ):
                resolved.unlink()
        except OSError:
            pass
    scenario_rows = remapped.get("planning_scenarios", [])
    return {
        "project_id": new_project_id,
        "project_name": str(source_project.get("name") or ""),
        "scenario_id": str(scenario_rows[0]["id"]) if scenario_rows else None,
        "operation": operation,
    }
