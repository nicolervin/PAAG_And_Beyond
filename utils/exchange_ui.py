import hashlib

from typing import Any

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
from utils.store import (
    audit_history,
    detect_pits_new_and_changed_parts,
    get_planning_scenario,
    get_project,
    import_fishbone_nodes,
    import_pits_id_snapshot,
    pits_catalog_id_resolution,
    pits_import_conflict_parts,
    pits_part_downstream_impacts,
    pits_records,
    project_models,
    record_audit_event,
    upsert_part,
)
from utils.table_filters import filter_table, split_filter_values
from utils.table_ui import selectable_dataframe


class _UploadedFileWrapper:
    """Lightweight in-memory wrapper for workbook data across dialog reruns."""

    def __init__(self, uploaded_or_name: Any, data: bytes | None = None) -> None:
        if data is None and hasattr(uploaded_or_name, "getvalue"):
            self.name = getattr(uploaded_or_name, "name", "pits_workbook.xlsx")
            self._data = uploaded_or_name.getvalue()
        elif isinstance(uploaded_or_name, str) and data is not None:
            self.name = uploaded_or_name
            self._data = data
        else:
            self.name = getattr(uploaded_or_name, "name", "pits_workbook.xlsx")
            self._data = bytes(uploaded_or_name) if uploaded_or_name else b""

    def getvalue(self) -> bytes:
        return self._data

    @property
    def size(self) -> int:
        return len(self._data)


def _save_pits_workbook_snapshot(
    project_id: str,
    scenario_id: str | None,
    records: list[dict],
    models: list[dict],
    bom_snapshot: dict,
    uploaded,
    *,
    overwrite_manual: bool,
    editor_name: str,
) -> dict:
    """Persist every recognized PITS worksheet through the combined import."""
    workbook_data = uploaded.getvalue() if hasattr(uploaded, "getvalue") else uploaded
    workbook_name = getattr(uploaded, "name", "pits_workbook.xlsx")
    return import_pits_id_snapshot(
        project_id,
        records,
        models,
        scenario_id=scenario_id,
        overwrite_manual=overwrite_manual,
        bom_snapshot=bom_snapshot,
        workbook_name=workbook_name,
        workbook_sha256=hashlib.sha256(workbook_data).hexdigest(),
        editor_name=editor_name,
    )


def _execute_pits_import(
    project_id: str,
    scenario_id: str | None,
    records: list[dict],
    models: list[dict],
    bom_snapshot: dict,
    uploaded,
    *,
    overwrite_manual: bool,
    editor_name: str,
    acknowledged_parts: list[str] | None = None,
) -> dict:
    """Execute PITS snapshot import, record revisions and audit log including acknowledged parts."""
    existing_pits = pits_records(project_id)
    previous_revisions = {
        str(row["pits_id"]): int(row["revision_no"])
        for _, row in existing_pits.iterrows()
    }
    summary = _save_pits_workbook_snapshot(
        project_id,
        scenario_id,
        records,
        models,
        bom_snapshot,
        uploaded,
        overwrite_manual=overwrite_manual,
        editor_name=editor_name,
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
        editor_name,
        {
            "rows_imported": len(records),
            "pits_revisions_created": created_revisions,
            "pits_revisions_updated": updated_revisions,
            "models_synchronized": summary["models"],
            "unchanged_pits_records": summary["unchanged"],
            "catalog_pits_ids_linked": summary["pits_ids_linked"],
            "catalog_pits_ids_resolved_from_bom": summary["pits_ids_resolved_from_bom"],
            "catalog_part_number_conflicts": summary["pits_id_conflicts"],
            "bom_part_numbers_with_multiple_pits_ids": summary["bom_pits_id_conflicts"],
            "pits_bom_import": summary.get("bom"),
            "acknowledged_parts": list(acknowledged_parts or []),
        },
    )
    success_message = (
        f"Imported {summary['new']} new IDs, detected {summary['changed']} revised IDs, "
        f"left {summary['unchanged']} unchanged, synchronized {summary['models']} models, "
        f"and linked {summary['pits_ids_linked']} PITS IDs to catalog parts "
        f"({summary['pits_ids_resolved_from_bom']} resolved from the BOM sheet)."
    )
    bom_summary = summary.get("bom")
    if bom_summary:
        success_message += (
            f" Staged {bom_summary['new']} new, {bom_summary['changed']} changed, "
            f"and {bom_summary['missing']} missing BOM occurrence(s) for Model Tree."
        )
    return {
        "summary": summary,
        "success_message": success_message,
        "bom_summary": bom_summary,
        "acknowledged_parts": list(acknowledged_parts or []),
    }


