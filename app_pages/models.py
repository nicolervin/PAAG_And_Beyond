import json
from html import escape

import pandas as pd
import streamlit as st

from utils.store import (
    _identify_top_level_assembly_pns,
    apply_inferred_part_feature_rules,
    audit_history,
    complexity_feature_delete_impacts,
    complexity_features,
    complexity_planning_snapshot,
    complexity_tree,
    complexity_visual_part_rules,
    deduplicate_visual_box_parts,
    delete_project_models,
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
    has_unsaved_table_changes,
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
        count = update_complexity_features(project_id, merged_features)
        st.session_state[feature_undo_key] = current_complexity_snapshot
        record_audit_event(
            project_id,
            "Feature definitions",
            "Save & Refresh",
            len(changed_features),
            st.session_state.get("current_editor", ""),
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
    if st.session_state.get(f"pending_multi_feature_review_{project_id}"):
        review_multi_feature_applicability_dialog(project_id)
    full_complexity_tree = complexity_tree(project_id)
    tree = full_complexity_tree.loc[
        full_complexity_tree["model_id"].astype(str).isin(active_model_ids)
    ].copy()
    active_feature_ids = active_features["id"].astype(str).tolist()
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
    for _, feature in active_features.iterrows():
        feature_id = str(feature["id"])
        choices = json.loads(feature["allowed_values"] or "[]")
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
        str(f["id"]): f"{f['category']} · {f['name']}"
        for _, f in active_features.iterrows()
    }
    visible_tree = filter_table(
        tree,
        key=f"complexity_tree_filters_{project_id}",
        dropdown_columns=active_feature_ids,
        search_columns=["official_model_number", "common_name", *active_feature_ids],
        labels=feature_filter_labels,
        reset_widget_keys=[tree_editor_key],
    )
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
        pending_tree = pd.DataFrame(pending.get("rows", []))
        changed_assignment_count = int(pending.get("changed_assignment_count", 0))
        count = update_complexity_tree(project_id, pending_tree)
        editor_name = st.session_state.get("current_editor", "")
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
            merged_tree = merge_filtered_edits(
                tree, visible_tree, edited_tree, id_column="model_id"
            )
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
    editable_table_heading("Complexity tree visual")
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
    visual_tree = full_complexity_tree.set_index("model_id")
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
            f"minmax(130px, 1.2fr) repeat({grid_columns}, minmax(90px, 1fr))"
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
        visual_html = [
            f'<div style="display:grid;grid-template-columns:{grid_template};'
            'gap:10px 8px;align-items:center;">',
            '<div style="font-weight:700;">Model</div>',
        ]
        for lines in group_label_lines:
            model_labels = "<br>".join(lines)
            visual_html.append(
                '<div style="font-weight:700;line-height:1.45;overflow-wrap:anywhere;'
                f'border:2px solid #000;border-radius:4px;padding:6px;min-height:{model_header_height}px;height:100%;'
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
            start = 0
            while start < len(values):
                end = start + 1
                while (
                    end < len(values)
                    and values[end] == values[start]
                    and (
                        not show_part_displays
                        or group_parts_by_col[end] == group_parts_by_col[start]
                    )
                ):
                    end += 1
                selected_value = values[start]
                background = color_by_choice.get(selected_value, "#f1f5f9")
                choice_index = choices.index(selected_value) if selected_value in choices else -1
                text_color = "#ffffff" if choice_index >= 4 else "#17324d"
                if not selected_value:
                    text_color = "#64748b"
                    label = escape("Not assigned")
                elif selected_feature_displays == ["Feature"]:
                    label = escape(selected_value)
                elif "Feature" not in selected_feature_displays:
                    matching_parts = group_parts_by_col[start]
                    if matching_parts:
                        label = "<br>".join(
                            _build_box_part_lines(matching_parts, selected_feature_displays)
                        )
                    else:
                        text_color = "#64748b"
                        label = escape("No parts assigned")
                else:
                    matching_parts = group_parts_by_col[start]
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
                    label = "<br>".join(segments)
                visual_html.append(
                    f'<div style="grid-column:span {end - start};background:{background};'
                    'border-radius:8px;padding:10px 12px;text-align:center;display:flex;'
                    'align-items:center;justify-content:center;line-height:1.45;overflow-wrap:anywhere;'
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
        for lines in group_label_lines:
            model_labels = "<br>".join(lines)
            visual_html.append(
                '<div style="font-weight:700;line-height:1.45;overflow-wrap:anywhere;'
                f'border:2px solid #000;border-radius:4px;padding:6px;min-height:{model_header_height}px;height:100%;'
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
