import json
from html import escape

import pandas as pd
import streamlit as st

from utils.store import (
    assembly_grid_model_mappings,
    audit_history,
    complexity_feature_delete_impacts,
    complexity_features,
    complexity_planning_snapshot,
    complexity_tree,
    delete_project_models,
    model_planning_snapshot,
    potential_duplicate_models,
    project_models,
    record_audit_event,
    restore_model_planning_snapshot,
    restore_complexity_planning_snapshot,
    update_complexity_features,
    update_complexity_tree,
    update_project_model_rows,
)
from utils.scope_ui import page_title_with_scope
from utils.table_ui import (
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    direct_entry_editor_rows,
    selectable_dataframe,
    stage_native_delete_confirmation,
    table_has_unsaved_changes,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    has_unsaved_table_changes,
    request_table_editor_reset,
)


project_id = st.session_state.get("project_id")
page_title_with_scope("Model definitions", scope="project")
st.caption("Translate each Official model number into the Common name and description the IE and lean team use during planning.")
if not project_id:
    st.stop()
model_editor_key = apply_pending_table_editor_reset("model_definitions_editor_v2")
feature_editor_key = apply_pending_table_editor_reset("complexity_feature_editor")
tree_editor_key = apply_pending_table_editor_reset("complexity_tree_editor")

models = project_models(project_id)
model_undo_key = f"model_information_undo_{project_id}"
current_model_snapshot = model_planning_snapshot(project_id)
for column, default in {
    "active": True,
    "source_payload": "{}",
}.items():
    if column not in models.columns:
        models[column] = pd.Series(dtype="bool" if column == "active" else "string")

active_count = int(models["active"].fillna(1).astype(bool).sum())
summary = st.columns(3)
summary[0].metric("Defined models", len(models))
summary[1].metric("Active for planning", active_count)
summary[2].metric("Imported from PITS", int(models["source_payload"].fillna("{}").ne("{}").sum()))

has_unsaved_changes = table_has_unsaved_changes(
    model_editor_key, native_row_selection=True
)
editable_table_heading("Model information")
st.caption("Official model number stays tied to the official source. Edit the Common name and turn off models that should not appear in the Parts Catalog.")
st.caption("Type or paste new model rows directly into the blank entry row, then save.")
definition_columns = [
    "id", "model_number", "display_name", "eau", "description", "active", "notes",
    "updated_at",
]
for column in definition_columns:
    if column not in models.columns:
        models[column] = pd.NA

models_for_editing = models.reindex(columns=definition_columns)
visible_models = filter_table(
    models_for_editing,
    key="model_definition_filters",
    dropdown_columns=["active"],
    search_columns=["model_number", "display_name", "description"],
    labels={"active": "Planning status"},
    reset_widget_keys=[model_editor_key],
)


models_editor_rows = direct_entry_editor_rows(
    visible_models,
    editor_key=model_editor_key,
    sort_columns=["active", "display_name", "model_number", "eau", "description"],
    labels={"display_name": "Common name", "model_number": "Official model number", "eau": "EAU"},
)
edited_models = st.data_editor(
    models_editor_rows,
    key=model_editor_key,
    hide_index=True,
    num_rows="dynamic",
    height=500,
    disabled=["id", "updated_at"],
    column_order=[
        "active", "display_name", "model_number", "eau", "description",
    ],
    column_config={
        "id": None,
        "active": st.column_config.CheckboxColumn(
            "Active",
            default=True,
            help="Active models appear as choices in the Parts Catalog.",
        ),
        "display_name": st.column_config.TextColumn("Common name", width="medium"),
        "model_number": st.column_config.TextColumn("Official model number", required=True),
        "eau": st.column_config.NumberColumn(
            "EAU",
            min_value=0,
            step=0.1,
            format="%.1f",
            help="Estimated annual usage for this model.",
        ),
        "description": st.column_config.TextColumn("Description", width="large"),
        "notes": None,
        "updated_at": None,
    },
)
model_actions = editable_table_footer(
    editor_key=model_editor_key,
    key_prefix="model_information",
    undo_available=model_undo_key in st.session_state,
    native_row_selection=True,
)
undo_requested = model_actions.undo
save_requested = model_actions.save_and_refresh
if undo_requested:
    if has_unsaved_changes:
        request_table_editor_reset(model_editor_key)
        st.toast("Discarded the unsaved model table edits", icon=":material/undo:")
    else:
        model_snapshot = st.session_state.pop(model_undo_key)
        restore_model_planning_snapshot(project_id, model_snapshot)
        record_audit_event(
            project_id,
            "Model definitions",
            "Undo saved change",
            len(model_snapshot.get("models", [])),
            st.session_state.get("current_editor", ""),
            {
                "model_snapshot_restore": True,
                "models_restored": len(model_snapshot.get("models", [])),
                "part_applicability_rows_restored": len(model_snapshot.get("parts", [])),
                "work_element_applicability_rows_restored": len(
                    model_snapshot.get("work_elements", [])
                ),
                "fishbone_applicability_rows_restored": len(
                    model_snapshot.get("fishbone_nodes", [])
                ),
            },
        )
        request_table_editor_reset(model_editor_key)
        st.toast("Undid the last saved model change", icon=":material/undo:")
    st.rerun()

