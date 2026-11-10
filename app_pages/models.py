import base64
import colorsys
import hashlib
import json
import streamlit.components.v1 as components
from html import escape

import pandas as pd
import streamlit as st

from utils.store import (
    _identify_top_level_assembly_pns,
    apply_inferred_part_feature_rules,
    audit_history,
    build_feature_choice_rename_map,
    complexity_feature_delete_impacts,
    complexity_features,
    complexity_planning_snapshot,
    complexity_tree,
    complexity_visual_part_rules,
    deduplicate_visual_box_parts,
    delete_project_models,
    get_project,
    model_planning_snapshot,
    part_feature_rules,
    potential_duplicate_models,
    preview_inferred_part_feature_rules,
    project_models,
    project_part_subsystems,
    project_table,
    record_audit_event,
    restore_model_planning_snapshot,
    restore_complexity_planning_snapshot,
    update_complexity_features,
    update_complexity_tree,
    update_project_model_rows,
)
from utils.part_feature_dialog import review_multi_feature_applicability_dialog
from utils.scope_ui import page_title_with_scope
from utils.table_ui import (
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    direct_entry_editor_rows,
    count_table_create_and_edit_rows, render_audit_history_table, selectable_dataframe,
    stage_native_delete_confirmation,
    table_has_unsaved_changes,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    get_effective_table_editor_state,
    has_unsaved_table_changes,
    logical_table_editor_key,
    merge_filtered_edits,
    request_table_editor_reset,
)


project_id = st.session_state.get("project_id")
page_title_with_scope("Complexity Trees", scope="project")
st.caption("Translate each Model number into the Model name and description the IE and lean team use during planning.")
if not project_id:
    st.stop()
if st.session_state.get("_models_active_project_id") != str(project_id):
    if st.session_state.get("_models_active_project_id") is not None:
        request_table_editor_reset(f"model_definitions_editor_v2_{project_id}")
        request_table_editor_reset(f"complexity_feature_editor_{project_id}")
        request_table_editor_reset(f"complexity_tree_editor_{project_id}")
    st.session_state["_models_active_project_id"] = str(project_id)
model_editor_key = apply_pending_table_editor_reset(f"model_definitions_editor_v2_{project_id}")
feature_editor_key = apply_pending_table_editor_reset(f"complexity_feature_editor_{project_id}")
tree_editor_key = apply_pending_table_editor_reset(f"complexity_tree_editor_{project_id}")

models = project_models(project_id)
model_undo_key = f"model_information_undo_{project_id}"
current_model_snapshot = model_planning_snapshot(project_id)
for column, default in {
    "active": True,
    "source_payload": "{}",
}.items():
    if column not in models.columns:
        models[column] = pd.Series(dtype="bool" if column == "active" else "string")

active_mask = models["active"].fillna(1).astype(bool) if not models.empty else pd.Series(dtype="bool")
active_count = int(active_mask.sum()) if not models.empty else 0
total_models = int(len(models))
pits_count = int(models["source_payload"].fillna("{}").ne("{}").sum()) if not models.empty else 0
active_models_df = models.loc[active_mask].copy() if not models.empty else models

missing_name_count = (
    int(
        (
            active_models_df["display_name"]
            .fillna("")
            .astype(str)
            .str.strip()
            == ""
        ).sum()
    )
    if not active_models_df.empty and "display_name" in active_models_df.columns
    else 0
)
models_icon = (
    "🟢"
    if (active_count > 0 and missing_name_count == 0)
    else ("🟡" if active_count > 0 else "🔴")
)
if active_count == 0:
    models_delta = f"{total_models} defined · Activate models below"
    models_delta_color = "inverse"
elif missing_name_count > 0:
    models_delta = f"{missing_name_count} missing Model name · {pits_count} from PITS"
    models_delta_color = "off"
else:
    models_delta = f"{total_models} defined · {pits_count} from PITS"
    models_delta_color = "normal"

eau_series = (
    pd.to_numeric(active_models_df["eau"], errors="coerce").fillna(0.0)
    if not active_models_df.empty and "eau" in active_models_df.columns
    else pd.Series(dtype="float64")
)
total_active_eau = float(eau_series.clip(lower=0.0).sum()) if not eau_series.empty else 0.0
missing_eau_count = int((eau_series <= 0).sum()) if not eau_series.empty else 0
eau_icon = (
    "🟢"
    if (active_count > 0 and missing_eau_count == 0)
    else ("🟡" if (total_active_eau > 0 and missing_eau_count > 0) else "🔴")
)
if active_count == 0:
    eau_delta = "No active models"
    eau_delta_color = "off"
elif missing_eau_count == 0:
    eau_delta = f"All {active_count} active models have EAU"
    eau_delta_color = "normal"
else:
    eau_delta = f"{missing_eau_count} active model(s) missing EAU"
    eau_delta_color = "inverse"

banner_features = complexity_features(project_id)
banner_active_features = (
    banner_features.loc[banner_features["active"].fillna(1).astype(bool)].copy()
    if not banner_features.empty
    else banner_features
)
active_feature_count = int(len(banner_active_features))
feature_categories_count = (
    int(
        banner_active_features["category"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .nunique()
    )
    if not banner_active_features.empty and "category" in banner_active_features.columns
    else 0
)
linked_subsystem_count = (
    int(
        (
            banner_active_features["subsystem"]
            .fillna("")
            .astype(str)
            .str.strip()
            != ""
        ).sum()
    )
    if not banner_active_features.empty and "subsystem" in banner_active_features.columns
    else 0
)
features_icon = "🟢" if active_feature_count > 0 else "🟡"
if active_feature_count > 0:
    cat_word = "category" if feature_categories_count == 1 else "categories"
    features_delta = f"{feature_categories_count} {cat_word} · {linked_subsystem_count} with subsystem"
else:
    features_delta = "Add feature definitions below"

banner_active_model_ids = (
    set(active_models_df["id"].astype(str)) if not active_models_df.empty else set()
)
banner_active_feature_ids = (
    banner_active_features["id"].astype(str).tolist()
    if not banner_active_features.empty
    else []
)
banner_full_tree = (
    complexity_tree(project_id)
    if (banner_active_model_ids and banner_active_feature_ids)
    else pd.DataFrame()
)
banner_active_tree = (
    banner_full_tree.loc[
        banner_full_tree["model_id"].astype(str).isin(banner_active_model_ids)
    ].copy()
    if not banner_full_tree.empty
    else pd.DataFrame()
)
total_tree_cells = len(banner_active_model_ids) * len(banner_active_feature_ids)
mapped_tree_cells = 0
if total_tree_cells > 0 and not banner_active_tree.empty:
    for fid in banner_active_feature_ids:
        if fid in banner_active_tree.columns:
            mapped_tree_cells += int(
                (
                    banner_active_tree[fid]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    != ""
                ).sum()
            )
unmapped_tree_cells = max(0, total_tree_cells - mapped_tree_cells)
if total_tree_cells > 0:
    mapped_pct = (mapped_tree_cells / total_tree_cells) * 100.0
    tree_icon = (
        "🟢"
        if unmapped_tree_cells == 0
        else ("🟡" if mapped_tree_cells > 0 else "🔴")
    )
    tree_value_str = f"{tree_icon} {mapped_pct:.0f}%"
    if unmapped_tree_cells == 0:
        tree_delta = f"All {total_tree_cells} cells mapped"
        tree_delta_color = "normal"
    else:
        tree_delta = f"{unmapped_tree_cells} of {total_tree_cells} cell(s) unmapped"
        tree_delta_color = "inverse"
else:
    tree_value_str = "—"
    tree_delta = "Needs active models & features"
    tree_delta_color = "off"

similar_model_ids: set[str] = set()
exact_pair_count = 0
near_pair_count = 0
pair_examples: list[str] = []
if len(banner_active_tree) >= 2 and banner_active_feature_ids:
    tree_records = banner_active_tree.to_dict("records")
    for idx_a in range(len(tree_records)):
        row_a = tree_records[idx_a]
        mid_a = str(row_a.get("model_id") or "")
        label_a = (
            str(row_a.get("common_name") or "").strip()
            or str(row_a.get("official_model_number") or "").strip()
            or mid_a[:6]
        )
        for idx_b in range(idx_a + 1, len(tree_records)):
            row_b = tree_records[idx_b]
            mid_b = str(row_b.get("model_id") or "")
            label_b = (
                str(row_b.get("common_name") or "").strip()
                or str(row_b.get("official_model_number") or "").strip()
                or mid_b[:6]
            )
            mutual_assigned = 0
            diff_count = 0
            for fid in banner_active_feature_ids:
                val_a = "" if pd.isna(row_a.get(fid)) else str(row_a.get(fid) or "").strip()
                val_b = "" if pd.isna(row_b.get(fid)) else str(row_b.get(fid) or "").strip()
                if val_a and val_b:
                    mutual_assigned += 1
                    if val_a != val_b:
                        diff_count += 1
                elif val_a or val_b:
                    diff_count += 1
            if mutual_assigned > 0 and diff_count <= 2:
                similar_model_ids.add(mid_a)
                similar_model_ids.add(mid_b)
                if diff_count == 0:
                    exact_pair_count += 1
                else:
                    near_pair_count += 1
                if len(pair_examples) < 5:
                    pair_examples.append(f"{label_a} ↔ {label_b} ({diff_count} diff)")

if active_count >= 2 and active_feature_count > 0:
    similar_value_str = f"{len(similar_model_ids)} / {active_count}"
    similar_delta = (
        f"{exact_pair_count} exact (0 diff) · {near_pair_count} within 1–2 features"
    )
else:
    similar_value_str = "—"
    similar_delta = "Map ≥2 models & ≥1 feature"

similar_help = (
    "Active models whose Complexity tree feature choices differ from another active model by "
    "0 to 2 features (0 differences = identical feature profile; 1–2 differences = near-identical "
    "models that can share most assembly work and tooling)."
)
if pair_examples:
    similar_help += " Closest pairs: " + "; ".join(pair_examples) + "."

summary = st.columns(5)
summary[0].metric(
    "Active models",
    f"{models_icon} {active_count}",
    delta=models_delta,
    delta_color=models_delta_color,
    help=(
        "Number of models checked as Active for planning out of all defined models. "
        "Active models appear in the Complexity tree and Parts Catalog model applicability. "
        "🟢 = active models defined with friendly Model names, "
        "🟡 = 1+ active models missing a friendly Model name, 🔴 = 0 active models."
    ),
)
summary[1].metric(
    "Total active EAU",
    f"{eau_icon} {int(round(total_active_eau)):,}",
    delta=eau_delta,
    delta_color=eau_delta_color,
    help=(
        "Sum of Estimated Annual Usage (EAU) across all active models (used to calculate "
        "Hours per unit on Project overview). 🟢 = all active models have EAU > 0, "
        "🟡 = some active models are missing EAU, 🔴 = total active EAU is 0."
    ),
)
summary[2].metric(
    "Active features",
    f"{features_icon} {active_feature_count}",
    delta=features_delta,
    delta_color="off",
    help=(
        "Number of active complexity features (such as Door Style, Ice Maker, or Color) "
        "used to differentiate models in the Complexity tree and infer part applicability."
    ),
)
summary[3].metric(
    "Tree mapping",
    tree_value_str,
    delta=tree_delta,
    delta_color=tree_delta_color,
    help=(
        "Percentage of (Active Model × Active Feature) cells in the Complexity tree table "
        "that have an assigned option. 🟢 = 100% mapped, 🟡 = partially mapped, 🔴 = 0% mapped."
    ),
)
summary[4].metric(
    "Similar models (0–2 features)",
    similar_value_str,
    delta=similar_delta,
    delta_color="off",
    help=similar_help,
)





has_unsaved_changes = table_has_unsaved_changes(
    model_editor_key, native_row_selection=True
)
editable_table_heading("Model information")
st.caption("Model number stays tied to the official source. Edit the Model name and turn off models that should not appear in the Parts Catalog.")
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
    key=f"model_definition_filters_{project_id}",
    dropdown_columns=["active"],
    search_columns=["model_number", "display_name", "description"],
    labels={"active": "Planning status"},
    reset_widget_keys=[model_editor_key],
)


