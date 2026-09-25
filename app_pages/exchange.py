import hashlib

import streamlit as st
import pandas as pd

from utils.excel_io import (
    export_workbook,
    has_pits_id_sheets,
    is_pits_format,
    mapped_bom,
    parse_pits,
    parse_pits_combined_workbook,
    read_bom,
    suggest_mapping,
)
from utils.project_transfer import (
    AUDIT_CATEGORY,
    export_project_package,
    import_project_package,
    preview_project_package,
)
from utils.store import (
    audit_history,
    assembly_sections,
    escalate_pits_bom_occurrence,
    fishbone_part_assignments,
    get_planning_scenario,
    get_project,
    import_fishbone_nodes,
    import_pits_id_snapshot,
    pits_import_conflict_parts,
    pits_bom_occurrences,
    pits_records,
    projects,
    project_models,
    record_audit_event,
    review_pits_bom_occurrences,
    upsert_part,
)
from utils.scope_ui import page_title_with_scope
from utils.table_filters import filter_table, split_filter_values
from utils.table_ui import selectable_dataframe, selected_dataframe_rows


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
page_title_with_scope("Import/Export Projects", scope="project")
if not project_id:
    st.stop()

import_upload_key = f"project_package_upload_{project_id}"
pending_import_key = f"pending_project_import_{project_id}"
pits_bom_review_key = f"pending_pits_bom_review_{project_id}"


def complete_project_import(pending: dict) -> None:
    uploaded = st.session_state.get(import_upload_key)
    if uploaded is None:
        raise ValueError("The selected project package is no longer available.")
    package_data = uploaded.getvalue()
    if hashlib.sha256(package_data).hexdigest() != pending["package_sha256"]:
        raise ValueError("The selected project package changed. Review it again before importing.")
    result = import_project_package(
        package_data,
        pending["operation"],
        st.session_state.get("current_editor", ""),
        replace_project_id=pending.get("replace_project_id"),
        current_project_id=project_id,
        allow_current_replace=bool(pending.get("allow_current_replace")),
    )
    for key in (
        pending_import_key,
        import_upload_key,
        f"project_import_operation_{project_id}",
        f"allow_current_project_replace_{project_id}",
        f"project_replace_target_{project_id}_0",
        f"project_replace_target_{project_id}_1",
    ):
        st.session_state.pop(key, None)
    st.session_state["project_id"] = result["project_id"]
    st.session_state["scenario_id"] = result["scenario_id"]
    st.toast(
        f"Imported project {result['project_name']}", icon=":material/check_circle:"
    )
    st.rerun(scope="app")


@st.dialog("Create imported project?")
def confirm_create_project_import(pending: dict) -> None:
    st.write("**Creates a new project.** Existing projects will not be changed.")
    st.caption("The package will be revalidated and every imported ID will be remapped.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_create_project_import_{project_id}"):
        st.session_state.pop(pending_import_key, None)
        st.rerun(scope="app")
    if actions.button(
        "Create new project",
        type="primary",
        icon=":material/add:",
        key=f"confirm_create_project_import_{project_id}",
    ):
        try:
            complete_project_import(pending)
        except (ValueError, OSError) as exc:
            st.error(str(exc))


@st.dialog("Replace existing project?", dismissible=False)
def confirm_replace_project_import(pending: dict) -> None:
    st.error(
        f"**Replaces an existing project:** {pending['replace_project_name']}. "
        "Its database records and owned uploads will be removed and replaced by the imported project."
    )
    st.caption("The package and target will be revalidated before any write.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_replace_project_import_{project_id}"):
        st.session_state.pop(pending_import_key, None)
        st.rerun(scope="app")
    if actions.button(
        "Replace project",
        type="primary",
        icon=":material/sync:",
        key=f"destructive_confirm_replace_project_import_{project_id}",
    ):
        try:
            complete_project_import(pending)
        except (ValueError, OSError) as exc:
            st.error(str(exc))