selected_models = native_selected_rows(
    models_editor_rows, editor_key=model_editor_key
)
request_model_delete = not selected_models.empty
if request_model_delete:
    if table_has_unsaved_changes(
        model_editor_key, native_row_selection=True
    ):
        st.warning("Save or undo other model edits before deleting selected models.")
    else:
        st.session_state[f"models_pending_delete_{project_id}"] = (
            selected_models["id"].astype(str).tolist()
        )
        stage_native_delete_confirmation(model_editor_key)


@st.dialog("Delete selected models?", dismissible=False)
def confirm_model_delete() -> None:
    pending_key = f"models_pending_delete_{project_id}"
    pending_ids = st.session_state.get(pending_key, [])
    grid_mappings = assembly_grid_model_mappings(project_id)
    mapping_count = (
        int(grid_mappings["model_id"].astype(str).isin(pending_ids).sum())
        if not grid_mappings.empty else 0
    )
    st.warning(
        f"Delete {len(pending_ids)} selected model definition(s)? Models still assigned elsewhere "
        "will block the entire deletion."
    )
    st.markdown(
        f"- **{mapping_count}** direct assembly-grid mapping(s) will also be removed. "
        "The underlying assembly records remain unchanged."
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_model_bulk_delete"):
        st.session_state.pop(pending_key, None)
        request_table_editor_reset(model_editor_key)
        st.rerun()
    if actions.button(
        "Delete models",
        type="primary",
        icon=":material/delete:",
        key="destructive_confirm_model_bulk_delete",
    ):
        try:
            labels = delete_project_models(project_id, pending_ids)
            st.session_state[model_undo_key] = current_model_snapshot
            record_audit_event(
                project_id,
                "Model definitions",
                "Bulk delete",
                len(labels),
                st.session_state.get("current_editor", ""),
                {"models": labels, "assembly_grid_mapping_count": mapping_count},
            )
            st.session_state.pop(pending_key, None)
            request_table_editor_reset(model_editor_key)
            st.toast(f"Deleted {len(labels)} selected models", icon=":material/delete:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if st.session_state.get(f"models_pending_delete_{project_id}"):
    confirm_model_delete()

if save_requested:
    try:
        if not selected_models.empty:
            raise ValueError("Clear selected rows before saving model edits.")
        edited_models = drop_untouched_new_rows(
            edited_models, identifying_columns=["model_number"]
        )
        existing_models_by_id = {
            str(row["id"]): row
            for _, row in models_for_editing.iterrows()
            if pd.notna(row.get("id")) and str(row.get("id")).strip()
        }
        model_audit_fields = [
            "model_number", "display_name", "eau", "description", "active", "notes",
        ]
        added_model_rows = 0
        edited_model_rows = 0
        for _, row in edited_models.iterrows():
            model_id = "" if pd.isna(row.get("id")) else str(row.get("id")).strip()
            if not model_id or model_id not in existing_models_by_id:
                added_model_rows += 1
                continue
            previous = existing_models_by_id[model_id]
            if any(
                (None if pd.isna(row.get(field)) else row.get(field))
                != (None if pd.isna(previous.get(field)) else previous.get(field))
                for field in model_audit_fields
            ):
                edited_model_rows += 1
        count = update_project_model_rows(project_id, edited_models)
        record_audit_event(
            project_id,
            "Model definitions",
            "Save & Refresh",
            added_model_rows + edited_model_rows,
            st.session_state.get("current_editor", ""),
            {
                "model_rows_added": added_model_rows,
                "model_rows_edited": edited_model_rows,
            },
        )
        st.session_state[model_undo_key] = current_model_snapshot
        request_table_editor_reset(model_editor_key)
        st.toast(f"Saved {count} model definitions", icon=":material/check_circle:")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


st.divider()
features = complexity_features(project_id)
current_complexity_snapshot = complexity_planning_snapshot(project_id)
feature_undo_key = f"complexity_features_undo_{project_id}"
feature_has_unsaved = table_has_unsaved_changes(
    feature_editor_key,
    native_row_selection=True,
)
editable_table_heading("Feature definitions")

st.caption(
    "Define the manufacturing characteristics that matter to this project. "
    "Enter allowed choices as a comma-separated list; for example, Dispenser, Non-dispenser."
)
feature_columns = ["id", "active", "category", "name", "allowed_choices", "description"]
if features.empty:
    feature_rows = pd.DataFrame({
        "id": pd.Series(dtype="string"),
        "active": pd.Series(dtype="bool"),
        "category": pd.Series(dtype="string"),
        "name": pd.Series(dtype="string"),
        "allowed_choices": pd.Series(dtype="string"),
        "description": pd.Series(dtype="string"),
    })
else:
    feature_rows = features.reindex(columns=feature_columns)

feature_editor_rows = direct_entry_editor_rows(
    feature_rows,
    editor_key=feature_editor_key,
    sort_columns=["active", "category", "name", "allowed_choices", "description"],
    labels={"active": "Active", "name": "Feature"},
)
edited_features = st.data_editor(
    feature_editor_rows,
    key=feature_editor_key,
    hide_index=True,
    num_rows="dynamic",
    height=320,
    disabled=["id"],
    column_order=["active", "category", "name", "allowed_choices", "description"],
    column_config={
        "id": None,
        "active": st.column_config.CheckboxColumn("Active", default=True),
        "category": st.column_config.TextColumn(
            "Category", required=True, help="A team-defined grouping such as Door, Controls, or Installation."
        ),
        "name": st.column_config.TextColumn(
            "Feature", required=True, help="A manufacturing-relevant characteristic."
        ),
        "allowed_choices": st.column_config.TextColumn(
            "Allowed choices", required=True, help="Separate choices with commas."
        ),
        "description": st.column_config.TextColumn("Description"),
    },
)
feature_actions = editable_table_footer(
    editor_key=feature_editor_key,
    key_prefix="complexity_features",
    undo_available=feature_undo_key in st.session_state,
    native_row_selection=True,
)
if feature_actions.undo:
    if feature_has_unsaved:
        request_table_editor_reset(feature_editor_key)
        st.toast("Discarded the unsaved feature edits", icon=":material/undo:")
    else:
        feature_snapshot = st.session_state.pop(feature_undo_key)
        restore_complexity_planning_snapshot(project_id, feature_snapshot)
        record_audit_event(
            project_id,
            "Feature definitions",
            "Undo saved change",
            len(feature_snapshot.get("features", [])),
            st.session_state.get("current_editor", ""),
            {
                "feature_snapshot_restore": True,
                "features_restored": len(feature_snapshot.get("features", [])),
                "model_feature_assignments_restored": len(
                    feature_snapshot.get("values", [])
                ),
                "part_rules_restored": len(feature_snapshot.get("part_rules", [])),
                "part_applicability_rows_restored": len(
                    feature_snapshot.get("part_applicability", [])
                ),
            },
        )
        request_table_editor_reset(feature_editor_key)
        request_table_editor_reset(tree_editor_key)
        st.toast("Undid the last feature-definition change", icon=":material/undo:")
    st.rerun()


def clean_feature_text(value: object) -> str:
    """Normalize nullable feature fields for confirmation and audit text."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def feature_summary(row: pd.Series | dict) -> str:
    """Return a short feature label that remains identifiable in history."""
    feature_id = clean_feature_text(row.get("id"))
    category = clean_feature_text(row.get("category")) or "Uncategorized"
    name = clean_feature_text(row.get("name")) or "Unnamed feature"
    return f"{category} · {name} (ID: {feature_id})"


def pending_feature_edit_summaries(
    excluded_ids: set[str] | None = None,
) -> list[str]:
    """Describe unsaved feature edits while ignoring native row selection."""
    excluded_ids = excluded_ids or set()
    state = st.session_state.get(feature_editor_key, {}) or {}
    summaries: list[str] = []
    for raw_position, changes in (state.get("edited_rows") or {}).items():
        position = int(raw_position)
        if not 0 <= position < len(feature_editor_rows):
            continue
        row = feature_editor_rows.iloc[position].to_dict()
        row.update(changes or {})
        feature_id = clean_feature_text(row.get("id"))
        if feature_id and feature_id in excluded_ids:
            continue
        summaries.append(feature_summary(row))
    for row in state.get("added_rows") or []:
        summaries.append(feature_summary(row))
    return list(dict.fromkeys(summaries))


def current_feature_editor_rows() -> pd.DataFrame:
    """Capture the feature draft before a confirmation-dialog rerun."""
    state = st.session_state.get(feature_editor_key, {}) or {}
    draft = feature_editor_rows.copy()
    for raw_position, changes in (state.get("edited_rows") or {}).items():
        position = int(raw_position)
        if not 0 <= position < len(draft):
            continue
        for column, value in (changes or {}).items():
            if column in draft.columns:
                draft.at[draft.index[position], column] = value
    selected_positions = {
        int(position)
        for position in state.get("deleted_rows") or []
        if 0 <= int(position) < len(draft)
    }
    if selected_positions:
        draft = draft.iloc[
            [position for position in range(len(draft)) if position not in selected_positions]
        ].copy()
    added_rows = state.get("added_rows") or []
    if added_rows:
        draft = pd.concat(
            [draft, pd.DataFrame(added_rows, columns=draft.columns)],
            ignore_index=True,
            sort=False,
        )
    return draft.reset_index(drop=True)


selected_features = native_selected_rows(
    feature_editor_rows,
    editor_key=feature_editor_key,
)
request_feature_delete = not selected_features.empty
feature_pending_delete_key = f"features_pending_delete_{project_id}"
if request_feature_delete:
    selected_ids = selected_features["id"].astype(str).tolist()
    impacts = complexity_feature_delete_impacts(project_id, selected_ids)
    impact_by_id = {
        str(row["id"]): row.to_dict()
        for _, row in impacts.iterrows()
    }
    pending_features = []
    for _, feature in selected_features.iterrows():
        feature_id = str(feature["id"])
        impact = impact_by_id.get(feature_id, {})
        pending_features.append(
            {
                "id": feature_id,
                "summary": feature_summary(feature),
                "model_value_count": int(impact.get("model_value_count") or 0),
                "part_rule_count": int(impact.get("part_rule_count") or 0),
                "affected_part_count": int(impact.get("affected_part_count") or 0),
            }
        )
    pending_ids = {item["id"] for item in pending_features}
    st.session_state[feature_pending_delete_key] = {
        "features": pending_features,
        "draft_rows": current_feature_editor_rows().to_dict("records"),
        "other_edits": pending_feature_edit_summaries(pending_ids),
        "snapshot": current_complexity_snapshot,
    }
    stage_native_delete_confirmation(feature_editor_key)


@st.dialog("Delete selected features?", dismissible=False)
def confirm_feature_delete() -> None:
    pending_state = st.session_state.get(feature_pending_delete_key, {})
    pending = pending_state.get("features", [])
    st.warning(
        f"Delete {len(pending)} selected feature(s)? Their Complexity tree assignments and "
        "part applicability rules will also be deleted. Affected parts will require applicability review."
    )
    for item in pending:
        st.write(
            f"- {item['summary']} — {item['model_value_count']} assigned Complexity tree "
            f"value(s), {item['part_rule_count']} part rule(s) across "
            f"{item['affected_part_count']} part(s)"
        )
    other_edits = pending_state.get("other_edits", [])
    if other_edits:
        st.info(
            "Other unsaved feature edits will be saved at the same time so they are not lost."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_feature_bulk_delete"):
        st.session_state.pop(feature_pending_delete_key, None)
        request_table_editor_reset(feature_editor_key)
        st.rerun()
    if actions.button(
        "Delete",
        type="primary",
        icon=":material/delete:",
        key="destructive_confirm_feature_bulk_delete",
    ):
        try:
            draft_rows = pd.DataFrame(
                pending_state.get("draft_rows", []),
                columns=feature_columns,
            )
            remaining_features = drop_untouched_new_rows(
                draft_rows,
                identifying_columns=["category", "name", "allowed_choices"],
            )
            update_complexity_features(project_id, remaining_features)
            st.session_state[feature_undo_key] = pending_state.get(
                "snapshot", current_complexity_snapshot
            )
            editor_name = st.session_state.get("current_editor", "")
            record_audit_event(
                project_id,
                "Feature definitions",
                "Bulk delete",
                len(pending),
                editor_name,
                {"features": pending},
            )
            if other_edits:
                record_audit_event(
                    project_id,
                    "Feature definitions",
                    "Save & Refresh",
                    len(other_edits),
                    editor_name,
                    {"features": other_edits, "saved_with_bulk_delete": True},
                )
            st.session_state.pop(feature_pending_delete_key, None)
            request_table_editor_reset(tree_editor_key)
            request_table_editor_reset(feature_editor_key)
            st.toast(f"Deleted {len(pending)} selected features", icon=":material/delete:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if st.session_state.get(feature_pending_delete_key):
    confirm_feature_delete()

if feature_actions.save_and_refresh:
    try:
        if not selected_features.empty:
            raise ValueError("Clear selected rows before saving feature edits.")
        edited_features = drop_untouched_new_rows(
            edited_features,
            identifying_columns=["category", "name", "allowed_choices"],
        )
        changed_features = pending_feature_edit_summaries()
        count = update_complexity_features(project_id, edited_features)
        st.session_state[feature_undo_key] = current_complexity_snapshot
        record_audit_event(
            project_id,
            "Feature definitions",
            "Save & Refresh",
            len(changed_features),
            st.session_state.get("current_editor", ""),
            {"features": changed_features},
        )
        request_table_editor_reset(tree_editor_key)
        request_table_editor_reset(feature_editor_key)
        st.toast(f"Saved {count} feature definitions", icon=":material/check_circle:")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


st.divider()
tree_undo_key = f"complexity_tree_undo_{project_id}"
tree_pending_save_key = f"complexity_tree_pending_save_{project_id}"
tree_has_unsaved = table_has_unsaved_changes(
    tree_editor_key, native_row_selection=True
)
editable_table_heading("Complexity tree")

active_features = (
    features.loc[features["active"].fillna(1).astype(bool)].copy()
    if not features.empty else features
)
active_model_ids = (
    set(models.loc[models["active"].fillna(1).astype(bool), "id"].astype(str))
    if not models.empty else set()
)
if models.empty:
    st.info("Add official models above before mapping the complexity tree.")
elif active_features.empty:
    st.info("Add and save at least one active feature definition to generate the complexity tree.")
else:
    st.caption(
        "Assign one team-defined choice per feature to each official model. Models may share the same process-relevant choices."
    )
    tree = complexity_tree(project_id)
    tree = tree.loc[tree["model_id"].astype(str).isin(active_model_ids)].copy()
    active_feature_ids = active_features["id"].astype(str).tolist()
    tree = tree[["model_id", "common_name", "official_model_number", *active_feature_ids]]
    spacer_count = max(6, len(active_feature_ids))
    spacer_columns = [
        f"__complexity_tree_spacer_{index}" for index in range(1, spacer_count + 1)
    ]
    for spacer_column in spacer_columns:
        tree[spacer_column] = ""
    tree_config = {
        "model_id": None,
        "common_name": st.column_config.TextColumn("Common name", width="medium"),
        "official_model_number": st.column_config.TextColumn(
            "Official model number", width="medium", pinned=True
        ),
    }
    for _, feature in active_features.iterrows():
        feature_id = str(feature["id"])
        choices = json.loads(feature["allowed_values"] or "[]")
        tree_config[feature_id] = st.column_config.SelectboxColumn(
            f"{feature['category']} · {feature['name']}",
            options=choices,
            width="medium",
            help=str(feature.get("description") or ""),
        )
    for spacer_column in spacer_columns:
        tree_config[spacer_column] = st.column_config.TextColumn(
            "", width="medium"
        )
    edited_tree = st.data_editor(
        tree,
        key=tree_editor_key,
        hide_index=True,
        num_rows="delete",
        height=420,
        width="content",
        disabled=[
            "model_id", "common_name", "official_model_number", *spacer_columns,
        ],
        column_order=[
            "official_model_number", "common_name", *active_feature_ids, *spacer_columns,
        ],
        column_config=tree_config,
    )
    tree_actions = editable_table_footer(
        editor_key=tree_editor_key,
        key_prefix="complexity_tree",
        undo_available=tree_undo_key in st.session_state,
        native_row_selection=True,
    )
    undo_tree = tree_actions.undo
    save_tree = tree_actions.save_and_refresh
    if undo_tree:
        if tree_has_unsaved:
            request_table_editor_reset(tree_editor_key)
            st.toast("Discarded the unsaved complexity-tree edits", icon=":material/undo:")
        else:
            tree_snapshot = st.session_state.pop(tree_undo_key)
            restore_complexity_planning_snapshot(project_id, tree_snapshot)
            record_audit_event(
                project_id,
                "Complexity tree",
                "Undo saved change",
                len(tree_snapshot.get("values", [])),
                st.session_state.get("current_editor", ""),
                {
                    "complexity_tree_snapshot_restore": True,
                    "model_feature_assignments_restored": len(
                        tree_snapshot.get("values", [])
                    ),
                    "part_applicability_rows_restored": len(
                        tree_snapshot.get("part_applicability", [])
                    ),
                },
            )
            request_table_editor_reset(tree_editor_key)
            st.toast("Undid the last complexity-tree change", icon=":material/undo:")
        st.rerun()
    selected_tree_rows = native_selected_rows(tree, editor_key=tree_editor_key)

    def persist_complexity_tree_save(pending: dict) -> None:
        pending_tree = pd.DataFrame(pending.get("rows", []))
        changed_assignment_count = int(pending.get("changed_assignment_count", 0))
        count = update_complexity_tree(project_id, pending_tree)
        record_audit_event(
            project_id,
            "Complexity tree",
            "Save & Refresh",
            changed_assignment_count,
            st.session_state.get("current_editor", ""),
            {
                "model_feature_assignments_changed": changed_assignment_count,
            },
        )
        st.session_state[tree_undo_key] = pending.get(
            "snapshot", current_complexity_snapshot
        )
        st.session_state.pop(tree_pending_save_key, None)
        request_table_editor_reset(tree_editor_key)
        st.toast(f"Saved {count} model feature selections", icon=":material/check_circle:")
        st.rerun()

    def dismiss_duplicate_model_warning() -> None:
        st.session_state.pop(tree_pending_save_key, None)

    @st.dialog(
        "Review potential duplicate models",
        width="large",
        icon=":material/warning:",
        on_dismiss=dismiss_duplicate_model_warning,
    )
    def confirm_duplicate_model_save() -> None:
        pending = st.session_state.get(tree_pending_save_key) or {}
        conflicts = pending.get("conflicts", [])
        st.warning(
            "These active models match on every feature that has a value assigned on both models."
        )
        for conflict in conflicts:
            left_name = conflict.get("left_common_name") or "No common name"
            left_number = conflict.get("left_official_model_number") or "No official model number"
            right_name = conflict.get("right_common_name") or "No common name"
            right_number = conflict.get("right_official_model_number") or "No official model number"
            st.write(
                f"{left_name} ({left_number}) and {right_name} ({right_number}) "
                f"— {int(conflict.get('mutual_feature_count', 0))} mutually assigned feature(s) match."
            )
        st.caption(
            "This is a review warning only. You may return to the table or save the values anyway."
        )
        actions = st.container(horizontal=True)
        if actions.button("Return to table", key=f"review_duplicate_models_{project_id}"):
            st.session_state.pop(tree_pending_save_key, None)
            st.rerun()
        if actions.button(
            "Save anyway",
            type="primary",
            icon=":material/save:",
            key=f"save_duplicate_models_anyway_{project_id}",
        ):
            persist_complexity_tree_save(pending)

    if save_tree:
        try:
            if not selected_tree_rows.empty:
                raise ValueError("Clear selected rows before saving complexity-tree edits.")
            existing_tree_by_model = {
                str(row["model_id"]): row for _, row in tree.iterrows()
            }
            changed_assignment_count = 0
            for _, row in edited_tree.iterrows():
                previous = existing_tree_by_model.get(str(row["model_id"]))
                if previous is None:
                    continue
                for feature_id in active_feature_ids:
                    edited_value = (
                        "" if pd.isna(row.get(feature_id))
                        else str(row.get(feature_id) or "").strip()
                    )
                    previous_value = (
                        "" if pd.isna(previous.get(feature_id))
                        else str(previous.get(feature_id) or "").strip()
                    )
                    if edited_value != previous_value:
                        changed_assignment_count += 1
            conflicts = potential_duplicate_models(project_id, edited_tree)
            pending = {
                "rows": edited_tree.to_dict("records"),
                "changed_assignment_count": changed_assignment_count,
                "snapshot": current_complexity_snapshot,
                "conflicts": conflicts,
            }
            if conflicts:
                st.session_state[tree_pending_save_key] = pending
            else:
                persist_complexity_tree_save(pending)
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.get(tree_pending_save_key):
        confirm_duplicate_model_save()

    st.divider()
    editable_table_heading("Complexity tree visual")
    category_values = sorted(
        {
            str(category).strip()
            for category in active_features["category"].dropna()
            if str(category).strip()
        }
    )
    visual_category = st.selectbox(
        "Category",
        ["", *category_values],
        index=0,
        format_func=lambda value: value or "Select a category",
        key=f"complexity_tree_visual_category_{project_id}",
    )
    visual_model_label = st.selectbox(
        "Model label",
        ["", "Common name", "Official model number"],
        index=0,
        format_func=lambda value: value or "Select a model label",
        key=f"complexity_tree_visual_model_label_{project_id}",
        help="Choose which model identifier appears in the visual headers.",
    )
    if not visual_category or not visual_model_label:
        if not visual_category and not visual_model_label:
            st.info("Select a category and model label to generate the complexity tree visual.")
        elif not visual_category:
            st.info("Select a category to generate the complexity tree visual.")
        else:
            st.info("Select a model label to generate the complexity tree visual.")
        visual_features = None
    else:
        visual_features = active_features.loc[
            active_features["category"].fillna("").astype(str).eq(visual_category)
        ]

    visual_models = models.loc[
        models["active"].fillna(1).astype(bool),
        ["id", "display_name", "model_number"],
    ].copy()
    visual_tree = complexity_tree(project_id).set_index("model_id")
    visual_model_groups: list[dict[str, object]] = []
    if visual_features is not None:
        feature_ids = [str(feature_id) for feature_id in visual_features["id"]]
        groups_by_values: dict[tuple[str, ...], dict[str, object]] = {}
        for _, model in visual_models.iterrows():
            model_id = str(model["id"])
            if model_id not in visual_tree.index:
                continue
            values = tuple(
                "" if pd.isna(visual_tree.at[model_id, feature_id])
                else str(visual_tree.at[model_id, feature_id]).strip()
                for feature_id in feature_ids
            )
            group = groups_by_values.setdefault(
                values,
                {"model_ids": [], "model_names": [], "model_numbers": []},
            )
            group["model_ids"].append(model_id)
            group["model_names"].append(str(model["display_name"] or "").strip())
            group["model_numbers"].append(str(model["model_number"]).strip())
        visual_model_groups = list(groups_by_values.values())
    if visual_features is None:
        pass
    elif visual_features.empty:
        st.info("No active features match this category.")
    elif not visual_model_groups:
        st.info("No active models are available for the complexity tree visual.")
    else:
        grid_columns = len(visual_model_groups)
        grid_template = (
            f"minmax(130px, 1.2fr) repeat({grid_columns}, minmax(90px, 1fr))"
        )
        model_header_height = max(
            42,
            max(len(group["model_numbers"]) for group in visual_model_groups) * 22 + 12,
        )
        visual_html = [
            f'<div style="display:grid;grid-template-columns:{grid_template};'
            'gap:10px 8px;align-items:center;">',
            '<div style="font-weight:700;">Model</div>',
        ]
        for group in visual_model_groups:
            labels = (
                group["model_names"]
                if visual_model_label == "Common name"
                else group["model_numbers"]
            )
            if visual_model_label == "Common name":
                labels = list(dict.fromkeys(labels))
            model_labels = "<br>".join(
                escape(str(label or "Common name not defined")) for label in labels
            )
            visual_html.append(
                '<div style="font-weight:700;line-height:1.45;overflow-wrap:anywhere;'
                f'border:2px solid #000;border-radius:4px;padding:6px;height:{model_header_height}px;'
                'box-sizing:border-box;display:flex;align-items:center;'
                'justify-content:center;text-align:center;">'
                f"{model_labels}</div>"
            )
        visual_html.append('<div></div>')
        visual_html.extend(
            '<div style="height:12px;width:0;border-left:2px solid #475569;'
            'margin:auto;"></div>'
            for _ in visual_model_groups
        )

        row_hues = [220, 145, 35, 295, 5, 180, 75, 255, 330, 110]
        feature_count = len(visual_features)
        for feature_index, (_, feature) in enumerate(visual_features.iterrows()):
            feature_id = str(feature["id"])
            choices = [str(choice).strip() for choice in json.loads(
                feature["allowed_values"] or "[]"
            ) if str(choice).strip()]
            color_by_choice = {
                choice: (
                    "hsl("
                    f"{row_hues[feature_index % len(row_hues)]}, 65%, "
                    f"{max(38, 92 - index * 8)}%)"
                )
                for index, choice in enumerate(choices)
            }
            visual_html.append(
                '<div style="font-weight:700;">'
                f"{escape(str(feature['name']).strip())}</div>"
            )
            values: list[str] = []
            for group in visual_model_groups:
                model_id = group["model_ids"][0]
                value = visual_tree.at[model_id, feature_id]
                selected_value = "" if pd.isna(value) else str(value).strip()
                values.append(selected_value)
            start = 0
            while start < len(values):
                end = start + 1
                while end < len(values) and values[end] == values[start]:
                    end += 1
                selected_value = values[start]
                background = color_by_choice.get(selected_value, "#f1f5f9")
                choice_index = choices.index(selected_value) if selected_value in choices else -1
                text_color = "#ffffff" if choice_index >= 4 else "#17324d"
                if not selected_value:
                    text_color = "#64748b"
                label = escape(selected_value or "Not assigned")
                visual_html.append(
                    f'<div style="grid-column:span {end - start};background:{background};'
                    'border-radius:8px;padding:10px 12px;text-align:center;display:flex;'
                    'align-items:center;justify-content:center;'
                    f'color:{text_color};"><strong>{label}</strong></div>'
                )
                start = end
            if feature_index < feature_count - 1:
                visual_html.append('<div></div>')
                visual_html.extend(
                    '<div style="height:12px;width:0;border-left:2px solid #475569;'
                    'margin:auto;"></div>'
                    for _ in visual_model_groups
                )
        visual_html.append('<div></div>')
        visual_html.extend(
            '<div style="height:12px;width:0;border-left:2px solid #475569;'
            'margin:auto;"></div>'
            for _ in visual_model_groups
        )
        visual_html.append('<div style="font-weight:700;">Model</div>')
        for group in visual_model_groups:
            labels = (
                group["model_names"]
                if visual_model_label == "Common name"
                else group["model_numbers"]
            )
            if visual_model_label == "Common name":
                labels = list(dict.fromkeys(labels))
            model_labels = "<br>".join(
                escape(str(label or "Common name not defined")) for label in labels
            )
            visual_html.append(
                '<div style="font-weight:700;line-height:1.45;overflow-wrap:anywhere;'
                f'border:2px solid #000;border-radius:4px;padding:6px;height:{model_header_height}px;'
                'box-sizing:border-box;display:flex;align-items:center;'
                'justify-content:center;text-align:center;">'
                f"{model_labels}</div>"
            )
        visual_html.append("</div>")
        st.markdown("".join(visual_html), unsafe_allow_html=True)

    st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)
with st.expander("History", icon=":material/history:"):
    models_history_tab, features_history_tab, tree_history_tab = st.tabs(
        ["Model information", "Feature definitions", "Complexity tree"]
    )
    with models_history_tab:
        models_history = audit_history(project_id, "Model definitions", limit=50)
        if models_history.empty:
            st.caption("No model-information history has been recorded yet.")
        else:
            selectable_dataframe(
                models_history.drop(columns=["details"], errors="ignore"),
                key=f"models_history_table_{project_id}",
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
    with features_history_tab:
        features_history = audit_history(project_id, "Feature definitions", limit=50)
        if features_history.empty:
            st.caption("No feature-definition history has been recorded yet.")
        else:
            selectable_dataframe(
                features_history.drop(columns=["details"], errors="ignore"),
                key=f"features_history_table_{project_id}",
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
    with tree_history_tab:
        tree_history = audit_history(project_id, "Complexity tree", limit=50)
        if tree_history.empty:
            st.caption("No complexity-tree history has been recorded yet.")
        else:
            selectable_dataframe(
                tree_history.drop(columns=["details"], errors="ignore"),
                key=f"complexity_tree_history_table_{project_id}",
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
