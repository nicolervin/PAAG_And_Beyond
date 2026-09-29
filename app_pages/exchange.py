import hashlib

import streamlit as st
import pandas as pd

from utils.project_transfer import (
    AUDIT_CATEGORY,
    export_project_package,
    import_project_package,
    preview_project_package,
)
from utils.store import (
    audit_history,
    projects,
)
from utils.scope_ui import page_title_with_scope
from utils.table_ui import selectable_dataframe


project_id = st.session_state.get("project_id")
page_title_with_scope("Import/Export Projects", scope="project")
if not project_id:
    st.stop()

import_upload_key = f"project_package_upload_{project_id}"
pending_import_key = f"pending_project_import_{project_id}"


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


with st.container(border=True):
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

with st.expander("History", icon=":material/history:"):
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