@st.dialog("Verify New Part Numbers & Descriptions", width="large", dismissible=False)
def _pits_part_verification_dialog(project_id: str) -> None:
    wizard_key = f"pits_verification_wizard_{project_id}"
    wizard_data = st.session_state.get(wizard_key)
    if not wizard_data:
        return

    reviews = wizard_data.get("pending_reviews") or []
    if not reviews:
        st.session_state.pop(wizard_key, None)
        st.rerun()

    step = int(wizard_data.get("current_step") or 0)
    total = len(reviews)
    if step >= total:
        step = total - 1
        wizard_data["current_step"] = step

    item = reviews[step]
    part_number = item["part_number"]
    change_type = item.get("change_type", "new_part")
    is_new = change_type == "new_part"
    replaces_pn = item.get("replaces_part_number")
    replaces_desc = item.get("replaces_description") or ""
    replaces_tracker = item.get("replaces_tracker_id") or ""

    st.progress((step + 1) / total, text=f"Reviewing part {step + 1} of {total}")

    if replaces_pn:
        st.subheader(f":material/swap_horiz: Part replacement: `{part_number}` replaces `{replaces_pn}`")
        st.warning(
            f"Part **{part_number}** replaces existing part **{replaces_pn}** "
            f"{f'({replaces_desc}) ' if replaces_desc else ''}on PITS Tracker ID **#{replaces_tracker}**.\n\n"
            "Please verify this replacement and review the downstream planning impacts inherited from the predecessor part below.",
            icon=":material/swap_horiz:",
        )
    elif is_new:
        st.subheader(f":material/add_circle: New part number: `{part_number}`")
        st.info(
            f"Part **{part_number}** does not exist in the current Parts Catalog. "
            "Please verify this new part and acknowledge awareness before completing the import.",
            icon=":material/new_releases:",
        )
    else:
        st.subheader(f":material/edit_note: Modified description: `{part_number}`")
        st.warning(
            f"Part **{part_number}** already exists in the Parts Catalog, but has a different description "
            "in this PITS workbook. Please verify the change and acknowledge awareness.",
            icon=":material/update:",
        )

    with st.container(border=True):
        m1, m2, m3 = st.columns(3)
        pits_display = ", ".join(item.get("all_pits_ids") or [item.get("pits_id", "")]) or "—"
        m1.markdown(f"**PITS ID(s):** {pits_display}")
        m1.markdown(f"**Subsystem:** {item.get('subsystem') or '—'}")
        m2.markdown(f"**Design maturity:** {item.get('design_maturity') or '—'}")
        m2.markdown(f"**Design engineer:** {item.get('design_engineer') or '—'}")
        m3.markdown(f"**PPM:** {item.get('ppm') or '—'}")
        m3.markdown(f"**Buyer / GCL:** {item.get('buyer_gcl') or '—'}")

        if replaces_pn:
            st.markdown("---")
            rc1, rc2 = st.columns(2)
            with rc1:
                st.caption(f"Replaced predecessor part (Tracker #{replaces_tracker})")
                st.info(f"**{replaces_pn}**\n\n{replaces_desc or '(No description)'}")
            with rc2:
                st.caption("Incoming replacement part")
                st.success(f"**{part_number}**\n\n{item.get('incoming_description') or '(No description)'}")
        elif not is_new:
            st.markdown("---")
            c1, c2 = st.columns(2)
            with c1:
                st.caption("Current catalog description")
                st.info(item.get("current_description") or "(blank)")
            with c2:
                st.caption("Incoming PITS description")
                st.success(item.get("incoming_description") or "(blank)")
        else:
            st.markdown(f"**Incoming description:** {item.get('incoming_description') or '(blank)'}")

        if item.get("comments"):
            st.caption(f"Workbook comments: {item.get('comments')}")

    st.markdown("##### Downstream Planning Impacts")
    impacts = pits_part_downstream_impacts(
        project_id,
        part_number,
        scenario_id=wizard_data.get("scenario_id"),
        bom_snapshot=wizard_data.get("bom_snapshot"),
        replaces_part_number=replaces_pn,
    )

    # 1. Fishbone Impact
    fb = impacts["fishbone"]
    fb_total = fb["count"] + fb.get("replaces_count", 0)
    with st.expander(
        f":material/account_tree: Fishbone Impact ({fb_total} placement{'s' if fb_total != 1 else ''})",
        expanded=fb_total > 0,
    ):
        if fb["count"] > 0:
            st.markdown(f"Part **{part_number}** is placed in **{fb['count']}** Fishbone assembly use(s):")
            fb_df = pd.DataFrame(fb["assignments"])[["section_name", "quantity", "use_description", "pits_sync_status"]]
            st.dataframe(
                fb_df,
                column_config={
                    "section_name": st.column_config.TextColumn("Assembly Section"),
                    "quantity": st.column_config.NumberColumn("Quantity"),
                    "use_description": st.column_config.TextColumn("Use Description"),
                    "pits_sync_status": st.column_config.TextColumn("Sync Status"),
                },
                hide_index=True,
                width="stretch",
            )
        if fb.get("replaces_count", 0) > 0:
            st.markdown(f":material/swap_horiz: Predecessor part **{replaces_pn}** is placed in **{fb['replaces_count']}** Fishbone assembly use(s):")
            replaces_fb_df = pd.DataFrame(fb["replaces_assignments"])[["section_name", "quantity", "use_description", "pits_sync_status"]]
            st.dataframe(
                replaces_fb_df,
                column_config={
                    "section_name": st.column_config.TextColumn("Assembly Section"),
                    "quantity": st.column_config.NumberColumn("Quantity"),
                    "use_description": st.column_config.TextColumn("Use Description"),
                    "pits_sync_status": st.column_config.TextColumn("Sync Status"),
                },
                hide_index=True,
                width="stretch",
            )
            st.info(
                f"Collaborator action: In the Fishbone tab, reassign these placements from `{replaces_pn}` to `{part_number}` after import.",
                icon=":material/lightbulb:",
            )
        elif fb["count"] == 0:
            st.info(
                "Not currently placed in any Fishbone Assembly Section. "
                "Upon import, this part will be added to the Parts Catalog as an unassigned candidate.",
                icon=":material/info:",
            )

    # 2. Model Tree Impact
    mt = impacts["model_tree"]
    mt_total = len(mt["occurrences"]) + mt.get("replaces_count", 0)
    with st.expander(
        f":material/park: Model Tree Impact ({mt_total} occurrence{'s' if mt_total != 1 else ''})",
        expanded=mt_total > 0,
    ):
        if mt["occurrences"]:
            st.markdown(f"Found **{len(mt['occurrences'])}** occurrence(s) for **{part_number}**:")
            mt_df = pd.DataFrame(mt["occurrences"])[["source", "proposed_depth", "parent_tracker_number", "proposed_quantity", "review_status"]]
            st.dataframe(
                mt_df,
                column_config={
                    "source": st.column_config.TextColumn("Source"),
                    "proposed_depth": st.column_config.NumberColumn("Level"),
                    "parent_tracker_number": st.column_config.TextColumn("Parent Tracker #"),
                    "proposed_quantity": st.column_config.NumberColumn("Quantity"),
                    "review_status": st.column_config.TextColumn("Review Status"),
                },
                hide_index=True,
                width="stretch",
            )
        if mt.get("replaces_count", 0) > 0:
            st.markdown(f":material/swap_horiz: Predecessor part **{replaces_pn}** has **{mt['replaces_count']}** occurrence(s) in active Model Tree:")
            rmt_df = pd.DataFrame(mt["replaces_occurrences"])[["source", "proposed_depth", "parent_tracker_number", "proposed_quantity", "review_status"]]
            st.dataframe(
                rmt_df,
                column_config={
                    "source": st.column_config.TextColumn("Source"),
                    "proposed_depth": st.column_config.NumberColumn("Level"),
                    "parent_tracker_number": st.column_config.TextColumn("Parent Tracker #"),
                    "proposed_quantity": st.column_config.NumberColumn("Quantity"),
                    "review_status": st.column_config.TextColumn("Review Status"),
                },
                hide_index=True,
                width="stretch",
            )
            st.caption("Active tree occurrences will be flagged for review in the Model Tree tab.")
        elif not mt["occurrences"]:
            st.info(
                "Part is listed in the PITS Tracker only. No occurrences found in the BOM sheet hierarchy.",
                icon=":material/info:",
            )

    # 3. Yamazumi Impact
    yz = impacts["yamazumi"]
    yz_total = yz["count"] + yz.get("replaces_count", 0)
    with st.expander(
        f":material/tune: Yamazumi Impact ({yz_total} element{'s' if yz_total != 1 else ''})",
        expanded=yz_total > 0,
    ):
        if yz["count"] > 0:
            st.markdown(f"Referenced in **{yz['count']}** Yamazumi work element(s):")
            yz_df = pd.DataFrame(yz["elements"])[["station", "operation", "cycle_time_s", "description"]]
            st.dataframe(
                yz_df,
                column_config={
                    "station": st.column_config.TextColumn("Station"),
                    "operation": st.column_config.TextColumn("Operation"),
                    "cycle_time_s": st.column_config.NumberColumn("Cycle Time (s)"),
                    "description": st.column_config.TextColumn("Description"),
                },
                hide_index=True,
                width="stretch",
            )
        if yz.get("replaces_count", 0) > 0:
            st.markdown(f":material/swap_horiz: Predecessor part **{replaces_pn}** is referenced in **{yz['replaces_count']}** Yamazumi work element(s):")
            ryz_df = pd.DataFrame(yz["replaces_elements"])[["station", "operation", "cycle_time_s", "description"]]
            st.dataframe(
                ryz_df,
                column_config={
                    "station": st.column_config.TextColumn("Station"),
                    "operation": st.column_config.TextColumn("Operation"),
                    "cycle_time_s": st.column_config.NumberColumn("Cycle Time (s)"),
                    "description": st.column_config.TextColumn("Description"),
                },
                hide_index=True,
                width="stretch",
            )
            st.info(
                f"Collaborator action: In the Yamazumi tab, update work element part number references from `{replaces_pn}` to `{part_number}`.",
                icon=":material/lightbulb:",
            )
        elif yz["count"] == 0:
            st.info(
                "No Yamazumi work elements currently reference this part number.",
                icon=":material/info:",
            )

    # 4. Process at a Glance Impact
    pr = impacts["process"]
    pr_total = pr["count"] + pr.get("replaces_count", 0)
    with st.expander(
        f":material/description: Process at a Glance Impact ({pr_total} requirement{'s' if pr_total != 1 else ''})",
        expanded=pr_total > 0,
    ):
        if pr["count"] > 0:
            st.markdown(f"Referenced in **{pr['count']}** Process at a Glance requirement(s):")
            pr_df = pd.DataFrame(pr["options"])[["station", "operation", "group_name", "handling_type"]]
            st.dataframe(
                pr_df,
                column_config={
                    "station": st.column_config.TextColumn("Station"),
                    "operation": st.column_config.TextColumn("Operation"),
                    "group_name": st.column_config.TextColumn("Part Group"),
                    "handling_type": st.column_config.TextColumn("Handling Type"),
                },
                hide_index=True,
                width="stretch",
            )
        if pr.get("replaces_count", 0) > 0:
            st.markdown(f":material/swap_horiz: Predecessor part **{replaces_pn}** is referenced in **{pr['replaces_count']}** Process at a Glance requirement(s):")
            rpr_df = pd.DataFrame(pr["replaces_options"])[["station", "operation", "group_name", "handling_type"]]
            st.dataframe(
                rpr_df,
                column_config={
                    "station": st.column_config.TextColumn("Station"),
                    "operation": st.column_config.TextColumn("Operation"),
                    "group_name": st.column_config.TextColumn("Part Group"),
                    "handling_type": st.column_config.TextColumn("Handling Type"),
                },
                hide_index=True,
                width="stretch",
            )
            st.info(
                f"Collaborator action: In Process at a Glance, update part requirements from `{replaces_pn}` to `{part_number}`.",
                icon=":material/lightbulb:",
            )
        elif pr["count"] == 0:
            st.info(
                "No Process at a Glance requirements currently reference this part.",
                icon=":material/info:",
            )

    # 5. Open Concerns (if any)
    cn = impacts["concerns"]
    cn_total = cn["count"] + cn.get("replaces_count", 0)
    if cn_total > 0:
        with st.expander(f":material/help_outline: Related Open Concerns ({cn_total})", expanded=False):
            if cn["count"] > 0:
                st.markdown(f"Open concerns for **{part_number}**:")
                cn_df = pd.DataFrame(cn["items"])[["category", "subject", "priority", "status"]]
                st.dataframe(
                    cn_df,
                    column_config={
                        "category": st.column_config.TextColumn("Category"),
                        "subject": st.column_config.TextColumn("Subject"),
                        "priority": st.column_config.TextColumn("Priority"),
                        "status": st.column_config.TextColumn("Status"),
                    },
                    hide_index=True,
                    width="stretch",
                )
            if cn.get("replaces_count", 0) > 0:
                st.markdown(f":material/swap_horiz: Open concerns for predecessor **{replaces_pn}**:")
                rcn_df = pd.DataFrame(cn["replaces_items"])[["category", "subject", "priority", "status"]]
                st.dataframe(
                    rcn_df,
                    column_config={
                        "category": st.column_config.TextColumn("Category"),
                        "subject": st.column_config.TextColumn("Subject"),
                        "priority": st.column_config.TextColumn("Priority"),
                        "status": st.column_config.TextColumn("Status"),
                    },
                    hide_index=True,
                    width="stretch",
                )

    if replaces_pn:
        ack_caption = (
            f"By clicking Acknowledge, you confirm awareness that **{part_number}** replaces **{replaces_pn}** "
            f"on PITS Tracker #{replaces_tracker} and acknowledge its downstream planning context."
        )
    elif is_new:
        ack_caption = (
            f"By clicking Acknowledge, you confirm awareness of new part number **{part_number}** "
            "and its downstream planning context."
        )
    else:
        ack_caption = (
            f"By clicking Acknowledge, you confirm awareness of the description update for **{part_number}** "
            "and its downstream planning context."
        )
    st.caption(ack_caption)
    col_cancel, col_space, col_action = st.columns([2, 1, 4])
    with col_cancel:
        if st.button("Cancel import", icon=":material/close:", key=f"pits_cancel_{step}", width="stretch"):
            st.session_state.pop(wizard_key, None)
            st.rerun()

    with col_action:
        if step < total - 1:
            if st.button(
                "Acknowledge & Next",
                type="primary",
                icon=":material/arrow_forward:",
                key=f"pits_next_{step}",
                width="stretch",
            ):
                wizard_data["acknowledged_parts"].append(part_number)
                wizard_data["current_step"] = step + 1
                st.rerun()
        else:
            if st.button(
                "Acknowledge & Complete Import",
                type="primary",
                icon=":material/check_circle:",
                key=f"pits_complete_{step}",
                width="stretch",
            ):
                wizard_data["acknowledged_parts"].append(part_number)
                result = _execute_pits_import(
                    wizard_data["project_id"],
                    wizard_data["scenario_id"],
                    wizard_data["records"],
                    wizard_data["models"],
                    wizard_data["bom_snapshot"],
                    wizard_data["uploaded"],
                    overwrite_manual=wizard_data.get("confirm_overwrite_manual", False),
                    editor_name=st.session_state.get("current_editor", ""),
                    acknowledged_parts=wizard_data["acknowledged_parts"],
                )
                st.session_state.pop(wizard_key, None)
                st.session_state[f"pits_import_completed_{project_id}"] = result
                st.rerun()