@st.dialog("Review PITS BOM structure changes", dismissible=False, width="large")
def review_pits_bom_import(import_id: str) -> None:
    review_rows = pits_bom_occurrences(project_id, actionable_only=True)
    if review_rows.empty:
        st.success("No PITS BOM structure changes need review.")
        if st.button("Close", key=f"close_empty_pits_bom_review_{project_id}"):
            st.session_state.pop(pits_bom_review_key, None)
            st.rerun()
        return
    relevant = review_rows.loc[
        review_rows["last_seen_import_id"].astype(str).eq(str(import_id))
        | review_rows["source_state"].astype(str).eq("Missing")
    ].reset_index(drop=True)
    if relevant.empty:
        relevant = review_rows.reset_index(drop=True)
    display = relevant[[
        "id", "source_state", "review_status", "parent_tracker_number",
        "child_tracker_number", "child_part_number", "proposed_depth",
        "proposed_quantity", "approved_quantity", "pits_sync_status",
        "validation_issues_json",
    ]].copy()
    st.write(
        "Review every suspected addition, change, and removal. Rows are selected by default; "
        "clear any row you do not want to acknowledge in this review. Approved Fishbone "
        "quantities remain unchanged."
    )
    event = selectable_dataframe(
        display,
        key=f"pits_bom_import_review_table_{project_id}_{import_id}",
        hide_index=True,
        height=420,
        selection_default={"selection": {"rows": list(range(len(display))) }},
        column_config={
            "id": None,
            "source_state": "PITS change",
            "review_status": "Review status",
            "parent_tracker_number": "Parent tracker number",
            "child_tracker_number": "Child tracker number",
            "child_part_number": "Child part number",
            "proposed_depth": "Level",
            "proposed_quantity": st.column_config.NumberColumn("PITS quantity"),
            "approved_quantity": st.column_config.NumberColumn("Approved Fishbone quantity"),
            "pits_sync_status": "Fishbone PITS state",
            "validation_issues_json": "Validation issues",
        },
    )
    selected = selected_dataframe_rows(display, event)
    st.caption(
        "Accepting records the reviewed source version. It never creates a Fishbone section, "
        "changes an approved quantity, or clears a PITS difference that still exists."
    )
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button(
            "Cancel",
            key=f"cancel_pits_bom_import_review_{project_id}_{import_id}",
        ):
            st.session_state.pop(pits_bom_review_key, None)
            st.rerun()
        if st.button(
            "Accept selected",
            type="primary",
            icon=":material/check:",
            disabled=selected.empty,
            key=f"accept_pits_bom_import_review_{project_id}_{import_id}",
        ):
            try:
                review_pits_bom_occurrences(
                    project_id,
                    selected["id"].astype(str).tolist(),
                    "Acknowledge",
                    st.session_state.get("current_editor", ""),
                )
                st.session_state.pop(pits_bom_review_key, None)
                st.toast("PITS BOM review recorded", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


part_data_tab, whole_project_tab = st.tabs(
    ["Part-data exchange", "Whole-project transfer"]
)
part_data_tab.caption(
    "Start from a draft BOM and publish a stable, tabular snapshot for Excel or Lucid data linking."
)
with whole_project_tab.container(border=True):
    st.subheader(":material/package_2: Whole-project transfer")
    st.write(
        "**Export Project** packages the current project, every planning scenario, and referenced "
        "uploads for transfer to another local PAAG installation."
    )
    package_state_key = f"project_export_package_{project_id}"
    if st.button(
        "Export Project",
        type="primary",
        icon=":material/archive:",
        key=f"prepare_project_export_{project_id}",
    ):
        try:
            st.session_state[package_state_key] = export_project_package(
                project_id, st.session_state.get("current_editor", "")
            )
            st.toast("Project package prepared", icon=":material/check_circle:")
        except ValueError as exc:
            st.error(str(exc))
    prepared_package = st.session_state.get(package_state_key)
    if prepared_package:
        manifest = prepared_package["manifest"]
        st.caption(
            f"Package version {manifest['package_version']} · "
            f"{sum(manifest['record_counts'].values()):,} records · "
            f"{len(manifest['uploads']):,} uploads"
        )
        st.download_button(
            "Download project package",
            data=prepared_package["data"],
            file_name=prepared_package["file_name"],
            mime="application/vnd.paag.project+zip",
            icon=":material/download:",
            key=f"download_project_export_{project_id}",
        )
    st.divider()
    st.write(
        "**Import Project** validates and previews a complete package before any local data can change."
    )
    import_package = st.file_uploader(
        "PAAG project package",
        type=["paagproject"],
        key=import_upload_key,
        help="Choose a .paagproject file created by Export Project.",
    )
    if import_package is not None:
        try:
            package_preview = preview_project_package(import_package.getvalue())
        except ValueError as exc:
            st.error(str(exc))
        else:
            import_manifest = package_preview["manifest"]
            st.success("Project package validated", icon=":material/verified:")
            st.metric("Package version", import_manifest["package_version"])

            st.markdown("**Included scenarios**")
            scenario_preview = pd.DataFrame(package_preview["scenarios"])
            if scenario_preview.empty:
                st.caption("No planning scenarios are included.")
            else:
                selectable_dataframe(
                    scenario_preview,
                    key=f"project_import_scenarios_{project_id}",
                    hide_index=True,
                )

            st.markdown("**Per-table record counts**")
            count_preview = pd.DataFrame(
                [
                    {"Table": table, "Records": count}
                    for table, count in package_preview["record_counts"].items()
                ]
            )
            selectable_dataframe(
                count_preview,
                key=f"project_import_counts_{project_id}",
                hide_index=True,
                column_config={"Records": st.column_config.NumberColumn(format="%d")},
            )

            st.markdown("**Included uploads**")
            upload_preview = pd.DataFrame(
                [
                    {
                        "Database path": upload["database_path"],
                        "Package path": upload["archive_path"],
                        "Size (bytes)": upload["size_bytes"],
                    }
                    for upload in package_preview["uploads"]
                ]
            )
            if upload_preview.empty:
                st.caption("No uploaded files are included.")
            else:
                selectable_dataframe(
                    upload_preview,
                    key=f"project_import_uploads_{project_id}",
                    hide_index=True,
                    column_config={
                        "Size (bytes)": st.column_config.NumberColumn(format="%d")
                    },
                )

            target_operation = st.segmented_control(
                "Target operation",
                ["Create new", "Replace an existing project"],
                selection_mode="single",
                key=f"project_import_operation_{project_id}",
            )
            replace_target_id = None
            if target_operation == "Create new":
                st.info("Creates a new project. Existing projects will not be changed.")
            elif target_operation == "Replace an existing project":
                st.warning("Replaces an existing project. No replacement occurs during this preview step.")
                allow_current = st.toggle(
                    "Allow the currently open project to appear as a replacement target",
                    value=False,
                    key=f"allow_current_project_replace_{project_id}",
                    help="This additional step prevents the open project from being selected accidentally.",
                )
                available_projects = projects()
                target_rows = {
                    str(row["id"]): row for row in available_projects
                    if allow_current or str(row["id"]) != str(project_id)
                }
                replace_target_id = st.selectbox(
                    "Project to replace",
                    options=[None, *target_rows],
                    index=0,
                    format_func=lambda value: (
                        "Choose a project"
                        if value is None
                        else (
                            f"{target_rows[value]['name']} (currently open)"
                            if str(value) == str(project_id)
                            else str(target_rows[value]["name"])
                        )
                    ),
                    key=f"project_replace_target_{project_id}_{int(allow_current)}",
                )
                if not target_rows:
                    st.caption("No non-current projects are available to replace.")

            can_continue = target_operation == "Create new" or (
                target_operation == "Replace an existing project"
                and replace_target_id is not None
            )
            if st.button(
                "Continue",
                type="primary",
                icon=":material/arrow_forward:",
                disabled=not can_continue,
                key=f"continue_project_import_preview_{project_id}",
            ):
                st.session_state[pending_import_key] = {
                    "operation": target_operation,
                    "replace_project_id": replace_target_id,
                    "replace_project_name": (
                        str(target_rows[replace_target_id]["name"])
                        if replace_target_id is not None else ""
                    ),
                    "allow_current_replace": bool(
                        target_operation == "Replace an existing project" and allow_current
                    ),
                    "package_sha256": hashlib.sha256(import_package.getvalue()).hexdigest(),
                }
                st.rerun(scope="app")

defined_models = project_models(project_id)
model_labels = {
    str(row["model_number"]): (str(row["display_name"]).strip() or "Familiar name not defined")
    for _, row in defined_models.iterrows()
}

import_col, export_col = part_data_tab.columns(2)
with import_col.container(border=True):
    st.subheader("Import a BOM draft")
    uploaded = st.file_uploader("Excel, CSV, TSV, or pasted text file", type=["xlsx", "xlsm", "csv", "tsv", "txt"])
    if uploaded:
        try:
            if has_pits_id_sheets(uploaded):
                records, models, bom_snapshot = parse_pits_combined_workbook(uploaded)
                st.success("ID-based PITS tracker detected", icon=":material/key:")
                unique_ids = {
                    str(record.get("pits_id") or "").strip()
                    for record in records
                    if str(record.get("pits_id") or "").strip()
                }
                part_numbers = [
                    str(record.get("part_number") or "").strip()
                    for record in records
                ]
                importable_parts = {part_number for part_number in part_numbers if part_number}
                missing_part_numbers = sum(not part_number for part_number in part_numbers)
                unique_models = {
                    str(model.get("model_number") or "").strip()
                    for model in models
                    if str(model.get("model_number") or "").strip()
                }
                summary_cols = st.columns(4)
                summary_cols[0].metric("PITS rows", len(records))
                summary_cols[1].metric("Unique IDs", len(unique_ids))
                summary_cols[2].metric("Importable parts", len(importable_parts))
                summary_cols[3].metric("Unique models", len(unique_models))
                if missing_part_numbers:
                    st.warning(
                        f"{missing_part_numbers:,} PITS row(s) have an ID but no part number. "
                        "They remain source-evidence records but cannot create Parts Catalog records.",
                        icon=":material/warning:",
                    )
                duplicate_part_rows = len(part_numbers) - missing_part_numbers - len(importable_parts)
                duplicate_model_rows = len(models) - len(unique_models)
                if duplicate_part_rows or duplicate_model_rows:
                    duplicate_details = []
                    if duplicate_part_rows:
                        duplicate_details.append(
                            f"{duplicate_part_rows:,} duplicate part-number row(s)"
                        )
                    if duplicate_model_rows:
                        duplicate_details.append(
                            f"{duplicate_model_rows:,} duplicate model-number row(s)"
                        )
                    st.info(
                        f"The workbook also contains {' and '.join(duplicate_details)}. "
                        "Repeated identifiers update the same project record during import.",
                        icon=":material/info:",
                    )
                st.caption(
                    "ID Number is the stable source key. Re-imports create source revisions "
                    "and flag changed MBOM candidates without overwriting collaborator-reviewed "
                    "planning decisions."
                )
                preview = [{key: value for key, value in record.items() if key != "source_payload"} for record in records]
                preview_table = filter_table(
                    pd.DataFrame(preview),
                    key="pits_import_preview_filters",
                    dropdown_columns=["status", "subsystem", "design_maturity", "workstation"],
                    search_columns=["pits_id", "part_number", "description", "comments", "subsystem"],
                )
                selectable_dataframe(preview_table.head(50), key="pits_import_preview_table", hide_index=True, height=360,
                             column_config={"pits_id": st.column_config.TextColumn("PITS ID", pinned=True), "part_number": st.column_config.TextColumn("Part number", pinned=True), "description": st.column_config.TextColumn("Part Name")})
                with st.expander("Models in this workbook", icon=":material/precision_manufacturing:"):
                    model_preview = [{key: value for key, value in model.items() if key != "source_payload"} for model in models]
                    model_preview_table = filter_table(
                        pd.DataFrame(model_preview),
                        key="pits_model_preview_filters",
                        dropdown_columns=["platform_size", "package_type", "base_model"],
                        search_columns=["model_number", "appearance", "sku_upc"],
                    )
                    selectable_dataframe(model_preview_table, key="pits_model_preview_table", hide_index=True)
                bom_occurrences = list(bom_snapshot.get("occurrences") or [])
                bom_issues = list(bom_snapshot.get("issues") or [])
                bom_duplicates = list(bom_snapshot.get("duplicates") or [])
                bom_duplicate_pair_count = len({
                    (
                        str(row.get("parent_tracker_number") or "").strip(),
                        str(row.get("child_tracker_number") or "").strip(),
                    )
                    for row in bom_duplicates
                })
                blocking_bom_issues = [issue for issue in bom_issues if issue.get("blocking")]
                if bom_snapshot.get("sheet_name"):
                    with st.expander(
                        f"BOM structure in this workbook ({len(bom_occurrences):,} occurrences)",
                        icon=":material/account_tree:",
                    ):
                        bom_preview = pd.DataFrame(bom_occurrences)
                        if not bom_preview.empty:
                            selectable_dataframe(
                                bom_preview.head(50),
                                key=f"pits_bom_preview_{project_id}",
                                hide_index=True,
                                height=360,
                                column_config={
                                    "parent_tracker_number": "Parent tracker number",
                                    "child_tracker_number": "Child tracker number",
                                    "part_number": "Part number",
                                    "description": "Part Name",
                                    "proposed_depth": "Level",
                                    "raw_quantity_text": "PITS quantity source",
                                    "proposed_quantity": "PITS quantity",
                                    "source_row": "BOM row",
                                    "raw_levels": None,
                                },
                            )
                        if bom_issues:
                            if blocking_bom_issues:
                                st.error(
                                    f"Import is blocked by {len(blocking_bom_issues):,} BOM row "
                                    "issue(s). The blocking rows are listed first below with their "
                                    "exact Excel row and available source values.",
                                    icon=":material/error:",
                                )
                            else:
                                st.warning(
                                    f"Found {len(bom_issues):,} nonblocking BOM row issue(s). "
                                    "Their exact Excel locations and source values are listed below.",
                                    icon=":material/warning:",
                                )
                            issue_preview = pd.DataFrame([{
                                "result": (
                                    "Blocks import" if issue.get("blocking") else "Flagged only"
                                ),
                                "source_row": issue.get("source_row"),
                                "issue": issue.get("issue"),
                                "child_tracker_number": issue.get("child_tracker_number", ""),
                                "part_number": issue.get("part_number", ""),
                                "description": issue.get("description", ""),
                                "proposed_depth": issue.get("proposed_depth"),
                                "expected_parent_level": issue.get("expected_parent_level"),
                                "raw_quantity_text": issue.get("raw_quantity_text", ""),
                            } for issue in bom_issues])
                            issue_preview["_blocking_order"] = issue_preview["result"].eq(
                                "Blocks import"
                            )
                            issue_preview = issue_preview.sort_values(
                                ["_blocking_order", "source_row"],
                                ascending=[False, True],
                                kind="stable",
                            ).drop(columns=["_blocking_order"])
                            selectable_dataframe(
                                issue_preview,
                                key=f"pits_bom_issue_preview_{project_id}",
                                hide_index=True,
                                height=360,
                                column_config={
                                    "result": st.column_config.TextColumn("Import result", pinned=True),
                                    "source_row": st.column_config.NumberColumn(
                                        "Excel row", format="%d", pinned=True
                                    ),
                                    "issue": st.column_config.TextColumn("Issue", width="large"),
                                    "child_tracker_number": "Tracker number (Column A)",
                                    "part_number": "Part number (Column B)",
                                    "description": st.column_config.TextColumn(
                                        "Description (Column C)", width="large"
                                    ),
                                    "proposed_depth": st.column_config.NumberColumn(
                                        "Populated level", format="%d"
                                    ),
                                    "expected_parent_level": st.column_config.NumberColumn(
                                        "Expected parent level", format="%d"
                                    ),
                                    "raw_quantity_text": "Level-cell value",
                                },
                            )
                        if bom_duplicates:
                            st.warning(
                                f"Found {len(bom_duplicates):,} additional BOM occurrence row(s) "
                                f"across {bom_duplicate_pair_count:,} duplicate parent/child pair(s). "
                                "Import will continue, and each affected occurrence will "
                                "be flagged with its BOM row numbers until a later PITS file resolves it.",
                                icon=":material/warning:",
                            )
                            duplicate_preview = pd.DataFrame(bom_duplicates)
                            selectable_dataframe(
                                duplicate_preview,
                                key=f"pits_bom_duplicate_preview_{project_id}",
                                hide_index=True,
                                column_config={
                                    "parent_tracker_number": "Parent tracker number",
                                    "child_tracker_number": "Child tracker number",
                                    "first_source_row": "First BOM row",
                                    "duplicate_source_row": "Duplicate BOM row",
                                    "part_number": "Part number (Column B)",
                                    "description": st.column_config.TextColumn(
                                        "Description (Column C)", width="large"
                                    ),
                                    "proposed_depth": st.column_config.NumberColumn(
                                        "Populated level", format="%d"
                                    ),
                                    "raw_quantity_text": "Level-cell value",
                                },
                            )
                else:
                    st.warning(
                        "This PITS workbook has no BOM worksheet. Tracker and Models can still "
                        "be imported, but no parent-child structure will be staged.",
                        icon=":material/warning:",
                    )
                excluded_records = [
                    record for record in records
                    if str(record.get("used_bom") or "").strip().casefold() in {"n", "no"}
                ]
                if excluded_records:
                    st.warning(
                        f"{len(excluded_records):,} workbook row(s) marked Used BOM = N will remain in the "
                        "Parts Catalog but will be marked inactive for the selected planning scenario.",
                        icon=":material/warning:",
                    )
                conflict_parts = pits_import_conflict_parts(project_id, records)
                manual_conflicts = [
                    conflict for conflict in conflict_parts
                    if conflict.get("conflict_type") == "manual_values"
                ]
                tracker_conflicts = [
                    conflict for conflict in conflict_parts
                    if conflict.get("conflict_type") == "pits_tracker_number"
                ]
                confirm_overwrite_manual = False
                if manual_conflicts:
                    st.warning(
                        f"Found {len(manual_conflicts):,} existing part(s) in the Parts Catalog with manual collaborator edits. "
                        "By default, manual edits are preserved. Check the box below if you wish to overwrite them.",
                        icon=":material/warning:",
                    )
                    confirm_overwrite_manual = st.checkbox(
                        f"Confirm overwriting manual edits for {len(manual_conflicts):,} catalog part(s) with PITS values",
                        key=f"confirm_overwrite_manual_{project_id}",
                    )
                if tracker_conflicts:
                    st.warning(
                        f"{len(tracker_conflicts):,} PITS Tracker number(s) are already assigned to other "
                        "Parts Catalog records. The affected imported parts will keep a blank PITS Tracker number.",
                        icon=":material/warning:",
                    )
                    with st.expander("PITS Tracker number conflicts", icon=":material/key:"):
                        selectable_dataframe(
                            pd.DataFrame(tracker_conflicts)[[
                                "pits_tracker_number", "part_number", "existing_part_number"
                            ]],
                            key=f"pits_tracker_conflicts_{project_id}",
                            hide_index=True,
                            column_config={
                                "pits_tracker_number": "PITS Tracker number",
                                "part_number": "Incoming part number",
                                "existing_part_number": "Existing owning part number",
                            },
                        )
                if st.button(
                    "Import PITS snapshot",
                    type="primary",
                    icon=":material/upload:",
                    disabled=bool(blocking_bom_issues),
                ):
                    existing_pits = pits_records(project_id)
                    previous_revisions = {
                        str(row["pits_id"]): int(row["revision_no"])
                        for _, row in existing_pits.iterrows()
                    }
                    summary = import_pits_id_snapshot(
                        project_id,
                        records,
                        models,
                        scenario_id=scenario_id,
                        overwrite_manual=confirm_overwrite_manual,
                        bom_snapshot=bom_snapshot,
                        workbook_name=uploaded.name,
                        workbook_sha256=hashlib.sha256(uploaded.getvalue()).hexdigest(),
                        editor_name=st.session_state.get("current_editor", ""),
                    )
                    imported_pits = pits_records(project_id)
                    imported_ids = {str(record["pits_id"]).strip() for record in records}
                    created_revisions = []
                    updated_revisions = []
                    for _, row in imported_pits.iterrows():
                        pits_id = str(row["pits_id"])
                        if pits_id not in imported_ids:
                            continue
                        revision = int(row["revision_no"])
                        revision_detail = {"pits_id": pits_id, "revision_no": revision}
                        previous_revision = previous_revisions.get(pits_id)
                        if previous_revision is None:
                            created_revisions.append(revision_detail)
                        elif revision > previous_revision:
                            updated_revisions.append(revision_detail)
                    record_audit_event(
                        project_id,
                        "PITS snapshot",
                        "Import PITS snapshot",
                        len(records),
                        st.session_state.get("current_editor", ""),
                        {
                            "rows_imported": len(records),
                            "pits_revisions_created": created_revisions,
                            "pits_revisions_updated": updated_revisions,
                            "models_synchronized": summary["models"],
                            "unchanged_pits_records": summary["unchanged"],
                            "pits_tracker_number_conflicts": summary["tracker_conflicts"],
                            "pits_bom_import": summary.get("bom"),
                        },
                    )
                    success_message = (
                        f"Imported {summary['new']} new IDs, detected {summary['changed']} revised IDs, "
                        f"left {summary['unchanged']} unchanged, and synchronized {summary['models']} models."
                    )
                    if summary["tracker_conflicts"]:
                        success_message += (
                            f" Left {summary['tracker_conflicts']} conflicting PITS Tracker number(s) blank."
                        )
                    bom_summary = summary.get("bom")
                    if bom_summary:
                        success_message += (
                            f" Staged {bom_summary['new']} new, {bom_summary['changed']} changed, "
                            f"and {bom_summary['missing']} missing BOM occurrence(s)."
                        )
                        if bom_summary.get("duplicate_pairs"):
                            success_message += (
                                f" Flagged {bom_summary['duplicate_pairs']} duplicate parent/child "
                                "pair(s) for review."
                            )
                        st.session_state[pits_bom_review_key] = bom_summary["import_id"]
                    st.success(success_message, icon=":material/check_circle:")
                    if bom_summary:
                        st.rerun()
                pending_bom_review = st.session_state.get(pits_bom_review_key)
                if pending_bom_review:
                    review_pits_bom_import(str(pending_bom_review))
                staged_bom = pits_bom_occurrences(project_id, actionable_only=True)
                if not staged_bom.empty:
                    with st.expander(
                        f"PITS BOM structure review queue ({len(staged_bom):,})",
                        icon=":material/rule:",
                    ):
                        queue_display = staged_bom[[
                            "id", "source_state", "review_status",
                            "parent_tracker_number", "child_tracker_number",
                            "child_part_number", "child_part_name", "proposed_depth",
                            "proposed_quantity", "approved_quantity", "pits_sync_status",
                            "validation_issues_json",
                        ]].reset_index(drop=True)
                        queue_event = selectable_dataframe(
                            queue_display,
                            key=f"pits_bom_review_queue_{project_id}",
                            hide_index=True,
                            height=360,
                            column_config={
                                "id": None,
                                "source_state": "PITS change",
                                "review_status": "Review status",
                                "parent_tracker_number": "Parent tracker number",
                                "child_tracker_number": "Child tracker number",
                                "child_part_number": "Child part number",
                                "child_part_name": "Part Name",
                                "proposed_depth": "Level",
                                "proposed_quantity": st.column_config.NumberColumn("PITS quantity"),
                                "approved_quantity": st.column_config.NumberColumn("Approved Fishbone quantity"),
                                "pits_sync_status": "Fishbone PITS state",
                                "validation_issues_json": "Validation issues",
                            },
                        )
                        queue_selected = selected_dataframe_rows(queue_display, queue_event)
                        if len(queue_selected) == 1:
                            selected_row = queue_selected.iloc[0]
                            selected_occurrence_id = str(selected_row["id"])
                            selected_full = staged_bom.loc[
                                staged_bom["id"].astype(str).eq(selected_occurrence_id)
                            ].iloc[0]
                            active_sections = assembly_sections(project_id)
                            active_sections = active_sections.loc[
                                active_sections["active"].fillna(0).astype(bool)
                            ].copy()
                            section_options = active_sections["id"].astype(str).tolist()
                            section_labels = {
                                str(row["id"]): str(row["name"])
                                for _, row in active_sections.iterrows()
                            }
                            selected_section_id = st.selectbox(
                                "Fishbone section",
                                options=section_options,
                                format_func=lambda value: section_labels.get(value, value),
                                key=f"pits_bom_review_section_{project_id}_{selected_occurrence_id}",
                                disabled=not section_options,
                            ) if section_options else None
                            existing_use_options = [""]
                            existing_use_labels = {"": "Create a new Fishbone use"}
                            if selected_section_id and selected_full.get("child_part_id"):
                                uses = fishbone_part_assignments(project_id)
                                uses = uses.loc[
                                    uses["section_id"].astype(str).eq(str(selected_section_id))
                                    & uses["part_id"].astype(str).eq(str(selected_full["child_part_id"]))
                                ]
                                for _, use in uses.iterrows():
                                    use_id = str(use["id"])
                                    existing_use_options.append(use_id)
                                    existing_use_labels[use_id] = (
                                        f"{use['use_description'] or 'Existing Fishbone use'} · "
                                        f"quantity {use['quantity']:g}"
                                    )
                            selected_use_id = st.selectbox(
                                "Fishbone use",
                                options=existing_use_options,
                                format_func=lambda value: existing_use_labels.get(value, value),
                                key=f"pits_bom_review_use_{project_id}_{selected_occurrence_id}",
                            )
                            with st.container(horizontal=True):
                                if st.button(
                                    "Approve",
                                    type="primary",
                                    icon=":material/check:",
                                    disabled=(
                                        selected_full["review_status"] == "Approved"
                                        or not selected_section_id
                                    ),
                                    key=f"approve_pits_bom_{project_id}_{selected_occurrence_id}",
                                ):
                                    try:
                                        review_pits_bom_occurrences(
                                            project_id, [selected_occurrence_id], "Approve",
                                            st.session_state.get("current_editor", ""),
                                            section_id=selected_section_id,
                                            existing_assignment_id=selected_use_id or None,
                                        )
                                        st.toast("PITS BOM occurrence approved", icon=":material/check_circle:")
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                                if st.button(
                                    "Reject",
                                    disabled=selected_full["review_status"] == "Approved",
                                    key=f"reject_pits_bom_{project_id}_{selected_occurrence_id}",
                                ):
                                    try:
                                        review_pits_bom_occurrences(
                                            project_id, [selected_occurrence_id], "Reject",
                                            st.session_state.get("current_editor", ""),
                                        )
                                        st.toast("PITS BOM occurrence rejected", icon=":material/block:")
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                                if st.button(
                                    "Escalate",
                                    icon=":material/help:",
                                    key=f"escalate_pits_bom_{project_id}_{selected_occurrence_id}",
                                ):
                                    try:
                                        escalate_pits_bom_occurrence(
                                            project_id, selected_occurrence_id,
                                            st.session_state.get("current_editor", ""),
                                        )
                                        st.toast(
                                            "Linked Questions and concerns record created",
                                            icon=":material/check_circle:",
                                        )
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                                if selected_full["review_status"] == "Approved" and st.button(
                                    "Detach",
                                    key=f"detach_pits_bom_{project_id}_{selected_occurrence_id}",
                                ):
                                    try:
                                        review_pits_bom_occurrences(
                                            project_id, [selected_occurrence_id], "Detach",
                                            st.session_state.get("current_editor", ""),
                                        )
                                        st.toast("PITS BOM occurrence detached", icon=":material/link_off:")
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                        else:
                            st.caption("Select one occurrence to approve, reject, escalate, or detach.")
                st.stop()
            raw = read_bom(uploaded)
            if is_pits_format(raw):
                parsed = parse_pits(raw)
                st.success("PITS hierarchy detected", icon=":material/account_tree:")
                summary_cols = st.columns(3)
                summary_cols[0].metric("Rows", len(parsed))
                summary_cols[1].metric("Unique parts", parsed["part_number"].replace("", None).nunique())
                summary_cols[2].metric("Maximum level", int(parsed["depth"].max()) if not parsed.empty else 0)
                st.warning("Level cell contents are program-specific and will not be interpreted as quantities, sequence, or model codes. Proposed depth uses only the leftmost populated Level column and must be reviewed.", icon=":material/warning:")
                parsed_preview = filter_table(
                    parsed[["sequence", "depth", "part_number", "description", "level_evidence", "subsystem", "model_feature", "comments"]],
                    key="legacy_pits_preview_filters",
                    dropdown_columns=["depth", "subsystem", "model_feature"],
                    search_columns=["part_number", "description", "level_evidence", "comments"],
                )
                selectable_dataframe(parsed_preview.head(50), key="legacy_pits_preview_table", hide_index=True,
                             column_config={"depth": st.column_config.NumberColumn("Proposed depth"), "description": st.column_config.TextColumn("Part Name"), "level_evidence": st.column_config.TextColumn("Uninterpreted Level values", width="large")})
                replace_existing = st.toggle("Replace the current fishbone", value=True, help="Turn this off to append another PITS section or model family.")
                if st.button("Send PITS candidates to MBOM review", type="primary", icon=":material/upload:"):
                    count = import_fishbone_nodes(project_id, parsed, replace=replace_existing)
                    record_audit_event(
                        project_id,
                        "MBOM review",
                        "Send PITS candidates to MBOM review",
                        count,
                        st.session_state.get("current_editor", ""),
                        {
                            "candidates_sent": count,
                            "review_status": "Needs review",
                            "replaced_existing_fishbone": replace_existing,
                        },
                    )
                    st.success(f"Sent {count:,} source occurrences to MBOM review. No candidate was accepted into the part catalog automatically.", icon=":material/check_circle:")
                st.stop()
            suggestions = suggest_mapping(raw.columns)
            raw_columns = [column for column in raw.columns.tolist() if str(column).strip()]
            options = [None] + raw_columns
            st.caption(f"{len(raw):,} rows found. Confirm the column mapping before importing.")
            mapping = {}
            for target, label in [("part_number", "Part number"), ("description", "Part Name"), ("quantity", "Quantity"), ("revision", "Revision"), ("model_applicability", "Model applicability")]:
                suggested = suggestions[target]
                mapping[target] = st.selectbox(
                    label,
                    options,
                    index=(options.index(suggested) if suggested in options else 0),
                    key=f"map_{target}",
                    help="Choose the column in the uploaded file that matches this required field.",
                )
            preview = mapped_bom(raw, mapping)
            preview_for_display = preview.copy()
            preview_for_display["model_applicability"] = preview_for_display["model_applicability"].apply(
                lambda value: ", ".join(
                    "All models" if model.casefold() in {"all", "all models"} else model_labels.get(model, model)
                    for model in (split_filter_values(value) or ["All"])
                )
            )
            mapped_preview = filter_table(
                preview_for_display,
                key="mapped_bom_preview_filters",
                dropdown_columns=["revision", "model_applicability"],
                search_columns=["part_number", "description", "revision", "model_applicability"],
                multi_value_columns=["model_applicability"],
                universal_values={"model_applicability": ["All", "All models", ""]},
            )
            selectable_dataframe(
                mapped_preview.head(20),
                key="mapped_bom_preview_table",
                hide_index=True,
                column_config={"description": st.column_config.TextColumn("Part Name")},
            )
            if st.button("Import parts", type="primary", icon=":material/upload:"):
                if not mapping["part_number"]:
                    st.error("Choose a part-number column.")
                else:
                    for row in preview.to_dict("records"):
                        upsert_part(project_id, {**row, "source": "BOM import"})
                    record_audit_event(
                        project_id,
                        "Parts",
                        "Import parts",
                        len(preview),
                        st.session_state.get("current_editor", ""),
                        {
                            "parts_imported_or_updated": len(preview),
                            "source": "BOM import",
                        },
                    )
                    st.success(f"Imported or updated {len(preview):,} parts.", icon=":material/check_circle:")
        except Exception as exc:
            st.error(f"Could not read this file: {exc}")

with export_col.container(border=True):
    st.subheader("Export planning snapshot")
    st.write("The workbook contains project, confirmed parts, Manufacturing BOM review, work elements, and concerns sheets, plus a flattened **Lucid Data Link** sheet.")
    st.caption("This is a snapshot export. A later release can add a controlled sync and Lucid-specific identifier strategy.")
    project = get_project(project_id)
    workbook = export_workbook(project_id, scenario_id)
    scenario = get_planning_scenario(project_id, scenario_id) if scenario_id else None
    safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in project["name"])
    revision_label = scenario["revision_label"] if scenario else project["revision"]
    st.download_button("Download Excel workbook", workbook, file_name=f"{safe_name}_rev_{revision_label}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", icon=":material/download:")


