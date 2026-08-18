import json

import pandas as pd
import streamlit as st

from utils.store import (
    complexity_features,
    complexity_planning_snapshot,
    complexity_tree,
    delete_project_models,
    model_planning_snapshot,
    project_models,
    record_audit_event,
    restore_model_planning_snapshot,
    restore_complexity_planning_snapshot,
    update_complexity_features,
    update_complexity_tree,
    update_project_model_rows,
)
from utils.table_ui import (
    drop_untouched_new_rows,
    native_selected_rows,
    sortable_editor_rows,
    table_has_unsaved_changes,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    has_unsaved_table_changes,
    request_table_editor_reset,
)


project_id = st.session_state.get("project_id")
st.title("Model definitions")
st.caption("Translate official model numbers into the names and descriptions the IE and lean team use during planning.")
if not project_id:
    st.stop()
for editor_key in (
    "model_definitions_editor_v2",
    "complexity_feature_editor",
    "complexity_tree_editor",
):
    apply_pending_table_editor_reset(editor_key)

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
    "model_definitions_editor_v2", native_row_selection=True
)
planning_title, planning_warning, planning_undo, planning_action = st.columns(
    [4, 0.8, 0.7, 1], vertical_alignment="center"
)
planning_title.subheader("Model information")
if has_unsaved_changes:
    planning_warning.markdown(
        ":orange[:material/warning: **Unsaved changes**]",
    )
undo_requested = planning_undo.button(
    "Undo",
    icon=":material/undo:",
    disabled=model_undo_key not in st.session_state and not has_unsaved_changes,
    help=(
        "Discard the current unsaved table edits."
        if has_unsaved_changes
        else "Undo the last saved model change in this browser session."
    ),
    key="undo_model_information",
)
save_requested = planning_action.button(
    "Save model definitions",
    type="primary",
    icon=":material/save:",
)
if undo_requested:
    if has_unsaved_changes:
        st.session_state.pop("model_definitions_editor_v2", None)
        st.toast("Discarded the unsaved model table edits", icon=":material/undo:")
    else:
        restore_model_planning_snapshot(project_id, st.session_state.pop(model_undo_key))
        st.session_state.pop("model_definitions_editor_v2", None)
        st.toast("Undid the last saved model change", icon=":material/undo:")
    st.rerun()
st.caption("Model number stays tied to the official source. Edit the team-facing definition and turn off models that should not appear on the Parts page.")
st.caption("Add a model by entering it in the blank row at the bottom of the table, then save.")
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
    reset_widget_keys=["model_definitions_editor_v2"],
)


models_editor_rows = sortable_editor_rows(visible_models, defaults={"active": True})
edited_models = st.data_editor(
    models_editor_rows,
    key="model_definitions_editor_v2",
    hide_index=True,
    num_rows="delete",
    height=500,
    disabled=["id", "updated_at"],
    column_order=[
        "active", "display_name", "model_number", "eau", "description",
    ],
    column_config={
        "id": None,
        "active": st.column_config.CheckboxColumn(
            "Use in planning",
            default=True,
            help="Active models appear as choices on the Parts page.",
        ),
        "display_name": st.column_config.TextColumn("Common name", width="medium"),
        "model_number": st.column_config.TextColumn("Official model numbers", required=True),
        "eau": st.column_config.NumberColumn(
            "EAU",
            min_value=0,
            step=1,
            format="%d",
            help="Estimated annual usage for this model.",
        ),
        "description": st.column_config.TextColumn("Description", width="large"),
        "notes": None,
        "updated_at": None,
    },
)

selected_models = native_selected_rows(
    visible_models, editor_key="model_definitions_editor_v2"
)
model_bulk_actions = st.container(horizontal=True, horizontal_alignment="right")
request_model_delete = model_bulk_actions.button(
    f"Delete selected ({len(selected_models)})",
    icon=":material/delete:",
    disabled=selected_models.empty,
    key="destructive_request_model_bulk_delete",
)
if request_model_delete:
    if table_has_unsaved_changes(
        "model_definitions_editor_v2", native_row_selection=True
    ):
        st.warning("Save or undo other model edits before deleting selected models.")
    else:
        st.session_state[f"models_pending_delete_{project_id}"] = (
            selected_models["id"].astype(str).tolist()
        )


@st.dialog("Delete selected models?")
def confirm_model_delete() -> None:
    pending_key = f"models_pending_delete_{project_id}"
    pending_ids = st.session_state.get(pending_key, [])
    st.warning(
        f"Delete {len(pending_ids)} selected model definition(s)? Models still assigned elsewhere "
        "will block the entire deletion."
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_model_bulk_delete"):
        st.session_state.pop(pending_key, None)
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
                {"models": labels},
            )
            st.session_state.pop(pending_key, None)
            request_table_editor_reset("model_definitions_editor_v2")
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
        count = update_project_model_rows(project_id, edited_models)
        st.session_state[model_undo_key] = current_model_snapshot
        request_table_editor_reset("model_definitions_editor_v2")
        st.toast(f"Saved {count} model definitions", icon=":material/check_circle:")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