def render_part_data_exchange(project_id: str, scenario_id: str | None) -> None:
    wizard_key = f"pits_verification_wizard_{project_id}"
    if wizard_key in st.session_state:
        _pits_part_verification_dialog(project_id)

    defined_models = project_models(project_id)
    model_labels = {
        str(row["model_number"]): (str(row["display_name"]).strip() or "Familiar name not defined")
        for _, row in defined_models.iterrows()
    }

    import_col, export_col = st.columns(2)
    with import_col.container(border=True):
        st.subheader("Import a BOM draft")
        completion_key = f"pits_import_completed_{project_id}"
        if completion_key in st.session_state:
            completed_data = st.session_state[completion_key]
            st.success(completed_data["success_message"], icon=":material/check_circle:")
            ack = completed_data.get("acknowledged_parts") or []
            if ack:
                st.info(
                    f"Acknowledged {len(ack):,} part number(s) during verification: {', '.join(ack[:10])}{'...' if len(ack) > 10 else ''}",
                    icon=":material/verified:",
                )
            summary = completed_data.get("summary") or {}
            if summary.get("bom_pits_id_conflicts"):
                st.warning(
                    "Multiple PITS IDs are assigned to "
                    f"{summary['bom_pits_id_conflicts']} part(s) in the BOM sheet. "
                    "Those catalog PITS IDs were left unchanged.",
                    icon=":material/warning:",
                )
            if summary.get("pits_id_conflicts"):
                st.warning(
                    f"{summary['pits_id_conflicts']} repeated tracker part number(s) did not have "
                    "one matching PITS ID in the BOM sheet, so their catalog PITS IDs were left unchanged.",
                    icon=":material/warning:",
                )

        uploaded = st.file_uploader("Excel, CSV, TSV, or pasted text file", type=["xlsx", "xlsm", "csv", "tsv", "txt"])
        last_file_token_key = f"pits_last_uploaded_token_{project_id}"
        current_file_token = (uploaded.name, uploaded.size) if uploaded else None
        if current_file_token != st.session_state.get(last_file_token_key):
            st.session_state[last_file_token_key] = current_file_token
            st.session_state.pop(completion_key, None)
            st.session_state.pop(wizard_key, None)
        if uploaded:
            try:
                if has_pits_id_sheets(uploaded):
                    records, models, bom_snapshot = parse_pits_combined_workbook(uploaded)
                    id_resolution = pits_catalog_id_resolution(records)
                    st.success("ID-based PITS tracker detected", icon=":material/key:")
                    summary_cols = st.columns(3)
                    summary_cols[0].metric("PITS records", len(records))
                    summary_cols[1].metric("Unique IDs", len({record["pits_id"] for record in records}))
                    summary_cols[2].metric("Models", len(models))
                    st.caption(
                        "ID Number is the stable source key. When a tracker part number has multiple IDs, "
                        "the BOM sheet's column-A PITS ID is used if it provides one unique match. Re-imports "
                        "create source revisions and flag changed MBOM candidates without overwriting collaborator decisions."
                    )
                    preview = [
                        {
                            key: value for key, value in record.items()
                            if key != "source_payload" and not key.startswith("_")
                        }
                        for record in records
                    ]
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
                    blocking_bom_issues = [
                        issue for issue in bom_issues if issue.get("blocking")
                    ]
                    if bom_snapshot.get("sheet_name"):
                        source_root_depth = int(bom_snapshot.get("source_root_depth") or 1)
                        if source_root_depth > 1:
                            st.info(
                                f"This BOM starts at Level {source_root_depth}; that level will be "
                                "treated as the workbook's root while its original level is preserved.",
                                icon=":material/account_tree:",
                            )
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
                                issue_message = (
                                    f"Import is blocked by {len(blocking_bom_issues):,} BOM row issue(s)."
                                    if blocking_bom_issues
                                    else f"Found {len(bom_issues):,} nonblocking BOM row issue(s)."
                                )
                                if blocking_bom_issues:
                                    st.error(issue_message, icon=":material/error:")
                                else:
                                    st.warning(issue_message, icon=":material/warning:")
                                issue_preview = pd.DataFrame(
                                    [
                                        {
                                            "result": (
                                                "Blocks import"
                                                if issue.get("blocking")
                                                else "Flagged only"
                                            ),
                                            "source_row": issue.get("source_row"),
                                            "issue": issue.get("issue"),
                                            "child_tracker_number": issue.get(
                                                "child_tracker_number", ""
                                            ),
                                            "part_number": issue.get("part_number", ""),
                                            "description": issue.get("description", ""),
                                            "proposed_depth": issue.get("proposed_depth"),
                                            "expected_parent_level": issue.get(
                                                "expected_parent_level"
                                            ),
                                            "raw_quantity_text": issue.get(
                                                "raw_quantity_text", ""
                                            ),
                                        }
                                        for issue in bom_issues
                                    ]
                                )
                                selectable_dataframe(
                                    issue_preview,
                                    key=f"pits_bom_issue_preview_{project_id}",
                                    hide_index=True,
                                    height=360,
                                    column_config={
                                        "result": "Import result",
                                        "source_row": st.column_config.NumberColumn(
                                            "Excel row", format="%d"
                                        ),
                                        "issue": st.column_config.TextColumn(
                                            "Issue", width="large"
                                        ),
                                        "child_tracker_number": "Tracker number (Column A)",
                                        "part_number": "Part number (Column B)",
                                        "description": "Description (Column C)",
                                        "proposed_depth": "Populated level",
                                        "expected_parent_level": "Expected parent level",
                                        "raw_quantity_text": "Level-cell value",
                                    },
                                )
                            if bom_duplicates:
                                st.warning(
                                    f"Found {len(bom_duplicates):,} additional duplicate BOM occurrence row(s). "
                                    "The retained occurrences will be flagged for review.",
                                    icon=":material/warning:",
                                )
                    else:
                        st.warning(
                            "This PITS workbook has no recognized BOM worksheet. Tracker and Models "
                            "can still be imported, but Model Tree will remain unchanged.",
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
                    if id_resolution["multiple_bom_ids"]:
                        st.warning(
                            "Multiple PITS IDs are assigned to "
                            f"{len(id_resolution['multiple_bom_ids']):,} part(s) in the BOM sheet. "
                            "Those part numbers cannot be resolved to one catalog PITS ID from the BOM.",
                            icon=":material/warning:",
                        )
                    conflict_parts = pits_import_conflict_parts(project_id, records)
                    manual_conflicts = [c for c in conflict_parts if c.get("conflict_type") == "manual_values"]
                    tracker_conflicts = [c for c in conflict_parts if c.get("conflict_type") == "tracker_number_reassigned"]
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
                    pending_part_reviews = detect_pits_new_and_changed_parts(project_id, records, bom_snapshot=bom_snapshot)
                    if pending_part_reviews:
                        replacements_count = sum(1 for r in pending_part_reviews if r.get("replaces_part_number"))
                        new_count = sum(1 for r in pending_part_reviews if r["change_type"] == "new_part" and not r.get("replaces_part_number"))
                        changed_count = sum(1 for r in pending_part_reviews if r["change_type"] == "changed_description")
                        details = []
                        if replacements_count:
                            details.append(f"{replacements_count} part replacement(s)")
                        if new_count:
                            details.append(f"{new_count} new part number(s)")
                        if changed_count:
                            details.append(f"{changed_count} modified description(s)")
                        st.info(
                            f"PITS upload contains {' and '.join(details)} that require verification before import.",
                            icon=":material/rule:",
                        )
                        if st.button(
                            f"Review & Import PITS snapshot ({len(pending_part_reviews)} to verify)",
                            type="primary",
                            icon=":material/verified_user:",
                            disabled=bool(blocking_bom_issues),
                            key=f"start_pits_review_{project_id}",
                        ):
                            uploaded_wrapper = _UploadedFileWrapper(uploaded)
                            st.session_state[wizard_key] = {
                                "project_id": project_id,
                                "scenario_id": scenario_id,
                                "records": records,
                                "models": models,
                                "bom_snapshot": bom_snapshot,
                                "uploaded": uploaded_wrapper,
                                "confirm_overwrite_manual": confirm_overwrite_manual,
                                "pending_reviews": pending_part_reviews,
                                "current_step": 0,
                                "acknowledged_parts": [],
                            }
                            st.rerun()
                    else:
                        if st.button(
                            "Import PITS snapshot",
                            type="primary",
                            icon=":material/upload:",
                            disabled=bool(blocking_bom_issues),
                            key=f"import_pits_snapshot_{project_id}",
                        ):
                            result = _execute_pits_import(
                                project_id,
                                scenario_id,
                                records,
                                models,
                                bom_snapshot,
                                uploaded,
                                overwrite_manual=confirm_overwrite_manual,
                                editor_name=st.session_state.get("current_editor", ""),
                                acknowledged_parts=[],
                            )
                            st.session_state[completion_key] = result
                            st.rerun()
                else:
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
                    else:
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
                        preview_for_display["model_applicability"] = [
                            ", ".join(
                                "All models" if model.casefold() in {"all", "all models"} else model_labels.get(model, model)
                                for model in (split_filter_values(value) or ["All"])
                            )
                            for value in preview_for_display["model_applicability"]
                        ]
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
        scenario = get_planning_scenario(project_id, scenario_id) if scenario_id else None
        safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in project["name"])
        revision_label = scenario["revision_label"] if scenario else project["revision"]
        st.download_button(
            "Download Excel workbook",
            data=lambda: export_workbook(project_id, scenario_id),
            file_name=f"{safe_name}_rev_{revision_label}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            icon=":material/download:",
        )



def render_pits_exchange_history(project_id: str) -> None:
    with st.expander("History", icon=":material/history:"):
        pits_history_tab, pits_bom_history_tab, mbom_history_tab, parts_history_tab = st.tabs(
            ["PITS snapshots", "PITS BOM structure", "MBOM review", "Parts import"]
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
