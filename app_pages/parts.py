import json
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.clipboard_image import as_uploaded_file, clipboard_image, decode_clipboard_image
from utils.store import (
    add_part_image,
    audit_history,
    complexity_features,
    delete_project_part,
    get_planning_scenario,
    part_feature_rules,
    part_images,
    part_scenario_activity,
    project_models,
    project_table,
    record_audit_event,
    set_part_image,
    update_part_feature_rules,
    update_part_rows,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    request_table_editor_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    drop_untouched_new_rows,
    editable_table_header,
    native_selected_rows,
    required_field_errors,
    standard_details_column_config,
    sortable_editor_rows,
    table_has_unsaved_changes,
)


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
parts_editor_key = f"parts_catalog_editor_v7_{scenario_id}"
st.title("Parts Catalog")
st.caption(
    "Connect official part numbers to CAD screenshots, revisions, model applicability, and the "
    "parts active in this planning scenario."
)
if not project_id or not scenario_id:
    st.stop()
scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()
st.caption(f"Active scenario: Rev {scenario['revision_label']} · {scenario['name']}")
apply_pending_table_editor_reset(parts_editor_key)

parts = project_table("parts", project_id, "part_number")
models = project_models(project_id)
features = complexity_features(project_id)
active_features = features.loc[features["active"].fillna(1).astype(bool)].copy() if not features.empty else features
rules = part_feature_rules(project_id)
activity_by_part = part_scenario_activity(project_id, scenario_id)
if models.empty:
    active_model_numbers = []
    model_labels = {}
else:
    active_models = models.loc[models["active"].fillna(1).astype(bool)].copy()
    active_model_numbers = active_models["model_number"].fillna("").astype(str).tolist()
    model_labels = {
        str(row["model_number"]): (
            str(row["display_name"]).strip() or "Familiar name not defined"
        )
        for _, row in models.iterrows()
    }


def split_model_applicability(value) -> list[str]:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() == "all":
        return ["All models"]
    if text in model_labels:
        return [text]

    # Official model identifiers can contain commas. Parse against the complete
    # set of defined identifiers before falling back to legacy comma splitting.
    candidates = sorted(model_labels, key=len, reverse=True)

    def parse_remaining(remaining: str) -> list[str] | None:
        for model_number in candidates:
            if remaining == model_number:
                return [model_number]
            prefix = f"{model_number}, "
            if remaining.startswith(prefix):
                parsed_tail = parse_remaining(remaining[len(prefix):])
                if parsed_tail is not None:
                    return [model_number, *parsed_tail]
        return None

    parsed = parse_remaining(text)
    return parsed if parsed is not None else [text]


feature_option_labels: dict[str, str] = {"All models": "All models"}
for _, feature in active_features.iterrows():
    for choice in json.loads(feature["allowed_values"] or "[]"):
        token = f"{feature['id']}::{choice}"
        feature_option_labels[token] = f"{feature['category']} · {feature['name']} = {choice}"
feature_token_by_label = {label: token for token, label in feature_option_labels.items()}
feature_options = list(feature_token_by_label)
rules_by_part: dict[str, list[str]] = {}
if not rules.empty:
    for part_id, part_rules in rules.groupby("part_id", sort=False):
        rules_by_part[str(part_id)] = [
            feature_option_labels.get(
                f"{row['feature_id']}::{row['value']}",
                f"{row['category']} · {row['feature_name']} = {row['value']}",
            )
            for _, row in part_rules.iterrows()
        ]


def readable_feature_applicability(part_id: str, legacy_value) -> str:
    selected = rules_by_part.get(str(part_id), [])
    if selected:
        return "; ".join(selected)
    if str(legacy_value or "").strip().casefold() in {"all", "all models"}:
        return "All models"
    return "Needs feature tagging"


parts_actions = editable_table_header(
    "All parts",
    editor_key=parts_editor_key,
    key_prefix="parts_catalog",
    native_row_selection=True,
)
save_part_table = parts_actions.save_and_refresh
if parts_actions.undo:
    st.session_state.pop(parts_editor_key, None)
    st.toast("Discarded the unsaved part-table edits", icon=":material/undo:")
    st.rerun()