st.divider()
features = complexity_features(project_id)
current_complexity_snapshot = complexity_planning_snapshot(project_id)
feature_undo_key = f"complexity_features_undo_{project_id}"
feature_editor_key = "complexity_feature_editor"
feature_has_unsaved = has_unsaved_table_changes(feature_editor_key)

feature_title, feature_warning, feature_undo, feature_save = st.columns(
    [4, 0.8, 0.7, 1], vertical_alignment="center"
)
feature_title.subheader("Feature definitions")
if feature_has_unsaved:
    feature_warning.markdown(":orange[:material/warning: **Unsaved changes**]")
undo_features = feature_undo.button(
    "Undo",
    icon=":material/undo:",
    disabled=feature_undo_key not in st.session_state and not feature_has_unsaved,
    help=(
        "Discard the current unsaved feature edits."
        if feature_has_unsaved
        else "Undo the last saved feature-definition change."
    ),
    key="undo_complexity_features",
)
save_features = feature_save.button(
    "Save features",
    type="primary",
    icon=":material/save:",
)
if undo_features:
    if feature_has_unsaved:
        st.session_state.pop(feature_editor_key, None)
        st.toast("Discarded the unsaved feature edits", icon=":material/undo:")
    else:
        restore_complexity_planning_snapshot(project_id, st.session_state.pop(feature_undo_key))
        st.session_state.pop(feature_editor_key, None)
        st.session_state.pop("complexity_tree_editor", None)
        st.toast("Undid the last feature-definition change", icon=":material/undo:")
    st.rerun()

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

feature_editor_rows = sortable_editor_rows(feature_rows, defaults={"active": True})
edited_features = st.data_editor(
    feature_editor_rows,
    key=feature_editor_key,
    hide_index=True,
    num_rows="delete",
    height=320,
    disabled=["id"],
    column_order=["active", "category", "name", "allowed_choices", "description"],
    column_config={
        "id": None,
        "active": st.column_config.CheckboxColumn("Use", default=True),
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
if save_features:
    try:
        edited_features = drop_untouched_new_rows(
            edited_features,
            identifying_columns=["category", "name", "allowed_choices"],
        )
        count = update_complexity_features(project_id, edited_features)
        st.session_state[feature_undo_key] = current_complexity_snapshot
        st.session_state.pop("complexity_tree_editor", None)
        request_table_editor_reset(feature_editor_key)
        st.toast(f"Saved {count} feature definitions", icon=":material/check_circle:")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


st.divider()
tree_undo_key = f"complexity_tree_undo_{project_id}"
tree_editor_key = "complexity_tree_editor"
tree_has_unsaved = has_unsaved_table_changes(tree_editor_key)
tree_title, tree_warning, tree_undo, tree_save = st.columns(
    [4, 0.8, 0.7, 1], vertical_alignment="center"
)
tree_title.subheader("Complexity tree")
if tree_has_unsaved:
    tree_warning.markdown(":orange[:material/warning: **Unsaved changes**]")
undo_tree = tree_undo.button(
    "Undo",
    icon=":material/undo:",
    disabled=tree_undo_key not in st.session_state and not tree_has_unsaved,
    help=(
        "Discard the current unsaved complexity-tree edits."
        if tree_has_unsaved
        else "Undo the last saved complexity-tree change."
    ),
    key="undo_complexity_tree",
)
save_tree = tree_save.button(
    "Save complexity tree",
    type="primary",
    icon=":material/save:",
    disabled=features.empty or models.empty,
)
if undo_tree:
    if tree_has_unsaved:
        st.session_state.pop(tree_editor_key, None)
        st.toast("Discarded the unsaved complexity-tree edits", icon=":material/undo:")
    else:
        restore_complexity_planning_snapshot(project_id, st.session_state.pop(tree_undo_key))
        st.session_state.pop(tree_editor_key, None)
        st.toast("Undid the last complexity-tree change", icon=":material/undo:")
    st.rerun()

active_features = (
    features.loc[features["active"].fillna(1).astype(bool)].copy()
    if not features.empty else features
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
    active_feature_ids = active_features["id"].astype(str).tolist()
    tree = tree[["model_id", "common_name", "official_model_number", *active_feature_ids]]
    tree_config = {
        "model_id": None,
        "common_name": st.column_config.TextColumn("Common name", pinned=True),
        "official_model_number": st.column_config.TextColumn("Official model number", pinned=True),
    }
    for _, feature in active_features.iterrows():
        feature_id = str(feature["id"])
        choices = json.loads(feature["allowed_values"] or "[]")
        tree_config[feature_id] = st.column_config.SelectboxColumn(
            f"{feature['category']} · {feature['name']}",
            options=choices,
            help=str(feature.get("description") or ""),
        )
    edited_tree = st.data_editor(
        tree,
        key=tree_editor_key,
        hide_index=True,
        num_rows="fixed",
        height=420,
        disabled=["model_id", "common_name", "official_model_number"],
        column_order=["common_name", "official_model_number", *active_feature_ids],
        column_config=tree_config,
    )
    if save_tree:
        try:
            count = update_complexity_tree(project_id, edited_tree)
            st.session_state[tree_undo_key] = current_complexity_snapshot
            request_table_editor_reset(tree_editor_key)
            st.toast(f"Saved {count} model feature selections", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