with st.expander("History", icon=":material/history:"):
    pits_history_tab, pits_bom_history_tab, mbom_history_tab, parts_history_tab, transfer_history_tab = st.tabs(
        ["PITS snapshots", "PITS BOM structure", "MBOM review", "Parts import", "Project transfer"]
    )
    with pits_history_tab:
        pits_history = audit_history(project_id, "PITS snapshot", limit=50)
        if pits_history.empty:
            st.caption("No PITS snapshot history has been recorded yet.")
        else:
            selectable_dataframe(
                pits_history.drop(columns=["details"], errors="ignore"),
                key=f"exchange_pits_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with pits_bom_history_tab:
        pits_bom_history = audit_history(project_id, "PITS BOM structure", limit=50)
        if pits_bom_history.empty:
            st.caption("No PITS BOM structure history has been recorded yet.")
        else:
            selectable_dataframe(
                pits_bom_history.drop(columns=["details"], errors="ignore"),
                key=f"exchange_pits_bom_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with mbom_history_tab:
        mbom_history = audit_history(project_id, "MBOM review", limit=50)
        if mbom_history.empty:
            st.caption("No MBOM review history has been recorded yet.")
        else:
            selectable_dataframe(
                mbom_history.drop(columns=["details"], errors="ignore"),
                key=f"exchange_mbom_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with parts_history_tab:
        parts_import_history = audit_history(project_id, "Parts", limit=50)
        if not parts_import_history.empty:
            parts_import_history = parts_import_history.loc[
                parts_import_history["action"] == "Import parts"
            ].copy()
        if parts_import_history.empty:
            st.caption("No parts-import history has been recorded yet.")
        else:
            selectable_dataframe(
                parts_import_history.drop(columns=["details"], errors="ignore"),
                key=f"exchange_parts_import_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with transfer_history_tab:
        transfer_history = audit_history(project_id, AUDIT_CATEGORY, limit=50)
        if transfer_history.empty:
            st.caption("No whole-project transfer history has been recorded yet.")
        else:
            selectable_dataframe(
                transfer_history.drop(columns=["details"], errors="ignore"),
                key=f"exchange_transfer_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )


pending_import = st.session_state.get(pending_import_key)
if pending_import:
    if pending_import["operation"] == "Replace an existing project":
        confirm_replace_project_import(pending_import)
    else:
        confirm_create_project_import(pending_import)