models_editor_rows = direct_entry_editor_rows(
    visible_models,
    editor_key=model_editor_key,
    sort_columns=["active", "display_name", "model_number", "eau", "description"],
    labels={"display_name": "Model name", "model_number": "Model number", "eau": "EAU"},
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
        "display_name": st.column_config.TextColumn(
            "Model name",
            width="medium",
            help="Friendly name used by the team to recognize this model during planning (for example, High End Stainless).",
        ),
        "model_number": st.column_config.TextColumn(
            "Model number",
            required=True,
            help="Unique model identifier from the product lineup or BOM (for example, GFE28GYNFS).",
        ),
        "eau": st.column_config.NumberColumn(
            "EAU",
            min_value=0,
            step=0.1,
            format="%.1f",
            help="Estimated annual usage for this model.",
        ),
        "description": st.column_config.TextColumn(
            "Description",
            width="large",
            help="Optional summary of the model's key configuration or market details.",
        ),
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
    st.warning(
        f"Delete {len(pending_ids)} selected model definition(s)? Models still assigned elsewhere "
        "will block the entire deletion."
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
                {"models": labels},
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
        merged_models = merge_filtered_edits(
            models_for_editing, visible_models, edited_models
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
        for _, row in merged_models.iterrows():
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
        count = update_project_model_rows(project_id, merged_models)
        record_audit_event(
            project_id,
            "Model definitions",
            "Save & Refresh",
            added_model_rows + edited_model_rows,
            st.session_state.get("current_editor", ""),
            {
                "model_rows_added": added_model_rows, "created_count": added_model_rows, "updated_count": edited_model_rows,
                "model_rows_edited": edited_model_rows,
            },
        )
        st.session_state[model_undo_key] = current_model_snapshot
        request_table_editor_reset(model_editor_key)
        model_save_details: list[str] = []
        if added_model_rows:
            model_save_details.append(f"{added_model_rows} added")
        if edited_model_rows:
            model_save_details.append(f"{edited_model_rows} updated")
        st.toast(
            f"Saved {count} model definition(s)"
            + (f" ({', '.join(model_save_details)})" if model_save_details else ""),
            icon=":material/check_circle:",
        )
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


st.divider()
features = complexity_features(project_id)
subsystem_options = project_part_subsystems(project_id)
current_complexity_snapshot = complexity_planning_snapshot(project_id)
feature_undo_key = f"complexity_features_undo_{project_id}"
feature_has_unsaved = table_has_unsaved_changes(
    feature_editor_key,
    native_row_selection=True,
)
editable_table_heading("Feature definitions")

st.caption(
    "Define the manufacturing characteristics that matter to this project. "
    "Group each **Feature** (product attribute) under a **Category** and optional Parts Catalog **Subsystem**, then list its **Allowed choices** (options) separated by commas — for example, Dispenser, Non-dispenser. Hover over any column header for details."
)
feature_columns = ["id", "active", "category", "subsystem", "name", "allowed_choices", "description"]
if features.empty:
    feature_rows = pd.DataFrame({
        "id": pd.Series(dtype="string"),
        "active": pd.Series(dtype="bool"),
        "category": pd.Series(dtype="string"),
        "subsystem": pd.Series(dtype="string"),
        "name": pd.Series(dtype="string"),
        "allowed_choices": pd.Series(dtype="string"),
        "description": pd.Series(dtype="string"),
    })
else:
    feature_rows = features.reindex(columns=feature_columns).copy()
    feature_rows["subsystem"] = (
        feature_rows["subsystem"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace({"": None})
    )

visible_features = filter_table(
    feature_rows,
    key=f"feature_definition_filters_{project_id}",
    dropdown_columns=["active", "category", "subsystem"],
    search_columns=["category", "subsystem", "name", "allowed_choices", "description"],
    labels={"active": "Planning status", "category": "Category", "subsystem": "Subsystem"},
    reset_widget_keys=[feature_editor_key],
)

feature_editor_rows = direct_entry_editor_rows(
    visible_features,
    editor_key=feature_editor_key,
    sort_columns=["active", "category", "subsystem", "name", "allowed_choices", "description"],
    labels={"active": "Active", "name": "Feature"},
)
edited_features = st.data_editor(
    feature_editor_rows,
    key=feature_editor_key,
    hide_index=True,
    num_rows="dynamic",
    height=320,
    disabled=["id"],
    column_order=["active", "category", "subsystem", "name", "allowed_choices", "description"],
    column_config={
        "id": None,
        "active": st.column_config.CheckboxColumn(
            "Active",
            default=True,
            help="When checked, this feature appears in the Complexity tree and is used to determine part applicability across models.",
        ),
        "category": st.column_config.TextColumn(
            "Category",
            required=True,
            help="High-level functional area or product grouping (for example, Door, Controls, or Refrigeration) used to organize related features in the Complexity tree and visual.",
        ),
        "subsystem": st.column_config.SelectboxColumn(
            "Subsystem",
            options=subsystem_options,
            required=False,
            help="Optional Parts Catalog subsystem link. When set, auto-assigning part applicability from the Complexity tree only matches parts that belong to this subsystem.",
        ),
        "name": st.column_config.TextColumn(
            "Feature",
            required=True,
            help="Unique product attribute or variation within this project that differs between models and affects which parts or assembly steps are needed (for example, Door Color, Wheel Color, Ice Maker, or Handle Style).",
        ),
        "allowed_choices": st.column_config.TextColumn(
            "Allowed choices",
            required=True,
            help="Comma-separated list of possible options a model can have for this feature (for example, Dispenser, Non-dispenser). Each active model is assigned one of these options in the Complexity tree below.",
        ),
        "description": st.column_config.TextColumn(
            "Description",
            help="Optional notes explaining this feature or when each option applies.",
        ),
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
            merged_draft = merge_filtered_edits(
                feature_rows, visible_features, draft_rows
            )
            remaining_features = drop_untouched_new_rows(
                merged_draft,
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

def _remap_choice_in_session_filters(
    proj_id: str, rename_maps: dict[str, dict[str, str]]
) -> None:
    """Update any active Complexity tree filter selections when allowed choices are renamed."""
    for feat_id, rmap in rename_maps.items():
        if not rmap:
            continue
        for filter_key in (
            f"complexity_tree_filters_{proj_id}_{feat_id}",
            f"_saved_filter_col_complexity_tree_filters_{proj_id}_{feat_id}",
        ):
            cur = st.session_state.get(filter_key)
            if isinstance(cur, list) and cur:
                updated = list(
                    dict.fromkeys(rmap.get(str(v).strip(), v) for v in cur)
                )
                if updated != cur:
                    st.session_state[filter_key] = updated


def _preserve_and_remap_tree_editor_draft(
    t_editor_key: str, rename_maps: dict[str, dict[str, str]]
) -> None:
    """Carry over any unsaved Complexity tree edits across a tree editor reset, remapping renamed choices."""
    logical_t_key = logical_table_editor_key(t_editor_key)
    filter_draft = st.session_state.get(f"_table_filter_id_draft_{logical_t_key}")
    if isinstance(filter_draft, dict) and filter_draft:
        remapped_filter_draft: dict[str, dict[str, object]] = {}
        for rid, changes in filter_draft.items():
            if not isinstance(changes, dict):
                continue
            new_changes: dict[str, object] = {}
            for col, val in changes.items():
                col_str = str(col)
                rmap = rename_maps.get(col_str)
                if rmap and val is not None and not pd.isna(val):
                    val_str = str(val).strip()
                    new_changes[col_str] = rmap.get(val_str, val)
                else:
                    new_changes[col_str] = val
            remapped_filter_draft[str(rid)] = new_changes
        st.session_state[f"_table_filter_id_draft_{logical_t_key}"] = remapped_filter_draft
    eff_state = get_effective_table_editor_state(t_editor_key)
    edited_rows = eff_state.get("edited_rows") or {}
    added_rows = eff_state.get("added_rows") or []
    deleted_rows = eff_state.get("deleted_rows") or []
    if not (edited_rows or added_rows or deleted_rows):
        if filter_draft:
            st.session_state[f"_preserve_filter_draft_{logical_t_key}"] = True
            st.session_state[f"_pending_undo_last_edit_{logical_t_key}"] = True
        return
    remapped_edited: dict[int, dict[str, object]] = {}
    for pos, changes in edited_rows.items():
        if not isinstance(changes, dict):
            continue
        new_changes = {}
        for col, val in changes.items():
            col_str = str(col)
            rmap = rename_maps.get(col_str)
            if rmap and val is not None and not pd.isna(val):
                val_str = str(val).strip()
                new_changes[col_str] = rmap.get(val_str, val)
            else:
                new_changes[col_str] = val
        remapped_edited[int(pos)] = new_changes
    st.session_state[f"_table_undo_seed_{logical_t_key}"] = {
        "edited_rows": remapped_edited,
        "added_rows": list(added_rows),
        "deleted_rows": list(deleted_rows),
    }
    st.session_state[f"_preserve_filter_draft_{logical_t_key}"] = True
    st.session_state[f"_pending_undo_last_edit_{logical_t_key}"] = True


def _resolve_live_complexity_features(
    base_features: pd.DataFrame,
    base_feature_rows: pd.DataFrame,
    visible_feature_rows: pd.DataFrame,
    edited_feature_rows: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    """Overlay valid live Feature definitions edits onto complexity_features and compute choice rename maps."""
    if base_features.empty and (edited_feature_rows is None or edited_feature_rows.empty):
        return base_features, {}
    saved_choices_by_id: dict[str, list[str]] = {}
    if not base_features.empty:
        for _, f_row in base_features.iterrows():
            fid = str(f_row.get("id") or "").strip()
            if not fid:
                continue
            try:
                saved_choices_by_id[fid] = [
                    str(c).strip()
                    for c in json.loads(f_row.get("allowed_values") or "[]")
                    if c is not None and str(c).strip()
                ]
            except Exception:
                saved_choices_by_id[fid] = []
    if edited_feature_rows is None or edited_feature_rows.empty:
        return base_features, {}
    cleaned_edited = drop_untouched_new_rows(
        edited_feature_rows,
        identifying_columns=["category", "name", "allowed_choices"],
    )
    merged_live = merge_filtered_edits(
        base_feature_rows, visible_feature_rows, cleaned_edited
    )
    base_by_id: dict[str, dict[str, object]] = {}
    if not base_features.empty:
        for _, f_row in base_features.iterrows():
            fid = str(f_row.get("id") or "").strip()
            if fid:
                base_by_id[fid] = f_row.to_dict()
    live_rows: list[dict[str, object]] = []
    rename_maps: dict[str, dict[str, str]] = {}
    for idx, row in merged_live.reset_index(drop=True).iterrows():
        fid = clean_feature_text(row.get("id"))
        cat = clean_feature_text(row.get("category"))
        name = clean_feature_text(row.get("name"))
        raw_allowed = clean_feature_text(row.get("allowed_choices"))
        choices = list(
            dict.fromkeys(c.strip() for c in raw_allowed.split(",") if c.strip())
        )
        base_rec = base_by_id.get(fid, {})
        if not cat and base_rec:
            cat = clean_feature_text(base_rec.get("category"))
        if not name and base_rec:
            name = clean_feature_text(base_rec.get("name"))
        if not choices and base_rec:
            choices = list(saved_choices_by_id.get(fid, []))
        if not fid or not cat or not name or not choices:
            continue
        old_choices = saved_choices_by_id.get(fid, [])
        rmap = build_feature_choice_rename_map(old_choices, choices)
        if rmap:
            rename_maps[fid] = rmap
        active_val = row.get("active")
        is_active = True if active_val is None or pd.isna(active_val) else bool(active_val)
        live_rows.append(
            {
                **base_rec,
                "id": fid,
                "project_id": project_id,
                "category": cat,
                "subsystem": clean_feature_text(row.get("subsystem")),
                "name": name,
                "allowed_values": json.dumps(choices),
                "allowed_choices": ", ".join(choices),
                "description": clean_feature_text(row.get("description")),
                "active": 1 if is_active else 0,
                "sequence": int(base_rec.get("sequence") or ((idx + 1) * 10)),
            }
        )
    if not live_rows:
        return base_features, rename_maps
    return pd.DataFrame(live_rows), rename_maps


live_features, live_choice_rename_maps = _resolve_live_complexity_features(
    features, feature_rows, visible_features, edited_features
)

if feature_actions.save_and_refresh:
    try:
        if not selected_features.empty:
            raise ValueError("Clear selected rows before saving feature edits.")
        edited_features = drop_untouched_new_rows(
            edited_features,
            identifying_columns=["category", "name", "allowed_choices"],
        )
        merged_features = merge_filtered_edits(
            feature_rows, visible_features, edited_features
        )
        changed_features = pending_feature_edit_summaries()
        _remap_choice_in_session_filters(project_id, live_choice_rename_maps)
        _preserve_and_remap_tree_editor_draft(tree_editor_key, live_choice_rename_maps)
        count = update_complexity_features(project_id, merged_features)
        editor_name = st.session_state.get("current_editor", "")
        apply_inferred_part_feature_rules(
            project_id,
            overwrite_existing=True,
            editor_name=editor_name,
            skip_multi_feature=True,
        )
        st.session_state[feature_undo_key] = current_complexity_snapshot
        record_audit_event(
            project_id,
            "Feature definitions",
            "Save & Refresh",
            len(changed_features),
            editor_name,
            {"features": changed_features, "created_count": count_table_create_and_edit_rows(feature_rows, merged_features)[0], "updated_count": count_table_create_and_edit_rows(feature_rows, merged_features)[1]},
        )
        request_table_editor_reset(tree_editor_key)
        request_table_editor_reset(feature_editor_key)
        st.toast(
            f"Saved {count} feature definition(s)"
            + (f" ({len(changed_features)} modified)" if changed_features else ""),
            icon=":material/check_circle:",
        )
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
    live_features.loc[live_features["active"].fillna(1).astype(bool)].copy()
    if not live_features.empty else live_features
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
    if st.session_state.get(f"pending_multi_feature_review_{project_id}"):
        review_multi_feature_applicability_dialog(project_id)
    if live_choice_rename_maps:
        _remap_choice_in_session_filters(project_id, live_choice_rename_maps)
    feature_schema_sig = tuple(
        (
            str(r.get("id") or ""),
            str(r.get("category") or ""),
            str(r.get("name") or ""),
            str(r.get("allowed_values") or "[]"),
        )
        for _, r in active_features.iterrows()
    )
    feature_sig_key = f"_complexity_tree_feature_sig_{project_id}"
    prev_feature_sig = st.session_state.get(feature_sig_key)
    if prev_feature_sig is not None and prev_feature_sig != feature_schema_sig:
        _preserve_and_remap_tree_editor_draft(tree_editor_key, live_choice_rename_maps)
        request_table_editor_reset(tree_editor_key)
        tree_editor_key = apply_pending_table_editor_reset(
            f"complexity_tree_editor_{project_id}"
        )
    st.session_state[feature_sig_key] = feature_schema_sig

    full_complexity_tree = complexity_tree(project_id)
    active_feature_ids = active_features["id"].astype(str).tolist()
    for _, feature in active_features.iterrows():
        fid = str(feature["id"])
        choices = [
            str(c).strip()
            for c in json.loads(feature["allowed_values"] or "[]")
            if c is not None and str(c).strip()
        ]
        choice_set = set(choices)
        if fid not in full_complexity_tree.columns:
            full_complexity_tree[fid] = None
            continue
        rmap = live_choice_rename_maps.get(fid, {})

        def _normalize_tree_cell(
            val: object,
            _rmap: dict[str, str] = rmap,
            _valid: set[str] = choice_set,
        ) -> object:
            if val is None or pd.isna(val):
                return None
            text = str(val).strip()
            if not text:
                return None
            mapped = _rmap.get(text, text)
            return mapped if mapped in _valid else None

        full_complexity_tree[fid] = full_complexity_tree[fid].map(_normalize_tree_cell)

    tree = full_complexity_tree.loc[
        full_complexity_tree["model_id"].astype(str).isin(active_model_ids)
    ].copy()
    tree["id"] = tree["model_id"]
    tree = tree[["id", "model_id", "common_name", "official_model_number", *active_feature_ids]]
    spacer_count = max(6, len(active_feature_ids))
    spacer_columns = [
        f"__complexity_tree_spacer_{index}" for index in range(1, spacer_count + 1)
    ]
    for spacer_column in spacer_columns:
        tree[spacer_column] = ""
    tree_config = {
        "id": None,
        "model_id": None,
        "common_name": st.column_config.TextColumn(
            "Model name",
            width="medium",
            help="Friendly name defined for this model in Model information above.",
        ),
        "official_model_number": st.column_config.TextColumn(
            "Model number",
            width="medium",
            pinned=True,
            help="Unique model identifier from Model information above.",
        ),
    }
    feature_filter_options: dict[str, list[str]] = {}
    for _, feature in active_features.iterrows():
        feature_id = str(feature["id"])
        choices = json.loads(feature["allowed_values"] or "[]")
        feature_filter_options[feature_id] = choices
        tree_config[feature_id] = st.column_config.SelectboxColumn(
            f"{feature['category']} · {feature['name']}",
            options=choices,
            width="medium",
            help=str(feature.get("description") or "").strip()
            or "Select which option from Allowed choices applies to each model for this feature.",
        )
    for spacer_column in spacer_columns:
        tree_config[spacer_column] = st.column_config.TextColumn(
            "", width="medium"
        )
    feature_filter_labels = {
        "official_model_number": "Model number",
        "common_name": "Model name",
        **{
            str(f["id"]): f"{f['category']} · {f['name']}"
            for _, f in active_features.iterrows()
        },
    }
    tree_filter_expander = st.expander(
        "Filter columns", icon=":material/filter_list:", expanded=False
    )
    tree_always_visible_filters = st.container(
        horizontal=True, vertical_alignment="bottom"
    )
    tree_caption_slot = st.container()
    with tree_filter_expander:
        visible_tree = filter_table(
            tree,
            key=f"complexity_tree_filters_{project_id}",
            dropdown_columns=[
                "official_model_number",
                "common_name",
                *active_feature_ids,
            ],
            always_visible_dropdown_columns=[
                "official_model_number",
                "common_name",
            ],
            dropdown_options=feature_filter_options,
            search_columns=[
                "official_model_number",
                "common_name",
                *active_feature_ids,
            ],
            labels=feature_filter_labels,
            reset_widget_keys=[tree_editor_key],
            keyword_container=tree_always_visible_filters,
            caption_container=tree_caption_slot,
        )
        clear_tree_filter_actions = st.container(
            horizontal=True, horizontal_alignment="right"
        )
        if clear_tree_filter_actions.button(
            "Clear filters",
            icon=":material/filter_alt_off:",
            key=f"clear_complexity_tree_filters_{project_id}",
        ):
            st.session_state.pop(
                f"complexity_tree_filters_{project_id}_keyword", None
            )
            st.session_state.pop(
                f"_saved_filter_kw_complexity_tree_filters_{project_id}", None
            )
            for filter_column in [
                "official_model_number",
                "common_name",
                *active_feature_ids,
            ]:
                w_key = f"complexity_tree_filters_{project_id}_{filter_column}"
                st.session_state.pop(w_key, None)
                st.session_state.pop(f"_saved_filter_col_{w_key}", None)
            st.rerun()
    edited_tree = st.data_editor(
        visible_tree,
        key=tree_editor_key,
        hide_index=True,
        num_rows="delete",
        height=420,
        width="content",
        disabled=[
            "id", "model_id", "common_name", "official_model_number", *spacer_columns,
        ],
        column_order=[
            "official_model_number", "common_name", *active_feature_ids, *spacer_columns,
        ],
        column_config=tree_config,
    )
    tree_has_unsaved = table_has_unsaved_changes(
        tree_editor_key, native_row_selection=True
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
    selected_tree_rows = native_selected_rows(visible_tree, editor_key=tree_editor_key)

    def persist_complexity_tree_save(pending: dict) -> None:
        editor_name = st.session_state.get("current_editor", "")
        if feature_has_unsaved and selected_features.empty:
            cleaned_feat = drop_untouched_new_rows(
                edited_features,
                identifying_columns=["category", "name", "allowed_choices"],
            )
            merged_feat = merge_filtered_edits(
                feature_rows, visible_features, cleaned_feat
            )
            changed_feat_summaries = pending_feature_edit_summaries()
            update_complexity_features(project_id, merged_feat)
            record_audit_event(
                project_id,
                "Feature definitions",
                "Save & Refresh",
                len(changed_feat_summaries),
                editor_name,
                {
                    "features": changed_feat_summaries,
                    "saved_with_complexity_tree": True,
                },
            )
            request_table_editor_reset(feature_editor_key)
        pending_tree = pd.DataFrame(pending.get("rows", []))
        changed_assignment_count = int(pending.get("changed_assignment_count", 0))
        count = update_complexity_tree(project_id, pending_tree)
        record_audit_event(
            project_id,
            "Complexity tree",
            "Save & Refresh",
            changed_assignment_count,
            editor_name,
            {
                "model_feature_assignments_changed": changed_assignment_count,
            },
        )
        auto_assigned_count = apply_inferred_part_feature_rules(
            project_id,
            overwrite_existing=True,
            editor_name=editor_name,
            skip_multi_feature=False,
        )
        preview = preview_inferred_part_feature_rules(
            project_id,
            overwrite_existing=True,
        )
        if preview["review"]:
            st.session_state[f"pending_multi_feature_review_{project_id}"] = {
                "preview": {**preview, "direct": {}},
                "source_page": "models",
            }
        st.session_state[tree_undo_key] = pending.get(
            "snapshot", current_complexity_snapshot
        )
        st.session_state.pop(tree_pending_save_key, None)
        request_table_editor_reset(tree_editor_key)
        tree_save_msg = f"Saved {count} model feature selection(s)"
        if changed_assignment_count:
            tree_save_msg += f" ({changed_assignment_count} changed)"
        if auto_assigned_count > 0:
            tree_save_msg += (
                f" · auto-assigned {auto_assigned_count} part(s) in Parts Catalog"
            )
        st.toast(tree_save_msg, icon=":material/check_circle:")
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
            left_name = conflict.get("left_common_name") or "No model name"
            left_number = conflict.get("left_official_model_number") or "No model number"
            right_name = conflict.get("right_common_name") or "No model name"
            right_number = conflict.get("right_official_model_number") or "No model number"
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
            merged_tree = merge_filtered_edits(
                tree, visible_tree, edited_tree, id_column="model_id"
            )
            existing_tree_by_model = {
                str(row["model_id"]): row for _, row in tree.iterrows()
            }
            changed_assignment_count = 0
            for _, row in merged_tree.iterrows():
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
            conflicts = potential_duplicate_models(project_id, merged_tree)
            pending = {
                "rows": merged_tree.to_dict("records"),
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
    visual_heading_cols = st.columns([6, 1], vertical_alignment="bottom")
    with visual_heading_cols[0]:
        editable_table_heading("Complexity tree visual")
    with visual_heading_cols[1]:
        if st.button(
            "Print",
            icon=":material/print:",
            key=f"btn_print_complexity_tree_visual_{project_id}",
            width="stretch",
            help="Print or export the Complexity tree visual to PDF",
        ):
            st.session_state[f"complexity_tree_print_active_{project_id}"] = True
    category_values = sorted(
        {
            str(category).strip()
            for category in active_features["category"].dropna()
            if str(category).strip()
        }
    )
    visual_category_key = f"complexity_tree_visual_category_{project_id}"
    existing_visual_category = st.session_state.get(visual_category_key)
    if isinstance(existing_visual_category, str):
        st.session_state[visual_category_key] = (
            [existing_visual_category]
            if existing_visual_category in category_values
            else []
        )
    elif isinstance(existing_visual_category, list):
        valid_categories = [
            cat for cat in existing_visual_category if cat in category_values
        ]
        if valid_categories != existing_visual_category:
            st.session_state[visual_category_key] = valid_categories
    visual_categories = st.multiselect(
        "Category",
        category_values,
        placeholder="Select one or more categories",
        key=visual_category_key,
    )
    visual_model_label_options = ["Model name", "Model number"]
    visual_model_label_key = f"complexity_tree_visual_model_label_{project_id}"

    def _normalize_visual_model_label(value: object) -> str:
        text = str(value or "").strip()
        if text == "Common name":
            return "Model name"
        if text == "Official model number":
            return "Model number"
        return text

    existing_visual_model_label = st.session_state.get(visual_model_label_key)
    if isinstance(existing_visual_model_label, str):
        normalized_model_label = _normalize_visual_model_label(existing_visual_model_label)
        st.session_state[visual_model_label_key] = (
            [normalized_model_label]
            if normalized_model_label in visual_model_label_options
            else []
        )
    elif isinstance(existing_visual_model_label, list):
        valid_model_labels = list(
            dict.fromkeys(
                _normalize_visual_model_label(item)
                for item in existing_visual_model_label
                if _normalize_visual_model_label(item) in visual_model_label_options
            )
        )
        if valid_model_labels != existing_visual_model_label:
            st.session_state[visual_model_label_key] = valid_model_labels
    visual_model_labels = st.multiselect(
        "Model label",
        visual_model_label_options,
        placeholder="Select one or more model labels",
        key=visual_model_label_key,
        help="Choose which model identifiers appear in the visual headers.",
    )
    visual_feature_display_options = ["Feature", "Part number", "Part name"]
    visual_feature_display_key = f"complexity_tree_visual_feature_display_{project_id}"
    if visual_feature_display_key not in st.session_state:
        st.session_state[visual_feature_display_key] = ["Feature"]
    else:
        existing_visual_feature_display = st.session_state.get(visual_feature_display_key)
        if isinstance(existing_visual_feature_display, str):
            cleaned_feature_display = existing_visual_feature_display.strip()
            st.session_state[visual_feature_display_key] = (
                [cleaned_feature_display]
                if cleaned_feature_display in visual_feature_display_options
                else []
            )
        elif isinstance(existing_visual_feature_display, list):
            valid_feature_displays = list(
                dict.fromkeys(
                    str(item).strip()
                    for item in existing_visual_feature_display
                    if str(item).strip() in visual_feature_display_options
                )
            )
            if valid_feature_displays != existing_visual_feature_display:
                st.session_state[visual_feature_display_key] = valid_feature_displays
    visual_feature_displays = st.multiselect(
        "Feature",
        visual_feature_display_options,
        placeholder="Select one or more feature displays",
        key=visual_feature_display_key,
        help="Choose whether the visual displays feature values from the complexity tree, assigned part numbers or part names from the Parts Catalog, or any combination.",
    )
    selected_categories = [
        str(category).strip()
        for category in (visual_categories or [])
        if str(category).strip()
    ]
    selected_model_labels = [
        str(label).strip()
        for label in (visual_model_labels or [])
        if str(label).strip() in visual_model_label_options
    ]
    selected_feature_displays = [
        str(display).strip()
        for display in (visual_feature_displays or [])
        if str(display).strip() in visual_feature_display_options
    ]
    if not selected_categories or not selected_model_labels or not selected_feature_displays:
        if not selected_categories and not selected_model_labels:
            st.info("Select at least one category and a model label to generate the complexity tree visual.")
        elif not selected_categories:
            st.info("Select at least one category to generate the complexity tree visual.")
        elif not selected_model_labels:
            st.info("Select a model label to generate the complexity tree visual.")
        else:
            st.info("Select at least one feature display option to generate the complexity tree visual.")
        visual_features = None
    else:
        category_order = {cat: idx for idx, cat in enumerate(selected_categories)}
        visual_features = (
            active_features.loc[
                active_features["category"]
                .fillna("")
                .astype(str)
                .str.strip()
                .isin(selected_categories)
            ]
            .assign(
                _category_order=lambda df: df["category"]
                .fillna("")
                .astype(str)
                .str.strip()
                .map(category_order)
            )
            .sort_values(by="_category_order", kind="stable")
            .drop(columns=["_category_order"])
        )

    visual_models = models.loc[
        models["active"].fillna(1).astype(bool),
        ["id", "display_name", "model_number"],
    ].copy()
    live_visual_tree_df = merge_filtered_edits(
        tree, visible_tree, edited_tree, id_column="model_id"
    )
    visual_tree = live_visual_tree_df.set_index("model_id")
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
        value_ranks: list[dict[str, int]] = [
            {} for _ in range(len(feature_ids))
        ]
        for values in groups_by_values:
            for idx, val in enumerate(values):
                if val not in value_ranks[idx]:
                    value_ranks[idx][val] = len(value_ranks[idx])
        sorted_group_keys = sorted(
            groups_by_values.keys(),
            key=lambda vals: tuple(
                value_ranks[idx][val] for idx, val in enumerate(vals)
            ),
        )
        visual_model_groups = [groups_by_values[key] for key in sorted_group_keys]
    if visual_features is None:
        pass
    elif visual_features.empty:
        st.info("No active features match the selected categories.")
    elif not visual_model_groups:
        st.info("No active models are available for the complexity tree visual.")
    else:
        grid_columns = len(visual_model_groups)
        grid_template = (
            f"minmax(130px, 1.2fr) repeat({grid_columns}, minmax(max-content, 1fr))"
        )

        def _build_group_model_label_lines(
            group: dict[str, object],
            selected_labels: list[str],
        ) -> list[str]:
            if selected_labels == ["Model name"]:
                return [
                    escape(str(label or "Model name not defined"))
                    for label in dict.fromkeys(group["model_names"])
                ]
            if selected_labels == ["Model number"]:
                return [escape(str(label)) for label in group["model_numbers"]]
            lines: list[str] = []
            for model_name, model_number in zip(
                group["model_names"],
                group["model_numbers"],
            ):
                for label_type in selected_labels:
                    if label_type == "Model name":
                        lines.append(escape(str(model_name or "Model name not defined")))
                    elif label_type == "Model number":
                        lines.append(escape(str(model_number)))
            return lines

        group_label_lines = [
            _build_group_model_label_lines(group, selected_model_labels)
            for group in visual_model_groups
        ]
        model_header_height = max(
            42,
            max(len(lines) for lines in group_label_lines) * 22 + 12,
        )
        active_model_total = len(visual_models)
        model_group_total = len(visual_model_groups)
        feature_total = len(visual_features)
        visual_summary_text = (
            f"{active_model_total} active model{'s' if active_model_total != 1 else ''} · "
            f"{model_group_total} model group{'s' if model_group_total != 1 else ''} · "
            f"{feature_total} feature{'s' if feature_total != 1 else ''}"
        )
        def _hsl_to_hex(h_deg: float, s_pct: float, l_pct: float) -> str:
            r, g, b = colorsys.hls_to_rgb(
                (h_deg % 360) / 360.0,
                max(0.0, min(1.0, l_pct / 100.0)),
                max(0.0, min(1.0, s_pct / 100.0)),
            )
            return (
                f"#{int(round(r * 255)):02x}"
                f"{int(round(g * 255)):02x}"
                f"{int(round(b * 255)):02x}"
            )

        visual_shell_css = (
            "<style>"
            ".complexity-tree-shell{position:relative;box-sizing:border-box;width:100%;max-width:100%;min-width:0;margin-top:6px;border:1px solid var(--st-border-color,#cbd5e1);border-radius:var(--st-base-radius,8px);overflow:hidden;background:var(--st-background-color,#ffffff);}"
            ".complexity-tree-shell.fullscreen-visual,.complexity-tree-shell:fullscreen{position:fixed;inset:0;z-index:999995;width:100vw;height:100vh;max-width:100vw;min-width:0;margin:0;border:0;border-radius:0;display:flex;flex-direction:column;overflow:hidden;background:var(--st-background-color,#ffffff);}"
            ".complexity-tree-toolbar{position:sticky;left:0;top:0;z-index:30;width:100%;box-sizing:border-box;display:flex;align-items:center;justify-content:space-between;gap:8px 12px;padding:8px 14px;border-bottom:1px solid var(--st-border-color,#cbd5e1);background:var(--st-secondary-background-color,#f8fafc);flex-wrap:wrap;flex:0 0 auto;}"
            ".complexity-tree-shell.fullscreen-visual .complexity-tree-toolbar,.complexity-tree-shell:fullscreen .complexity-tree-toolbar{padding:10px 16px;box-shadow:0 2px 8px rgba(0,0,0,.08);}"
            ".complexity-tree-toolbar-title{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;min-width:0;}"
            ".complexity-tree-toolbar-title strong{font-size:.95rem;color:var(--st-text-color,#0f172a);white-space:nowrap;}"
            ".complexity-tree-toolbar-title span{color:var(--st-secondary-text-color,#475569);font-size:.82rem;white-space:nowrap;}"
            ".complexity-tree-toolbar-hint{color:var(--st-secondary-text-color,#64748b);font-size:.78rem;white-space:nowrap;}"
            ".complexity-tree-toolbar-controls{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}"
            ".complexity-tree-zoom-controls{display:inline-flex;align-items:center;gap:6px;}"
            ".complexity-tree-toolbar-controls button{display:inline-flex;align-items:center;justify-content:center;gap:4px;min-width:32px;min-height:30px;height:auto;padding:4px 10px;white-space:nowrap;flex-shrink:0;line-height:1.2;box-sizing:border-box;border:1px solid var(--st-border-color,#cbd5e1);border-radius:var(--st-button-radius,6px);color:var(--st-text-color,#0f172a);background:var(--st-background-color,#ffffff);cursor:pointer;font:inherit;font-size:.81rem;font-weight:600;}"
            ".complexity-tree-toolbar-controls button.btn-tool{background:var(--st-secondary-background-color,#f8fafc);}"
            ".complexity-tree-toolbar-controls button.btn-tool.is-active-tool{border-color:var(--st-primary-color,#2563eb);color:var(--st-primary-color,#2563eb);background:rgba(37,99,235,.08);}"
            ".complexity-tree-toolbar-controls button:hover:not(:disabled){border-color:var(--st-primary-color,#2563eb);color:var(--st-primary-color,#2563eb);}"
            ".complexity-tree-toolbar-controls button:disabled{opacity:.48;cursor:not-allowed;}"
            ".complexity-tree-body{display:flex;width:100%;max-width:100%;min-width:0;align-items:stretch;box-sizing:border-box;}"
            ".complexity-tree-shell.fullscreen-visual .complexity-tree-body,.complexity-tree-shell:fullscreen .complexity-tree-body{flex:1 1 auto;min-height:0;overflow:hidden;}"
            ".complexity-tree-sidebar{flex:0 0 320px;width:320px;max-width:350px;box-sizing:border-box;border-right:1px solid var(--st-border-color,#cbd5e1);background:var(--st-secondary-background-color,#f8fafc);display:flex;flex-direction:column;max-height:680px;overflow:hidden;}"
            ".complexity-tree-shell.fullscreen-visual .complexity-tree-sidebar,.complexity-tree-shell:fullscreen .complexity-tree-sidebar{max-height:none;height:100%;}"
            ".complexity-tree-sidebar.collapsed{display:none !important;}"
            ".complexity-tree-sidebar-header{padding:10px 12px 8px;border-bottom:1px solid var(--st-border-color,#cbd5e1);display:flex;flex-direction:column;gap:3px;flex:0 0 auto;}"
            ".complexity-tree-sidebar-title-row{display:flex;align-items:center;justify-content:space-between;gap:6px;}"
            ".complexity-tree-sidebar-title-row strong{font-size:.88rem;color:var(--st-text-color,#0f172a);}"
            ".complexity-tree-sidebar-badge{font-size:.72rem;font-weight:700;padding:1px 7px;border-radius:999px;background:var(--st-background-color,#ffffff);border:1px solid var(--st-border-color,#cbd5e1);color:var(--st-secondary-text-color,#475569);}"
            ".complexity-tree-sidebar-hint{font-size:.74rem;line-height:1.3;color:var(--st-secondary-text-color,#64748b);}"
            ".complexity-tree-sidebar-controls{padding:8px 12px;border-bottom:1px solid var(--st-border-color,#cbd5e1);display:flex;flex-direction:column;gap:6px;flex:0 0 auto;background:var(--st-background-color,#ffffff);}"
            ".ct-sidebar-search{width:100%;box-sizing:border-box;padding:5px 8px;border:1px solid var(--st-border-color,#cbd5e1);border-radius:6px;font:inherit;font-size:.8rem;color:var(--st-text-color,#0f172a);background:var(--st-secondary-background-color,#f8fafc);}"
            ".ct-sidebar-search:focus{outline:none;border-color:var(--st-primary-color,#2563eb);background:var(--st-background-color,#ffffff);}"
            ".ct-sidebar-tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;}"
            ".ct-sidebar-tab{padding:4px 6px;border:1px solid var(--st-border-color,#cbd5e1);border-radius:5px;background:var(--st-secondary-background-color,#f8fafc);color:var(--st-secondary-text-color,#475569);font:inherit;font-size:.74rem;font-weight:600;cursor:pointer;text-align:center;}"
            ".ct-sidebar-tab.active{background:var(--st-primary-color,#2563eb);border-color:var(--st-primary-color,#2563eb);color:#ffffff;}"
            ".complexity-tree-sidebar-list{flex:1 1 auto;min-height:0;overflow-y:auto;padding:8px 10px 12px;display:flex;flex-direction:column;gap:8px;}"
            ".ct-sidebar-section-hdr{font-size:.73rem;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:var(--st-secondary-text-color,#64748b);padding:4px 2px 2px;display:flex;align-items:center;justify-content:space-between;}"
            ".ct-sidebar-card{border:1px solid var(--st-border-color,#cbd5e1);border-radius:7px;background:var(--st-background-color,#ffffff);padding:7px 9px;display:flex;flex-direction:column;gap:6px;box-shadow:0 1px 2px rgba(15,23,42,.03);}"
            ".ct-sidebar-row{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;}"
            ".ct-sidebar-label{font-size:.8rem;font-weight:700;color:var(--st-text-color,#0f172a);line-height:1.25;min-width:0;overflow:hidden;text-overflow:ellipsis;}"
            ".ct-sidebar-sublabel{font-size:.72rem;font-weight:500;color:var(--st-secondary-text-color,#64748b);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}"
            ".ct-color-actions{display:inline-flex;align-items:center;gap:4px;flex-shrink:0;}"
            ".ct-color-input{width:24px;height:24px;padding:0;border:1px solid var(--st-border-color,#cbd5e1);border-radius:5px;background:transparent;cursor:pointer;flex-shrink:0;}"
            ".ct-color-reset-mini{width:22px;height:22px;padding:0;border:1px solid var(--st-border-color,#cbd5e1);border-radius:5px;background:var(--st-secondary-background-color,#f8fafc);color:var(--st-secondary-text-color,#475569);font-size:.75rem;line-height:1;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;}"
            ".ct-color-reset-mini:hover{border-color:#dc2626;color:#dc2626;background:#fef2f2;}"
            ".ct-preset-swatches{display:flex;align-items:center;gap:4px;flex-wrap:wrap;}"
            ".ct-preset-swatch{width:16px;height:16px;border-radius:999px;border:1.5px solid rgba(15,23,42,.2);padding:0;cursor:pointer;flex-shrink:0;transition:transform .1s ease,border-color .1s ease;}"
            ".ct-preset-swatch:hover{transform:scale(1.18);border-color:#0f172a;}"
            ".ct-family-pill-btn{display:inline-flex;align-items:center;gap:5px;padding:3px 7px;border:1px solid var(--st-border-color,#cbd5e1);border-radius:999px;background:var(--st-secondary-background-color,#f8fafc);color:var(--st-text-color,#0f172a);font:inherit;font-size:.72rem;font-weight:600;cursor:pointer;transition:border-color .12s ease,background-color .12s ease;}"
            ".ct-family-pill-btn:hover,.ct-family-pill-btn.is-open{border-color:var(--st-primary-color,#2563eb);background:rgba(37,99,235,.06);color:var(--st-primary-color,#2563eb);}"
            ".ct-family-mini-dots{display:inline-flex;align-items:center;gap:2px;}"
            ".ct-family-mini-dot{width:10px;height:10px;border-radius:999px;border:1px solid rgba(15,23,42,.18);display:inline-block;}"
            ".ct-palette-drawer{margin-top:2px;padding:8px;border:1px solid var(--st-border-color,#cbd5e1);border-radius:8px;background:var(--st-secondary-background-color,#f8fafc);display:flex;flex-direction:column;gap:7px;}"
            ".ct-palette-drawer-title{font-size:.72rem;font-weight:700;color:var(--st-secondary-text-color,#475569);display:flex;align-items:center;justify-content:space-between;gap:4px;}"
            ".ct-palette-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 8px;align-items:center;}"
            ".ct-palette-family-row{display:flex;align-items:center;justify-content:space-between;gap:3px;padding:4px 6px;border-radius:999px;border:1.5px solid rgba(15,23,42,.08);background:#ffffff;cursor:pointer;transition:border-color .12s ease,box-shadow .12s ease,transform .1s ease;}"
            ".ct-palette-family-row:hover{border-color:var(--st-primary-color,#2563eb);box-shadow:0 2px 6px rgba(37,99,235,.15);transform:translateY(-1px);}"
            ".ct-palette-family-row.is-active-family{border-color:var(--st-primary-color,#2563eb);box-shadow:0 0 0 2px rgba(37,99,235,.16);background:#f8fafc;}"
            ".ct-shade-dot{width:19px;height:19px;border-radius:999px;border:1.5px solid rgba(15,23,42,.18);padding:0;cursor:pointer;flex-shrink:0;transition:transform .1s ease,border-color .1s ease,box-shadow .1s ease;box-sizing:border-box;background-clip:padding-box;}"
            ".ct-shade-dot:hover{transform:scale(1.2);border-color:#0f172a;z-index:2;}"
            ".ct-shade-dot.is-active-shade{border:2px solid #0f172a !important;box-shadow:0 0 0 2px #ffffff inset,0 1px 4px rgba(15,23,42,.35);transform:scale(1.1);}"
            ".ct-saved-custom-section{display:flex;flex-direction:column;gap:5px;padding-top:6px;border-top:1px dashed var(--st-border-color,#cbd5e1);}"
            ".ct-saved-custom-row{display:flex;align-items:center;justify-content:space-between;gap:4px;}"
            ".ct-saved-custom-delete{width:20px;height:20px;padding:0;border:1px solid var(--st-border-color,#cbd5e1);border-radius:999px;background:#ffffff;color:#64748b;font-size:.72rem;line-height:1;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;}"
            ".ct-saved-custom-delete:hover{border-color:#dc2626;color:#dc2626;background:#fef2f2;}"
            ".ct-custom-creator-bar{display:flex;align-items:center;justify-content:space-between;gap:6px;padding-top:6px;border-top:1px dashed var(--st-border-color,#cbd5e1);flex-wrap:wrap;}"
            ".ct-custom-creator-left{display: inline-flex;align-items:center;gap:5px;}"
            ".ct-custom-save-btn{padding:3px 8px;border:1px solid var(--st-primary-color,#2563eb);border-radius:5px;background:var(--st-primary-color,#2563eb);color:#ffffff;font:inherit;font-size:.72rem;font-weight:700;cursor:pointer;white-space:nowrap;}"
            ".ct-custom-save-btn:hover{opacity:.92;}"
            ".ct-choice-chips{display:flex;flex-direction:column;gap:5px;padding-top:5px;border-top:1px dashed var(--st-border-color,#e2e8f0);}"
            ".ct-choice-row{display:flex;align-items:center;justify-content:space-between;gap:6px;padding:3px 5px;border-radius:6px;background:var(--st-secondary-background-color,#f8fafc);flex-wrap:wrap;}"
            ".ct-choice-preview{font-size:.74rem;font-weight:700;padding:2px 7px;border-radius:4px;min-width:0;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:1px solid rgba(15,23,42,.12);}"
            ".ct-choice-shades{display:inline-flex;align-items:center;gap:3px;}"
            ".complexity-tree-viewport{position:relative;box-sizing:border-box;flex:1 1 auto;width:100%;max-width:100%;min-width:0;padding:12px 14px 16px;overflow-x:auto;overflow-y:visible;}"
            ".complexity-tree-shell.fullscreen-visual .complexity-tree-viewport,.complexity-tree-shell:fullscreen .complexity-tree-viewport{flex:1 1 auto;min-height:0;padding:16px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable both-edges;cursor:grab;}"
            ".complexity-tree-shell.is-panning .complexity-tree-viewport{cursor:grabbing !important;user-select:none;}"
            ".complexity-tree-zoom-stage{position:relative;box-sizing:border-box;width:100%;min-width:100%;}"
            ".complexity-tree-content{position:relative;box-sizing:border-box;width:100%;min-width:100%;transform-origin:0 0;}"
            ".ct-model-col-header{position:relative;cursor:grab;user-select:none;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;transition:border-color .14s ease,box-shadow .14s ease,transform .12s ease,background-color .14s ease;background:var(--st-background-color,#ffffff);}"
            ".ct-col-header-label{display:inline-block;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;}"
            ".ct-model-col-header:hover{border-color:#0284c7 !important;box-shadow:0 3px 10px rgba(2,132,199,.22);}"
            ".ct-model-col-header.is-dragging-col{opacity:.52;border-style:dashed !important;border-color:#0284c7 !important;background:#e0f2fe !important;cursor:grabbing !important;}"
            ".ct-col-move-btn{position:absolute;top:2px;width:18px;height:18px;border-radius:4px;border:1px solid #cbd5e1;background:rgba(255,255,255,.94);color:#0f172a;font-size:10px;line-height:1;display:none;align-items:center;justify-content:center;cursor:pointer;padding:0;z-index:4;box-shadow:0 1px 3px rgba(0,0,0,.12);}"
            ".ct-col-move-btn:hover{background:#0284c7;color:#ffffff;border-color:#0284c7;}"
            ".ct-col-move-left{left:2px;}"
            ".ct-col-move-right{right:2px;}"
            ".ct-model-col-header:hover .ct-col-move-btn{display:inline-flex;}"
            ".ct-model-col-header[data-is-first='true'] .ct-col-move-left{display:none !important;}"
            ".ct-model-col-header[data-is-last='true'] .ct-col-move-right{display:none !important;}"
            ".ct-feature-box{transition:box-shadow .18s ease,outline .18s ease,transform .18s ease;}"
            ".ct-feature-box.ct-will-merge-preview{outline:3px solid #ec4899 !important;outline-offset:1px;box-shadow:0 0 0 3px rgba(236,72,153,.28),0 4px 12px rgba(236,72,153,.25) !important;z-index:3;position:relative;}"
            "@keyframes ctMergePulse{0%{outline:3px solid #ec4899;box-shadow:0 0 0 5px rgba(236,72,153,.35);}100%{outline:0px solid transparent;box-shadow:none;}}"
            ".ct-feature-box.ct-merged-box-flash{animation:ctMergePulse 1.15s ease-out;position:relative;z-index:2;}"
            ".ct-col-drop-indicator{position:fixed;width:4px;border-radius:999px;background:#0284c7;box-shadow:0 0 10px rgba(2,132,199,.75);pointer-events:none;z-index:1000030;display:none;}"
            ".ct-col-drop-indicator::before,.ct-col-drop-indicator::after{content:'';position:absolute;left:50%;transform:translateX(-50%);width:12px;height:12px;border-radius:999px;background:#0284c7;border:2px solid #ffffff;box-shadow:0 1px 4px rgba(0,0,0,.25);}"
            ".ct-col-drop-indicator::before{top:-6px;}"
            ".ct-col-drop-indicator::after{bottom:-6px;}"
            ".ct-col-drag-ghost{position:fixed;z-index:1000035;pointer-events:none;background:#0f172a;color:#ffffff;padding:6px 12px;border-radius:999px;font-size:.8rem;font-weight:700;box-shadow:0 8px 24px rgba(15,23,42,.35);border:1.5px solid #38bdf8;white-space:nowrap;display:none;align-items:center;gap:6px;}"
            ".ct-col-drag-ghost .ct-ghost-merge-badge{background:#ec4899;color:#ffffff;padding:1px 7px;border-radius:999px;font-size:.72rem;font-weight:800;}"
            "</style>"
        )
        initial_sidebar_items_html: list[str] = [
            '<div class="ct-sidebar-section-hdr"><span>Model definitions</span>'
            f'<span>{len(visual_model_groups)}</span></div>'
        ]
        for group in visual_model_groups:
            grp_key = "|".join(str(m) for m in group["model_numbers"])
            grp_label = " / ".join(str(m) for m in group["model_numbers"])
            initial_sidebar_items_html.append(
                f'<div class="ct-sidebar-card" data-sidebar-model-group="{escape(grp_key)}">'
                '<div class="ct-sidebar-row">'
                f'<span class="ct-sidebar-label">{escape(grp_label)}</span>'
                '</div></div>'
            )
        initial_sidebar_items_html.append(
            '<div class="ct-sidebar-section-hdr"><span>Feature definitions</span>'
            f'<span>{len(visual_features)}</span></div>'
        )
        for _, feat_row_preview in visual_features.iterrows():
            f_name_preview = str(feat_row_preview["name"]).strip()
            initial_sidebar_items_html.append(
                f'<div class="ct-sidebar-card" data-sidebar-feature-id="{escape(str(feat_row_preview["id"]))}">'
                '<div class="ct-sidebar-row">'
                f'<span class="ct-sidebar-label">{escape(f_name_preview)}</span>'
                '</div></div>'
            )

        visual_html = [
            visual_shell_css,
            f'<div id="complexity-tree-shell" class="complexity-tree-shell" data-project-id="{escape(str(project_id))}">',
            '<div class="complexity-tree-toolbar" id="complexity-tree-toolbar">',
            '<div class="complexity-tree-toolbar-title" id="complexity-tree-toolbar-title">',
            '<strong>Complexity tree visual</strong>',
            f'<span id="complexity-tree-toolbar-summary">{escape(visual_summary_text)}</span>',
            '<span class="complexity-tree-toolbar-hint">· Drag any Model column left/right (or click ◀ ▶) to reorder &amp; merge matching variant boxes</span>',
            '</div>',
            '<div class="complexity-tree-toolbar-controls">',
            '<button id="complexity-tree-toggle-sidebar" type="button" data-ct-action="toggle-sidebar" class="btn-tool is-active-tool" title="Toggle the model &amp; feature color customization sidebar" aria-expanded="true">🎨 Colors</button>',
            '<button id="complexity-tree-reset-colors" type="button" data-ct-action="reset-colors" class="btn-tool" title="Reset all custom model &amp; feature colors to default" disabled>↺ Reset Colors</button>',
            '<button id="complexity-tree-reset-cols" type="button" data-ct-action="reset-cols" class="btn-tool" title="Reset model columns to default order" disabled>↺ Reset Columns</button>',
            '<button id="complexity-tree-print" type="button" data-ct-action="print" class="btn-tool" title="Print or export the Complexity tree visual to PDF">🖨️ Print</button>',
            '<div class="complexity-tree-zoom-controls" id="complexity-tree-zoom-controls">',
            '<button id="complexity-tree-zoom-out" type="button" data-ct-action="zoom-out" title="Zoom out">−</button>',
            '<button id="complexity-tree-zoom-in" type="button" data-ct-action="zoom-in" title="Zoom in">+</button>',
            '<button id="complexity-tree-fit-view" type="button" data-ct-action="fit-view" title="Fit the entire complexity tree visual">Fit</button>',
            '<button id="complexity-tree-zoom-reset" type="button" data-ct-action="zoom-reset" title="Reset zoom to 100%">100%</button>',
            '</div>',
            '<button id="full-screen" type="button" data-ct-action="full-screen" title="Open the complexity tree visual full screen" aria-pressed="false">Full Screen</button>',
            '</div>',
            '</div>',
            '<div class="complexity-tree-body" id="complexity-tree-body">',
            '<aside id="complexity-tree-sidebar" class="complexity-tree-sidebar" aria-label="Color customization sidebar">',
            '<div class="complexity-tree-sidebar-header">',
            '<div class="complexity-tree-sidebar-title-row">',
            '<strong>Definition colors</strong>',
            f'<span class="complexity-tree-sidebar-badge" id="complexity-tree-sidebar-count">{len(visual_model_groups)} models · {len(visual_features)} features</span>',
            '</div>',
            '<span class="complexity-tree-sidebar-hint">Pick colors for model definitions, feature rows, or individual choices</span>',
            '</div>',
            '<div class="complexity-tree-sidebar-controls" id="complexity-tree-sidebar-controls"></div>',
            '<div class="complexity-tree-sidebar-list" id="complexity-tree-sidebar-list">',
            "".join(initial_sidebar_items_html),
            '</div>',
            '</aside>',
            '<div class="complexity-tree-viewport" id="complexity-tree-viewport">',
            '<div class="complexity-tree-zoom-stage" id="complexity-tree-zoom-stage">',
            '<div class="complexity-tree-content" id="complexity-tree-content">',
            f'<div class="complexity-tree-grid" style="display:grid;grid-template-columns:{grid_template};'
            'gap:10px 8px;align-items:center;">',
            '<div style="font-weight:700;">Model</div>',
        ]
        total_group_cols = len(group_label_lines)
        for col_idx, (group, lines) in enumerate(zip(visual_model_groups, group_label_lines)):
            model_labels = "<br>".join(lines)
            group_key = "|".join(str(m) for m in group["model_numbers"])
            is_first_str = "true" if col_idx == 0 else "false"
            is_last_str = "true" if col_idx == total_group_cols - 1 else "false"
            visual_html.append(
                f'<div class="ct-model-col-header" data-row-pos="top" data-col-index="{col_idx}" '
                f'data-group-key="{escape(group_key)}" data-is-first="{is_first_str}" data-is-last="{is_last_str}" '
                'title="Drag left or right to move this model column (matching adjacent feature boxes merge automatically)" '
                'style="font-weight:700;line-height:1.45;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;'
                f'border:2px solid #000;border-radius:4px;padding:6px 8px;min-height:{model_header_height}px;height:100%;'
                'box-sizing:border-box;display:flex;align-items:center;'
                'justify-content:center;text-align:center;">'
                '<button type="button" class="ct-col-move-btn ct-col-move-left" data-ct-move-col="-1" title="Move column left">◀</button>'
                f'<span class="ct-col-header-label">{model_labels}</span>'
                '<button type="button" class="ct-col-move-btn ct-col-move-right" data-ct-move-col="1" title="Move column right">▶</button>'
                '</div>'
            )
        visual_html.append('<div></div>')
        visual_html.extend(
            '<div style="height:12px;width:0;border-left:2px solid #475569;'
            'margin:auto;"></div>'
            for _ in visual_model_groups
        )

        show_part_displays = any(
            mode in selected_feature_displays for mode in ("Part number", "Part name")
        )
        part_rules_by_feature_value: dict[tuple[str, str], list[tuple[str, set[str] | None]]] = {}
        bom_descendants_by_pn: dict[str, set[str]] = {}
        part_name_by_pn: dict[str, str] = {}
        if show_part_displays:
            part_rules_by_feature_value, bom_descendants_by_pn = complexity_visual_part_rules(
                project_id
            )
            if "Part name" in selected_feature_displays:
                parts_df = project_table("parts", project_id)
                if not parts_df.empty:
                    for raw_pn, raw_desc in zip(
                        parts_df["part_number"], parts_df["description"]
                    ):
                        pn_key = str(raw_pn or "").strip().upper()
                        p_name = str(raw_desc or "").strip()
                        if pn_key and (
                            pn_key not in part_name_by_pn
                            or (p_name and not part_name_by_pn[pn_key])
                        ):
                            part_name_by_pn[pn_key] = p_name

        def _build_box_part_lines(
            matching_parts: list[str],
            part_modes: list[str],
        ) -> list[str]:
            if part_modes == ["Part number"]:
                return [escape(pn) for pn in matching_parts]
            if part_modes == ["Part name"]:
                return [
                    escape(label)
                    for label in dict.fromkeys(
                        part_name_by_pn.get(pn.upper(), "") or "Part name not defined"
                        for pn in matching_parts
                    )
                ]
            lines: list[str] = []
            for pn in matching_parts:
                part_name = part_name_by_pn.get(pn.upper(), "") or "Part name not defined"
                for mode in part_modes:
                    if mode == "Part number":
                        lines.append(escape(pn))
                    elif mode == "Part name":
                        lines.append(escape(part_name))
            return lines

        row_hues = [220, 145, 35, 295, 5, 180, 75, 255, 330, 110]
        feature_count = len(visual_features)
        spec_features: list[dict[str, object]] = []
        spec_columns: list[dict[str, object]] = [
            {
                "groupKey": "|".join(str(m) for m in group["model_numbers"]),
                "modelNumbers": [str(m) for m in group["model_numbers"]],
                "modelNames": [str(n) for n in group["model_names"]],
                "modelHeaderHtml": "<br>".join(lines),
                "displayLabel": " / ".join(str(m) for m in group["model_numbers"]),
                "defaultHeaderBg": "#ffffff",
                "defaultHeaderText": "#0f172a",
                "cells": [],
            }
            for group, lines in zip(visual_model_groups, group_label_lines)
        ]
        for feature_index, (_, feature) in enumerate(visual_features.iterrows()):
            feature_id = str(feature["id"])
            base_hue = row_hues[feature_index % len(row_hues)]
            default_row_hex = _hsl_to_hex(base_hue, 65, 65)
            choices = [str(choice).strip() for choice in json.loads(
                feature["allowed_values"] or "[]"
            ) if str(choice).strip()]
            color_by_choice = {
                choice: _hsl_to_hex(
                    base_hue,
                    65,
                    max(38, 92 - index * 8),
                )
                for index, choice in enumerate(choices)
            }
            feature_name = str(feature["name"]).strip()
            feature_category = str(feature.get("category") or "").strip()
            feature_row_label = (
                f"{feature_category} · {feature_name}"
                if len(selected_categories) > 1 and feature_category
                else feature_name
            )
            visual_html.append(
                '<div style="font-weight:700;">'
                f"{escape(feature_row_label)}</div>"
            )
            values: list[str] = []
            group_parts_by_col: list[list[str]] = []
            for group in visual_model_groups:
                model_id = group["model_ids"][0]
                value = visual_tree.at[model_id, feature_id]
                selected_value = "" if pd.isna(value) else str(value).strip()
                values.append(selected_value)
                if selected_value and selected_value not in color_by_choice:
                    extra_idx = len(color_by_choice)
                    color_by_choice[selected_value] = _hsl_to_hex(
                        base_hue,
                        65,
                        max(38, 92 - extra_idx * 8),
                    )
                    choices.append(selected_value)
                if show_part_displays and selected_value:
                    group_models = {str(m).strip() for m in group.get("model_numbers", []) if str(m).strip()}
                    raw_matching = [
                        pn
                        for pn, app_models in part_rules_by_feature_value.get(
                            (feature_id, selected_value), []
                        )
                        if app_models is None or bool(group_models & app_models)
                    ]
                    matching_for_group = deduplicate_visual_box_parts(
                        raw_matching, bom_descendants_by_pn
                    )
                    group_parts_by_col.append(matching_for_group)
                else:
                    group_parts_by_col.append([])

            default_shade_lightnesses = (
                (38, 52, 68, 84, 92) if len(choices) > 5 else (60, 68, 76, 84, 92)
            )
            default_shades = [
                _hsl_to_hex(base_hue, 65, light_pct)
                for light_pct in default_shade_lightnesses
            ]
            spec_features.append(
                {
                    "id": feature_id,
                    "rowLabelHtml": escape(feature_row_label),
                    "labelText": feature_row_label,
                    "defaultHue": base_hue,
                    "defaultRowHex": default_row_hex,
                    "defaultShades": default_shades,
                    "choices": [
                        {
                            "value": ch_val,
                            "defaultBg": color_by_choice.get(ch_val, "#f1f5f9"),
                            "defaultText": "#ffffff" if ch_idx >= 4 else "#17324d",
                        }
                        for ch_idx, ch_val in enumerate(choices)
                    ],
                }
            )

            for col_idx, selected_value in enumerate(values):
                matching_parts = group_parts_by_col[col_idx]
                background = color_by_choice.get(selected_value, "#f1f5f9")
                choice_index = choices.index(selected_value) if selected_value in choices else -1
                text_color = "#ffffff" if choice_index >= 4 else "#17324d"
                if not selected_value:
                    text_color = "#64748b"
                    cell_label = escape("Not assigned")
                elif selected_feature_displays == ["Feature"]:
                    cell_label = escape(selected_value)
                elif "Feature" not in selected_feature_displays:
                    if matching_parts:
                        cell_label = "<br>".join(
                            _build_box_part_lines(matching_parts, selected_feature_displays)
                        )
                    else:
                        text_color = "#64748b"
                        cell_label = escape("No parts assigned")
                else:
                    part_modes = [
                        mode
                        for mode in selected_feature_displays
                        if mode in ("Part number", "Part name")
                    ]
                    feature_between_part_modes = (
                        len(part_modes) == 2
                        and selected_feature_displays.index("Feature") == 1
                    )
                    segments: list[str] = []
                    emitted_combined_parts = False
                    for display_mode in selected_feature_displays:
                        if display_mode == "Feature":
                            segments.append(escape(selected_value))
                        elif not matching_parts:
                            if not emitted_combined_parts:
                                segments.append(
                                    f'<span style="font-weight:400;opacity:0.8;">{escape("No parts assigned")}</span>'
                                )
                                emitted_combined_parts = True
                        elif feature_between_part_modes:
                            mode_lines = _build_box_part_lines(matching_parts, [display_mode])
                            segments.append(
                                f'<span style="font-weight:400;">{"<br>".join(mode_lines)}</span>'
                            )
                        elif not emitted_combined_parts:
                            combined_lines = _build_box_part_lines(matching_parts, part_modes)
                            segments.append(
                                f'<span style="font-weight:400;">{"<br>".join(combined_lines)}</span>'
                            )
                            emitted_combined_parts = True
                    cell_label = "<br>".join(segments)
                merge_key = (
                    f"{selected_value}::{'|'.join(matching_parts)}"
                    if show_part_displays
                    else selected_value
                )
                spec_columns[col_idx]["cells"].append(
                    {
                        "featureId": feature_id,
                        "choiceValue": selected_value,
                        "mergeKey": merge_key,
                        "background": background,
                        "defaultBackground": background,
                        "textColor": text_color,
                        "defaultTextColor": text_color,
                        "labelHtml": cell_label,
                    }
                )

            start = 0
            while start < len(values):
                end = start + 1
                while (
                    end < len(values)
                    and spec_columns[end]["cells"][feature_index]["mergeKey"]
                    == spec_columns[start]["cells"][feature_index]["mergeKey"]
                ):
                    end += 1
                cell_info = spec_columns[start]["cells"][feature_index]
                visual_html.append(
                    f'<div class="ct-feature-box" data-feature-index="{feature_index}" '
                    f'data-col-start="{start}" data-col-end="{end}" '
                    f'data-merge-key="{escape(str(cell_info["mergeKey"]))}" '
                    f'style="grid-column:span {end - start};background:{cell_info["background"]};'
                    'border-radius:8px;padding:10px 12px;text-align:center;display:flex;'
                    'align-items:center;justify-content:center;line-height:1.45;overflow-wrap:anywhere;'
                    f'color:{cell_info["textColor"]};"><strong>{cell_info["labelHtml"]}</strong></div>'
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
        for col_idx, (group, lines) in enumerate(zip(visual_model_groups, group_label_lines)):
            model_labels = "<br>".join(lines)
            group_key = "|".join(str(m) for m in group["model_numbers"])
            is_first_str = "true" if col_idx == 0 else "false"
            is_last_str = "true" if col_idx == total_group_cols - 1 else "false"
            visual_html.append(
                f'<div class="ct-model-col-header" data-row-pos="bottom" data-col-index="{col_idx}" '
                f'data-group-key="{escape(group_key)}" data-is-first="{is_first_str}" data-is-last="{is_last_str}" '
                'title="Drag left or right to move this model column (matching adjacent feature boxes merge automatically)" '
                'style="font-weight:700;line-height:1.45;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;'
                f'border:2px solid #000;border-radius:4px;padding:6px 8px;min-height:{model_header_height}px;height:100%;'
                'box-sizing:border-box;display:flex;align-items:center;'
                'justify-content:center;text-align:center;">'
                '<button type="button" class="ct-col-move-btn ct-col-move-left" data-ct-move-col="-1" title="Move column left">◀</button>'
                f'<span class="ct-col-header-label">{model_labels}</span>'
                '<button type="button" class="ct-col-move-btn ct-col-move-right" data-ct-move-col="1" title="Move column right">▶</button>'
                '</div>'
            )
        visual_html.append("</div></div></div></div></div></div>")
        st.markdown("".join(visual_html), unsafe_allow_html=True)
        visual_spec_json = json.dumps(
            {
                "projectId": str(project_id),
                "gridTemplate": grid_template,
                "modelHeaderHeight": model_header_height,
                "features": spec_features,
                "columns": spec_columns,
            }
        )
        visual_spec_b64 = base64.b64encode(visual_spec_json.encode("utf-8")).decode("ascii")
        st.html(
            f"""<div style="display:none;" data-ct-boot="{escape(str(project_id))}"></div><script>
            (function() {{
                const SPEC = JSON.parse(
                    new TextDecoder().decode(
                        Uint8Array.from(atob("{visual_spec_b64}"), function(c) {{
                            return c.charCodeAt(0);
                        }})
                    )
                );
                const rootDoc = (window.parent && window.parent.document) ? window.parent.document : document;
                const rootWin = (window.parent && window.parent.document) ? window.parent : window;
                const MIN_ZOOM = 0.2;
                const MAX_ZOOM = 3.0;
                const clampZoom = function(val) {{
                    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(val) || 1));
                }};
                const escapeAttr = function(val) {{
                    return String(val ?? "").replace(/[&\\x3c>"']/g, function(ch) {{
                        return ({{ "&": "&amp;", "\\x3c": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }})[ch];
                    }});
                }};
                if (!Number.isFinite(Number(rootWin.__paagComplexityTreeZoom))) {{
                    rootWin.__paagComplexityTreeZoom = 1;
                }}
                rootWin.__paagComplexityTreeColOrderByProject = rootWin.__paagComplexityTreeColOrderByProject || {{}};
                rootWin.__paagComplexityTreeColorsByProject = rootWin.__paagComplexityTreeColorsByProject || {{}};
                rootWin.__paagComplexityTreeSavedPaletteByProject = rootWin.__paagComplexityTreeSavedPaletteByProject || {{}};
                rootWin.__paagComplexityTreeOpenPalettes = rootWin.__paagComplexityTreeOpenPalettes || {{}};
                rootWin.__paagComplexityTreeDraftCustomHex = rootWin.__paagComplexityTreeDraftCustomHex || "#287ec2";
                rootWin.__paagComplexityTreeSidebarFilter = rootWin.__paagComplexityTreeSidebarFilter || "all";
                rootWin.__paagComplexityTreeSidebarSearch = rootWin.__paagComplexityTreeSidebarSearch || "";

                const CURATED_COLOR_PALETTES = [
                    {{ id: "gold", name: "Honey Gold", shades: ["#ebb95e", "#f3db6d", "#faefb4", "#f6f9b8", "#fcfde8"] }},
                    {{ id: "plum", name: "Plum Berry", shades: ["#73446c", "#bf618a", "#d592b2", "#efcadd", "#fcebf3"] }},
                    {{ id: "coral", name: "Terracotta Coral", shades: ["#e97f5e", "#f09c93", "#f6c5ac", "#f7cfcd", "#f7e5e2"] }},
                    {{ id: "rose", name: "Rose Pink", shades: ["#e15795", "#ec8bb5", "#f6c8dd", "#f0d3e2", "#faedf4"] }},
                    {{ id: "sand", name: "Warm Sand", shades: ["#a88e74", "#c2b37d", "#dcd9be", "#e3dca2", "#fcfde0"] }},
                    {{ id: "sky", name: "Ocean Sky", shades: ["#287ec2", "#6ec0e8", "#8dc5e2", "#b7e2f7", "#e2f3fb"] }},
                    {{ id: "sage", name: "Sage Green", shades: ["#79915a", "#7ec77c", "#b8cfb0", "#cce6c2", "#eaf7e4"] }},
                    {{ id: "indigo", name: "Indigo Blue", shades: ["#707db7", "#6d8bc6", "#9eb3dd", "#c9cee7", "#e7eef9"] }},
                    {{ id: "teal", name: "Deep Teal", shades: ["#1d636c", "#719ea3", "#73c7c2", "#b3dedd", "#e0f2f7"] }},
                    {{ id: "lavender", name: "Soft Lavender", shades: ["#9281b6", "#b09bc9", "#c7b6dc", "#ded4e5", "#f3ecf6"] }}
                ];

                const MODEL_PRESET_SWATCHES = [
                    "#ffffff", "#e2f3fb", "#eaf7e4", "#fcfde8",
                    "#f3ecf6", "#f7e5e2", "#f1f5f9", "#1d636c"
                ];

                function normalizeHexColor(val, fallback) {{
                    const fb = fallback || "#ffffff";
                    if (!val || typeof val !== "string") return fb;
                    const s = val.trim();
                    if (/^#[0-9a-fA-F]{{6}}$/.test(s)) return s.toLowerCase();
                    if (/^#[0-9a-fA-F]{{3}}$/.test(s)) {{
                        return (
                            "#" +
                            s[1] + s[1] +
                            s[2] + s[2] +
                            s[3] + s[3]
                        ).toLowerCase();
                    }}
                    return fb;
                }}

                function hexToRgb(hex) {{
                    const clean = normalizeHexColor(hex, "#ffffff").slice(1);
                    return {{
                        r: parseInt(clean.slice(0, 2), 16),
                        g: parseInt(clean.slice(2, 4), 16),
                        b: parseInt(clean.slice(4, 6), 16),
                    }};
                }}

                function getContrastingTextColor(hexBg, darkFallback) {{
                    const rgb = hexToRgb(hexBg);
                    const lum = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255;
                    return lum < 0.57 ? "#ffffff" : (darkFallback || "#17324d");
                }}

                function hexToHsl(hex) {{
                    const rgb = hexToRgb(hex);
                    const r = rgb.r / 255;
                    const g = rgb.g / 255;
                    const b = rgb.b / 255;
                    const max = Math.max(r, g, b);
                    const min = Math.min(r, g, b);
                    let h = 0;
                    let s = 0;
                    const l = (max + min) / 2;
                    if (max !== min) {{
                        const d = max - min;
                        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
                        switch (max) {{
                            case r: h = (g - b) / d + (g < b ? 6 : 0); break;
                            case g: h = (b - r) / d + 2; break;
                            case b: h = (r - g) / d + 4; break;
                        }}
                        h /= 6;
                    }}
                    return {{
                        h: Math.round(h * 360),
                        s: Math.round(s * 100),
                        l: Math.round(l * 100),
                    }};
                }}

                function hslToHex(hDeg, sPct, lPct) {{
                    const h = ((hDeg % 360) + 360) % 360 / 360;
                    const s = Math.max(0, Math.min(100, sPct)) / 100;
                    const l = Math.max(0, Math.min(100, lPct)) / 100;
                    let r, g, b;
                    if (s === 0) {{
                        r = g = b = l;
                    }} else {{
                        const hue2rgb = function(p, q, t) {{
                            if (t < 0) t += 1;
                            if (t > 1) t -= 1;
                            if (t < 1 / 6) return p + (q - p) * 6 * t;
                            if (t < 1 / 2) return q;
                            if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
                            return p;
                        }};
                        const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
                        const p = 2 * l - q;
                        r = hue2rgb(p, q, h + 1 / 3);
                        g = hue2rgb(p, q, h);
                        b = hue2rgb(p, q, h - 1 / 3);
                    }}
                    const toHex = function(x) {{
                        const str = Math.round(x * 255).toString(16);
                        return str.length === 1 ? "0" + str : str;
                    }};
                    return "#" + toHex(r) + toHex(g) + toHex(b);
                }}

                function buildFiveShadeRamp(baseHex) {{
                    const clean = normalizeHexColor(baseHex, "#287ec2");
                    for (let i = 0; i < CURATED_COLOR_PALETTES.length; i++) {{
                        const fam = CURATED_COLOR_PALETTES[i];
                        if (fam.shades.indexOf(clean) !== -1) {{
                            return fam.shades.slice();
                        }}
                    }}
                    const hsl = hexToHsl(clean);
                    const sBase = hsl.s < 8 ? hsl.s : Math.max(38, Math.min(82, hsl.s));
                    const lAnchor = Math.max(32, Math.min(58, hsl.l));
                    const lights = [
                        lAnchor,
                        Math.min(72, lAnchor + 12),
                        Math.min(81, lAnchor + 23),
                        Math.min(89, lAnchor + 33),
                        Math.min(95, lAnchor + 42)
                    ];
                    const sats = [
                        sBase,
                        Math.max(12, Math.round(sBase * 0.92)),
                        Math.max(10, Math.round(sBase * 0.82)),
                        Math.max(8, Math.round(sBase * 0.72)),
                        Math.max(6, Math.round(sBase * 0.58))
                    ];
                    return lights.map(function(lv, idx) {{
                        return hslToHex(hsl.h, hsl.s < 8 ? hsl.s : sats[idx], lv);
                    }});
                }}

                function getSavedUserPalette(projId) {{
                    const key = projId || "default";
                    const mem = rootWin.__paagComplexityTreeSavedPaletteByProject[key];
                    if (Array.isArray(mem)) return mem.slice();
                    try {{
                        const raw = (
                            sessionStorage.getItem("paag_ct_saved_palette_" + key) ||
                            localStorage.getItem("paag_ct_saved_palette_" + key) ||
                            localStorage.getItem("paag_ct_saved_palette")
                        );
                        if (raw) {{
                            const parsed = JSON.parse(raw);
                            if (Array.isArray(parsed)) {{
                                const cleaned = [];
                                parsed.forEach(function(item) {{
                                    const hex = normalizeHexColor(item, "");
                                    if (hex && cleaned.indexOf(hex) === -1) cleaned.push(hex);
                                }});
                                rootWin.__paagComplexityTreeSavedPaletteByProject[key] = cleaned;
                                return cleaned.slice();
                            }}
                        }}
                    }} catch (e) {{}}
                    return [];
                }}

                function persistSavedUserPalette(projId, hexList) {{
                    const key = projId || "default";
                    const cleaned = [];
                    (hexList || []).forEach(function(item) {{
                        const hex = normalizeHexColor(item, "");
                        if (hex && cleaned.indexOf(hex) === -1) cleaned.push(hex);
                    }});
                    rootWin.__paagComplexityTreeSavedPaletteByProject[key] = cleaned;
                    try {{
                        const serialized = JSON.stringify(cleaned);
                        sessionStorage.setItem("paag_ct_saved_palette_" + key, serialized);
                        localStorage.setItem("paag_ct_saved_palette_" + key, serialized);
                        localStorage.setItem("paag_ct_saved_palette", serialized);
                    }} catch (e) {{}}
                }}

                function saveUserCustomColor(projId, hexVal) {{
                    const clean = normalizeHexColor(hexVal, "");
                    if (!clean) return getSavedUserPalette(projId);
                    const list = getSavedUserPalette(projId);
                    if (list.indexOf(clean) === -1) {{
                        list.push(clean);
                        persistSavedUserPalette(projId, list);
                    }}
                    return list;
                }}

                function removeUserCustomColor(projId, hexVal) {{
                    const clean = normalizeHexColor(hexVal, "");
                    const list = getSavedUserPalette(projId).filter(function(c) {{
                        return c !== clean;
                    }});
                    persistSavedUserPalette(projId, list);
                    return list;
                }}

                function emptyColorConfig() {{
                    return {{ models: {{}}, features: {{}}, featureShades: {{}}, choices: {{}} }};
                }}

                function getSavedCustomColors(projId) {{
                    if (!projId) return emptyColorConfig();
                    const mem = rootWin.__paagComplexityTreeColorsByProject[projId];
                    if (mem && typeof mem === "object") {{
                        return {{
                            models: Object.assign({{}}, mem.models || {{}}),
                            features: Object.assign({{}}, mem.features || {{}}),
                            featureShades: Object.assign({{}}, mem.featureShades || {{}}),
                            choices: Object.assign({{}}, mem.choices || {{}}),
                        }};
                    }}
                    try {{
                        const raw = sessionStorage.getItem("paag_ct_colors_" + projId) || localStorage.getItem("paag_ct_colors_" + projId);
                        if (raw) {{
                            const parsed = JSON.parse(raw);
                            if (parsed && typeof parsed === "object") {{
                                const norm = {{
                                    models: Object.assign({{}}, parsed.models || {{}}),
                                    features: Object.assign({{}}, parsed.features || {{}}),
                                    featureShades: Object.assign({{}}, parsed.featureShades || {{}}),
                                    choices: Object.assign({{}}, parsed.choices || {{}}),
                                }};
                                rootWin.__paagComplexityTreeColorsByProject[projId] = norm;
                                return norm;
                            }}
                        }}
                    }} catch (e) {{}}
                    return emptyColorConfig();
                }}

                function isCustomColorsActive(projId) {{
                    const cfg = getSavedCustomColors(projId);
                    return (
                        Object.keys(cfg.models || {{}}).length > 0 ||
                        Object.keys(cfg.features || {{}}).length > 0 ||
                        Object.keys(cfg.featureShades || {{}}).length > 0 ||
                        Object.keys(cfg.choices || {{}}).length > 0
                    );
                }}

                function saveCustomColors(projId, cfg) {{
                    if (!projId) return;
                    const norm = {{
                        models: Object.assign({{}}, (cfg && cfg.models) || {{}}),
                        features: Object.assign({{}}, (cfg && cfg.features) || {{}}),
                        featureShades: Object.assign({{}}, (cfg && cfg.featureShades) || {{}}),
                        choices: Object.assign({{}}, (cfg && cfg.choices) || {{}}),
                    }};
                    const hasAny = (
                        Object.keys(norm.models).length > 0 ||
                        Object.keys(norm.features).length > 0 ||
                        Object.keys(norm.featureShades).length > 0 ||
                        Object.keys(norm.choices).length > 0
                    );
                    if (!hasAny) {{
                        delete rootWin.__paagComplexityTreeColorsByProject[projId];
                        try {{
                            sessionStorage.removeItem("paag_ct_colors_" + projId);
                            localStorage.removeItem("paag_ct_colors_" + projId);
                        }} catch (e) {{}}
                        return;
                    }}
                    rootWin.__paagComplexityTreeColorsByProject[projId] = norm;
                    try {{
                        const serialized = JSON.stringify(norm);
                        sessionStorage.setItem("paag_ct_colors_" + projId, serialized);
                        localStorage.setItem("paag_ct_colors_" + projId, serialized);
                    }} catch (e) {{}}
                }}

                function resolveModelHeaderColor(col, customColors) {{
                    const modelsMap = (customColors && customColors.models) || {{}};
                    let chosenHex = modelsMap[col.groupKey] || null;
                    if (!chosenHex && Array.isArray(col.modelNumbers)) {{
                        for (let i = 0; i < col.modelNumbers.length; i++) {{
                            const mKey = "model::" + String(col.modelNumbers[i]);
                            if (modelsMap[mKey]) {{
                                chosenHex = modelsMap[mKey];
                                break;
                            }}
                        }}
                    }}
                    if (!chosenHex && modelsMap["__all__"]) {{
                        chosenHex = modelsMap["__all__"];
                    }}
                    if (chosenHex) {{
                        const bg = normalizeHexColor(chosenHex, "#ffffff");
                        return {{
                            bg: bg,
                            text: getContrastingTextColor(bg, "#0f172a"),
                            isCustom: true,
                        }};
                    }}
                    return {{
                        bg: col.defaultHeaderBg || "#ffffff",
                        text: col.defaultHeaderText || "#0f172a",
                        isCustom: false,
                    }};
                }}

                function getFeatureActiveShades(feat, featIndex, customColors) {{
                    const fId = String(feat.id);
                    const fShadesMap = (customColors && customColors.featureShades) || {{}};
                    if (Array.isArray(fShadesMap[fId]) && fShadesMap[fId].length > 0) {{
                        return fShadesMap[fId].map(function(s) {{ return normalizeHexColor(s, "#e2f3fb"); }});
                    }}
                    const featuresMap = (customColors && customColors.features) || {{}};
                    if (featuresMap[fId]) {{
                        return buildFiveShadeRamp(featuresMap[fId]);
                    }}
                    if (Array.isArray(feat.defaultShades) && feat.defaultShades.length >= 5) {{
                        return feat.defaultShades.slice(0, 5).map(function(s) {{ return normalizeHexColor(s, "#e2f3fb"); }});
                    }}
                    if (typeof feat.defaultHue === "number") {{
                        return [60, 68, 76, 84, 92].map(function(lp) {{
                            return hslToHex(feat.defaultHue, 65, lp);
                        }});
                    }}
                    const defaultFam = CURATED_COLOR_PALETTES[(featIndex || 0) % CURATED_COLOR_PALETTES.length];
                    return defaultFam.shades.slice();
                }}

                function findActiveShadeIndex(shadesList, targetHex) {{
                    if (!Array.isArray(shadesList) || shadesList.length === 0 || !targetHex) return -1;
                    const cleanTarget = normalizeHexColor(targetHex, "");
                    const exactIdx = shadesList.findIndex(function(s) {{
                        return normalizeHexColor(s, "") === cleanTarget;
                    }});
                    if (exactIdx !== -1) return exactIdx;
                    const targetHsl = hexToHsl(cleanTarget);
                    const firstHsl = hexToHsl(shadesList[0]);
                    const hueDiff = Math.min(
                        Math.abs(targetHsl.h - firstHsl.h),
                        360 - Math.abs(targetHsl.h - firstHsl.h)
                    );
                    if (hueDiff > 18) return -1;
                    const tRgb = hexToRgb(cleanTarget);
                    let bestIdx = 0;
                    let bestDist = Infinity;
                    shadesList.forEach(function(sh, idx) {{
                        const sRgb = hexToRgb(sh);
                        const d = (
                            (tRgb.r - sRgb.r) * (tRgb.r - sRgb.r) +
                            (tRgb.g - sRgb.g) * (tRgb.g - sRgb.g) +
                            (tRgb.b - sRgb.b) * (tRgb.b - sRgb.b)
                        );
                        if (d < bestDist) {{
                            bestDist = d;
                            bestIdx = idx;
                        }}
                    }});
                    return bestIdx;
                }}

                function computeShadedChoiceHex(baseRowHex, choiceIdx, totalChoices, explicitShades) {{
                    const shades = (Array.isArray(explicitShades) && explicitShades.length > 0)
                        ? explicitShades
                        : buildFiveShadeRamp(baseRowHex);
                    if (totalChoices <= 1) {{
                        return normalizeHexColor(shades[0] || baseRowHex, "#dbeafe");
                    }}
                    if (choiceIdx < shades.length) {{
                        return normalizeHexColor(shades[choiceIdx], "#dbeafe");
                    }}
                    const hsl = hexToHsl(shades[0] || baseRowHex);
                    const sat = hsl.s < 12 ? hsl.s : Math.max(40, Math.min(85, hsl.s));
                    const light = Math.max(36, Math.min(93, 40 + (choiceIdx % 7) * 8));
                    return hslToHex(hsl.h, sat, light);
                }}

                function resolveFeatureChoiceColor(feat, choiceValue, defaultBg, defaultText, customColors) {{
                    const choicesMap = (customColors && customColors.choices) || {{}};
                    const featuresMap = (customColors && customColors.features) || {{}};
                    const featureShadesMap = (customColors && customColors.featureShades) || {{}};
                    const cKey = String(feat.id) + "::" + String(choiceValue || "");
                    if (choiceValue && choicesMap[cKey]) {{
                        const bg = normalizeHexColor(choicesMap[cKey], defaultBg || "#f1f5f9");
                        return {{
                            bg: bg,
                            text: getContrastingTextColor(bg, "#17324d"),
                            isCustom: true,
                            isChoiceCustom: true,
                        }};
                    }}
                    const hasRowTheme = Boolean(
                        choiceValue && (featuresMap[feat.id] || (Array.isArray(featureShadesMap[feat.id]) && featureShadesMap[feat.id].length > 0))
                    );
                    if (hasRowTheme) {{
                        const featChoices = Array.isArray(feat.choices) ? feat.choices : [];
                        let chIdx = 0;
                        for (let i = 0; i < featChoices.length; i++) {{
                            if (featChoices[i].value === choiceValue) {{
                                chIdx = i;
                                break;
                            }}
                        }}
                        const shaded = computeShadedChoiceHex(
                            featuresMap[feat.id] || (featureShadesMap[feat.id] && featureShadesMap[feat.id][0]) || "#287ec2",
                            chIdx,
                            Math.max(2, featChoices.length),
                            featureShadesMap[feat.id]
                        );
                        return {{
                            bg: shaded,
                            text: getContrastingTextColor(shaded, "#17324d"),
                            isCustom: true,
                            isChoiceCustom: false,
                        }};
                    }}
                    const fbBg = normalizeHexColor(defaultBg || "#f1f5f9", "#f1f5f9");
                    return {{
                        bg: fbBg,
                        text: defaultText || "#17324d",
                        isCustom: false,
                        isChoiceCustom: false,
                    }};
                }}

                function getSavedModelOrder(projId) {{
                    if (!projId) return null;
                    const mem = rootWin.__paagComplexityTreeColOrderByProject[projId];
                    if (Array.isArray(mem) && mem.length > 0) return mem;
                    try {{
                        const raw = sessionStorage.getItem("paag_ct_col_order_" + projId) || localStorage.getItem("paag_ct_col_order_" + projId);
                        if (raw) {{
                            const parsed = JSON.parse(raw);
                            if (Array.isArray(parsed) && parsed.length > 0) {{
                                rootWin.__paagComplexityTreeColOrderByProject[projId] = parsed;
                                return parsed;
                            }}
                        }}
                    }} catch (e) {{}}
                    return null;
                }}

                function saveModelOrder(projId, modelNums) {{
                    if (!projId) return;
                    if (!Array.isArray(modelNums) || modelNums.length === 0) {{
                        delete rootWin.__paagComplexityTreeColOrderByProject[projId];
                        try {{
                            sessionStorage.removeItem("paag_ct_col_order_" + projId);
                            localStorage.removeItem("paag_ct_col_order_" + projId);
                        }} catch (e) {{}}
                        return;
                    }}
                    rootWin.__paagComplexityTreeColOrderByProject[projId] = modelNums.slice();
                    try {{
                        const serialized = JSON.stringify(modelNums);
                        sessionStorage.setItem("paag_ct_col_order_" + projId, serialized);
                        localStorage.setItem("paag_ct_col_order_" + projId, serialized);
                    }} catch (e) {{}}
                }}

                function computeOrderedColumns(spec) {{
                    if (!spec || !Array.isArray(spec.columns)) return [];
                    const defaultCols = spec.columns.map(function(col, idx) {{
                        return Object.assign({{}}, col, {{ defaultIndex: idx }});
                    }});
                    const savedOrder = getSavedModelOrder(spec.projectId);
                    if (!savedOrder || savedOrder.length === 0) {{
                        return defaultCols;
                    }}
                    const rankMap = new Map();
                    savedOrder.forEach(function(mNum, idx) {{
                        if (!rankMap.has(String(mNum))) {{
                            rankMap.set(String(mNum), idx);
                        }}
                    }});
                    return defaultCols.slice().sort(function(a, b) {{
                        let rankA = Infinity;
                        (a.modelNumbers || []).forEach(function(m) {{
                            const r = rankMap.get(String(m));
                            if (r !== undefined && r < rankA) rankA = r;
                        }});
                        let rankB = Infinity;
                        (b.modelNumbers || []).forEach(function(m) {{
                            const r = rankMap.get(String(m));
                            if (r !== undefined && r < rankB) rankB = r;
                        }});
                        if (rankA !== rankB) return rankA - rankB;
                        return a.defaultIndex - b.defaultIndex;
                    }});
                }}

                function isCustomOrderActive(cols, spec) {{
                    if (!spec || !Array.isArray(spec.columns) || cols.length !== spec.columns.length) return false;
                    for (let i = 0; i < cols.length; i++) {{
                        if (cols[i].groupKey !== spec.columns[i].groupKey) return true;
                    }}
                    return false;
                }}

                function ensureGlobalFullScreenStyle() {{
                    const styleId = "paag-complexity-tree-fullscreen-global-style";
                    let styleEl = rootDoc.getElementById(styleId);
                    if (!styleEl) {{
                        styleEl = rootDoc.createElement("style");
                        styleEl.id = styleId;
                        (rootDoc.head || rootDoc.documentElement).appendChild(styleEl);
                    }}
                    const desiredCss = `
                        .complexity-tree-shell {{
                            position: relative;
                            box-sizing: border-box;
                            width: 100%;
                            max-width: 100%;
                            min-width: 0;
                            margin-top: 6px;
                            border: 1px solid var(--st-border-color, #cbd5e1);
                            border-radius: var(--st-base-radius, 8px);
                            overflow: hidden;
                            background: var(--st-background-color, #ffffff);
                        }}
                        .complexity-tree-shell.fullscreen-visual,
                        .complexity-tree-shell:fullscreen,
                        .complexity-tree-shell:-webkit-full-screen {{
                            position: fixed !important;
                            inset: 0 !important;
                            top: 0 !important;
                            left: 0 !important;
                            right: 0 !important;
                            bottom: 0 !important;
                            z-index: 999995 !important;
                            width: 100vw !important;
                            height: 100vh !important;
                            max-width: 100vw !important;
                            max-height: 100vh !important;
                            min-width: 0 !important;
                            margin: 0 !important;
                            border: 0 !important;
                            border-radius: 0 !important;
                            display: flex !important;
                            flex-direction: column !important;
                            overflow: hidden !important;
                            background: var(--st-background-color, #ffffff) !important;
                        }}
                        .complexity-tree-toolbar {{
                            position: sticky;
                            left: 0;
                            top: 0;
                            z-index: 30;
                            width: 100%;
                            box-sizing: border-box;
                            display: flex;
                            align-items: center;
                            justify-content: space-between;
                            gap: 8px 12px;
                            padding: 8px 14px;
                            border-bottom: 1px solid var(--st-border-color, #cbd5e1);
                            background: var(--st-secondary-background-color, #f8fafc);
                            flex-wrap: wrap;
                            flex: 0 0 auto;
                        }}
                        .complexity-tree-shell.fullscreen-visual .complexity-tree-toolbar,
                        .complexity-tree-shell:fullscreen .complexity-tree-toolbar,
                        .complexity-tree-shell:-webkit-full-screen .complexity-tree-toolbar {{
                            padding: 10px 16px;
                            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
                        }}
                        .complexity-tree-toolbar-controls button {{
                            display: inline-flex;
                            align-items: center;
                            justify-content: center;
                            gap: 4px;
                            min-width: 32px;
                            min-height: 30px;
                            height: auto;
                            padding: 4px 10px;
                            white-space: nowrap;
                            flex-shrink: 0;
                            line-height: 1.2;
                            box-sizing: border-box;
                            border: 1px solid var(--st-border-color, #cbd5e1);
                            border-radius: var(--st-button-radius, 6px);
                            color: var(--st-text-color, #0f172a);
                            background: var(--st-background-color, #ffffff);
                            cursor: pointer;
                            font: inherit;
                            font-size: 0.81rem;
                            font-weight: 600;
                        }}
                        .complexity-tree-toolbar-controls button:hover:not(:disabled) {{
                            border-color: var(--st-primary-color, #2563eb);
                            color: var(--st-primary-color, #2563eb);
                        }}
                        .complexity-tree-toolbar-controls button.btn-tool.is-active-tool {{
                            border-color: var(--st-primary-color, #2563eb);
                            color: var(--st-primary-color, #2563eb);
                            background: rgba(37, 99, 235, 0.08);
                        }}
                        .complexity-tree-toolbar-controls button:disabled {{
                            opacity: 0.48;
                            cursor: not-allowed;
                        }}
                        .complexity-tree-body {{
                            display: flex;
                            width: 100%;
                            max-width: 100%;
                            min-width: 0;
                            align-items: stretch;
                            box-sizing: border-box;
                        }}
                        .complexity-tree-shell.fullscreen-visual .complexity-tree-body,
                        .complexity-tree-shell:fullscreen .complexity-tree-body,
                        .complexity-tree-shell:-webkit-full-screen .complexity-tree-body {{
                            flex: 1 1 auto !important;
                            min-height: 0 !important;
                            overflow: hidden !important;
                        }}
                        .complexity-tree-sidebar {{
                            flex: 0 0 320px;
                            width: 320px;
                            max-width: 350px;
                            box-sizing: border-box;
                            border-right: 1px solid var(--st-border-color, #cbd5e1);
                            background: var(--st-secondary-background-color, #f8fafc);
                            display: flex;
                            flex-direction: column;
                            max-height: 680px;
                            overflow: hidden;
                        }}
                        .complexity-tree-shell.fullscreen-visual .complexity-tree-sidebar,
                        .complexity-tree-shell:fullscreen .complexity-tree-sidebar,
                        .complexity-tree-shell:-webkit-full-screen .complexity-tree-sidebar {{
                            max-height: none !important;
                            height: 100% !important;
                        }}
                        .complexity-tree-sidebar.collapsed {{
                            display: none !important;
                        }}
                        .complexity-tree-shell.fullscreen-visual .complexity-tree-viewport,
                        .complexity-tree-shell:fullscreen .complexity-tree-viewport,
                        .complexity-tree-shell:-webkit-full-screen .complexity-tree-viewport {{
                            flex: 1 1 auto !important;
                            min-height: 0 !important;
                            padding: 16px !important;
                            overflow: auto !important;
                            overscroll-behavior: contain;
                            scrollbar-gutter: stable both-edges;
                            cursor: grab;
                        }}
                        .complexity-tree-shell.is-panning .complexity-tree-viewport {{
                            cursor: grabbing !important;
                            user-select: none;
                        }}
                        .ct-model-col-header {{
                            position: relative;
                            cursor: grab;
                            user-select: none;
                            transition: border-color 0.14s ease, box-shadow 0.14s ease, transform 0.12s ease, background-color 0.14s ease;
                            background: var(--st-background-color, #ffffff);
                        }}
                        .ct-model-col-header:hover {{
                            border-color: #0284c7 !important;
                            box-shadow: 0 3px 10px rgba(2, 132, 199, 0.22);
                        }}
                        .ct-model-col-header.is-dragging-col {{
                            opacity: 0.52;
                            border-style: dashed !important;
                            border-color: #0284c7 !important;
                            background: #e0f2fe !important;
                            cursor: grabbing !important;
                        }}
                        .ct-col-move-btn {{
                            position: absolute;
                            top: 2px;
                            width: 18px;
                            height: 18px;
                            border-radius: 4px;
                            border: 1px solid #cbd5e1;
                            background: rgba(255, 255, 255, 0.94);
                            color: #0f172a;
                            font-size: 10px;
                            line-height: 1;
                            display: none;
                            align-items: center;
                            justify-content: center;
                            cursor: pointer;
                            padding: 0;
                            z-index: 4;
                            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
                        }}
                        .ct-col-move-btn:hover {{
                            background: #0284c7;
                            color: #ffffff;
                            border-color: #0284c7;
                        }}
                        .ct-col-move-left {{ left: 2px; }}
                        .ct-col-move-right {{ right: 2px; }}
                        .ct-model-col-header:hover .ct-col-move-btn {{ display: inline-flex; }}
                        .ct-model-col-header[data-is-first='true'] .ct-col-move-left {{ display: none !important; }}
                        .ct-model-col-header[data-is-last='true'] .ct-col-move-right {{ display: none !important; }}
                        .ct-feature-box {{
                            transition: box-shadow 0.18s ease, outline 0.18s ease, transform 0.18s ease;
                        }}
                        .ct-feature-box.ct-will-merge-preview {{
                            outline: 3px solid #ec4899 !important;
                            outline-offset: 1px;
                            box-shadow: 0 0 0 3px rgba(236, 72, 153, 0.28), 0 4px 12px rgba(236, 72, 153, 0.25) !important;
                            z-index: 3;
                            position: relative;
                        }}
                        @keyframes ctMergePulse {{
                            0% {{ outline: 3px solid #ec4899; box-shadow: 0 0 0 5px rgba(236, 72, 153, 0.35); }}
                            100% {{ outline: 0px solid transparent; box-shadow: none; }}
                        }}
                        .ct-feature-box.ct-merged-box-flash {{
                            animation: ctMergePulse 1.15s ease-out;
                            position: relative;
                            z-index: 2;
                        }}
                        .ct-col-drop-indicator {{
                            position: fixed;
                            width: 4px;
                            border-radius: 999px;
                            background: #0284c7;
                            box-shadow: 0 0 10px rgba(2, 132, 199, 0.75);
                            pointer-events: none;
                            z-index: 1000030;
                            display: none;
                        }}
                        .ct-col-drop-indicator::before,
                        .ct-col-drop-indicator::after {{
                            content: '';
                            position: absolute;
                            left: 50%;
                            transform: translateX(-50%);
                            width: 12px;
                            height: 12px;
                            border-radius: 999px;
                            background: #0284c7;
                            border: 2px solid #ffffff;
                            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
                        }}
                        .ct-col-drop-indicator::before {{ top: -6px; }}
                        .ct-col-drop-indicator::after {{ bottom: -6px; }}
                        .ct-col-drag-ghost {{
                            position: fixed;
                            z-index: 1000035;
                            pointer-events: none;
                            background: #0f172a;
                            color: #ffffff;
                            padding: 6px 12px;
                            border-radius: 999px;
                            font-size: 0.8rem;
                            font-weight: 700;
                            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.35);
                            border: 1.5px solid #38bdf8;
                            white-space: nowrap;
                            display: none;
                            align-items: center;
                            gap: 6px;
                        }}
                        .ct-col-drag-ghost .ct-ghost-merge-badge {{
                            background: #ec4899;
                            color: #ffffff;
                            padding: 1px 7px;
                            border-radius: 999px;
                            font-size: 0.72rem;
                            font-weight: 800;
                        }}
                        html.paag-complexity-tree-fullscreen-active header[data-testid="stHeader"],
                        html.paag-complexity-tree-fullscreen-active [data-testid="stHeader"],
                        html.paag-complexity-tree-fullscreen-active .stAppHeader,
                        html.paag-complexity-tree-fullscreen-active [data-testid="stToolbar"],
                        html.paag-complexity-tree-fullscreen-active [data-testid="stDecoration"],
                        html.paag-complexity-tree-fullscreen-active [data-testid="stStatusWidget"],
                        html.paag-complexity-tree-fullscreen-active [data-testid="stSidebar"],
                        html.paag-complexity-tree-fullscreen-active [data-testid="stSidebarCollapsedControl"],
                        html.paag-complexity-tree-fullscreen-active [data-testid="stExpandSidebarButton"],
                        html.paag-complexity-tree-fullscreen-active [data-testid="collapsedControl"] {{
                            display: none !important;
                            visibility: hidden !important;
                            height: 0 !important;
                            min-height: 0 !important;
                            overflow: hidden !important;
                            pointer-events: none !important;
                        }}
                        html.paag-complexity-tree-fullscreen-active [data-testid="stModal"],
                        html.paag-complexity-tree-fullscreen-active [data-baseweb="modal"] {{
                            z-index: 1000010 !important;
                        }}
                    `;
                    if (styleEl.textContent !== desiredCss) {{
                        styleEl.textContent = desiredCss;
                    }}
                }}

                function getElements() {{
                    const shell = rootDoc.getElementById("complexity-tree-shell");
                    if (!shell) return null;
                    return {{
                        shell: shell,
                        body: shell.querySelector("#complexity-tree-body"),
                        sidebar: shell.querySelector("#complexity-tree-sidebar"),
                        sidebarControls: shell.querySelector("#complexity-tree-sidebar-controls"),
                        sidebarList: shell.querySelector("#complexity-tree-sidebar-list"),
                        sidebarCount: shell.querySelector("#complexity-tree-sidebar-count"),
                        viewport: shell.querySelector("#complexity-tree-viewport"),
                        zoomStage: shell.querySelector("#complexity-tree-zoom-stage"),
                        content: shell.querySelector("#complexity-tree-content"),
                        fullScreenBtn: shell.querySelector("#full-screen"),
                        zoomResetBtn: shell.querySelector("#complexity-tree-zoom-reset"),
                        resetColsBtn: shell.querySelector("#complexity-tree-reset-cols"),
                        resetColorsBtn: shell.querySelector("#complexity-tree-reset-colors"),
                        toggleSidebarBtn: shell.querySelector("#complexity-tree-toggle-sidebar"),
                    }};
                }}

                function renderComplexityTreeGrid(cols, spec, movedColIndex) {{
                    const els = getElements();
                    if (!els || !els.content || !spec) return;
                    const totalCols = cols.length;
                    const hdrH = Number(spec.modelHeaderHeight) || 42;
                    const customColors = getSavedCustomColors(spec.projectId);
                    const html = [];
                    html.push(
                        '\\x3cdiv class="complexity-tree-grid" style="display:grid;grid-template-columns:' +
                        spec.gridTemplate +
                        ';gap:10px 8px;align-items:center;">'
                    );

                    const buildModelRow = function(rowPos) {{
                        html.push('\\x3cdiv style="font-weight:700;">Model\\x3c/div>');
                        cols.forEach(function(col, cIdx) {{
                            const isFirst = cIdx === 0 ? "true" : "false";
                            const isLast = cIdx === totalCols - 1 ? "true" : "false";
                            const hdrColor = resolveModelHeaderColor(col, customColors);
                            html.push(
                                '\\x3cdiv class="ct-model-col-header" data-row-pos="' + rowPos + '" data-col-index="' + cIdx + '" ' +
                                'data-group-key="' + escapeAttr(col.groupKey) + '" data-is-first="' + isFirst + '" data-is-last="' + isLast + '" ' +
                                'title="Drag left or right to move this model column (matching adjacent feature boxes merge automatically)" ' +
                                'style="font-weight:700;line-height:1.45;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;' +
                                'background:' + hdrColor.bg + ';color:' + hdrColor.text + ';' +
                                'border:2px solid #000;border-radius:4px;padding:6px 8px;min-height:' + hdrH + 'px;height:100%;' +
                                'box-sizing:border-box;display:flex;align-items:center;justify-content:center;text-align:center;">' +
                                '\\x3cbutton type="button" class="ct-col-move-btn ct-col-move-left" data-ct-move-col="-1" title="Move column left">◀\\x3c/button>' +
                                '\\x3cspan class="ct-col-header-label">' + col.modelHeaderHtml + '\\x3c/span>' +
                                '\\x3cbutton type="button" class="ct-col-move-btn ct-col-move-right" data-ct-move-col="1" title="Move column right">▶\\x3c/button>' +
                                '\\x3c/div>'
                            );
                        }});
                    }};

                    const appendConnectorRow = function() {{
                        html.push('\\x3cdiv>\\x3c/div>');
                        for (let i = 0; i < totalCols; i++) {{
                            html.push('\\x3cdiv style="height:12px;width:0;border-left:2px solid #475569;margin:auto;">\\x3c/div>');
                        }}
                    }};

                    buildModelRow("top");
                    appendConnectorRow();

                    const features = spec.features || [];
                    for (let fIdx = 0; fIdx < features.length; fIdx++) {{
                        const feat = features[fIdx];
                        html.push('\\x3cdiv style="font-weight:700;">' + feat.rowLabelHtml + '\\x3c/div>');
                        let start = 0;
                        while (start < totalCols) {{
                            let end = start + 1;
                            const baseCell = cols[start].cells[fIdx];
                            while (
                                end < totalCols &&
                                cols[end].cells[fIdx] &&
                                cols[end].cells[fIdx].mergeKey === baseCell.mergeKey
                            ) {{
                                end += 1;
                            }}
                            const span = end - start;
                            const isNewlyMerged = (
                                typeof movedColIndex === "number" &&
                                movedColIndex >= start &&
                                movedColIndex < end &&
                                span > 1
                            );
                            const cellColor = resolveFeatureChoiceColor(
                                feat,
                                baseCell.choiceValue,
                                baseCell.defaultBackground || baseCell.background,
                                baseCell.defaultTextColor || baseCell.textColor,
                                customColors
                            );
                            html.push(
                                '\\x3cdiv class="ct-feature-box' + (isNewlyMerged ? ' ct-merged-box-flash' : '') + '" ' +
                                'data-feature-index="' + fIdx + '" data-col-start="' + start + '" data-col-end="' + end + '" ' +
                                'data-merge-key="' + escapeAttr(baseCell.mergeKey) + '" ' +
                                'style="grid-column:span ' + span + ';background:' + cellColor.bg + ';' +
                                'border-radius:8px;padding:10px 12px;text-align:center;display:flex;' +
                                'align-items:center;justify-content:center;line-height:1.45;overflow-wrap:anywhere;' +
                                'color:' + cellColor.text + ';">\\x3cstrong>' + baseCell.labelHtml + '\\x3c/strong>\\x3c/div>'
                            );
                            start = end;
                        }}
                        if (fIdx < features.length - 1) {{
                            appendConnectorRow();
                        }}
                    }}

                    appendConnectorRow();
                    buildModelRow("bottom");
                    html.push('\\x3c/div>');
                    els.content.innerHTML = html.join("");
                    if (els.resetColsBtn) {{
                        els.resetColsBtn.disabled = !isCustomOrderActive(cols, spec);
                    }}
                    if (els.resetColorsBtn) {{
                        els.resetColorsBtn.disabled = !isCustomColorsActive(spec.projectId);
                    }}
                    bindShellInteractiveElements(els.shell);
                    applyZoomTransform();
                }}

                function renderColorSidebarControls() {{
                    const els = getElements();
                    if (!els || !els.sidebarControls) return;
                    const activeFilter = rootWin.__paagComplexityTreeSidebarFilter || "all";
                    const searchVal = rootWin.__paagComplexityTreeSidebarSearch || "";
                    els.sidebarControls.innerHTML = (
                        '\\x3cinput type="search" id="ct-sidebar-search-input" class="ct-sidebar-search" ' +
                        'placeholder="Search models, features, or choices..." value="' + escapeAttr(searchVal) + '" />' +
                        '\\x3cdiv class="ct-sidebar-tabs">' +
                        '\\x3cbutton type="button" class="ct-sidebar-tab' + (activeFilter === "all" ? ' active' : '') + '" data-ct-sidebar-tab="all">All\\x3c/button>' +
                        '\\x3cbutton type="button" class="ct-sidebar-tab' + (activeFilter === "models" ? ' active' : '') + '" data-ct-sidebar-tab="models">Models\\x3c/button>' +
                        '\\x3cbutton type="button" class="ct-sidebar-tab' + (activeFilter === "features" ? ' active' : '') + '" data-ct-sidebar-tab="features">Features\\x3c/button>' +
                        '\\x3c/div>'
                    );
                    const searchInput = els.sidebarControls.querySelector("#ct-sidebar-search-input");
                    if (searchInput) {{
                        searchInput.oninput = function() {{
                            rootWin.__paagComplexityTreeSidebarSearch = searchInput.value || "";
                            renderColorSidebarList();
                        }};
                    }}
                    els.sidebarControls.querySelectorAll("[data-ct-sidebar-tab]").forEach(function(tabBtn) {{
                        tabBtn.onclick = function(ev) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            rootWin.__paagComplexityTreeSidebarFilter = tabBtn.getAttribute("data-ct-sidebar-tab") || "all";
                            renderColorSidebarControls();
                            renderColorSidebarList();
                        }};
                    }});
                }}

                function buildPaletteDrawerHtml(targetMode, targetKey, activeHex, activeShades, projId) {{
                    const savedCustomList = getSavedUserPalette(projId);
                    const draftHex = normalizeHexColor(
                        rootWin.__paagComplexityTreeDraftCustomHex || activeHex || "#287ec2",
                        "#287ec2"
                    );
                    const draftRamp = buildFiveShadeRamp(draftHex);
                    const isFeatureMode = (targetMode === "feature");
                    const activeFirstShade = normalizeHexColor(
                        (Array.isArray(activeShades) && activeShades[0]) || activeHex || "",
                        ""
                    );
                    const activeHexClean = normalizeHexColor(activeHex || "", "");

                    const familyGridHtml = CURATED_COLOR_PALETTES.map(function(fam) {{
                        const famFirst = normalizeHexColor(fam.shades[0], "");
                        const isActiveFam = isFeatureMode && famFirst === activeFirstShade;
                        const dotsHtml = fam.shades.map(function(shHex, sIdx) {{
                            const cleanSh = normalizeHexColor(shHex, "#ffffff");
                            const isDotActive = !isFeatureMode && cleanSh === activeHexClean;
                            return (
                                '\\x3cbutton type="button" class="ct-shade-dot' + (isDotActive ? ' is-active-shade' : '') + '" ' +
                                (isFeatureMode
                                    ? 'data-ct-family-target="feature" data-ct-feature-id="' + escapeAttr(targetKey) + '" data-ct-family-shades="' + escapeAttr(fam.shades.join(",")) + '" data-ct-family-base="' + cleanSh + '" title="Use ' + escapeAttr(fam.name) + ' palette for this feature"'
                                    : 'data-ct-swatch-type="' + escapeAttr(targetMode) + '" data-ct-target-key="' + escapeAttr(targetKey) + '" data-ct-swatch-color="' + cleanSh + '" title="Select ' + escapeAttr(fam.name) + ' shade ' + (sIdx + 1) + ' (' + cleanSh + ')"'
                                ) +
                                ' style="background:' + cleanSh + ';">\\x3c/button>'
                            );
                        }}).join("");
                        return (
                            '\\x3cdiv class="ct-palette-family-row' + (isActiveFam ? ' is-active-family' : '') + '" ' +
                            (isFeatureMode
                                ? 'data-ct-family-target="feature" data-ct-feature-id="' + escapeAttr(targetKey) + '" data-ct-family-shades="' + escapeAttr(fam.shades.join(",")) + '" data-ct-family-base="' + famFirst + '" title="Apply ' + escapeAttr(fam.name) + ' shade family"'
                                : 'title="' + escapeAttr(fam.name) + ' shades"'
                            ) +
                            '>' + dotsHtml + '\\x3c/div>'
                        );
                    }}).join("");

                    let savedCustomHtml = "";
                    if (savedCustomList.length > 0) {{
                        const savedRows = savedCustomList.map(function(savedHex) {{
                            const cleanSaved = normalizeHexColor(savedHex, "#287ec2");
                            const ramp = buildFiveShadeRamp(cleanSaved);
                            const isActiveSavedFam = isFeatureMode && normalizeHexColor(ramp[0], "") === activeFirstShade;
                            const dots = ramp.map(function(shHex, sIdx) {{
                                const cleanSh = normalizeHexColor(shHex, "#ffffff");
                                const isDotActive = !isFeatureMode && cleanSh === activeHexClean;
                                return (
                                    '\\x3cbutton type="button" class="ct-shade-dot' + (isDotActive ? ' is-active-shade' : '') + '" ' +
                                    (isFeatureMode
                                        ? 'data-ct-family-target="feature" data-ct-feature-id="' + escapeAttr(targetKey) + '" data-ct-family-shades="' + escapeAttr(ramp.join(",")) + '" data-ct-family-base="' + cleanSaved + '" title="Use saved custom palette (' + cleanSaved + ')"'
                                        : 'data-ct-swatch-type="' + escapeAttr(targetMode) + '" data-ct-target-key="' + escapeAttr(targetKey) + '" data-ct-swatch-color="' + cleanSh + '" title="Select saved custom shade ' + (sIdx + 1) + ' (' + cleanSh + ')"'
                                    ) +
                                    ' style="background:' + cleanSh + ';">\\x3c/button>'
                                );
                            }}).join("");
                            return (
                                '\\x3cdiv class="ct-saved-custom-row">' +
                                '\\x3cdiv class="ct-palette-family-row' + (isActiveSavedFam ? ' is-active-family' : '') + '" style="flex:1 1 auto;" ' +
                                (isFeatureMode
                                    ? 'data-ct-family-target="feature" data-ct-feature-id="' + escapeAttr(targetKey) + '" data-ct-family-shades="' + escapeAttr(ramp.join(",")) + '" data-ct-family-base="' + cleanSaved + '" title="Apply saved custom shade family (' + cleanSaved + ')"'
                                    : ''
                                ) +
                                '>' + dots + '\\x3c/div>' +
                                '\\x3cbutton type="button" class="ct-saved-custom-delete" data-ct-delete-saved-color="' + cleanSaved + '" title="Remove saved custom color ' + cleanSaved + '">×\\x3c/button>' +
                                '\\x3c/div>'
                            );
                        }}).join("");
                        savedCustomHtml = (
                            '\\x3cdiv class="ct-saved-custom-section">' +
                            '\\x3cdiv class="ct-palette-drawer-title">\\x3cspan>Saved custom colors (5 shades each)\\x3c/span>\\x3c/div>' +
                            savedRows +
                            '\\x3c/div>'
                        );
                    }}

                    const draftMiniDots = draftRamp.map(function(sh) {{
                        return '\\x3cspan class="ct-family-mini-dot" style="background:' + sh + ';">\\x3c/span>';
                    }}).join("");

                    return (
                        '\\x3cdiv class="ct-palette-drawer" data-ct-palette-drawer="' + escapeAttr(targetMode + ":" + targetKey) + '">' +
                        '\\x3cdiv class="ct-palette-drawer-title">' +
                        '\\x3cspan>' + (isFeatureMode ? 'Choose a color palette (5 shades)' : 'Choose a shade from the palette') + '\\x3c/span>' +
                        '\\x3c/div>' +
                        '\\x3cdiv class="ct-palette-grid">' + familyGridHtml + '\\x3c/div>' +
                        savedCustomHtml +
                        '\\x3cdiv class="ct-custom-creator-bar">' +
                        '\\x3cdiv class="ct-custom-creator-left">' +
                        '\\x3cinput type="color" class="ct-color-input" data-ct-draft-custom-input="true" value="' + draftHex + '" title="Create your own custom color" />' +
                        '\\x3cspan class="ct-family-mini-dots" data-ct-draft-preview-dots="true" title="5 shades generated from your custom color">' + draftMiniDots + '\\x3c/span>' +
                        '\\x3c/div>' +
                        '\\x3cbutton type="button" class="ct-custom-save-btn" data-ct-save-custom-mode="' + escapeAttr(targetMode) + '" data-ct-save-custom-key="' + escapeAttr(targetKey) + '" title="Save this custom color to your palette and apply it">+ Save &amp; Apply\\x3c/button>' +
                        '\\x3c/div>' +
                        '\\x3c/div>'
                    );
                }}

                function renderColorSidebarList() {{
                    const els = getElements();
                    const state = rootWin.__paagComplexityTreeState;
                    if (!els || !els.sidebarList || !state || !state.spec) return;
                    const spec = state.spec;
                    const cols = state.cols || spec.columns || [];
                    const features = spec.features || [];
                    const customColors = getSavedCustomColors(spec.projectId);
                    const openPalettes = rootWin.__paagComplexityTreeOpenPalettes || {{}};
                    const activeFilter = rootWin.__paagComplexityTreeSidebarFilter || "all";
                    const query = String(rootWin.__paagComplexityTreeSidebarSearch || "").trim().toLowerCase();

                    const html = [];
                    const showModels = (activeFilter === "all" || activeFilter === "models");
                    const showFeatures = (activeFilter === "all" || activeFilter === "features");

                    if (showModels) {{
                        const matchingCols = cols.filter(function(col) {{
                            if (!query) return true;
                            const lbl = String(col.displayLabel || col.groupKey || "").toLowerCase();
                            const names = Array.isArray(col.modelNames) ? col.modelNames.join(" ").toLowerCase() : "";
                            return lbl.indexOf(query) !== -1 || names.indexOf(query) !== -1;
                        }});
                        if (matchingCols.length > 0 || !query) {{
                            html.push(
                                '\\x3cdiv class="ct-sidebar-section-hdr">' +
                                '\\x3cspan>Model definitions\\x3c/span>' +
                                '\\x3cspan>' + matchingCols.length + '\\x3c/span>' +
                                '\\x3c/div>'
                            );
                            if (!query) {{
                                const allModelsColor = normalizeHexColor(
                                    (customColors.models && customColors.models["__all__"]) || "#ffffff",
                                    "#ffffff"
                                );
                                const hasAllModelCustom = Boolean(customColors.models && customColors.models["__all__"]);
                                const isAllOpen = Boolean(openPalettes["all-models:__all__"]);
                                const allSwatches = MODEL_PRESET_SWATCHES.map(function(sw) {{
                                    const isAct = normalizeHexColor(sw, "") === allModelsColor && hasAllModelCustom;
                                    return (
                                        '\\x3cbutton type="button" class="ct-shade-dot' + (isAct ? ' is-active-shade' : '') + '" ' +
                                        'data-ct-swatch-type="all-models" data-ct-target-key="__all__" data-ct-swatch-color="' + sw + '" ' +
                                        'title="Apply ' + sw + ' to all model boxes" style="background:' + sw + ';">\\x3c/button>'
                                    );
                                }}).join("");
                                html.push(
                                    '\\x3cdiv class="ct-sidebar-card" data-sidebar-model-group="__all__">' +
                                    '\\x3cdiv class="ct-sidebar-row">' +
                                    '\\x3cdiv style="min-width:0;">' +
                                    '\\x3cdiv class="ct-sidebar-label">All model header boxes\\x3c/div>' +
                                    '\\x3cspan class="ct-sidebar-sublabel">Default color for every model column\\x3c/span>' +
                                    '\\x3c/div>' +
                                    '\\x3cdiv class="ct-color-actions">' +
                                    '\\x3cbutton type="button" class="ct-family-pill-btn' + (isAllOpen ? ' is-open' : '') + '" data-ct-toggle-palette="all-models:__all__" title="Open shade palette &amp; custom colors">Palette ' + (isAllOpen ? '▴' : '▾') + '\\x3c/button>' +
                                    (hasAllModelCustom
                                        ? '\\x3cbutton type="button" class="ct-color-reset-mini" data-ct-reset-type="all-models" title="Reset default model header color">↺\\x3c/button>'
                                        : '') +
                                    '\\x3c/div>' +
                                    '\\x3c/div>' +
                                    '\\x3cdiv class="ct-preset-swatches">' + allSwatches + '\\x3c/div>' +
                                    (isAllOpen ? buildPaletteDrawerHtml("all-models", "__all__", allModelsColor, null, spec.projectId) : '') +
                                    '\\x3c/div>'
                                );
                            }}
                            matchingCols.forEach(function(col) {{
                                const resolved = resolveModelHeaderColor(col, customColors);
                                const hasSpecificCustom = Boolean(
                                    customColors.models && (
                                        customColors.models[col.groupKey] ||
                                        (Array.isArray(col.modelNumbers) && col.modelNumbers.some(function(m) {{ return Boolean(customColors.models["model::" + m]); }}))
                                    )
                                );
                                const titleText = col.displayLabel || (col.modelNumbers || []).join(" / ") || col.groupKey;
                                const uniqueNames = [];
                                (col.modelNames || []).forEach(function(nm) {{
                                    const s = String(nm || "").trim();
                                    if (s && uniqueNames.indexOf(s) === -1) uniqueNames.push(s);
                                }});
                                const subText = uniqueNames.join(" · ");
                                const pKey = "model:" + col.groupKey;
                                const isModelOpen = Boolean(openPalettes[pKey]);
                                const modelSwatches = MODEL_PRESET_SWATCHES.map(function(sw) {{
                                    const isAct = hasSpecificCustom && normalizeHexColor(sw, "") === normalizeHexColor(resolved.bg, "");
                                    return (
                                        '\\x3cbutton type="button" class="ct-shade-dot' + (isAct ? ' is-active-shade' : '') + '" ' +
                                        'data-ct-swatch-type="model" data-ct-target-key="' + escapeAttr(col.groupKey) + '" data-ct-group-key="' + escapeAttr(col.groupKey) + '" ' +
                                        'data-ct-swatch-color="' + sw + '" title="Set model box color to ' + sw + '" ' +
                                        'style="background:' + sw + ';">\\x3c/button>'
                                    );
                                }}).join("");
                                html.push(
                                    '\\x3cdiv class="ct-sidebar-card" data-sidebar-model-group="' + escapeAttr(col.groupKey) + '">' +
                                    '\\x3cdiv class="ct-sidebar-row">' +
                                    '\\x3cdiv style="min-width:0;flex:1 1 auto;">' +
                                    '\\x3cdiv class="ct-choice-preview" style="max-width:165px;background:' + resolved.bg + ';color:' + resolved.text + ';border-color:#0f172a;">' +
                                    escapeAttr(titleText) +
                                    '\\x3c/div>' +
                                    (subText ? '\\x3cspan class="ct-sidebar-sublabel" style="margin-top:2px;">' + escapeAttr(subText) + '\\x3c/span>' : '') +
                                    '\\x3c/div>' +
                                    '\\x3cdiv class="ct-color-actions">' +
                                    '\\x3cbutton type="button" class="ct-family-pill-btn' + (isModelOpen ? ' is-open' : '') + '" data-ct-toggle-palette="' + escapeAttr(pKey) + '" title="Open shade palette &amp; custom colors for ' + escapeAttr(titleText) + '">Palette ' + (isModelOpen ? '▴' : '▾') + '\\x3c/button>' +
                                    (hasSpecificCustom
                                        ? '\\x3cbutton type="button" class="ct-color-reset-mini" data-ct-reset-type="model" data-ct-group-key="' + escapeAttr(col.groupKey) + '" title="Reset color for ' + escapeAttr(titleText) + '">↺\\x3c/button>'
                                        : '') +
                                    '\\x3c/div>' +
                                    '\\x3c/div>' +
                                    '\\x3cdiv class="ct-preset-swatches">' + modelSwatches + '\\x3c/div>' +
                                    (isModelOpen ? buildPaletteDrawerHtml("model", col.groupKey, resolved.bg, null, spec.projectId) : '') +
                                    '\\x3c/div>'
                                );
                            }});
                        }}
                    }}

                    if (showFeatures) {{
                        const matchingFeatures = features.filter(function(feat) {{
                            if (!query) return true;
                            const fLbl = String(feat.labelText || feat.rowLabelHtml || "").toLowerCase();
                            if (fLbl.indexOf(query) !== -1) return true;
                            const chList = Array.isArray(feat.choices) ? feat.choices : [];
                            return chList.some(function(ch) {{
                                return String(ch.value || "").toLowerCase().indexOf(query) !== -1;
                            }});
                        }});
                        if (matchingFeatures.length > 0) {{
                            html.push(
                                '\\x3cdiv class="ct-sidebar-section-hdr">' +
                                '\\x3cspan>Feature &amp; choice definitions\\x3c/span>' +
                                '\\x3cspan>' + matchingFeatures.length + '\\x3c/span>' +
                                '\\x3c/div>'
                            );
                            matchingFeatures.forEach(function(feat) {{
                                const fId = String(feat.id);
                                const featOrigIdx = Math.max(0, features.indexOf(feat));
                                const activeShades = getFeatureActiveShades(feat, featOrigIdx, customColors);
                                const rowHex = normalizeHexColor(
                                    (customColors.features && customColors.features[fId]) || activeShades[0] || feat.defaultRowHex || "#287ec2",
                                    "#287ec2"
                                );
                                const choices = Array.isArray(feat.choices) ? feat.choices : [];
                                const hasAnyChoiceCustom = choices.some(function(ch) {{
                                    return Boolean(customColors.choices && customColors.choices[fId + "::" + String(ch.value || "")]);
                                }});
                                const hasRowCustom = Boolean(
                                    (customColors.features && customColors.features[fId]) ||
                                    (customColors.featureShades && customColors.featureShades[fId]) ||
                                    hasAnyChoiceCustom
                                );
                                const fPaletteKey = "feature:" + fId;
                                const isFeatPaletteOpen = Boolean(openPalettes[fPaletteKey]);
                                const miniDotsHtml = activeShades.slice(0, 5).map(function(sh) {{
                                    return '\\x3cspan class="ct-family-mini-dot" style="background:' + sh + ';">\\x3c/span>';
                                }}).join("");

                                const choiceRowsHtml = choices.filter(function(ch) {{
                                    if (!query) return true;
                                    const fLbl = String(feat.labelText || "").toLowerCase();
                                    if (fLbl.indexOf(query) !== -1) return true;
                                    return String(ch.value || "").toLowerCase().indexOf(query) !== -1;
                                }}).map(function(ch) {{
                                    const cVal = String(ch.value || "");
                                    const cKey = fId + "::" + cVal;
                                    const resolved = resolveFeatureChoiceColor(
                                        feat,
                                        cVal,
                                        ch.defaultBg,
                                        ch.defaultText,
                                        customColors
                                    );
                                    const resolvedBgClean = normalizeHexColor(resolved.bg, "#f1f5f9");
                                    const hasChoiceCustom = Boolean(customColors.choices && customColors.choices[cKey]);
                                    const cPaletteKey = "choice:" + cKey;
                                    const isChoicePaletteOpen = Boolean(openPalettes[cPaletteKey]);
                                    const fiveShades = activeShades.slice(0, 5);
                                    const matchedShadeIdx = findActiveShadeIndex(fiveShades, resolvedBgClean);
                                    const shadeDotsHtml = fiveShades.map(function(shHex, sIdx) {{
                                        const cleanSh = normalizeHexColor(shHex, "#ffffff");
                                        const isSelectedShade = (sIdx === matchedShadeIdx);
                                        return (
                                            '\\x3cbutton type="button" class="ct-shade-dot' + (isSelectedShade ? ' is-active-shade' : '') + '" ' +
                                            'data-ct-swatch-type="choice" data-ct-target-key="' + escapeAttr(cKey) + '" ' +
                                            'data-ct-feature-id="' + escapeAttr(fId) + '" data-ct-choice-value="' + escapeAttr(cVal) + '" ' +
                                            'data-ct-swatch-color="' + cleanSh + '" ' +
                                            'title="Select shade ' + (sIdx + 1) + ' (' + cleanSh + ') for ' + escapeAttr(cVal) + '" ' +
                                            'style="background:' + cleanSh + ';">\\x3c/button>'
                                        );
                                    }}).join("");
                                    return (
                                        '\\x3cdiv style="display:flex;flex-direction:column;gap:4px;">' +
                                        '\\x3cdiv class="ct-choice-row">' +
                                        '\\x3cspan class="ct-choice-preview" title="' + escapeAttr(cVal) + '" style="background:' + resolved.bg + ';color:' + resolved.text + ';">' +
                                        escapeAttr(cVal) +
                                        '\\x3c/span>' +
                                        '\\x3cdiv class="ct-color-actions">' +
                                        '\\x3cdiv class="ct-choice-shades" title="Choose from the 5 shades of this feature color">' +
                                        shadeDotsHtml +
                                        '\\x3c/div>' +
                                        '\\x3cbutton type="button" class="ct-family-pill-btn' + (isChoicePaletteOpen ? ' is-open' : '') + '" style="padding:2px 5px;" ' +
                                        'data-ct-toggle-palette="' + escapeAttr(cPaletteKey) + '" title="All palettes &amp; custom color for ' + escapeAttr(cVal) + '">🎨\\x3c/button>' +
                                        (hasChoiceCustom
                                            ? '\\x3cbutton type="button" class="ct-color-reset-mini" data-ct-reset-type="choice" data-ct-feature-id="' + escapeAttr(fId) + '" data-ct-choice-value="' + escapeAttr(cVal) + '" title="Reset choice color">↺\\x3c/button>'
                                            : '') +
                                        '\\x3c/div>' +
                                        '\\x3c/div>' +
                                        (isChoicePaletteOpen ? buildPaletteDrawerHtml("choice", cKey, resolvedBgClean, activeShades, spec.projectId) : '') +
                                        '\\x3c/div>'
                                    );
                                }}).join("");

                                html.push(
                                    '\\x3cdiv class="ct-sidebar-card" data-sidebar-feature-id="' + escapeAttr(fId) + '">' +
                                    '\\x3cdiv class="ct-sidebar-row">' +
                                    '\\x3cdiv style="min-width:0;">' +
                                    '\\x3cdiv class="ct-sidebar-label">' + (feat.rowLabelHtml || escapeAttr(feat.labelText || "")) + '\\x3c/div>' +
                                    '\\x3cspan class="ct-sidebar-sublabel">Choose color family, then pick shade per choice\\x3c/span>' +
                                    '\\x3c/div>' +
                                    '\\x3cdiv class="ct-color-actions">' +
                                    '\\x3cbutton type="button" class="ct-family-pill-btn' + (isFeatPaletteOpen ? ' is-open' : '') + '" data-ct-toggle-palette="' + escapeAttr(fPaletteKey) + '" title="Choose color family or create custom color for ' + escapeAttr(feat.labelText || "") + '">' +
                                    '\\x3cspan class="ct-family-mini-dots">' + miniDotsHtml + '\\x3c/span>' +
                                    '\\x3cspan>Palette ' + (isFeatPaletteOpen ? '▴' : '▾') + '\\x3c/span>' +
                                    '\\x3c/button>' +
                                    (hasRowCustom
                                        ? '\\x3cbutton type="button" class="ct-color-reset-mini" data-ct-reset-type="feature" data-ct-feature-id="' + escapeAttr(fId) + '" title="Reset feature row &amp; choice colors">↺\\x3c/button>'
                                        : '') +
                                    '\\x3c/div>' +
                                    '\\x3c/div>' +
                                    (isFeatPaletteOpen ? buildPaletteDrawerHtml("feature", fId, rowHex, activeShades, spec.projectId) : '') +
                                    (choiceRowsHtml ? '\\x3cdiv class="ct-choice-chips">' + choiceRowsHtml + '\\x3c/div>' : '') +
                                    '\\x3c/div>'
                                );
                            }});
                        }}
                    }}

                    if (html.length === 0) {{
                        html.push(
                            '\\x3cdiv style="padding:18px 8px;text-align:center;color:var(--st-secondary-text-color,#64748b);font-size:.8rem;">' +
                            'No model or feature definitions match your filter.' +
                            '\\x3c/div>'
                        );
                    }}

                    els.sidebarList.innerHTML = html.join("");
                    bindSidebarColorEvents(els.sidebarList);
                }}

                function applyModelColorChange(groupKey, hexVal) {{
                    const state = rootWin.__paagComplexityTreeState;
                    if (!state || !state.spec) return;
                    const cfg = getSavedCustomColors(state.spec.projectId);
                    const cleanHex = normalizeHexColor(hexVal, "#ffffff");
                    cfg.models[groupKey] = cleanHex;
                    const cols = state.cols || state.spec.columns || [];
                    cols.forEach(function(col) {{
                        if (col.groupKey === groupKey && Array.isArray(col.modelNumbers)) {{
                            col.modelNumbers.forEach(function(m) {{
                                cfg.models["model::" + String(m)] = cleanHex;
                            }});
                        }}
                    }});
                    saveCustomColors(state.spec.projectId, cfg);
                    renderComplexityTreeGrid(state.cols, state.spec, null);
                }}

                function applyAllModelsColorChange(hexVal) {{
                    const state = rootWin.__paagComplexityTreeState;
                    if (!state || !state.spec) return;
                    const cfg = getSavedCustomColors(state.spec.projectId);
                    cfg.models["__all__"] = normalizeHexColor(hexVal, "#ffffff");
                    saveCustomColors(state.spec.projectId, cfg);
                    renderComplexityTreeGrid(state.cols, state.spec, null);
                }}

                function applyFeaturePaletteFamily(featureId, shadesList, baseHex) {{
                    const state = rootWin.__paagComplexityTreeState;
                    if (!state || !state.spec) return;
                    const cfg = getSavedCustomColors(state.spec.projectId);
                    const ramp = (Array.isArray(shadesList) && shadesList.length >= 5)
                        ? shadesList.slice(0, 5).map(function(s) {{ return normalizeHexColor(s, "#287ec2"); }})
                        : buildFiveShadeRamp(baseHex || "#287ec2");
                    cfg.features[featureId] = normalizeHexColor(baseHex || ramp[0], "#287ec2");
                    cfg.featureShades[featureId] = ramp;
                    const prefix = String(featureId) + "::";
                    Object.keys(cfg.choices).forEach(function(k) {{
                        if (k.indexOf(prefix) === 0) {{
                            delete cfg.choices[k];
                        }}
                    }});
                    const features = state.spec.features || [];
                    features.forEach(function(feat) {{
                        if (String(feat.id) === String(featureId) && Array.isArray(feat.choices)) {{
                            feat.choices.forEach(function(ch, idx) {{
                                const cVal = String(ch.value || "");
                                if (cVal) {{
                                    cfg.choices[prefix + cVal] = ramp[idx % ramp.length];
                                }}
                            }});
                        }}
                    }});
                    saveCustomColors(state.spec.projectId, cfg);
                    renderComplexityTreeGrid(state.cols, state.spec, null);
                }}

                function applyFeatureRowColorChange(featureId, hexVal) {{
                    const ramp = buildFiveShadeRamp(hexVal);
                    applyFeaturePaletteFamily(featureId, ramp, hexVal);
                }}

                function applyFeatureChoiceColorChange(featureId, choiceVal, hexVal) {{
                    const state = rootWin.__paagComplexityTreeState;
                    if (!state || !state.spec) return;
                    const cfg = getSavedCustomColors(state.spec.projectId);
                    cfg.choices[String(featureId) + "::" + String(choiceVal)] = normalizeHexColor(hexVal, "#f1f5f9");
                    saveCustomColors(state.spec.projectId, cfg);
                    renderComplexityTreeGrid(state.cols, state.spec, null);
                }}

                function bindSidebarColorEvents(listEl) {{
                    if (!listEl) return;

                    listEl.querySelectorAll("[data-ct-toggle-palette]").forEach(function(btn) {{
                        btn.onclick = function(ev) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            const key = btn.getAttribute("data-ct-toggle-palette") || "";
                            if (!key) return;
                            rootWin.__paagComplexityTreeOpenPalettes = rootWin.__paagComplexityTreeOpenPalettes || {{}};
                            rootWin.__paagComplexityTreeOpenPalettes[key] = !rootWin.__paagComplexityTreeOpenPalettes[key];
                            renderColorSidebarList();
                        }};
                    }});

                    listEl.querySelectorAll("[data-ct-family-target='feature']").forEach(function(famEl) {{
                        famEl.onclick = function(ev) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            const fId = famEl.getAttribute("data-ct-feature-id") || "";
                            const rawShades = famEl.getAttribute("data-ct-family-shades") || "";
                            const baseHex = famEl.getAttribute("data-ct-family-base") || "#287ec2";
                            const shades = rawShades ? rawShades.split(",").filter(Boolean) : buildFiveShadeRamp(baseHex);
                            applyFeaturePaletteFamily(fId, shades, baseHex);
                            renderColorSidebarList();
                        }};
                    }});

                    listEl.querySelectorAll("[data-ct-swatch-type]").forEach(function(swBtn) {{
                        swBtn.onclick = function(ev) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            const sType = swBtn.getAttribute("data-ct-swatch-type");
                            const sColor = swBtn.getAttribute("data-ct-swatch-color") || "#ffffff";
                            const targetKey = swBtn.getAttribute("data-ct-target-key") || "";
                            if (sType === "all-models") {{
                                applyAllModelsColorChange(sColor);
                            }} else if (sType === "model") {{
                                applyModelColorChange(swBtn.getAttribute("data-ct-group-key") || targetKey, sColor);
                            }} else if (sType === "feature") {{
                                applyFeatureRowColorChange(swBtn.getAttribute("data-ct-feature-id") || targetKey, sColor);
                            }} else if (sType === "choice") {{
                                let fId = swBtn.getAttribute("data-ct-feature-id") || "";
                                let cVal = swBtn.getAttribute("data-ct-choice-value") || "";
                                if ((!fId || !cVal) && targetKey.indexOf("::") !== -1) {{
                                    const splitIdx = targetKey.indexOf("::");
                                    fId = targetKey.slice(0, splitIdx);
                                    cVal = targetKey.slice(splitIdx + 2);
                                }}
                                applyFeatureChoiceColorChange(fId, cVal, sColor);
                            }}
                            renderColorSidebarList();
                        }};
                    }});

                    listEl.querySelectorAll("input[data-ct-draft-custom-input]").forEach(function(inp) {{
                        const updateDraftPreview = function() {{
                            const val = normalizeHexColor(inp.value, "#287ec2");
                            rootWin.__paagComplexityTreeDraftCustomHex = val;
                            const ramp = buildFiveShadeRamp(val);
                            const bar = inp.closest(".ct-custom-creator-bar");
                            if (bar) {{
                                const previewEl = bar.querySelector("[data-ct-draft-preview-dots]");
                                if (previewEl) {{
                                    previewEl.innerHTML = ramp.map(function(sh) {{
                                        return '\\x3cspan class="ct-family-mini-dot" style="background:' + sh + ';">\\x3c/span>';
                                    }}).join("");
                                }}
                            }}
                        }};
                        inp.oninput = updateDraftPreview;
                        inp.onchange = updateDraftPreview;
                    }});

                    listEl.querySelectorAll("[data-ct-save-custom-mode]").forEach(function(saveBtn) {{
                        saveBtn.onclick = function(ev) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            const state = rootWin.__paagComplexityTreeState;
                            if (!state || !state.spec) return;
                            const bar = saveBtn.closest(".ct-custom-creator-bar");
                            const inp = bar ? bar.querySelector("input[data-ct-draft-custom-input]") : null;
                            const pickedHex = normalizeHexColor(
                                (inp && inp.value) || rootWin.__paagComplexityTreeDraftCustomHex || "#287ec2",
                                "#287ec2"
                            );
                            rootWin.__paagComplexityTreeDraftCustomHex = pickedHex;
                            saveUserCustomColor(state.spec.projectId, pickedHex);
                            const mode = saveBtn.getAttribute("data-ct-save-custom-mode") || "";
                            const tKey = saveBtn.getAttribute("data-ct-save-custom-key") || "";
                            if (mode === "feature") {{
                                applyFeaturePaletteFamily(tKey, buildFiveShadeRamp(pickedHex), pickedHex);
                            }} else if (mode === "choice") {{
                                const splitIdx = tKey.indexOf("::");
                                if (splitIdx !== -1) {{
                                    applyFeatureChoiceColorChange(tKey.slice(0, splitIdx), tKey.slice(splitIdx + 2), pickedHex);
                                }}
                            }} else if (mode === "model") {{
                                applyModelColorChange(tKey, pickedHex);
                            }} else if (mode === "all-models") {{
                                applyAllModelsColorChange(pickedHex);
                            }}
                            renderColorSidebarList();
                        }};
                    }});

                    listEl.querySelectorAll("[data-ct-delete-saved-color]").forEach(function(delBtn) {{
                        delBtn.onclick = function(ev) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            const state = rootWin.__paagComplexityTreeState;
                            if (!state || !state.spec) return;
                            const hexToRemove = delBtn.getAttribute("data-ct-delete-saved-color") || "";
                            removeUserCustomColor(state.spec.projectId, hexToRemove);
                            renderColorSidebarList();
                        }};
                    }});

                    listEl.querySelectorAll("[data-ct-reset-type]").forEach(function(rstBtn) {{
                        rstBtn.onclick = function(ev) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            const state = rootWin.__paagComplexityTreeState;
                            if (!state || !state.spec) return;
                            const cfg = getSavedCustomColors(state.spec.projectId);
                            const rType = rstBtn.getAttribute("data-ct-reset-type");
                            if (rType === "all-models") {{
                                delete cfg.models["__all__"];
                            }} else if (rType === "model") {{
                                const gKey = rstBtn.getAttribute("data-ct-group-key") || "";
                                delete cfg.models[gKey];
                                const cols = state.cols || state.spec.columns || [];
                                cols.forEach(function(col) {{
                                    if (col.groupKey === gKey && Array.isArray(col.modelNumbers)) {{
                                        col.modelNumbers.forEach(function(m) {{
                                            delete cfg.models["model::" + String(m)];
                                        }});
                                    }}
                                }});
                            }} else if (rType === "feature") {{
                                const fId = rstBtn.getAttribute("data-ct-feature-id") || "";
                                delete cfg.features[fId];
                                delete cfg.featureShades[fId];
                                const prefix = String(fId) + "::";
                                Object.keys(cfg.choices).forEach(function(k) {{
                                    if (k.indexOf(prefix) === 0) {{
                                        delete cfg.choices[k];
                                    }}
                                }});
                            }} else if (rType === "choice") {{
                                const fId = rstBtn.getAttribute("data-ct-feature-id") || "";
                                const cVal = rstBtn.getAttribute("data-ct-choice-value") || "";
                                delete cfg.choices[fId + "::" + cVal];
                            }}
                            saveCustomColors(state.spec.projectId, cfg);
                            renderComplexityTreeGrid(state.cols, state.spec, null);
                            renderColorSidebarList();
                        }};
                    }});
                }}

                function renderColorSidebar() {{
                    renderColorSidebarControls();
                    renderColorSidebarList();
                }}

                function toggleComplexityTreeSidebar() {{
                    const els = getElements();
                    if (!els || !els.sidebar) return;
                    const nextCollapsed = !els.sidebar.classList.contains("collapsed");
                    els.sidebar.classList.toggle("collapsed", nextCollapsed);
                    rootWin.__paagComplexityTreeSidebarCollapsed = nextCollapsed;
                    if (els.toggleSidebarBtn) {{
                        els.toggleSidebarBtn.setAttribute("aria-expanded", String(!nextCollapsed));
                        els.toggleSidebarBtn.classList.toggle("is-active-tool", !nextCollapsed);
                    }}
                    applyZoomTransform();
                }}

                function resetColorsToDefault() {{
                    const state = rootWin.__paagComplexityTreeState;
                    if (!state || !state.spec) return;
                    saveCustomColors(state.spec.projectId, emptyColorConfig());
                    renderComplexityTreeGrid(state.cols, state.spec, null);
                    renderColorSidebarList();
                }}

                function moveColumnToSlot(fromIndex, toInsertSlot) {{
                    const state = rootWin.__paagComplexityTreeState;
                    if (!state || !state.spec || !Array.isArray(state.cols)) return;
                    const cols = state.cols.slice();
                    const total = cols.length;
                    if (fromIndex < 0 || fromIndex >= total) return;
                    const clampedSlot = Math.max(0, Math.min(total, toInsertSlot));
                    if (clampedSlot === fromIndex || clampedSlot === fromIndex + 1) return;
                    const movedCol = cols.splice(fromIndex, 1)[0];
                    const targetIndex = clampedSlot > fromIndex ? clampedSlot - 1 : clampedSlot;
                    cols.splice(targetIndex, 0, movedCol);
                    state.cols = cols;
                    const flatModels = [];
                    cols.forEach(function(c) {{
                        (c.modelNumbers || []).forEach(function(m) {{
                            flatModels.push(String(m));
                        }});
                    }});
                    if (isCustomOrderActive(cols, state.spec)) {{
                        saveModelOrder(state.spec.projectId, flatModels);
                    }} else {{
                        saveModelOrder(state.spec.projectId, []);
                    }}
                    renderComplexityTreeGrid(cols, state.spec, targetIndex);
                    renderColorSidebarList();
                }}

                function resetColumnsToDefault() {{
                    const state = rootWin.__paagComplexityTreeState;
                    if (!state || !state.spec) return;
                    saveModelOrder(state.spec.projectId, []);
                    state.cols = computeOrderedColumns(state.spec);
                    renderComplexityTreeGrid(state.cols, state.spec, null);
                    renderColorSidebarList();
                }}

                function isSidebarExpanded() {{
                    const sb = rootDoc.querySelector('[data-testid="stSidebar"]');
                    return sb ? sb.getAttribute("aria-expanded") === "true" : false;
                }}

                function collapseSidebarIfExpanded() {{
                    if (!isSidebarExpanded()) return;
                    const btn =
                        rootDoc.querySelector('[data-testid="stSidebarCollapseButton"] button') ||
                        rootDoc.querySelector('[data-testid="stSidebarCollapseButton"]');
                    if (btn && typeof btn.click === "function") btn.click();
                }}

                function expandSidebarIfCollapsed() {{
                    if (isSidebarExpanded()) return;
                    const btn =
                        rootDoc.querySelector('button[data-testid="stExpandSidebarButton"]') ||
                        rootDoc.querySelector('[data-testid="stExpandSidebarButton"] button') ||
                        rootDoc.querySelector('[data-testid="stExpandSidebarButton"]') ||
                        rootDoc.querySelector('[data-testid="stSidebarCollapsedControl"] button');
                    if (btn && typeof btn.click === "function") btn.click();
                }}

                function isVisualFullScreen() {{
                    const fsEl = rootDoc.fullscreenElement || rootDoc.webkitFullscreenElement;
                    const els = getElements();
                    if (fsEl && (fsEl === rootDoc.documentElement || (els && (fsEl === els.shell || els.shell.contains(fsEl))))) {{
                        return true;
                    }}
                    return Boolean(rootWin.__paagComplexityTreeFallbackFullScreen);
                }}

                function applyZoomTransform() {{
                    const els = getElements();
                    if (!els || !els.content || !els.zoomStage || !els.viewport) return;
                    const activeScale = clampZoom(rootWin.__paagComplexityTreeZoom || 1);
                    if (els.zoomResetBtn) {{
                        els.zoomResetBtn.textContent = Math.round(activeScale * 100) + "%";
                    }}
                    if (Math.abs(activeScale - 1) < 0.001) {{
                        els.content.style.width = "";
                        els.content.style.minWidth = "";
                        els.content.style.transform = "";
                        els.zoomStage.style.width = "";
                        els.zoomStage.style.height = "";
                        return;
                    }}
                    const viewportInnerWidth = Math.max(320, els.viewport.clientWidth - 28);
                    els.content.style.minWidth = viewportInnerWidth + "px";
                    els.content.style.transform = "scale(" + activeScale + ")";
                    const unscaledWidth = Math.max(els.content.scrollWidth, els.content.offsetWidth);
                    const unscaledHeight = Math.max(els.content.scrollHeight, els.content.offsetHeight);
                    els.zoomStage.style.width = Math.ceil(unscaledWidth * activeScale) + "px";
                    els.zoomStage.style.height = Math.ceil(unscaledHeight * activeScale) + "px";
                }}

                function setZoomScale(nextScale, anchor) {{
                    const els = getElements();
                    const prevScale = clampZoom(rootWin.__paagComplexityTreeZoom || 1);
                    const targetScale = clampZoom(nextScale);
                    rootWin.__paagComplexityTreeZoom = targetScale;
                    if (!els || !els.viewport) return;
                    const vp = els.viewport;
                    const anchorX = (anchor && Number.isFinite(anchor.x)) ? anchor.x : vp.clientWidth / 2;
                    const anchorY = (anchor && Number.isFinite(anchor.y)) ? anchor.y : vp.clientHeight / 2;
                    const contentX = (vp.scrollLeft + anchorX) / prevScale;
                    const contentY = (vp.scrollTop + anchorY) / prevScale;
                    applyZoomTransform();
                    if (anchor && anchor.resetScroll) {{
                        vp.scrollLeft = 0;
                        vp.scrollTop = 0;
                    }} else if (Math.abs(targetScale - prevScale) > 0.0001) {{
                        vp.scrollLeft = Math.max(0, contentX * targetScale - anchorX);
                        vp.scrollTop = Math.max(0, contentY * targetScale - anchorY);
                    }}
                }}

                function fitComplexityTreeView() {{
                    const els = getElements();
                    if (!els || !els.content || !els.viewport) return;
                    const prevTransform = els.content.style.transform;
                    const prevMinW = els.content.style.minWidth;
                    els.content.style.transform = "";
                    els.content.style.minWidth = "0px";
                    const gridEl = els.content.firstElementChild || els.content;
                    const contentW = Math.max(gridEl.scrollWidth, els.content.scrollWidth, 240);
                    const contentH = Math.max(gridEl.scrollHeight, els.content.scrollHeight, 120);
                    els.content.style.minWidth = prevMinW;
                    els.content.style.transform = prevTransform;
                    const availW = Math.max(els.viewport.clientWidth - 32, 160);
                    const availH = isVisualFullScreen()
                        ? Math.max(els.viewport.clientHeight - 32, 160)
                        : Math.max(rootWin.innerHeight * 0.72, 240);
                    const fitScale = clampZoom(Math.min(availW / contentW, availH / contentH, 1.35));
                    setZoomScale(fitScale, {{ resetScroll: true }});
                }}

                function updateFullScreenControl() {{
                    ensureGlobalFullScreenStyle();
                    const els = getElements();
                    const isFs = isVisualFullScreen();
                    const wasFs = Boolean(rootWin.__paagComplexityTreeFullScreenActive);
                    rootDoc.documentElement.classList.toggle("paag-complexity-tree-fullscreen-active", isFs);
                    if (isFs && !wasFs) {{
                        if (typeof rootWin.__paagComplexityTreeSidebarWasExpanded !== "boolean") {{
                            rootWin.__paagComplexityTreeSidebarWasExpanded = isSidebarExpanded();
                        }}
                        rootWin.__paagComplexityTreeFullScreenActive = true;
                        collapseSidebarIfExpanded();
                    }} else if (!isFs && wasFs) {{
                        const shouldRestore = Boolean(rootWin.__paagComplexityTreeSidebarWasExpanded);
                        rootWin.__paagComplexityTreeFullScreenActive = false;
                        rootWin.__paagComplexityTreeSidebarWasExpanded = undefined;
                        rootWin.__paagComplexityTreeZoom = 1;
                        if (els && els.viewport) {{
                            els.viewport.scrollTop = 0;
                        }}
                        if (shouldRestore) {{
                            expandSidebarIfCollapsed();
                        }}
                    }}
                    if (!els) return;
                    els.shell.classList.toggle("fullscreen-visual", isFs);
                    if (els.fullScreenBtn) {{
                        els.fullScreenBtn.textContent = isFs ? "Exit Full Screen" : "Full Screen";
                        els.fullScreenBtn.title = isFs
                            ? "Exit the full-screen complexity tree visual (Esc)"
                            : "Open the complexity tree visual full screen";
                        els.fullScreenBtn.setAttribute("aria-pressed", String(isFs));
                    }}
                    const state = rootWin.__paagComplexityTreeState;
                    if (els.resetColsBtn && state && state.spec && Array.isArray(state.cols)) {{
                        els.resetColsBtn.disabled = !isCustomOrderActive(state.cols, state.spec);
                    }}
                    if (els.resetColorsBtn && state && state.spec) {{
                        els.resetColorsBtn.disabled = !isCustomColorsActive(state.spec.projectId);
                    }}
                    if (els.sidebar) {{
                        const isCollapsed = Boolean(rootWin.__paagComplexityTreeSidebarCollapsed);
                        els.sidebar.classList.toggle("collapsed", isCollapsed);
                        if (els.toggleSidebarBtn) {{
                            els.toggleSidebarBtn.setAttribute("aria-expanded", String(!isCollapsed));
                            els.toggleSidebarBtn.classList.toggle("is-active-tool", !isCollapsed);
                        }}
                    }}
                    applyZoomTransform();
                }}

                async function toggleComplexityTreeFullScreen() {{
                    const isFs = isVisualFullScreen();
                    const els = getElements();
                    const fsTarget = (els && els.shell) ? els.shell : rootDoc.documentElement;
                    if (isFs) {{
                        rootWin.__paagComplexityTreeFallbackFullScreen = false;
                        try {{
                            if (rootDoc.fullscreenElement || rootDoc.webkitFullscreenElement) {{
                                if (rootDoc.exitFullscreen) {{
                                    await rootDoc.exitFullscreen();
                                }} else if (rootDoc.webkitExitFullscreen) {{
                                    rootDoc.webkitExitFullscreen();
                                }}
                            }}
                        }} catch (e) {{}}
                        updateFullScreenControl();
                    }} else {{
                        rootWin.__paagComplexityTreeSidebarWasExpanded = isSidebarExpanded();
                        try {{
                            if (typeof fsTarget.requestFullscreen === "function") {{
                                await fsTarget.requestFullscreen();
                            }} else if (typeof fsTarget.webkitRequestFullscreen === "function") {{
                                fsTarget.webkitRequestFullscreen();
                            }} else {{
                                rootWin.__paagComplexityTreeFallbackFullScreen = true;
                            }}
                        }} catch (e) {{
                            rootWin.__paagComplexityTreeFallbackFullScreen = true;
                        }}
                        updateFullScreenControl();
                    }}
                }}

                function triggerComplexityTreePrint() {{
                    const printBtn = rootDoc.querySelector('[class*="st-key-btn_print_complexity_tree_visual_"] button');
                    if (printBtn && typeof printBtn.click === "function") {{
                        printBtn.click();
                    }}
                }}

                const orderedInitialCols = computeOrderedColumns(SPEC);
                rootWin.__paagComplexityTreeState = {{
                    spec: SPEC,
                    cols: orderedInitialCols,
                }};

                rootWin.__paagSyncComplexityTreeVisual = updateFullScreenControl;
                rootWin.__paagComplexityTreeActions = {{
                    zoomIn: function() {{ setZoomScale((rootWin.__paagComplexityTreeZoom || 1) * 1.2); }},
                    zoomOut: function() {{ setZoomScale((rootWin.__paagComplexityTreeZoom || 1) / 1.2); }},
                    fitView: fitComplexityTreeView,
                    zoomReset: function() {{ setZoomScale(1, {{ resetScroll: false }}); }},
                    resetCols: resetColumnsToDefault,
                    resetColors: resetColorsToDefault,
                    toggleSidebar: toggleComplexityTreeSidebar,
                    moveColumnToSlot: moveColumnToSlot,
                    fullScreen: toggleComplexityTreeFullScreen,
                    print: triggerComplexityTreePrint,
                    setZoomScale: setZoomScale,
                    isVisualFullScreen: isVisualFullScreen,
                    updateFullScreenControl: updateFullScreenControl,
                    getElements: getElements,
                }};

                if (typeof rootWin.__paagComplexityTreeCleanup === "function") {{
                    try {{ rootWin.__paagComplexityTreeCleanup(); }} catch (e) {{}}
                }}

                let colDragState = null;
                let panState = null;

                function ensureDragOverlays(shellEl) {{
                    const host = shellEl || rootDoc.getElementById("complexity-tree-shell") || rootDoc.body;
                    let indicator = rootDoc.getElementById("paag-ct-col-drop-indicator");
                    if (!indicator) {{
                        indicator = rootDoc.createElement("div");
                        indicator.id = "paag-ct-col-drop-indicator";
                        indicator.className = "ct-col-drop-indicator";
                        host.appendChild(indicator);
                    }} else if (indicator.parentElement !== host) {{
                        host.appendChild(indicator);
                    }}
                    let ghost = rootDoc.getElementById("paag-ct-col-drag-ghost");
                    if (!ghost) {{
                        ghost = rootDoc.createElement("div");
                        ghost.id = "paag-ct-col-drag-ghost";
                        ghost.className = "ct-col-drag-ghost";
                        host.appendChild(ghost);
                    }} else if (ghost.parentElement !== host) {{
                        host.appendChild(ghost);
                    }}
                    return {{ indicator: indicator, ghost: ghost }};
                }}

                function clearMergePreview(contentEl) {{
                    if (!contentEl) return;
                    contentEl.querySelectorAll(".ct-will-merge-preview").forEach(function(el) {{
                        el.classList.remove("ct-will-merge-preview");
                    }});
                }}

                function updateColumnDragPreview(clientX, clientY) {{
                    if (!colDragState || !colDragState.content) return;
                    const content = colDragState.content;
                    const fromIndex = colDragState.fromIndex;
                    const topHeaders = Array.from(content.querySelectorAll('.ct-model-col-header[data-row-pos="top"]'));
                    const bottomHeaders = Array.from(content.querySelectorAll('.ct-model-col-header[data-row-pos="bottom"]'));
                    if (topHeaders.length === 0) return;

                    let insertSlot = topHeaders.length;
                    for (let i = 0; i < topHeaders.length; i++) {{
                        const r = topHeaders[i].getBoundingClientRect();
                        if (clientX < r.left + r.width / 2) {{
                            insertSlot = i;
                            break;
                        }}
                    }}
                    colDragState.insertSlot = insertSlot;

                    const overlays = ensureDragOverlays(colDragState.shell);
                    const firstRect = topHeaders[0].getBoundingClientRect();
                    const lastBottomRect = (bottomHeaders[bottomHeaders.length - 1] || topHeaders[topHeaders.length - 1]).getBoundingClientRect();
                    let lineX = firstRect.left;
                    if (insertSlot === 0) {{
                        lineX = firstRect.left - 4;
                    }} else if (insertSlot >= topHeaders.length) {{
                        const lastRect = topHeaders[topHeaders.length - 1].getBoundingClientRect();
                        lineX = lastRect.right + 2;
                    }} else {{
                        const prevRect = topHeaders[insertSlot - 1].getBoundingClientRect();
                        const nextRect = topHeaders[insertSlot].getBoundingClientRect();
                        lineX = (prevRect.right + nextRect.left) / 2 - 2;
                    }}

                    overlays.indicator.style.display = "block";
                    overlays.indicator.style.left = Math.round(lineX) + "px";
                    overlays.indicator.style.top = Math.round(firstRect.top - 4) + "px";
                    overlays.indicator.style.height = Math.max(40, Math.round(lastBottomRect.bottom - firstRect.top + 8)) + "px";

                    clearMergePreview(content);
                    let mergeCount = 0;
                    const state = rootWin.__paagComplexityTreeState;
                    if (state && Array.isArray(state.cols) && insertSlot !== fromIndex && insertSlot !== fromIndex + 1) {{
                        const cols = state.cols;
                        const draggedCol = cols[fromIndex];
                        const leftNeighborIdx = (insertSlot > 0 && insertSlot - 1 !== fromIndex) ? insertSlot - 1 : -1;
                        const rightNeighborIdx = (insertSlot < cols.length && insertSlot !== fromIndex) ? insertSlot : -1;
                        const featureCount = (state.spec && state.spec.features) ? state.spec.features.length : 0;

                        for (let fIdx = 0; fIdx < featureCount; fIdx++) {{
                            const draggedKey = draggedCol && draggedCol.cells[fIdx] ? draggedCol.cells[fIdx].mergeKey : null;
                            if (draggedKey === null) continue;
                            const matchLeft = leftNeighborIdx >= 0 && cols[leftNeighborIdx].cells[fIdx].mergeKey === draggedKey;
                            const matchRight = rightNeighborIdx >= 0 && cols[rightNeighborIdx].cells[fIdx].mergeKey === draggedKey;
                            if (matchLeft || matchRight) {{
                                mergeCount += 1;
                                const rowBoxes = content.querySelectorAll('.ct-feature-box[data-feature-index="' + fIdx + '"]');
                                rowBoxes.forEach(function(box) {{
                                    const cStart = Number(box.getAttribute("data-col-start"));
                                    const cEnd = Number(box.getAttribute("data-col-end"));
                                    if (
                                        (fromIndex >= cStart && fromIndex < cEnd) ||
                                        (matchLeft && leftNeighborIdx >= cStart && leftNeighborIdx < cEnd) ||
                                        (matchRight && rightNeighborIdx >= cStart && rightNeighborIdx < cEnd)
                                    ) {{
                                        box.classList.add("ct-will-merge-preview");
                                    }}
                                }});
                            }}
                        }}
                    }}

                    overlays.ghost.style.display = "inline-flex";
                    overlays.ghost.style.left = Math.round(clientX + 14) + "px";
                    overlays.ghost.style.top = Math.round(clientY + 14) + "px";
                    const badgeHtml = mergeCount > 0
                        ? ' \\x3cspan class="ct-ghost-merge-badge">Merges ' + mergeCount + ' row' + (mergeCount === 1 ? '' : 's') + '\\x3c/span>'
                        : '';
                    overlays.ghost.innerHTML = '\\x3cspan>⇄ ' + escapeAttr(colDragState.label) + '\\x3c/span>' + badgeHtml;
                }}

                function getEventElement(event) {{
                    if (!event) return null;
                    let t = event.target;
                    if (!t) return null;
                    if (t.nodeType === 1 && typeof t.closest === "function") return t;
                    if (t.parentElement && typeof t.parentElement.closest === "function") return t.parentElement;
                    return null;
                }}

                function executeToolbarAction(action) {{
                    const api = rootWin.__paagComplexityTreeActions;
                    if (!api || !action) return;
                    if (action === "full-screen") api.fullScreen();
                    else if (action === "zoom-in") api.zoomIn();
                    else if (action === "zoom-out") api.zoomOut();
                    else if (action === "fit-view") api.fitView();
                    else if (action === "zoom-reset") api.zoomReset();
                    else if (action === "reset-cols") api.resetCols();
                    else if (action === "reset-colors") api.resetColors();
                    else if (action === "toggle-sidebar") api.toggleSidebar();
                    else if (action === "print") api.print();
                }}

                function bindShellInteractiveElements(shell) {{
                    if (!shell) return;
                    shell.querySelectorAll("[data-ct-action]").forEach(function(btn) {{
                        btn.onclick = function(ev) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            executeToolbarAction(btn.getAttribute("data-ct-action"));
                        }};
                    }});
                    shell.querySelectorAll("[data-ct-move-col]").forEach(function(moveColBtn) {{
                        moveColBtn.onclick = function(ev) {{
                            ev.preventDefault();
                            ev.stopPropagation();
                            const headerEl = moveColBtn.closest(".ct-model-col-header");
                            if (headerEl && rootWin.__paagComplexityTreeActions) {{
                                const fromIdx = Number(headerEl.getAttribute("data-col-index"));
                                const dir = Number(moveColBtn.getAttribute("data-ct-move-col"));
                                if (Number.isFinite(fromIdx) && Number.isFinite(dir)) {{
                                    const targetSlot = dir < 0 ? fromIdx - 1 : fromIdx + 2;
                                    rootWin.__paagComplexityTreeActions.moveColumnToSlot(fromIdx, targetSlot);
                                }}
                            }}
                        }};
                    }});
                }}

                const onWinClickCapture = function(event) {{
                    const target = getEventElement(event);
                    if (!target) return;
                    const moveColBtn = target.closest("[data-ct-move-col]");
                    if (moveColBtn) {{
                        const headerEl = moveColBtn.closest(".ct-model-col-header");
                        const shell = moveColBtn.closest("#complexity-tree-shell");
                        if (headerEl && shell && rootWin.__paagComplexityTreeActions) {{
                            event.preventDefault();
                            event.stopPropagation();
                            if (typeof event.stopImmediatePropagation === "function") event.stopImmediatePropagation();
                            const fromIdx = Number(headerEl.getAttribute("data-col-index"));
                            const dir = Number(moveColBtn.getAttribute("data-ct-move-col"));
                            if (Number.isFinite(fromIdx) && Number.isFinite(dir)) {{
                                const targetSlot = dir < 0 ? fromIdx - 1 : fromIdx + 2;
                                rootWin.__paagComplexityTreeActions.moveColumnToSlot(fromIdx, targetSlot);
                            }}
                            return;
                        }}
                    }}
                    const btn = target.closest("[data-ct-action]");
                    if (!btn) return;
                    const shell = btn.closest("#complexity-tree-shell");
                    if (!shell) return;
                    event.preventDefault();
                    event.stopPropagation();
                    if (typeof event.stopImmediatePropagation === "function") event.stopImmediatePropagation();
                    executeToolbarAction(btn.getAttribute("data-ct-action"));
                }};

                const onFullscreenChange = function() {{
                    if (rootWin.__paagComplexityTreeActions) {{
                        rootWin.__paagComplexityTreeActions.updateFullScreenControl();
                    }}
                }};

                const onKeyDownCapture = function(event) {{
                    if (event.key === "Escape" && rootWin.__paagComplexityTreeFallbackFullScreen) {{
                        rootWin.__paagComplexityTreeFallbackFullScreen = false;
                        if (rootWin.__paagComplexityTreeActions) {{
                            rootWin.__paagComplexityTreeActions.updateFullScreenControl();
                        }}
                    }}
                }};

                const onWheel = function(event) {{
                    const api = rootWin.__paagComplexityTreeActions;
                    if (!api || !api.isVisualFullScreen()) return;
                    const target = getEventElement(event);
                    if (!target) return;
                    const vp = target.closest("#complexity-tree-viewport");
                    if (!vp || target.closest("#complexity-tree-toolbar")) return;
                    event.preventDefault();
                    const rect = vp.getBoundingClientRect();
                    const anchorX = event.clientX - rect.left;
                    const anchorY = event.clientY - rect.top;
                    const delta = event.deltaY < 0 ? 1.12 : 0.89;
                    api.setZoomScale((rootWin.__paagComplexityTreeZoom || 1) * delta, {{ x: anchorX, y: anchorY }});
                }};

                const onMouseDown = function(event) {{
                    if (event.button !== 0) return;
                    const target = getEventElement(event);
                    if (!target) return;
                    if (target.closest("[data-ct-move-col]")) return;

                    const headerEl = target.closest(".ct-model-col-header");
                    if (headerEl) {{
                        const shell = headerEl.closest("#complexity-tree-shell");
                        const vp = headerEl.closest("#complexity-tree-viewport");
                        const content = headerEl.closest("#complexity-tree-content");
                        const fromIndex = Number(headerEl.getAttribute("data-col-index"));
                        if (shell && vp && content && Number.isFinite(fromIndex)) {{
                            event.preventDefault();
                            const lblEl = headerEl.querySelector(".ct-col-header-label") || headerEl;
                            const rawLabel = (lblEl.textContent || "Model").trim().replace(/\\s+/g, " / ");
                            colDragState = {{
                                shell: shell,
                                vp: vp,
                                content: content,
                                fromIndex: fromIndex,
                                insertSlot: fromIndex,
                                startX: event.clientX,
                                startY: event.clientY,
                                active: false,
                                label: rawLabel,
                            }};
                            return;
                        }}
                    }}

                    const api = rootWin.__paagComplexityTreeActions;
                    if (!api || !api.isVisualFullScreen()) return;
                    if (target.closest("button, input, select, textarea, a, #complexity-tree-toolbar, #complexity-tree-sidebar")) return;
                    const vp = target.closest("#complexity-tree-viewport");
                    const shell = target.closest("#complexity-tree-shell");
                    if (!vp || !shell) return;
                    panState = {{
                        vp: vp,
                        shell: shell,
                        startX: event.clientX,
                        startY: event.clientY,
                        scrollLeft: vp.scrollLeft,
                        scrollTop: vp.scrollTop,
                    }};
                    shell.classList.add("is-panning");
                }};

                const onMouseMove = function(event) {{
                    if (colDragState) {{
                        if (!colDragState.active && Math.hypot(event.clientX - colDragState.startX, event.clientY - colDragState.startY) > 4) {{
                            colDragState.active = true;
                            colDragState.content.querySelectorAll('.ct-model-col-header[data-col-index="' + colDragState.fromIndex + '"]').forEach(function(el) {{
                                el.classList.add("is-dragging-col");
                            }});
                        }}
                        if (colDragState.active) {{
                            updateColumnDragPreview(event.clientX, event.clientY);
                        }}
                        return;
                    }}
                    if (!panState || !panState.vp) return;
                    panState.vp.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX);
                    panState.vp.scrollTop = panState.scrollTop - (event.clientY - panState.startY);
                }};

                const onMouseUp = function() {{
                    if (colDragState) {{
                        const stateToFinish = colDragState;
                        colDragState = null;
                        const overlays = ensureDragOverlays(stateToFinish.shell);
                        overlays.indicator.style.display = "none";
                        overlays.ghost.style.display = "none";
                        if (stateToFinish.content) {{
                            clearMergePreview(stateToFinish.content);
                            stateToFinish.content.querySelectorAll(".is-dragging-col").forEach(function(el) {{
                                el.classList.remove("is-dragging-col");
                            }});
                        }}
                        if (stateToFinish.active && rootWin.__paagComplexityTreeActions) {{
                            rootWin.__paagComplexityTreeActions.moveColumnToSlot(
                                stateToFinish.fromIndex,
                                stateToFinish.insertSlot
                            );
                        }}
                        return;
                    }}
                    if (!panState) return;
                    if (panState.shell) panState.shell.classList.remove("is-panning");
                    panState = null;
                }};

                rootWin.addEventListener("click", onWinClickCapture, true);
                rootDoc.addEventListener("fullscreenchange", onFullscreenChange);
                rootDoc.addEventListener("webkitfullscreenchange", onFullscreenChange);
                rootWin.addEventListener("keydown", onKeyDownCapture, true);
                rootDoc.addEventListener("wheel", onWheel, {{ passive: false }});
                rootDoc.addEventListener("mousedown", onMouseDown);
                rootWin.addEventListener("mousemove", onMouseMove);
                rootWin.addEventListener("mouseup", onMouseUp);

                rootWin.__paagComplexityTreeCleanup = function() {{
                    rootWin.removeEventListener("click", onWinClickCapture, true);
                    rootDoc.removeEventListener("fullscreenchange", onFullscreenChange);
                    rootDoc.removeEventListener("webkitfullscreenchange", onFullscreenChange);
                    rootWin.removeEventListener("keydown", onKeyDownCapture, true);
                    rootDoc.removeEventListener("wheel", onWheel);
                    rootDoc.removeEventListener("mousedown", onMouseDown);
                    rootWin.removeEventListener("mousemove", onMouseMove);
                    rootWin.removeEventListener("mouseup", onMouseUp);
                }};

                function initComplexityTreeVisual() {{
                    ensureGlobalFullScreenStyle();
                    const els = getElements();
                    if (!els) return false;
                    const state = rootWin.__paagComplexityTreeState;
                    if (
                        state &&
                        state.spec &&
                        Array.isArray(state.cols) &&
                        (isCustomOrderActive(state.cols, state.spec) || isCustomColorsActive(state.spec.projectId))
                    ) {{
                        renderComplexityTreeGrid(state.cols, state.spec, null);
                    }}
                    renderColorSidebar();
                    bindShellInteractiveElements(els.shell);
                    updateFullScreenControl();
                    return true;
                }}

                if (!initComplexityTreeVisual()) {{
                    let attempts = 0;
                    const timer = setInterval(function() {{
                        attempts += 1;
                        if (initComplexityTreeVisual() || attempts >= 50) {{
                            clearInterval(timer);
                        }}
                    }}, 40);
                }} else {{
                    setTimeout(updateFullScreenControl, 60);
                }}
            }})();
            </script>""",
            unsafe_allow_javascript=True,
        )

    def _build_complexity_tree_grid_for_print(
        target_categories: list[str],
        target_model_labels: list[str],
        target_feature_displays: list[str],
    ) -> str | None:
        if not target_categories or not target_model_labels or not target_feature_displays:
            return None
        cat_order = {cat: idx for idx, cat in enumerate(target_categories)}
        p_features = (
            active_features.loc[
                active_features["category"]
                .fillna("")
                .astype(str)
                .str.strip()
                .isin(target_categories)
            ]
            .assign(
                _category_order=lambda df: df["category"]
                .fillna("")
                .astype(str)
                .str.strip()
                .map(cat_order)
            )
            .sort_values(by="_category_order", kind="stable")
            .drop(columns=["_category_order"])
        )
        if p_features.empty or visual_models.empty:
            return None
        f_ids = [str(fid) for fid in p_features["id"]]
        grp_by_vals: dict[tuple[str, ...], dict[str, object]] = {}
        for _, m_row in visual_models.iterrows():
            m_id = str(m_row["id"])
            if m_id not in visual_tree.index:
                continue
            vals = tuple(
                "" if pd.isna(visual_tree.at[m_id, fid])
                else str(visual_tree.at[m_id, fid]).strip()
                for fid in f_ids
            )
            grp = grp_by_vals.setdefault(
                vals,
                {"model_ids": [], "model_names": [], "model_numbers": []},
            )
            grp["model_ids"].append(m_id)
            grp["model_names"].append(str(m_row["display_name"] or "").strip())
            grp["model_numbers"].append(str(m_row["model_number"]).strip())
        if not grp_by_vals:
            return None
        v_ranks: list[dict[str, int]] = [{} for _ in range(len(f_ids))]
        for vals in grp_by_vals:
            for idx, val in enumerate(vals):
                if val not in v_ranks[idx]:
                    v_ranks[idx][val] = len(v_ranks[idx])
        s_keys = sorted(
            grp_by_vals.keys(),
            key=lambda vals: tuple(v_ranks[idx][val] for idx, val in enumerate(vals)),
        )
        p_groups = [grp_by_vals[k] for k in s_keys]
        g_cols = len(p_groups)
        g_tmpl = f"minmax(130px, 1.2fr) repeat({g_cols}, minmax(max-content, 1fr))"

        def _grp_model_lines(grp_obj: dict[str, object]) -> list[str]:
            if target_model_labels == ["Model name"]:
                return [
                    escape(str(lbl or "Model name not defined"))
                    for lbl in dict.fromkeys(grp_obj["model_names"])
                ]
            if target_model_labels == ["Model number"]:
                return [escape(str(lbl)) for lbl in grp_obj["model_numbers"]]
            res_lines: list[str] = []
            for m_name, m_num in zip(grp_obj["model_names"], grp_obj["model_numbers"]):
                for l_type in target_model_labels:
                    if l_type == "Model name":
                        res_lines.append(escape(str(m_name or "Model name not defined")))
                    elif l_type == "Model number":
                        res_lines.append(escape(str(m_num)))
            return res_lines

        grp_lbl_lines = [_grp_model_lines(g) for g in p_groups]
        m_hdr_height = max(42, max(len(lns) for lns in grp_lbl_lines) * 22 + 12)
        p_show_parts = any(
            m in target_feature_displays for m in ("Part number", "Part name")
        )
        p_rules_map: dict[tuple[str, str], list[tuple[str, set[str] | None]]] = {}
        p_desc_map: dict[str, set[str]] = {}
        p_name_map: dict[str, str] = {}
        if p_show_parts:
            p_rules_map, p_desc_map = complexity_visual_part_rules(project_id)
            if "Part name" in target_feature_displays:
                p_df = project_table("parts", project_id)
                if not p_df.empty:
                    for r_pn, r_desc in zip(p_df["part_number"], p_df["description"]):
                        pk = str(r_pn or "").strip().upper()
                        pn_val = str(r_desc or "").strip()
                        if pk and (pk not in p_name_map or (pn_val and not p_name_map[pk])):
                            p_name_map[pk] = pn_val

        def _p_box_part_lines(m_parts: list[str], p_modes: list[str]) -> list[str]:
            if p_modes == ["Part number"]:
                return [escape(pn) for pn in m_parts]
            if p_modes == ["Part name"]:
                return [
                    escape(lbl)
                    for lbl in dict.fromkeys(
                        p_name_map.get(pn.upper(), "") or "Part name not defined"
                        for pn in m_parts
                    )
                ]
            p_lines: list[str] = []
            for pn in m_parts:
                p_nm = p_name_map.get(pn.upper(), "") or "Part name not defined"
                for md in p_modes:
                    if md == "Part number":
                        p_lines.append(escape(pn))
                    elif md == "Part name":
                        p_lines.append(escape(p_nm))
            return p_lines

        print_spec_features: list[dict[str, str]] = []
        print_spec_columns: list[dict[str, object]] = [
            {
                "groupKey": "|".join(str(m) for m in grp["model_numbers"]),
                "modelNumbers": [str(m) for m in grp["model_numbers"]],
                "modelHeaderHtml": "<br>".join(lns),
                "cells": [],
            }
            for grp, lns in zip(p_groups, grp_lbl_lines)
        ]

        out_html = [
            f'<div class="complexity-visual-grid" style="display:grid;grid-template-columns:{g_tmpl};'
            'gap:10px 8px;align-items:center;">',
            '<div style="font-weight:700;color:#0f172a;">Model</div>',
        ]
        for lns in grp_lbl_lines:
            m_lbls = "<br>".join(lns)
            out_html.append(
                '<div class="print-model-col-header" style="font-weight:700;line-height:1.45;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;color:#0f172a;background:#ffffff;'
                f'border:2px solid #000;border-radius:4px;padding:6px 8px;min-height:{m_hdr_height}px;height:100%;'
                'box-sizing:border-box;display:flex;align-items:center;'
                'justify-content:center;text-align:center;">'
                f"{m_lbls}</div>"
            )
        out_html.append("<div></div>")
        out_html.extend(
            '<div style="height:12px;width:0;border-left:2px solid #475569;margin:auto;"></div>'
            for _ in p_groups
        )

        r_hues = [220, 145, 35, 295, 5, 180, 75, 255, 330, 110]
        f_cnt = len(p_features)
        for f_idx, (_, f_row) in enumerate(p_features.iterrows()):
            fid = str(f_row["id"])
            p_base_hue = r_hues[f_idx % len(r_hues)]
            f_choices = [
                str(c).strip()
                for c in json.loads(f_row["allowed_values"] or "[]")
                if str(c).strip()
            ]
            c_by_choice = {
                c: _hsl_to_hex(p_base_hue, 65, max(38, 92 - idx * 8))
                for idx, c in enumerate(f_choices)
            }
            f_name = str(f_row["name"]).strip()
            f_cat = str(f_row.get("category") or "").strip()
            f_row_lbl = (
                f"{f_cat} · {f_name}"
                if len(target_categories) > 1 and f_cat
                else f_name
            )
            out_html.append(
                f'<div style="font-weight:700;color:#0f172a;">{escape(f_row_lbl)}</div>'
            )
            f_vals: list[str] = []
            g_parts_col: list[list[str]] = []
            for grp in p_groups:
                m_id = grp["model_ids"][0]
                v_raw = visual_tree.at[m_id, fid]
                s_val = "" if pd.isna(v_raw) else str(v_raw).strip()
                f_vals.append(s_val)
                if s_val and s_val not in c_by_choice:
                    ex_i = len(c_by_choice)
                    c_by_choice[s_val] = _hsl_to_hex(p_base_hue, 65, max(38, 92 - ex_i * 8))
                    f_choices.append(s_val)
                if p_show_parts and s_val:
                    g_models = {str(m).strip() for m in grp.get("model_numbers", []) if str(m).strip()}
                    raw_m = [
                        pn
                        for pn, app_m in p_rules_map.get((fid, s_val), [])
                        if app_m is None or bool(g_models & app_m)
                    ]
                    g_parts_col.append(deduplicate_visual_box_parts(raw_m, p_desc_map))
                else:
                    g_parts_col.append([])

            print_spec_features.append(
                {
                    "id": fid,
                    "rowLabelHtml": escape(f_row_lbl),
                    "choices": [
                        {
                            "value": ch_v,
                            "defaultBg": c_by_choice.get(ch_v, "#f1f5f9"),
                            "defaultText": "#ffffff" if ch_i >= 4 else "#17324d",
                        }
                        for ch_i, ch_v in enumerate(f_choices)
                    ],
                }
            )

            for col_i, s_val in enumerate(f_vals):
                m_parts = g_parts_col[col_i]
                bg = c_by_choice.get(s_val, "#f1f5f9")
                c_i = f_choices.index(s_val) if s_val in f_choices else -1
                txt_col = "#ffffff" if c_i >= 4 else "#17324d"
                if not s_val:
                    txt_col = "#64748b"
                    box_lbl = escape("Not assigned")
                elif target_feature_displays == ["Feature"]:
                    box_lbl = escape(s_val)
                elif "Feature" not in target_feature_displays:
                    if m_parts:
                        box_lbl = "<br>".join(_p_box_part_lines(m_parts, target_feature_displays))
                    else:
                        txt_col = "#64748b"
                        box_lbl = escape("No parts assigned")
                else:
                    p_modes = [
                        m for m in target_feature_displays if m in ("Part number", "Part name")
                    ]
                    f_between = (
                        len(p_modes) == 2 and target_feature_displays.index("Feature") == 1
                    )
                    segs: list[str] = []
                    emitted = False
                    for d_mode in target_feature_displays:
                        if d_mode == "Feature":
                            segs.append(escape(s_val))
                        elif not m_parts:
                            if not emitted:
                                segs.append(
                                    f'<span style="font-weight:400;opacity:0.8;">{escape("No parts assigned")}</span>'
                                )
                                emitted = True
                        elif f_between:
                            m_lns = _p_box_part_lines(m_parts, [d_mode])
                            segs.append(f'<span style="font-weight:400;">{"<br>".join(m_lns)}</span>')
                        elif not emitted:
                            c_lns = _p_box_part_lines(m_parts, p_modes)
                            segs.append(f'<span style="font-weight:400;">{"<br>".join(c_lns)}</span>')
                            emitted = True
                    box_lbl = "<br>".join(segs)
                merge_k = (
                    f"{s_val}::{'|'.join(m_parts)}"
                    if p_show_parts
                    else s_val
                )
                print_spec_columns[col_i]["cells"].append(
                    {
                        "featureId": fid,
                        "choiceValue": s_val,
                        "mergeKey": merge_k,
                        "background": bg,
                        "defaultBackground": bg,
                        "textColor": txt_col,
                        "defaultTextColor": txt_col,
                        "labelHtml": box_lbl,
                    }
                )

            st_idx = 0
            while st_idx < len(f_vals):
                end_idx = st_idx + 1
                while (
                    end_idx < len(f_vals)
                    and print_spec_columns[end_idx]["cells"][f_idx]["mergeKey"]
                    == print_spec_columns[st_idx]["cells"][f_idx]["mergeKey"]
                ):
                    end_idx += 1
                c_info = print_spec_columns[st_idx]["cells"][f_idx]
                out_html.append(
                    f'<div style="grid-column:span {end_idx - st_idx};background:{c_info["background"]};'
                    'border-radius:8px;padding:10px 12px;text-align:center;display:flex;'
                    'align-items:center;justify-content:center;line-height:1.45;overflow-wrap:anywhere;'
                    f'color:{c_info["textColor"]};-webkit-print-color-adjust:exact;print-color-adjust:exact;"><strong>{c_info["labelHtml"]}</strong></div>'
                )
                st_idx = end_idx
            if f_idx < f_cnt - 1:
                out_html.append("<div></div>")
                out_html.extend(
                    '<div style="height:12px;width:0;border-left:2px solid #475569;margin:auto;"></div>'
                    for _ in p_groups
                )
        out_html.append("<div></div>")
        out_html.extend(
            '<div style="height:12px;width:0;border-left:2px solid #475569;margin:auto;"></div>'
            for _ in p_groups
        )
        out_html.append('<div style="font-weight:700;color:#0f172a;">Model</div>')
        for lns in grp_lbl_lines:
            m_lbls = "<br>".join(lns)
            out_html.append(
                '<div class="print-model-col-header" style="font-weight:700;line-height:1.45;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;color:#0f172a;background:#ffffff;'
                f'border:2px solid #000;border-radius:4px;padding:6px 8px;min-height:{m_hdr_height}px;height:100%;'
                'box-sizing:border-box;display:flex;align-items:center;'
                'justify-content:center;text-align:center;">'
                f"{m_lbls}</div>"
            )
        out_html.append("</div>")
        print_spec_b64 = base64.b64encode(
            json.dumps(
                {
                    "projectId": str(project_id),
                    "gridTemplate": g_tmpl,
                    "modelHeaderHeight": m_hdr_height,
                    "features": print_spec_features,
                    "columns": print_spec_columns,
                }
            ).encode("utf-8")
        ).decode("ascii")
        return (
            f'<div class="print-complexity-grid-host" data-print-spec-b64="{print_spec_b64}">'
            + "".join(out_html)
            + "</div>"
        )

    def _render_printable_complexity_tree_deck(
        pages_spec: list[tuple[str, str]],
        *,
        paper_size: str,
        project_name: str,
        model_labels_desc: str,
        feature_displays_desc: str,
    ) -> str:
        page_w_in = "17in" if paper_size == "tabloid" else "11in"
        page_h_in = "11in" if paper_size == "tabloid" else "8.5in"
        page_css_size = "17in 11in" if paper_size == "tabloid" else "11in 8.5in"
        total_p = len(pages_spec)
        sheets_html: list[str] = []
        for idx, (cat_label, grid_markup) in enumerate(pages_spec, start=1):
            page_badge = f"Page {idx} of {total_p}" if total_p > 1 else "Page 1 of 1"
            sheets_html.append(
                f"""<section class="print-sheet">
  <header class="print-sheet-header">
    <div>
      <div class="print-sheet-title">{escape(project_name)} — Complexity Tree Visual</div>
      <div class="print-sheet-subtitle">Category: <strong>{escape(cat_label)}</strong> &nbsp;&bull;&nbsp; Model label: {escape(model_labels_desc)} &nbsp;&bull;&nbsp; Display: {escape(feature_displays_desc)}</div>
    </div>
    <div class="print-sheet-badge">{escape(page_badge)}</div>
  </header>
  <div class="print-sheet-body">
    <div class="print-tree-stage">{grid_markup}</div>
  </div>
</section>"""
            )
        joined_sheets = "\n".join(sheets_html)
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{escape(project_name)} - Complexity Tree Visual</title>
<style>
  @page {{
    size: {page_css_size};
    margin: 0.3in;
  }}
  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    color-adjust: exact !important;
  }}
  html, body {{
    margin: 0;
    padding: 0;
    background: #f8fafc;
    color: #0f172a;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .print-sheet {{
    background: #ffffff;
    width: calc({page_w_in} - 0.6in);
    min-height: calc({page_h_in} - 0.6in);
    margin: 12px auto;
    padding: 14px 18px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    page-break-after: always;
    break-after: page;
    overflow: hidden;
  }}
  .print-sheet:last-child {{
    page-break-after: auto;
    break-after: auto;
  }}
  .print-sheet-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2px solid #0f172a;
    padding-bottom: 8px;
    flex: 0 0 auto;
  }}
  .print-sheet-title {{
    font-size: 1.15rem;
    font-weight: 800;
    color: #0f172a;
  }}
  .print-sheet-subtitle {{
    font-size: 0.84rem;
    color: #334155;
    margin-top: 2px;
  }}
  .print-sheet-badge {{
    font-size: 0.8rem;
    font-weight: 700;
    color: #334155;
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 999px;
    padding: 4px 10px;
    white-space: nowrap;
  }}
  .print-sheet-body {{
    flex: 1 1 auto;
    display: flex;
    align-items: flex-start;
    justify-content: stretch;
    width: 100%;
    overflow: hidden;
  }}
  .print-tree-stage {{
    width: 100%;
    transform-origin: top left;
  }}
  .print-model-col-header {{
    white-space: nowrap !important;
    word-break: keep-all !important;
    overflow-wrap: normal !important;
  }}
  @media print {{
    html, body {{
      background: #ffffff !important;
    }}
    .print-sheet {{
      margin: 0 !important;
      border: none !important;
      border-radius: 0 !important;
      width: 100% !important;
      height: calc({page_h_in} - 0.6in) !important;
      min-height: 0 !important;
      padding: 4px 6px !important;
    }}
  }}
</style>
</head>
<body>
{joined_sheets}
<script>
  function decodePrintSpec(b64) {{
    try {{
      return JSON.parse(
        new TextDecoder().decode(
          Uint8Array.from(atob(b64), function(c) {{
            return c.charCodeAt(0);
          }})
        )
      );
    }} catch (e) {{
      return null;
    }}
  }}

  function resolveSavedModelOrderForPrint(projId) {{
    if (!projId) return null;
    try {{
      if (Array.isArray(window.__paagPrintCustomModelOrder) && window.__paagPrintCustomModelOrder.length > 0) {{
        return window.__paagPrintCustomModelOrder;
      }}
    }} catch (e) {{}}
    try {{
      const winCandidates = [window];
      if (window.parent && window.parent !== window) winCandidates.push(window.parent);
      if (window.opener && window.opener !== window) winCandidates.push(window.opener);
      for (let i = 0; i < winCandidates.length; i++) {{
        const w = winCandidates[i];
        if (w && w.__paagComplexityTreeColOrderByProject && Array.isArray(w.__paagComplexityTreeColOrderByProject[projId]) && w.__paagComplexityTreeColOrderByProject[projId].length > 0) {{
          return w.__paagComplexityTreeColOrderByProject[projId];
        }}
      }}
    }} catch (e) {{}}
    try {{
      const raw = sessionStorage.getItem("paag_ct_col_order_" + projId) || localStorage.getItem("paag_ct_col_order_" + projId);
      if (raw) {{
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }}
    }} catch (e) {{}}
    return null;
  }}

  function resolveSavedColorsForPrint(projId) {{
    if (!projId) return null;
    try {{
      if (window.__paagPrintCustomColors && typeof window.__paagPrintCustomColors === "object") {{
        return window.__paagPrintCustomColors;
      }}
    }} catch (e) {{}}
    try {{
      const winCandidates = [window];
      if (window.parent && window.parent !== window) winCandidates.push(window.parent);
      if (window.opener && window.opener !== window) winCandidates.push(window.opener);
      for (let i = 0; i < winCandidates.length; i++) {{
        const w = winCandidates[i];
        if (w && w.__paagComplexityTreeColorsByProject && w.__paagComplexityTreeColorsByProject[projId]) {{
          return w.__paagComplexityTreeColorsByProject[projId];
        }}
      }}
    }} catch (e) {{}}
    try {{
      const raw = sessionStorage.getItem("paag_ct_colors_" + projId) || localStorage.getItem("paag_ct_colors_" + projId);
      if (raw) {{
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") return parsed;
      }}
    }} catch (e) {{}}
    return null;
  }}

  function printNormalizeHex(val, fallback) {{
    const fb = fallback || "#ffffff";
    if (!val || typeof val !== "string") return fb;
    const s = val.trim();
    if (/^#[0-9a-fA-F]{{6}}$/.test(s)) return s.toLowerCase();
    if (/^#[0-9a-fA-F]{{3}}$/.test(s)) {{
      return ("#" + s[1] + s[1] + s[2] + s[2] + s[3] + s[3]).toLowerCase();
    }}
    return fb;
  }}

  function printHexToRgb(hex) {{
    const clean = printNormalizeHex(hex, "#ffffff").slice(1);
    return {{
      r: parseInt(clean.slice(0, 2), 16),
      g: parseInt(clean.slice(2, 4), 16),
      b: parseInt(clean.slice(4, 6), 16),
    }};
  }}

  function printContrastText(hexBg, darkFallback) {{
    const rgb = printHexToRgb(hexBg);
    const lum = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255;
    return lum < 0.57 ? "#ffffff" : (darkFallback || "#17324d");
  }}

  function printHexToHsl(hex) {{
    const rgb = printHexToRgb(hex);
    const r = rgb.r / 255, g = rgb.g / 255, b = rgb.b / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h = 0, s = 0;
    const l = (max + min) / 2;
    if (max !== min) {{
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {{
        case r: h = (g - b) / d + (g < b ? 6 : 0); break;
        case g: h = (b - r) / d + 2; break;
        case b: h = (r - g) / d + 4; break;
      }}
      h /= 6;
    }}
    return {{ h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) }};
  }}

  function printHslToHex(hDeg, sPct, lPct) {{
    const h = ((hDeg % 360) + 360) % 360 / 360;
    const s = Math.max(0, Math.min(100, sPct)) / 100;
    const l = Math.max(0, Math.min(100, lPct)) / 100;
    let r, g, b;
    if (s === 0) {{
      r = g = b = l;
    }} else {{
      const hue2rgb = function(p, q, t) {{
        if (t < 0) t += 1;
        if (t > 1) t -= 1;
        if (t < 1 / 6) return p + (q - p) * 6 * t;
        if (t < 1 / 2) return q;
        if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
        return p;
      }};
      const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
      const p = 2 * l - q;
      r = hue2rgb(p, q, h + 1 / 3);
      g = hue2rgb(p, q, h);
      b = hue2rgb(p, q, h - 1 / 3);
    }}
    const toHex = function(x) {{
      const str = Math.round(x * 255).toString(16);
      return str.length === 1 ? "0" + str : str;
    }};
    return "#" + toHex(r) + toHex(g) + toHex(b);
  }}

  function printResolveModelColor(col, customColors) {{
    const modelsMap = (customColors && customColors.models) || {{}};
    let chosenHex = modelsMap[col.groupKey] || null;
    if (!chosenHex && Array.isArray(col.modelNumbers)) {{
      for (let i = 0; i < col.modelNumbers.length; i++) {{
        const mKey = "model::" + String(col.modelNumbers[i]);
        if (modelsMap[mKey]) {{ chosenHex = modelsMap[mKey]; break; }}
      }}
    }}
    if (!chosenHex && modelsMap["__all__"]) chosenHex = modelsMap["__all__"];
    if (chosenHex) {{
      const bg = printNormalizeHex(chosenHex, "#ffffff");
      return {{ bg: bg, text: printContrastText(bg, "#0f172a") }};
    }}
    return {{ bg: "#ffffff", text: "#0f172a" }};
  }}

  function printResolveFeatureCellColor(feat, cell, customColors) {{
    const choicesMap = (customColors && customColors.choices) || {{}};
    const featuresMap = (customColors && customColors.features) || {{}};
    const featureShadesMap = (customColors && customColors.featureShades) || {{}};
    const cVal = cell.choiceValue || "";
    const cKey = String(feat.id) + "::" + String(cVal);
    if (cVal && choicesMap[cKey]) {{
      const bg = printNormalizeHex(choicesMap[cKey], cell.background || "#f1f5f9");
      return {{ bg: bg, text: printContrastText(bg, "#17324d") }};
    }}
    if (cVal && Array.isArray(featureShadesMap[feat.id]) && featureShadesMap[feat.id].length > 0) {{
      const featChoices = Array.isArray(feat.choices) ? feat.choices : [];
      let chIdx = 0;
      for (let i = 0; i < featChoices.length; i++) {{
        if (featChoices[i].value === cVal) {{ chIdx = i; break; }}
      }}
      const shades = featureShadesMap[feat.id];
      const bg = printNormalizeHex(shades[chIdx % shades.length], cell.background || "#f1f5f9");
      return {{ bg: bg, text: printContrastText(bg, "#17324d") }};
    }}
    if (cVal && featuresMap[feat.id]) {{
      const featChoices = Array.isArray(feat.choices) ? feat.choices : [];
      let chIdx = 0;
      for (let i = 0; i < featChoices.length; i++) {{
        if (featChoices[i].value === cVal) {{ chIdx = i; break; }}
      }}
      const hsl = printHexToHsl(featuresMap[feat.id]);
      const totalCh = Math.max(2, featChoices.length);
      const shaded = totalCh <= 1
        ? printNormalizeHex(featuresMap[feat.id], "#dbeafe")
        : printHslToHex(hsl.h, hsl.s < 12 ? hsl.s : Math.max(42, Math.min(85, hsl.s)), Math.max(38, Math.min(92, 90 - chIdx * 8)));
      return {{ bg: shaded, text: printContrastText(shaded, "#17324d") }};
    }}
    return {{ bg: cell.defaultBackground || cell.background, text: cell.defaultTextColor || cell.textColor }};
  }}

  function applySavedOrderToPrintGrids() {{
    const hosts = document.querySelectorAll(".print-complexity-grid-host[data-print-spec-b64]");
    hosts.forEach(function(host) {{
      const spec = decodePrintSpec(host.getAttribute("data-print-spec-b64") || "");
      if (!spec || !Array.isArray(spec.columns) || spec.columns.length === 0) return;
      const savedOrder = resolveSavedModelOrderForPrint(spec.projectId);
      const savedColors = resolveSavedColorsForPrint(spec.projectId);
      const hasColors = Boolean(
        savedColors && (
          Object.keys(savedColors.models || {{}}).length > 0 ||
          Object.keys(savedColors.features || {{}}).length > 0 ||
          Object.keys(savedColors.featureShades || {{}}).length > 0 ||
          Object.keys(savedColors.choices || {{}}).length > 0
        )
      );
      if ((!savedOrder || savedOrder.length === 0) && !hasColors) return;

      let cols = spec.columns.map(function(col, idx) {{
        return Object.assign({{}}, col, {{ defaultIndex: idx }});
      }});
      if (savedOrder && savedOrder.length > 0) {{
        const rankMap = new Map();
        savedOrder.forEach(function(mNum, idx) {{
          if (!rankMap.has(String(mNum))) rankMap.set(String(mNum), idx);
        }});
        cols = cols.sort(function(a, b) {{
          let rankA = Infinity;
          (a.modelNumbers || []).forEach(function(m) {{
            const r = rankMap.get(String(m));
            if (r !== undefined && r < rankA) rankA = r;
          }});
          let rankB = Infinity;
          (b.modelNumbers || []).forEach(function(m) {{
            const r = rankMap.get(String(m));
            if (r !== undefined && r < rankB) rankB = r;
          }});
          if (rankA !== rankB) return rankA - rankB;
          return a.defaultIndex - b.defaultIndex;
        }});
      }}

      const totalCols = cols.length;
      const hdrH = Number(spec.modelHeaderHeight) || 42;
      const html = [];
      html.push(
        '\\x3cdiv class="complexity-visual-grid" style="display:grid;grid-template-columns:' +
        spec.gridTemplate +
        ';gap:10px 8px;align-items:center;">'
      );

      const appendModelRow = function() {{
        html.push('\\x3cdiv style="font-weight:700;color:#0f172a;">Model\\x3c/div>');
        cols.forEach(function(col) {{
          const mCol = printResolveModelColor(col, savedColors);
          html.push(
            '\\x3cdiv class="print-model-col-header" style="font-weight:700;line-height:1.45;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;color:' + mCol.text + ';background:' + mCol.bg + ';' +
            'border:2px solid #000;border-radius:4px;padding:6px 8px;min-height:' + hdrH + 'px;height:100%;' +
            'box-sizing:border-box;display:flex;align-items:center;justify-content:center;text-align:center;">' +
            col.modelHeaderHtml + '\\x3c/div>'
          );
        }});
      }};

      const appendConnectorRow = function() {{
        html.push('\\x3cdiv>\\x3c/div>');
        for (let i = 0; i < totalCols; i++) {{
          html.push('\\x3cdiv style="height:12px;width:0;border-left:2px solid #475569;margin:auto;">\\x3c/div>');
        }}
      }};

      appendModelRow();
      appendConnectorRow();

      const features = spec.features || [];
      for (let fIdx = 0; fIdx < features.length; fIdx++) {{
        const feat = features[fIdx];
        html.push('\\x3cdiv style="font-weight:700;color:#0f172a;">' + feat.rowLabelHtml + '\\x3c/div>');
        let start = 0;
        while (start < totalCols) {{
          let end = start + 1;
          const baseCell = cols[start].cells[fIdx];
          while (
            end < totalCols &&
            cols[end].cells[fIdx] &&
            cols[end].cells[fIdx].mergeKey === baseCell.mergeKey
          ) {{
            end += 1;
          }}
          const span = end - start;
          const cellCol = printResolveFeatureCellColor(feat, baseCell, savedColors);
          html.push(
            '\\x3cdiv style="grid-column:span ' + span + ';background:' + cellCol.bg + ';' +
            'border-radius:8px;padding:10px 12px;text-align:center;display:flex;' +
            'align-items:center;justify-content:center;line-height:1.45;overflow-wrap:anywhere;' +
            'color:' + cellCol.text + ';-webkit-print-color-adjust:exact;print-color-adjust:exact;">\\x3cstrong>' + baseCell.labelHtml + '\\x3c/strong>\\x3c/div>'
          );
          start = end;
        }}
        if (fIdx < features.length - 1) {{
          appendConnectorRow();
        }}
      }}

      appendConnectorRow();
      appendModelRow();
      html.push('\\x3c/div>');
      host.innerHTML = html.join("");
    }});
  }}

  function fitComplexitySheets() {{
    applySavedOrderToPrintGrids();
    const sheets = document.querySelectorAll('.print-sheet');
    sheets.forEach(function(sheet) {{
      const body = sheet.querySelector('.print-sheet-body');
      const stage = sheet.querySelector('.print-tree-stage');
      if (!body || !stage) return;
      stage.style.zoom = '1';
      stage.style.width = '100%';
      const availW = body.clientWidth || 980;
      const headerEl = sheet.querySelector('.print-sheet-header');
      const availH = (sheet.clientHeight - (headerEl ? headerEl.offsetHeight : 50) - 28) || 680;
      const naturalW = stage.scrollWidth || availW;
      const naturalH = stage.scrollHeight || availH;
      const scaleW = naturalW > availW ? availW / naturalW : 1;
      const scaleH = naturalH > availH ? availH / naturalH : 1;
      const scale = Math.min(scaleW, scaleH, 1);
      if (scale < 0.995) {{
        stage.style.zoom = String(Math.max(0.35, scale));
      }}
    }});
  }}
  fitComplexitySheets();
  window.addEventListener('load', function() {{ setTimeout(fitComplexitySheets, 60); }});
  window.addEventListener('resize', fitComplexitySheets);
  window.addEventListener('beforeprint', fitComplexitySheets);
</script>
</body>
</html>"""

    @st.dialog("Print Complexity Tree Visual", width="large")
    def print_complexity_tree_visual_dialog() -> None:
        _, close_col = st.columns([5.0, 1.4])
        with close_col:
            if st.button(
                "Close Print View",
                icon=":material/close:",
                width="stretch",
                key=f"close_complexity_print_dlg_{project_id}",
            ):
                st.session_state[f"complexity_tree_print_active_{project_id}"] = False
                st.rerun()

        st.markdown("#### Export and Print Settings")
        col_scope, col_fmt = st.columns([1.5, 1.2])

        with col_scope:
            scope_options: list[str] = []
            if selected_categories:
                scope_options.append(
                    f"Current visual selection ({', '.join(selected_categories)})"
                )
            scope_options.append(
                f"All active categories — 1 page per category ({len(category_values)} page{'s' if len(category_values) != 1 else ''})"
            )
            scope_options.append(
                f"All active categories — combined on 1 page ({len(category_values)} categor{'ies' if len(category_values) != 1 else 'y'})"
            )
            scope_options.append("Select specific categories...")

            chosen_scope = st.radio(
                "Print Selection",
                scope_options,
                index=0,
                key=f"complexity_print_scope_{project_id}",
                help="Choose whether to print your current category selection, each category on its own page, or all categories combined.",
            )

            custom_cats: list[str] = []
            custom_combine = False
            if "Select specific categories" in chosen_scope:
                custom_cats = st.multiselect(
                    "Categories to include",
                    options=category_values,
                    default=selected_categories or category_values[:1],
                    key=f"complexity_print_custom_cats_{project_id}",
                )
                layout_mode = st.radio(
                    "Category Page Layout",
                    ["One page per category", "Combine selected categories on one page"],
                    index=0,
                    key=f"complexity_print_custom_layout_{project_id}",
                )
                custom_combine = "Combine" in layout_mode

        with col_fmt:
            format_choice = st.radio(
                "Page Format",
                ["8.5 × 11 in (Letter Landscape)", "11 × 17 in (Tabloid Landscape)"],
                index=0,
                key=f"complexity_print_fmt_{project_id}",
                help="8.5×11 Letter is standard printer paper. 11×17 Tabloid gives extra horizontal room for many model columns.",
            )
            paper_size = "letter" if "8.5 × 11" in format_choice else "tabloid"

            default_m_labels = (
                selected_model_labels
                if selected_model_labels
                else ["Model name", "Model number"]
            )
            print_model_labels = st.multiselect(
                "Model label in print",
                options=visual_model_label_options,
                default=default_m_labels,
                key=f"complexity_print_model_labels_{project_id}",
            )
            default_f_displays = (
                selected_feature_displays
                if selected_feature_displays
                else ["Feature"]
            )
            print_feature_displays = st.multiselect(
                "Feature display in print",
                options=visual_feature_display_options,
                default=default_f_displays,
                key=f"complexity_print_feature_displays_{project_id}",
            )

        if not print_model_labels:
            st.warning("Select at least one Model label option to generate the print view.")
            return
        if not print_feature_displays:
            st.warning("Select at least one Feature display option to generate the print view.")
            return

        pages_to_build: list[list[str]] = []
        if chosen_scope.startswith("Current visual selection"):
            pages_to_build = [selected_categories] if selected_categories else []
        elif "1 page per category" in chosen_scope:
            pages_to_build = [[cat] for cat in category_values]
        elif "combined on 1 page" in chosen_scope:
            pages_to_build = [category_values] if category_values else []
        else:
            clean_custom = [c for c in custom_cats if c in category_values]
            if custom_combine:
                pages_to_build = [clean_custom] if clean_custom else []
            else:
                pages_to_build = [[cat] for cat in clean_custom]

        pages_spec: list[tuple[str, str]] = []
        for cat_group in pages_to_build:
            g_html = _build_complexity_tree_grid_for_print(
                cat_group, print_model_labels, print_feature_displays
            )
            if g_html:
                pages_spec.append((", ".join(cat_group), g_html))

        if not pages_spec:
            st.warning("No Complexity tree visual pages match the selected categories.")
            return

        proj_row = get_project(project_id) or {}
        project_name = str(proj_row.get("name") or "Project").strip()
        full_deck_html = _render_printable_complexity_tree_deck(
            pages_spec,
            paper_size=paper_size,
            project_name=project_name,
            model_labels_desc=", ".join(print_model_labels),
            feature_displays_desc=", ".join(print_feature_displays),
        )
        total_pages_cnt = len(pages_spec)
        paper_label = (
            "8.5 × 11 in (Letter Landscape)"
            if paper_size == "letter"
            else "11 × 17 in (Tabloid Landscape)"
        )
        st.info(
            f"Ready to print **{total_pages_cnt} page{'s' if total_pages_cnt != 1 else ''}** on **{paper_label}**"
        )

        scope_sig = f"{chosen_scope}_{paper_size}_{','.join(print_model_labels)}_{','.join(print_feature_displays)}_{total_pages_cnt}"
        scope_slug = hashlib.md5(scope_sig.encode()).hexdigest()[:8]

        act_col1, act_col2 = st.columns([1.6, 1.4], vertical_alignment="center")
        with act_col1:
            escaped_deck_html = (
                json.dumps(full_deck_html)
                .replace("</script>", "<\\/script>")
                .replace("</Script>", "<\\/Script>")
            )
            action_btn_html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{
    margin: 0;
    padding: 2px 0;
    background: transparent;
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .btn-print {{
    background: #0284c7;
    color: #ffffff !important;
    text-decoration: none;
    font-size: 0.95rem;
    font-weight: 700;
    padding: 8px 18px;
    border-radius: 6px;
    border: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12);
  }}
  .btn-print:hover {{
    background: #0369a1;
  }}
  .btn-open {{
    background: #f1f5f9;
    color: #0f172a !important;
    text-decoration: none;
    font-size: 0.95rem;
    font-weight: 600;
    padding: 8px 14px;
    border-radius: 6px;
    border: 1px solid #cbd5e1;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }}
  .btn-open:hover {{
    background: #e2e8f0;
  }}
</style>
</head>
<body>
  <button id="btnActionPrint" class="btn-print" title="Opens print preview immediately for 1-click printing or PDF export">
    <span>🖨️</span> Print to PDF / Printer
  </button>
  <button id="btnActionOpen" class="btn-open" title="Open printable complexity tree in a new browser tab">
    <span>↗️</span> Open in New Tab
  </button>
  <script>
    const deckContent = {escaped_deck_html};
    const activeProjectId = {json.dumps(str(project_id))};
    function injectSavedModelOrderIntoDeck(html) {{
      let order = null;
      let colors = null;
      try {{
        const parentWin = window.parent || window;
        if (parentWin.__paagComplexityTreeColOrderByProject && Array.isArray(parentWin.__paagComplexityTreeColOrderByProject[activeProjectId])) {{
          order = parentWin.__paagComplexityTreeColOrderByProject[activeProjectId];
        }}
        if (parentWin.__paagComplexityTreeColorsByProject && parentWin.__paagComplexityTreeColorsByProject[activeProjectId]) {{
          colors = parentWin.__paagComplexityTreeColorsByProject[activeProjectId];
        }}
      }} catch (e) {{}}
      if (!order || order.length === 0) {{
        try {{
          const raw = sessionStorage.getItem("paag_ct_col_order_" + activeProjectId) || localStorage.getItem("paag_ct_col_order_" + activeProjectId);
          if (raw) order = JSON.parse(raw);
        }} catch (e) {{}}
      }}
      if (!colors) {{
        try {{
          const rawC = sessionStorage.getItem("paag_ct_colors_" + activeProjectId) || localStorage.getItem("paag_ct_colors_" + activeProjectId);
          if (rawC) colors = JSON.parse(rawC);
        }} catch (e) {{}}
      }}
      let scriptPayload = "";
      if (Array.isArray(order) && order.length > 0) {{
        scriptPayload += "window.__paagPrintCustomModelOrder = " + JSON.stringify(order) + ";";
      }}
      if (colors && typeof colors === "object") {{
        scriptPayload += "window.__paagPrintCustomColors = " + JSON.stringify(colors) + ";";
      }}
      if (scriptPayload) {{
        return html.replace("<head>", "<head><script>" + scriptPayload + "<\\/script>");
      }}
      return html;
    }}
    document.getElementById("btnActionPrint").onclick = function(e) {{
      e.preventDefault();
      const orderedDeck = injectSavedModelOrderIntoDeck(deckContent);
      const printHtml = orderedDeck.replace('</body>', '<script>window.addEventListener("load", function(){{ setTimeout(function(){{ window.print(); }}, 350); }});<\\/script></body>');
      const blob = new Blob([printHtml], {{ type: "text/html;charset=utf-8" }});
      const blobUrl = URL.createObjectURL(blob);
      const win = window.open(blobUrl, "_blank");
      if (win) win.focus();
    }};
    document.getElementById("btnActionOpen").onclick = function(e) {{
      e.preventDefault();
      const orderedDeck = injectSavedModelOrderIntoDeck(deckContent);
      const blob = new Blob([orderedDeck], {{ type: "text/html;charset=utf-8" }});
      const blobUrl = URL.createObjectURL(blob);
      const win = window.open(blobUrl, "_blank");
      if (win) win.focus();
    }};
  </script>
</body>
</html>"""
            components.html(action_btn_html, height=45)

        with act_col2:
            safe_fn = f"Complexity_Tree_{project_name}_{paper_size}_{total_pages_cnt}_pages.html".replace(" ", "_")
            st.download_button(
                f"Download HTML ({total_pages_cnt} Page{'s' if total_pages_cnt != 1 else ''})",
                data=full_deck_html,
                file_name=safe_fn,
                mime="text/html",
                icon=":material/download:",
                type="secondary",
                key=f"dl_complexity_tree_btn_{project_id}_{scope_slug}",
            )

        st.divider()
        st.caption(f"Preview ({total_pages_cnt} page{'s' if total_pages_cnt != 1 else ''} on {paper_label}):")
        st.html(full_deck_html, unsafe_allow_javascript=True)

    if st.session_state.get(f"complexity_tree_print_active_{project_id}", False):
        print_complexity_tree_visual_dialog()

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
            render_audit_history_table(
                models_history.drop(columns=["details"], errors="ignore"),
                key=f"models_history_table_{project_id}",
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
    with features_history_tab:
        features_history = audit_history(project_id, "Feature definitions", limit=50)
        if features_history.empty:
            st.caption("No feature-definition history has been recorded yet.")
        else:
            render_audit_history_table(
                features_history.drop(columns=["details"], errors="ignore"),
                key=f"features_history_table_{project_id}",
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
    with tree_history_tab:
        tree_history = audit_history(project_id, "Complexity tree", limit=50)
        if tree_history.empty:
            st.caption("No complexity-tree history has been recorded yet.")
        else:
            render_audit_history_table(
                tree_history.drop(columns=["details"], errors="ignore"),
                key=f"complexity_tree_history_table_{project_id}",
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
