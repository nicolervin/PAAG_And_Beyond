import json
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.clipboard_image import as_uploaded_file, clipboard_image, decode_clipboard_image
from utils.scope_ui import page_title_with_scope
from utils.store import (
    add_assembly_image,
    assembly_bom_components,
    assembly_catalog_delete_impact,
    assembly_catalog_rows,
    assembly_feature_rules,
    assembly_images,
    assembly_model_applicability,
    assembly_sections,
    audit_history,
    complexity_features,
    delete_assembly_catalog_rows,
    delete_assembly_images,
    fishbone_part_assignments,
    record_audit_event,
    save_assembly_bom_components,
    save_assembly_catalog_rows,
    save_assembly_feature_rules,
    set_assembly_image,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    direct_entry_editor_rows,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    format_clean_number,
    native_selected_rows,
    part_number_cell_style,
    selectable_dataframe,
    standard_details_column_config,
    table_has_unsaved_changes,
)


project_id = st.session_state.get("project_id")
page_title_with_scope("Assemblies", scope="project")
st.caption(
    "Maintain real assembly numbers, their built and installed Fishbone sections, explicit "
    "mini-BOMs, model rules, nesting, and images."
)
if not project_id:
    st.stop()

catalog_editor_key = f"assembly_catalog_editor_{project_id}"
selected_assembly_key = f"assemblies_selected_id_{project_id}"
apply_pending_table_editor_reset(catalog_editor_key)

catalog = assembly_catalog_rows(project_id)
sections = assembly_sections(project_id)
section_name_by_id = (
    {str(row["id"]): str(row["name"]) for _, row in sections.iterrows()}
    if not sections.empty else {}
)
section_id_by_name = {name: section_id for section_id, name in section_name_by_id.items()}


def empty_catalog_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": pd.Series(dtype="string"),
            "assembly_number": pd.Series(dtype="string"),
            "name": pd.Series(dtype="string"),
            "make_buy": pd.Series(dtype="string"),
            "built_section_id": pd.Series(dtype="string"),
            "installed_section_id": pd.Series(dtype="string"),
            "parent_id": pd.Series(dtype="string"),
            "active": pd.Series(dtype="bool"),
            "notes": pd.Series(dtype="string"),
        }
    )


def save_catalog_records(records: list[dict]) -> None:
    result = save_assembly_catalog_rows(project_id, records)
    record_audit_event(
        project_id,
        "Assemblies catalog",
        "Save & Refresh",
        result["count"],
        st.session_state.get("current_editor", ""),
        {
            "assembly_ids": result["assembly_ids"],
            "make_buy_changes": result["make_buy_changes"],
            "nesting_mismatch_count": len(result["mismatch_warnings"]),
            "updated_at": result["updated_at"],
        },
    )
    st.session_state.pop(f"assembly_catalog_pending_save_{project_id}", None)
    request_table_editor_reset(catalog_editor_key)
    st.toast(f"Saved {result['count']} assemblies", icon=":material/check_circle:")
    st.rerun()


editable_table_heading("Assembly catalog")
st.caption(
    "Built section is where component work occurs. Installed section is where the completed "
    "assembly will eventually be available to downstream Process planning."
)
if sections.empty:
    st.info("Create at least one Fishbone section before adding an assembly.")