st.caption("Edit catalog fields directly, then save. Select View details on a row to open its photos and full information below.")
editable_columns = ["id", "part_number", "description", "quantity", "revision", "model_applicability", "notes", "source", "image_path", "updated_at"]
parts_for_editing = parts.reindex(columns=editable_columns).copy()
parts_for_editing["active"] = parts_for_editing["id"].apply(
    lambda part_id: activity_by_part.get(str(part_id), True)
).astype(bool)
parts_for_editing["feature_applicability"] = parts_for_editing.apply(
    lambda row: (
        rules_by_part.get(str(row["id"]), [])
        or (["All models"] if str(row["model_applicability"] or "").strip().casefold() in {"all", "all models"} else [])
    ),
    axis=1,
)
parts_for_editing["applicability_status"] = parts_for_editing.apply(
    lambda row: readable_feature_applicability(str(row["id"]), row["model_applicability"]), axis=1
)
parts_for_editing["view_details"] = ":material/visibility: View details"
parts_for_editing["photo_status"] = parts_for_editing["image_path"].apply(
    lambda value: "✅ Added" if str(value or "").strip() else "❌ Missing"
)
parts_for_editing = filter_table(
    parts_for_editing,
    key="part_catalog_filters",
    dropdown_columns=["active", "source", "revision", "photo_status", "applicability_status"],
    search_columns=["part_number", "description", "photo_status", "applicability_status", "notes", "source"],
    labels={
        "active": "Active in scenario",
        "photo_status": "Photo status",
        "applicability_status": "Feature applicability",
    },
    reset_widget_keys=[parts_editor_key],
)
selected_part_key = f"parts_selected_id_{project_id}"


def open_part_details() -> None:
    click = st.session_state.get("parts_view_details")
    if click and 0 <= click["row"] < len(parts_for_editing):
        st.session_state[selected_part_key] = str(parts_for_editing.iloc[click["row"]]["id"])


parts_editor_rows = sortable_editor_rows(
    parts_for_editing,
    defaults={
        "active": True,
        "revision": "0",
        "feature_applicability": ["All models"],
    },
)
edited_parts = st.data_editor(
    parts_editor_rows,
    key=parts_editor_key,
    hide_index=True,
    num_rows="delete",
    height=430,
    disabled=["id", "model_applicability", "photo_status", "applicability_status", "source", "image_path", "updated_at"],
    column_order=["view_details", "active", "photo_status", "part_number", "description", "revision", "feature_applicability", "applicability_status", "notes", "source", "updated_at"],
    column_config={
        "id": None,
        "view_details": standard_details_column_config(on_click=open_part_details, key="parts_view_details"),
        "active": st.column_config.CheckboxColumn(
            "Active",
            default=True,
            help=(
                "Turn off to keep this catalog record but hide it from downstream views in "
                "the active planning scenario."
            ),
        ),
        "photo_status": st.column_config.TextColumn(
            "Photo status",
            help="A green check means a primary CAD image is attached; a red X means it is missing.",
        ),
        "part_number": st.column_config.TextColumn("Part number", required=True),
        "description": st.column_config.TextColumn("Part Name", width="large"),
        "quantity": None,
        "revision": st.column_config.TextColumn("Revision", default="0"),
        "model_applicability": None,
        "image_path": None,
        "feature_applicability": st.column_config.MultiselectColumn(
            "Feature applicability",
            options=feature_options,
            help="Choose All models alone, or feature choices. Within-feature choices are OR; across-feature choices are AND.",
            width="large",
            default=["All models"],
        ),
        "applicability_status": None,
        "notes": st.column_config.TextColumn("Notes", width="large"),
        "source": st.column_config.TextColumn("Source"),
        "updated_at": st.column_config.DatetimeColumn("Updated", format="MMM DD, YYYY HH:mm"),
    },
)
st.caption(
    "Add a part in the blank row, then save. Use View details to manage its Primary CAD image "
    "and additional views."
)

export_columns = [
    "active", "part_number", "description", "revision", "feature_applicability",
    "photo_status", "notes", "source", "updated_at",
]
st.download_button(
    "Export filtered rows",
    data=dataframe_to_excel(parts_for_editing.reindex(columns=export_columns), "Parts"),
    file_name="parts_filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
)

selected_saved_parts = native_selected_rows(parts_for_editing, editor_key=parts_editor_key)
bulk_controls = st.container(horizontal=True, vertical_alignment="bottom")
bulk_applicability = bulk_controls.multiselect(
    "Feature applicability for selected parts",
    options=feature_options,
    placeholder="Choose All models or feature values",
    key="parts_bulk_feature_applicability",
)
apply_bulk_applicability = bulk_controls.button(
    f"Apply to selected ({len(selected_saved_parts)})",
    type="primary",
    icon=":material/checklist:",
    disabled=selected_saved_parts.empty,
)
request_delete_bulk_parts = bulk_controls.button(
    f"Delete selected ({len(selected_saved_parts)})",
    icon=":material/delete:",
    disabled=selected_saved_parts.empty,
    key="destructive_request_parts_bulk_delete",
)

if apply_bulk_applicability:
    if table_has_unsaved_changes(parts_editor_key, native_row_selection=True):
        st.warning("Save or undo other table edits before applying a bulk feature change.")
    elif not bulk_applicability:
        st.warning("Choose All models or at least one feature value.")
    elif "All models" in bulk_applicability and len(bulk_applicability) > 1:
        st.warning("Choose All models by itself, or choose feature values.")
    else:
        try:
            update_part_feature_rules(
                project_id,
                {
                    str(part_id): [feature_token_by_label[label] for label in bulk_applicability]
                    for part_id in selected_saved_parts["id"]
                },
            )
            record_audit_event(
                project_id, "Parts", "Bulk feature edit", len(selected_saved_parts),
                st.session_state.get("current_editor", ""),
                {"feature_applicability": bulk_applicability},
            )
            request_table_editor_reset(parts_editor_key)
            st.toast(f"Updated feature applicability for {len(selected_saved_parts)} parts", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

if request_delete_bulk_parts:
    if table_has_unsaved_changes(parts_editor_key, native_row_selection=True):
        st.warning("Save or undo other table edits before deleting selected parts.")
    else:
        st.session_state.parts_pending_bulk_delete = selected_saved_parts["id"].astype(str).tolist()


@st.dialog("Delete selected parts?")
def confirm_bulk_part_delete() -> None:
    pending_ids = st.session_state.get("parts_pending_bulk_delete", [])
    st.warning(
        f"This will permanently delete {len(pending_ids)} part(s), their photos, and their fishbone uses."
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_bulk_part_delete"):
        st.session_state.pop("parts_pending_bulk_delete", None)
        st.rerun()
    if actions.button(
        "Delete parts",
        type="primary",
        icon=":material/delete:",
        key="destructive_confirm_bulk_part_delete",
    ):
        deleted_labels = [
            delete_project_part(project_id, str(part_id))
            for part_id in pending_ids
        ]
        deleted_ids = set(pending_ids)
        if st.session_state.get(selected_part_key) in deleted_ids:
            st.session_state.pop(selected_part_key, None)
        record_audit_event(
            project_id, "Parts", "Bulk delete", len(deleted_labels),
            st.session_state.get("current_editor", ""), {"part_numbers": deleted_labels},
        )
        st.session_state.pop("parts_pending_bulk_delete", None)
        request_table_editor_reset(parts_editor_key)
        st.toast(f"Deleted {len(deleted_labels)} selected parts and their fishbone uses", icon=":material/delete:")
        st.rerun()


if st.session_state.get("parts_pending_bulk_delete"):
    confirm_bulk_part_delete()

if save_part_table:
    try:
        if not selected_saved_parts.empty:
            raise ValueError("Clear the selected rows before saving table edits. Selection is reserved for bulk actions.")
        edited_parts = drop_untouched_new_rows(
            edited_parts, identifying_columns=["part_number"]
        )
        validation_errors = required_field_errors(edited_parts, {"part_number": "Part number"})
        if validation_errors:
            raise ValueError(" ".join(validation_errors))
        invalid_all = edited_parts["feature_applicability"].apply(
            lambda selected: "All models" in (selected or []) and len(selected or []) > 1
        )
        if invalid_all.any():
            raise ValueError("Choose All models by itself, or choose feature values.")
        missing_rule = edited_parts["feature_applicability"].apply(lambda selected: not (selected or []))
        if missing_rule.any():
            raise ValueError("Every part needs All models or at least one feature choice.")
        parts_to_save = edited_parts.drop(
            columns=["view_details", "active", "photo_status", "feature_applicability", "applicability_status"]
        ).copy()
        new_row_mask = parts_to_save["id"].isna() | parts_to_save["id"].astype(str).str.strip().eq("")
        parts_to_save.loc[new_row_mask, "id"] = [str(uuid4()) for _ in range(int(new_row_mask.sum()))]
        edited_parts = edited_parts.copy()
        edited_parts.loc[new_row_mask, "id"] = parts_to_save.loc[new_row_mask, "id"]
        parts_to_save.loc[new_row_mask, "quantity"] = 1
        parts_to_save.loc[new_row_mask, "model_applicability"] = "All"
        parts_to_save.loc[new_row_mask, "source"] = "Manual"
        count = update_part_rows(
            project_id,
            parts_to_save,
            scenario_id=scenario_id,
            activity_by_part={
                str(row["id"]): (
                    True
                    if row.get("active") is None or pd.isna(row.get("active"))
                    else bool(row.get("active"))
                )
                for _, row in edited_parts.iterrows()
            },
        )
        update_part_feature_rules(
            project_id,
            {
                str(row["id"]): [
                    feature_token_by_label[label]
                    for label in (row["feature_applicability"] or [])
                    if label in feature_token_by_label
                ]
                for _, row in edited_parts.iterrows()
            },
        )
        record_audit_event(
            project_id,
            "Parts",
            "Save & refresh",
            count,
            st.session_state.get("current_editor", ""),
            {"scenario_id": scenario_id},
        )
        request_table_editor_reset(parts_editor_key)
        st.toast(f"Saved {count} parts", icon=":material/check_circle:")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

def render_parts_history() -> None:
    """Render Parts history at the bottom of the current page state."""
    with st.expander("Parts history", icon=":material/history:"):
        history = audit_history(project_id, "Parts", limit=50)
        if history.empty:
            st.caption("No standardized Parts-table changes have been recorded yet.")
        else:
            st.dataframe(
                history.drop(columns=["details"], errors="ignore"),
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

if parts.empty:
    st.info("Add the first part in the blank row above, then select Save part table.")
    render_parts_history()
    st.stop()

valid_part_ids = set(parts["id"].astype(str))
if st.session_state.get(selected_part_key) not in valid_part_ids:
    st.session_state[selected_part_key] = str(parts.iloc[0]["id"])
part = parts.loc[parts["id"].astype(str) == st.session_state[selected_part_key]].iloc[0].to_dict()
part_name = str(part.get("description") or "").strip()
part_details_title = f"Part Details · {part['part_number']}"
if part_name:
    part_details_title += f" {part_name}"
st.subheader(part_details_title)
image_col, details_col = st.columns([2, 3])
with image_col.container(border=True):
    st.subheader("Primary CAD image")
    image_path = Path(part["image_path"]) if part.get("image_path") else None
    if image_path and image_path.exists():
        st.image(str(image_path), caption=part["part_number"])
    else:
        st.caption("No image attached.")
    uploaded = st.file_uploader("Attach screenshot or rendered view", type=["png", "jpg", "jpeg", "webp"], key=f"image_{part['id']}")
    if uploaded and st.button("Save image", type="primary", icon=":material/upload:"):
        set_part_image(part["id"], uploaded)
        st.toast("Image attached", icon=":material/check_circle:")
        st.rerun()

    st.caption(
        "Or press Win+Shift+S, select a region, and paste it here. "
        "It saves immediately as the Primary CAD image."
    )
    primary_clipboard_key = f"clipboard_primary_{part['id']}"
    primary_pending_key = f"pending_primary_{part['id']}"
    st.session_state.pop(primary_pending_key, None)
    pasted = clipboard_image(key=primary_clipboard_key)
    pasted_payload = getattr(pasted, "image", None)
    if pasted_payload:
        try:
            primary_image = decode_clipboard_image(pasted_payload)
            set_part_image(part["id"], as_uploaded_file(primary_image))
            record_audit_event(
                project_id,
                "Parts",
                "Paste Primary CAD image",
                1,
                st.session_state.get("current_editor", ""),
                {"part_id": str(part["id"])},
            )
            st.toast(
                "Screenshot saved as the Primary CAD image",
                icon=":material/check_circle:",
            )
            st.rerun()
        except (OSError, ValueError) as exc:
            st.error(str(exc))

    st.subheader("Additional views")
    images = part_images(part["id"])
    for supplemental in images:
        supplemental_path = Path(supplemental["image_path"])
        if supplemental_path.exists():
            st.image(str(supplemental_path), caption=supplemental["caption"] or supplemental["image_type"])
    with st.form(f"supplemental_{part['id']}"):
        extra = st.file_uploader("Add an exploded or supplemental view", type=["png", "jpg", "jpeg", "webp"])
        image_type = st.selectbox("View type", ["Exploded assembly", "Alternate CAD view", "Prototype photo", "Quality detail", "Other"])
        caption = st.text_input("Caption")
        if st.form_submit_button("Add view", icon=":material/add_photo_alternate:"):
            if not extra:
                st.error("Choose an image first.")
            else:
                add_part_image(part["id"], extra, image_type, caption)
                st.toast("Additional view added", icon=":material/check_circle:")
                st.rerun()

with details_col.container(border=True):
    st.subheader(part["part_number"])
    st.write(part["description"] or "No part name")
    detail_cols = st.columns(2)
    detail_cols[0].metric("Revision", part["revision"] or "—")
    detail_cols[1].metric("Source", part["source"])
    st.markdown(f"**Feature applicability:** {readable_feature_applicability(part['id'], part['model_applicability'])}")
    if part["notes"]:
        st.write(part["notes"])

render_parts_history()