else:
    catalog_source = catalog.copy() if not catalog.empty else empty_catalog_rows()
    catalog_source["make_buy"] = (
        catalog_source.get("make_buy", pd.Series(dtype="string"))
        .fillna("")
        .astype("string")
        .replace("", pd.NA)
    )
    catalog_source["make_buy_filter"] = catalog_source["make_buy"].fillna("Unclassified")
    assembly_number_by_id = (
        {str(row["id"]): str(row["assembly_number"]) for _, row in catalog.iterrows()}
        if not catalog.empty else {}
    )
    assembly_id_by_number = {
        number: assembly_id for assembly_id, number in assembly_number_by_id.items()
    }
    catalog_source["built_section"] = catalog_source.get(
        "built_section_id", pd.Series(dtype="string")
    ).map(section_name_by_id)
    catalog_source["installed_section"] = catalog_source.get(
        "installed_section_id", pd.Series(dtype="string")
    ).map(section_name_by_id)
    catalog_source["parent_assembly"] = catalog_source.get(
        "parent_id", pd.Series(dtype="string")
    ).map(assembly_number_by_id).fillna("No parent")
    catalog_source["details"] = ":material/open_in_new: Details"
    catalog_source["warnings"] = catalog_source.apply(
        lambda row: " · ".join(
            message for message in [
                (
                    f"{int(row.get('component_mismatch_count') or 0)} mini-BOM mismatch(es)"
                    if int(row.get("component_mismatch_count") or 0) else ""
                ),
                (
                    f"{int(row.get('stale_rule_count') or 0)} stale rule(s)"
                    if int(row.get("stale_rule_count") or 0) else ""
                ),
            ] if message
        ),
        axis=1,
    )
    full_catalog_source = catalog_source.copy()
    visible_catalog = filter_table(
        catalog_source,
        key=f"assembly_catalog_filters_{project_id}",
        dropdown_columns=["make_buy_filter", "built_section", "installed_section", "active"],
        search_columns=["assembly_number", "name", "notes"],
        labels={
            "built_section": "Built section",
            "installed_section": "Installed section",
            "make_buy_filter": "Make / buy",
            "active": "Active",
        },
        reset_widget_keys=[catalog_editor_key],
    )
    visible_catalog = direct_entry_editor_rows(
        visible_catalog,
        editor_key=catalog_editor_key,
        sort_columns=[
            "assembly_number", "name", "make_buy", "built_section", "installed_section"
        ],
    )

    def open_assembly_details() -> None:
        click = st.session_state.get("assembly_catalog_details_action") or {}
        if 0 <= int(click.get("row", -1)) < len(visible_catalog):
            assembly_id = str(visible_catalog.iloc[int(click["row"])].get("id") or "")
            if assembly_id:
                st.session_state[selected_assembly_key] = assembly_id

    edited_catalog = st.data_editor(
        visible_catalog,
        key=catalog_editor_key,
        hide_index=True,
        num_rows="dynamic",
        disabled=[
            "id", "details", "warnings", "component_count", "rule_count",
            "supplemental_image_count", "component_mismatch_count", "stale_rule_count",
        ],
        column_order=[
            "details", "assembly_number", "name", "make_buy", "built_section",
            "installed_section", "parent_assembly", "active", "notes", "warnings",
        ],
        column_config={
            "id": None,
            "details": standard_details_column_config(
                on_click=open_assembly_details, key="assembly_catalog_details_action"
            ),
            "assembly_number": st.column_config.TextColumn(
                "Assembly number", required=True, pinned=True
            ),
            "name": st.column_config.TextColumn("Assembly name", required=True, width="large"),
            "make_buy": st.column_config.SelectboxColumn(
                "Make / buy",
                options=["Make", "Buy"],
                help=(
                    "Make means the assembly is produced internally. Buy means it is obtained "
                    "as a complete assembly. This classification applies across every planning "
                    "scenario."
                ),
            ),
            "built_section": st.column_config.SelectboxColumn(
                "Built section",
                options=list(section_id_by_name),
                required=True,
                help="The Fishbone section containing the part uses eligible for this assembly's mini-BOM.",
            ),
            "installed_section": st.column_config.SelectboxColumn(
                "Installed section",
                options=list(section_id_by_name),
                required=True,
                help="The Fishbone section where the completed assembly is installed.",
            ),
            "parent_assembly": st.column_config.SelectboxColumn(
                "Parent assembly", options=["No parent", *list(assembly_id_by_number)]
            ),
            "active": st.column_config.CheckboxColumn("Active", default=True),
            "notes": st.column_config.TextColumn("Notes", width="large"),
            "warnings": st.column_config.TextColumn("Review", width="large"),
        },
    )
    catalog_actions = editable_table_footer(
        editor_key=catalog_editor_key,
        key_prefix="assembly_catalog",
        native_row_selection=True,
    )
    if catalog_actions.undo:
        st.session_state.pop(catalog_editor_key, None)
        st.toast("Discarded unsaved assembly edits", icon=":material/undo:")
        st.rerun()

    selected_catalog_rows = native_selected_rows(
        visible_catalog, editor_key=catalog_editor_key
    )
    catalog_delete_key = f"assembly_catalog_pending_delete_{project_id}"
    if not selected_catalog_rows.empty and not table_has_unsaved_changes(
        catalog_editor_key, native_row_selection=True
    ):
        st.session_state[catalog_delete_key] = selected_catalog_rows["id"].astype(str).tolist()

    @st.dialog("Delete selected assemblies?", width="large")
    def confirm_catalog_delete() -> None:
        pending_ids = st.session_state.get(catalog_delete_key, [])
        try:
            impact = assembly_catalog_delete_impact(project_id, pending_ids)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.warning(
            f"Delete {impact['selected_count']} selected assembly record(s)? "
            f"The complete tree contains {impact['descendant_count']} child assembly record(s)."
        )
        st.markdown(
            f"- **{impact['component_count']}** mini-BOM row(s)\n"
            f"- **{impact['rule_count']}** feature-rule row(s)\n"
            f"- **{impact['primary_image_count']}** primary image(s)\n"
            f"- **{impact['supplemental_image_count']}** supplemental image row(s)\n"
            f"- **{impact['image_file_count']}** owned uploaded image file(s)\n"
            f"- **{impact['policy_count']}** dormant scenario-policy row(s)\n"
            f"- **{impact['material_option_count']}** dormant material-option row(s)\n"
            f"- **{impact['target_assembly_link_count']}** dormant target-assembly link(s)"
        )
        level_actions = {}
        for depth, level_rows in sorted(impact["levels"].items()):
            labels = ", ".join(str(row["assembly_number"]) for row in level_rows)
            if depth == 0:
                st.caption(f"Selected for deletion: {labels}")
                continue
            level_actions[depth] = st.selectbox(
                f"Child level {depth}: {labels}",
                ["Move to grandparent", "Delete entirely", "Become unassigned"],
                key=f"assembly_delete_level_{project_id}_{depth}",
            )
        action_row = st.container(horizontal=True)
        if action_row.button("Cancel", key=f"cancel_assembly_delete_{project_id}"):
            st.session_state.pop(catalog_delete_key, None)
            request_table_editor_reset(catalog_editor_key)
            st.rerun()
        if action_row.button(
            "Delete assemblies",
            type="primary",
            icon=":material/delete:",
            key=f"destructive_confirm_assembly_delete_{project_id}",
        ):
            result = delete_assembly_catalog_rows(project_id, pending_ids, level_actions)
            record_audit_event(
                project_id,
                "Assemblies catalog",
                "Bulk delete",
                result["deleted_count"],
                st.session_state.get("current_editor", ""),
                {
                    "selected_ids": pending_ids,
                    "deleted_count": result["deleted_count"],
                    "level_actions": level_actions,
                    "component_count": result["component_count"],
                    "rule_count": result["rule_count"],
                    "policy_count": result["policy_count"],
                },
            )
            if st.session_state.get(selected_assembly_key) in result["affected_ids"]:
                st.session_state.pop(selected_assembly_key, None)
            st.session_state.pop(catalog_delete_key, None)
            request_table_editor_reset(catalog_editor_key)
            st.toast(f"Deleted {result['deleted_count']} assemblies", icon=":material/delete:")
            st.rerun()

    if st.session_state.get(catalog_delete_key):
        confirm_catalog_delete()

    merged_catalog = merge_filtered_edits(
        full_catalog_source, visible_catalog, edited_catalog
    )
    merged_catalog = drop_untouched_new_rows(
        merged_catalog, identifying_columns=["assembly_number", "name"]
    )
    catalog_records = []
    for _, row in merged_catalog.iterrows():
        row_id = "" if pd.isna(row.get("id")) else str(row.get("id") or "").strip()
        catalog_records.append(
            {
                "id": row_id or str(uuid4()),
                "assembly_number": str(row.get("assembly_number") or "").strip(),
                "name": str(row.get("name") or "").strip(),
                "make_buy": (
                    "" if pd.isna(row.get("make_buy"))
                    else str(row.get("make_buy") or "").strip()
                ),
                "built_section_id": section_id_by_name.get(str(row.get("built_section") or "")),
                "installed_section_id": section_id_by_name.get(
                    str(row.get("installed_section") or "")
                ),
                "parent_id": assembly_id_by_number.get(
                    str(row.get("parent_assembly") or "")
                ),
                "active": True if pd.isna(row.get("active")) else bool(row.get("active")),
                "notes": str(row.get("notes") or "").strip(),
            }
        )

    @st.dialog("Review assembly nesting", width="large")
    def confirm_catalog_mismatch_save() -> None:
        pending = st.session_state.get(f"assembly_catalog_pending_save_{project_id}", [])
        by_id = {row["id"]: row for row in pending}
        mismatches = []
        for row in pending:
            parent = by_id.get(row.get("parent_id"))
            if parent and row.get("installed_section_id") != parent.get("built_section_id"):
                mismatches.append(
                    f"{row['assembly_number']} is installed in "
                    f"{section_name_by_id.get(row.get('installed_section_id'), 'Unknown')} while "
                    f"parent {parent['assembly_number']} is built in "
                    f"{section_name_by_id.get(parent.get('built_section_id'), 'Unknown')}."
                )
        st.warning("The selected nesting does not match the expected built/installed pattern.")
        for mismatch in mismatches:
            st.write(f"- {mismatch}")
        st.caption("This is a review warning only. You may save the selected parent relationship.")
        actions = st.container(horizontal=True)
        if actions.button("Review table", key=f"review_assembly_nesting_{project_id}"):
            st.session_state.pop(f"assembly_catalog_pending_save_{project_id}", None)
            st.rerun()
        if actions.button(
            "Save anyway",
            type="primary",
            icon=":material/save:",
            key=f"save_assembly_nesting_anyway_{project_id}",
        ):
            save_catalog_records(pending)

    if catalog_actions.save_and_refresh:
        try:
            if not selected_catalog_rows.empty:
                raise ValueError("Clear selected assembly rows before saving.")
            by_id = {row["id"]: row for row in catalog_records}
            mismatched = any(
                by_id.get(row.get("parent_id"))
                and row.get("installed_section_id")
                != by_id[row["parent_id"]].get("built_section_id")
                for row in catalog_records
            )
            if mismatched:
                st.session_state[f"assembly_catalog_pending_save_{project_id}"] = catalog_records
            else:
                save_catalog_records(catalog_records)
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.get(f"assembly_catalog_pending_save_{project_id}"):
        confirm_catalog_mismatch_save()

    st.download_button(
        "Export filtered assemblies",
        dataframe_to_excel(
            visible_catalog.drop(columns=["details", "make_buy_filter"], errors="ignore"),
            "Assemblies",
        ),
        file_name="assemblies.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
    )


catalog = assembly_catalog_rows(project_id)
if not catalog.empty:
    valid_ids = set(catalog["id"].astype(str))
    if st.session_state.get(selected_assembly_key) not in valid_ids:
        st.session_state[selected_assembly_key] = str(catalog.iloc[0]["id"])
    assembly_id = str(st.session_state[selected_assembly_key])
    assembly = catalog.loc[catalog["id"].astype(str).eq(assembly_id)].iloc[0].to_dict()
    st.subheader(f"Assembly details · {assembly['assembly_number']} {assembly['name']}")
    bom_tab, rules_tab, images_tab = st.tabs(["Mini-BOM", "Feature rules", "Images"])

    with bom_tab:
        st.caption(
            f"Components must come from exact Fishbone uses in Built section: "
            f"{assembly.get('built_section_name') or 'Not assigned'}. Quantities are independent after saving."
        )
        components = assembly_bom_components(project_id, assembly_id)
        if components.empty:
            if str(assembly.get("make_buy") or "") == "Buy":
                st.caption(
                    "No components listed. A Buy assembly may intentionally have an empty mini-BOM."
                )
            elif str(assembly.get("make_buy") or "") == "Make":
                st.caption("No components listed yet.")
            else:
                st.caption("No components listed.")
        all_uses = fishbone_part_assignments(project_id)
        eligible = all_uses.loc[
            all_uses["section_id"].astype(str).eq(str(assembly.get("built_section_id") or ""))
        ].copy() if not all_uses.empty else all_uses
        existing_use_ids = (
            set(components["fishbone_assignment_id"].astype(str))
            if not components.empty else set()
        )
        use_options = eligible.copy()
        if existing_use_ids and not all_uses.empty:
            use_options = pd.concat(
                [use_options, all_uses.loc[all_uses["id"].astype(str).isin(existing_use_ids)]],
                ignore_index=True,
            ).drop_duplicates("id")
        use_label_by_id = {
            str(row["id"]): (
                f"{row['part_number']} · {row.get('use_description') or 'No use description'} "
                f"· Fishbone qty {format_clean_number(row['quantity'])}"
            )
            for _, row in use_options.iterrows()
        }
        use_id_by_label = {label: use_id for use_id, label in use_label_by_id.items()}
        bom_editor_key = f"assembly_bom_editor_{assembly_id}"
        apply_pending_table_editor_reset(bom_editor_key)
        if components.empty:
            bom_source = pd.DataFrame(
                {
                    "id": pd.Series(dtype="string"),
                    "part_number": pd.Series(dtype="string"),
                    "fishbone_use": pd.Series(dtype="string"),
                    "quantity": pd.Series(dtype="float"),
                    "status": pd.Series(dtype="string"),
                }
            )
        else:
            bom_source = components.copy()
            bom_source["fishbone_use"] = bom_source["fishbone_assignment_id"].astype(str).map(
                use_label_by_id
            )
            bom_source["status"] = bom_source["section_mismatch"].map(
                lambda value: "Warning: Fishbone use is outside the Built section" if value else "Current"
            )
        bom_source = direct_entry_editor_rows(
            bom_source,
            editor_key=bom_editor_key,
            sort_columns=["part_number", "fishbone_use", "quantity"],
        )
        styled_bom_source = bom_source.style.map(
            part_number_cell_style, subset=["part_number"]
        )
        edited_bom = st.data_editor(
            styled_bom_source,
            key=bom_editor_key,
            hide_index=True,
            num_rows="dynamic",
            disabled=["id", "part_number", "status"],
            column_order=["part_number", "fishbone_use", "quantity", "status"],
            column_config={
                "id": None,
                "part_number": st.column_config.TextColumn(
                    "Part number", pinned=True
                ),
                "fishbone_use": st.column_config.SelectboxColumn(
                    "Fishbone use", options=list(use_id_by_label), required=True, width="large"
                ),
                "quantity": st.column_config.NumberColumn(
                    "Quantity", step=0.01, format="%g",
                    help="A blank new quantity defaults to the Fishbone quantity when saved.",
                ),
                "status": st.column_config.TextColumn("Review", width="large"),
            },
        )
        bom_actions = editable_table_footer(
            editor_key=bom_editor_key,
            key_prefix=f"assembly_bom_{assembly_id}",
            native_row_selection=True,
        )
        if bom_actions.undo:
            st.session_state.pop(bom_editor_key, None)
            st.rerun()
        selected_bom = native_selected_rows(bom_source, editor_key=bom_editor_key)
        bom_to_save = drop_untouched_new_rows(
            edited_bom, identifying_columns=["fishbone_use"]
        )
        bom_records = [
            {
                "id": "" if pd.isna(row.get("id")) else str(row.get("id") or ""),
                "fishbone_assignment_id": use_id_by_label.get(str(row.get("fishbone_use") or "")),
                "quantity": row.get("quantity"),
            }
            for _, row in bom_to_save.iterrows()
        ]

        @st.dialog("Delete selected mini-BOM rows?")
        def confirm_bom_delete() -> None:
            st.warning(
                f"Delete {len(selected_bom)} selected component row(s) from "
                f"assembly {assembly['assembly_number']}? Fishbone uses remain unchanged."
            )
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_bom_delete_{assembly_id}"):
                request_table_editor_reset(bom_editor_key)
                st.rerun()
            if actions.button(
                "Delete components", type="primary", icon=":material/delete:",
                key=f"destructive_bom_delete_{assembly_id}",
            ):
                result = save_assembly_bom_components(project_id, assembly_id, bom_records)
                record_audit_event(
                    project_id, "Assembly mini-BOM", "Delete components", len(selected_bom),
                    st.session_state.get("current_editor", ""),
                    {"assembly_id": assembly_id, "remaining_count": result["count"]},
                )
                request_table_editor_reset(bom_editor_key)
                st.rerun()

        if not selected_bom.empty:
            confirm_bom_delete()
        if bom_actions.save_and_refresh:
            try:
                if not selected_bom.empty:
                    raise ValueError("Clear selected mini-BOM rows before saving.")
                result = save_assembly_bom_components(project_id, assembly_id, bom_records)
                record_audit_event(
                    project_id, "Assembly mini-BOM", "Save & Refresh", result["count"],
                    st.session_state.get("current_editor", ""),
                    {"assembly_id": assembly_id, "updated_at": result["updated_at"]},
                )
                request_table_editor_reset(bom_editor_key)
                st.toast("Saved assembly mini-BOM", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with rules_tab:
        saved_rules = assembly_feature_rules(project_id, assembly_id)
        features = complexity_features(project_id)
        active_features = (
            features.loc[features["active"].fillna(1).astype(bool)].copy()
            if not features.empty else features
        )
        feature_label_by_id = {
            str(row["id"]): f"{row['category']} · {row['name']}"
            for _, row in features.iterrows()
        }
        feature_id_by_label = {label: feature_id for feature_id, label in feature_label_by_id.items()}
        saved_signature = tuple(
            (str(row["id"]), str(row["feature_id"]), str(row["value"]))
            for _, row in saved_rules.iterrows()
        ) if not saved_rules.empty else ()
        rules_draft_key = f"assembly_rules_draft_{assembly_id}"
        rules_signature_key = f"assembly_rules_signature_{assembly_id}"
        if st.session_state.get(rules_signature_key) != saved_signature:
            st.session_state[rules_signature_key] = saved_signature
            st.session_state[rules_draft_key] = [
                {"id": item[0], "feature_id": item[1], "value": item[2]}
                for item in saved_signature
            ]
        draft_rules = list(st.session_state.get(rules_draft_key, []))
        controls = st.container(horizontal=True, vertical_alignment="bottom")
        active_labels = [
            feature_label_by_id[str(row["id"])] for _, row in active_features.iterrows()
        ]
        selected_feature_label = controls.selectbox(
            "Feature", active_labels, key=f"assembly_rule_feature_{assembly_id}"
        ) if active_labels else None
        selected_feature_id = feature_id_by_label.get(selected_feature_label or "")
        feature_row = (
            features.loc[features["id"].astype(str).eq(str(selected_feature_id))].iloc[0]
            if selected_feature_id and not features.empty else None
        )
        choices = json.loads(feature_row["allowed_values"] or "[]") if feature_row is not None else []
        selected_choice = controls.selectbox(
            "Choice", [str(choice) for choice in choices],
            key=f"assembly_rule_choice_{assembly_id}",
        ) if choices else None
        if controls.button(
            "Add rule", icon=":material/add:", disabled=not selected_feature_id or not selected_choice,
            key=f"assembly_add_rule_{assembly_id}",
        ):
            if any(rule["feature_id"] == selected_feature_id for rule in draft_rules):
                st.error("This assembly already has a rule for that feature.")
            else:
                draft_rules.append(
                    {"id": str(uuid4()), "feature_id": selected_feature_id, "value": selected_choice}
                )
                st.session_state[rules_draft_key] = draft_rules
                st.rerun()
        rule_rows = pd.DataFrame(
            [
                {
                    **rule,
                    "feature": feature_label_by_id.get(rule["feature_id"], "Removed feature"),
                    "choice": rule["value"],
                    "warning": (
                        str(saved_rules.loc[saved_rules["id"].astype(str).eq(rule["id"]), "warning"].iloc[0])
                        if not saved_rules.empty
                        and saved_rules["id"].astype(str).eq(rule["id"]).any() else ""
                    ),
                }
                for rule in draft_rules
            ]
        )
        if rule_rows.empty:
            st.info("No rules recorded. This assembly applies to all models.")
            st.write("**This assembly applies to: All models**")
        else:
            st.write(
                "**This assembly applies where: "
                + " AND ".join(f"{row['feature']} = {row['choice']}" for _, row in rule_rows.iterrows())
                + "**"
            )
            rule_editor_key = f"assembly_rule_list_{assembly_id}"
            apply_pending_table_editor_reset(rule_editor_key)
            rule_editor = st.data_editor(
                rule_rows,
                key=rule_editor_key,
                hide_index=True,
                num_rows="delete",
                disabled=list(rule_rows.columns),
                column_order=["feature", "choice", "warning"],
                column_config={"id": None, "feature_id": None, "warning": "Review"},
            )
            selected_rules = native_selected_rows(rule_rows, editor_key=rule_editor_key)

            @st.dialog("Remove selected assembly rules?")
            def confirm_rule_removal() -> None:
                st.warning(
                    f"Remove {len(selected_rules)} selected rule(s) from assembly "
                    f"{assembly['assembly_number']}? This changes the unsaved draft; use "
                    "Save & Refresh to persist the removal."
                )
                actions = st.container(horizontal=True)
                if actions.button("Cancel", key=f"cancel_rule_removal_{assembly_id}"):
                    request_table_editor_reset(rule_editor_key)
                    st.rerun()
                if actions.button(
                    "Remove rules", type="primary", icon=":material/delete:",
                    key=f"confirm_rule_removal_{assembly_id}",
                ):
                    selected_ids = set(selected_rules["id"].astype(str))
                    st.session_state[rules_draft_key] = [
                        rule for rule in draft_rules if rule["id"] not in selected_ids
                    ]
                    request_table_editor_reset(rule_editor_key)
                    st.rerun()

            if not selected_rules.empty:
                confirm_rule_removal()
        current_signature = tuple(
            (rule["id"], rule["feature_id"], rule["value"]) for rule in draft_rules
        )
        rules_dirty = current_signature != saved_signature
        rules_footer_key = f"assembly_rules_footer_{assembly_id}"
        rules_actions = editable_table_footer(
            editor_key=rules_footer_key,
            key_prefix=f"assembly_rules_{assembly_id}",
            additional_unsaved_changes=rules_dirty,
        )
        if rules_actions.undo:
            st.session_state[rules_draft_key] = [
                {"id": item[0], "feature_id": item[1], "value": item[2]}
                for item in saved_signature
            ]
            st.rerun()
        if rules_actions.save_and_refresh:
            try:
                result = save_assembly_feature_rules(project_id, assembly_id, draft_rules)
                record_audit_event(
                    project_id, "Assembly feature rules", "Save & Refresh", result["count"],
                    st.session_state.get("current_editor", ""),
                    {"assembly_id": assembly_id, "updated_at": result["updated_at"]},
                )
                st.session_state.pop(rules_draft_key, None)
                st.session_state.pop(rules_signature_key, None)
                st.toast("Saved assembly feature rules", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        applicability = assembly_model_applicability(project_id, assembly_id)
        if applicability["stale"]:
            st.warning("A stale rule fails closed, so this assembly currently matches no models.")
        else:
            model_names = applicability["models"].get("model_number", pd.Series(dtype="string")).astype(str).tolist()
            st.caption("Matching official models: " + (", ".join(model_names) or "None"))

    with images_tab:
        image_path = Path(str(assembly.get("image_path") or ""))
        st.subheader("Primary assembly image")
        if image_path.is_file():
            st.image(str(image_path), caption=str(assembly["assembly_number"]))
        else:
            st.caption("No primary image attached.")
        primary_upload = st.file_uploader(
            "Upload primary assembly image", type=["png", "jpg", "jpeg", "webp"],
            key=f"assembly_primary_upload_{assembly_id}",
        )
        if primary_upload and st.button(
            "Save primary image", type="primary", icon=":material/upload:",
            key=f"save_assembly_primary_{assembly_id}",
        ):
            set_assembly_image(project_id, assembly_id, primary_upload)
            record_audit_event(
                project_id, "Assembly images", "Save primary image", 1,
                st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
            )
            st.rerun()
        st.caption("Or paste a Windows screenshot; it saves immediately as the primary image.")
        primary_paste = clipboard_image(key=f"assembly_primary_paste_{assembly_id}")
        if getattr(primary_paste, "image", None):
            try:
                payload = decode_clipboard_image(primary_paste.image)
                set_assembly_image(project_id, assembly_id, as_uploaded_file(payload))
                record_audit_event(
                    project_id, "Assembly images", "Paste primary image", 1,
                    st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
                )
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        st.subheader("Supplemental images")
        supplemental = assembly_images(project_id, assembly_id)
        for image in supplemental:
            supplemental_path = Path(str(image["image_path"]))
            if supplemental_path.is_file():
                st.image(str(supplemental_path), caption=image.get("caption") or "Supplemental image")
        extra_caption = st.text_input("Supplemental image caption", key=f"assembly_extra_caption_{assembly_id}")
        extra_upload = st.file_uploader(
            "Upload supplemental image", type=["png", "jpg", "jpeg", "webp"],
            key=f"assembly_extra_upload_{assembly_id}",
        )
        if extra_upload and st.button(
            "Add supplemental image", icon=":material/add_photo_alternate:",
            key=f"add_assembly_extra_{assembly_id}",
        ):
            add_assembly_image(project_id, assembly_id, extra_upload, extra_caption)
            record_audit_event(
                project_id, "Assembly images", "Add supplemental image", 1,
                st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
            )
            st.rerun()
        st.caption("You can also paste a screenshot as a supplemental image.")
        supplemental_paste = clipboard_image(key=f"assembly_extra_paste_{assembly_id}")
        if getattr(supplemental_paste, "image", None):
            try:
                payload = decode_clipboard_image(supplemental_paste.image)
                add_assembly_image(
                    project_id, assembly_id, as_uploaded_file(payload), extra_caption
                )
                record_audit_event(
                    project_id, "Assembly images", "Paste supplemental image", 1,
                    st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
                )
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        if supplemental:
            image_table = pd.DataFrame(supplemental)[["id", "caption", "created_at"]]
            image_editor_key = f"assembly_image_selection_{assembly_id}"
            apply_pending_table_editor_reset(image_editor_key)
            st.data_editor(
                image_table,
                key=image_editor_key,
                hide_index=True,
                num_rows="delete",
                disabled=list(image_table.columns),
                column_config={"id": None, "caption": "Caption", "created_at": "Added"},
            )
            selected_images = native_selected_rows(
                image_table, editor_key=image_editor_key
            )
            if not selected_images.empty:
                st.session_state[f"assembly_images_pending_delete_{assembly_id}"] = (
                    selected_images["id"].astype(str).tolist()
                )

            @st.dialog("Delete selected assembly images?")
            def confirm_image_delete() -> None:
                pending_key = f"assembly_images_pending_delete_{assembly_id}"
                pending_ids = st.session_state.get(pending_key, [])
                st.warning(
                    f"Delete {len(pending_ids)} supplemental image(s) from "
                    f"assembly {assembly['assembly_number']}? The uploaded files will also be removed."
                )
                actions = st.container(horizontal=True)
                if actions.button("Cancel", key=f"cancel_assembly_image_delete_{assembly_id}"):
                    st.session_state.pop(pending_key, None)
                    request_table_editor_reset(image_editor_key)
                    st.rerun()
                if actions.button(
                    "Delete images", type="primary", icon=":material/delete:",
                    key=f"destructive_confirm_assembly_image_delete_{assembly_id}",
                ):
                    count = delete_assembly_images(
                        project_id, assembly_id, pending_ids
                    )
                    record_audit_event(
                        project_id, "Assembly images", "Delete supplemental images", count,
                        st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
                    )
                    st.session_state.pop(pending_key, None)
                    request_table_editor_reset(image_editor_key)
                    st.rerun()

            if st.session_state.get(f"assembly_images_pending_delete_{assembly_id}"):
                confirm_image_delete()


with st.expander("History", icon=":material/history:"):
    history_tabs = st.tabs(["Catalog", "Mini-BOM", "Feature rules", "Images"])
    for tab, table_name in zip(
        history_tabs,
        ["Assemblies catalog", "Assembly mini-BOM", "Assembly feature rules", "Assembly images"],
    ):
        with tab:
            history = audit_history(project_id, table_name, limit=50)
            if history.empty:
                st.caption("No standardized changes recorded yet.")
            else:
                if table_name == "Assemblies catalog":
                    def make_buy_history_summary(raw_details) -> str:
                        try:
                            details = json.loads(str(raw_details or "{}"))
                        except (TypeError, json.JSONDecodeError):
                            return ""
                        summaries = []
                        for change in details.get("make_buy_changes", []):
                            old_value = str(change.get("old_value") or "Unclassified")
                            new_value = str(change.get("new_value") or "Unclassified")
                            summaries.append(
                                f"{change.get('assembly_number') or 'Unknown assembly'}: "
                                f"{old_value} → {new_value}"
                            )
                        return "; ".join(summaries)

                    history = history.copy()
                    history["make_buy_changes"] = history["details"].apply(
                        make_buy_history_summary
                    )
                history_column_config = {
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                }
                if "make_buy_changes" in history.columns:
                    history_column_config["make_buy_changes"] = st.column_config.TextColumn(
                        "Make / buy changes", width="large"
                    )
                selectable_dataframe(
                    history.drop(columns=["details"], errors="ignore"),
                    key=f"assembly_history_{project_id}_{table_name}",
                    hide_index=True,
                    column_config=history_column_config,
                )
