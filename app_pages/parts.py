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
    part_feature_rules,
    part_images,
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
    editable_table_header,
    native_selected_rows,
    required_field_errors,
    standard_details_column_config,
    table_has_unsaved_changes,
)


project_id = st.session_state.get("project_id")
parts_editor_key = "parts_catalog_editor_v6"
st.title("Part catalog")
st.caption("Connect official part numbers to CAD screenshots, quantities, revisions, and model applicability.")
if not project_id:
    st.stop()
apply_pending_table_editor_reset(parts_editor_key)

parts = project_table("parts", project_id, "part_number")
models = project_models(project_id)
features = complexity_features(project_id)
active_features = features.loc[features["active"].fillna(1).astype(bool)].copy() if not features.empty else features
rules = part_feature_rules(project_id)
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
parts_for_editing["photo_action"] = parts_for_editing["image_path"].apply(
    lambda value: ":material/add_a_photo: Photo" if not str(value or "").strip() else ":material/image: Photo"
) if "image_path" in parts_for_editing.columns else ":material/add_a_photo: Photo"
parts_for_editing["delete_part"] = ":material/delete: Delete part"
parts_for_editing = filter_table(
    parts_for_editing,
    key="part_catalog_filters",
    dropdown_columns=["source", "revision", "photo_status", "applicability_status"],
    search_columns=["part_number", "description", "photo_status", "applicability_status", "notes", "source"],
    labels={"photo_status": "Photo status", "applicability_status": "Feature applicability"},
    reset_widget_keys=[parts_editor_key],
)
selected_part_key = f"parts_selected_id_{project_id}"
photo_part_key = f"parts_photo_id_{project_id}"


def open_part_details() -> None:
    click = st.session_state.get("parts_view_details")
    if click and 0 <= click["row"] < len(parts_for_editing):
        st.session_state[selected_part_key] = str(parts_for_editing.iloc[click["row"]]["id"])


def open_part_photo() -> None:
    click = st.session_state.get("parts_photo_action")
    if click and 0 <= click["row"] < len(parts_for_editing):
        part_id = parts_for_editing.iloc[click["row"]]["id"]
        if part_id is not None and not pd.isna(part_id):
            st.session_state[photo_part_key] = str(part_id)


def delete_part_row() -> None:
    click = st.session_state.get("parts_delete_part")
    if not click or not 0 <= click["row"] < len(parts_for_editing):
        return
    if table_has_unsaved_changes(parts_editor_key, native_row_selection=True):
        st.toast("Save or undo the other table edits before deleting a part.", icon=":material/warning:")
        return
    row = parts_for_editing.iloc[click["row"]]
    part_id = row.get("id")
    if part_id is None or pd.isna(part_id):
        return
    label = delete_project_part(project_id, str(part_id))
    if st.session_state.get(selected_part_key) == str(part_id):
        st.session_state.pop(selected_part_key, None)
    if st.session_state.get(photo_part_key) == str(part_id):
        st.session_state.pop(photo_part_key, None)
    request_table_editor_reset(parts_editor_key)
    st.toast(f"Deleted part {label} and its fishbone uses", icon=":material/delete:")


edited_parts = st.data_editor(
    parts_for_editing,
    key=parts_editor_key,
    hide_index=True,
    num_rows="dynamic",
    height=430,
    disabled=["id", "model_applicability", "photo_status", "applicability_status", "source", "image_path", "updated_at"],
    column_order=["view_details", "delete_part", "photo_action", "photo_status", "part_number", "description", "revision", "feature_applicability", "applicability_status", "notes", "source", "updated_at"],
    column_config={
        "id": None,
        "view_details": standard_details_column_config(on_click=open_part_details, key="parts_view_details"),
        "photo_action": st.column_config.ButtonColumn(
            "Photo",
            type="tertiary",
            on_click=open_part_photo,
            key="parts_photo_action",
            help="Open upload and direct-paste controls for this part.",
        ),
        "photo_status": st.column_config.TextColumn(
            "Photo status",
            help="A green check means a primary CAD image is attached; a red X means it is missing.",
        ),
        "delete_part": st.column_config.ButtonColumn(
            "Delete part",
            type="tertiary",
            on_click=delete_part_row,
            key="parts_delete_part",
            help="Delete this catalog part, its photos, and all of its fishbone uses.",
        ),
        "part_number": st.column_config.TextColumn("Part number", required=True),
        "description": st.column_config.TextColumn("Description", width="large"),
        "quantity": None,
        "revision": st.column_config.TextColumn("Revision"),
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
st.caption("Add a part in the blank row, then save. After it is saved, use its Photo cell to upload a file or paste a screenshot.")

export_columns = [
    "part_number", "description", "revision", "feature_applicability",
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
    if actions.button("Delete parts", type="primary", icon=":material/delete:", key="confirm_bulk_part_delete"):
        deleted_labels = [
            delete_project_part(project_id, str(part_id))
            for part_id in pending_ids
        ]
        deleted_ids = set(pending_ids)
        if st.session_state.get(selected_part_key) in deleted_ids:
            st.session_state.pop(selected_part_key, None)
        if st.session_state.get(photo_part_key) in deleted_ids:
            st.session_state.pop(photo_part_key, None)
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

photo_part_id = st.session_state.get(photo_part_key)
photo_rows = parts.loc[parts["id"].astype(str) == str(photo_part_id)] if photo_part_id else parts.iloc[0:0]
if not photo_rows.empty:
    photo_part = photo_rows.iloc[0].to_dict()
    with st.container(border=True):
        photo_title, photo_close = st.columns([5, 0.7], vertical_alignment="center")
        photo_title.subheader(f"Primary CAD image · {photo_part['part_number']}")
        if photo_close.button("Close", icon=":material/close:", key="close_table_photo_editor"):
            st.session_state.pop(photo_part_key, None)
            st.rerun()
        photo_path = Path(photo_part["image_path"]) if photo_part.get("image_path") else None
        if photo_path and photo_path.exists():
            st.image(str(photo_path), caption=photo_part["part_number"], width=240)
        uploaded_from_table = st.file_uploader(
            "Upload the primary CAD image",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"table_photo_upload_{photo_part_id}",
        )
        if uploaded_from_table and st.button(
            "Save uploaded image", type="primary", icon=":material/upload:", key=f"save_table_upload_{photo_part_id}"
        ):
            set_part_image(str(photo_part_id), uploaded_from_table)
            st.toast("Primary CAD image saved", icon=":material/check_circle:")
            st.rerun()
        st.caption("Press Win+Shift+S, select a region, then paste it below—no intermediate file needed.")
        table_clipboard_key = f"clipboard_table_part_{photo_part_id}"
        table_pending_key = f"pending_table_part_{photo_part_id}"
        table_pasted = clipboard_image(key=table_clipboard_key)
        table_payload = getattr(table_pasted, "image", None)
        if table_payload:
            try:
                st.session_state[table_pending_key] = decode_clipboard_image(table_payload)
            except ValueError as exc:
                st.error(str(exc))
        table_pending = st.session_state.get(table_pending_key)
        if table_pending:
            st.image(table_pending["bytes"], caption="Pasted screenshot preview", width=240)
            table_photo_actions = st.container(horizontal=True)
            if table_photo_actions.button(
                "Save pasted screenshot", type="primary", icon=":material/save:", key=f"save_table_paste_{photo_part_id}"
            ):
                set_part_image(str(photo_part_id), as_uploaded_file(table_pending))
                st.session_state.pop(table_pending_key, None)
                st.toast("Primary CAD image saved", icon=":material/check_circle:")
                st.rerun()
            if table_photo_actions.button("Discard", icon=":material/delete:", key=f"discard_table_paste_{photo_part_id}"):
                st.session_state.pop(table_pending_key, None)
                st.rerun()

if save_part_table:
    try:
        if not selected_saved_parts.empty:
            raise ValueError("Clear the selected rows before saving table edits. Selection is reserved for bulk actions.")
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
            columns=["view_details", "photo_status", "photo_action", "delete_part", "feature_applicability", "applicability_status"]
        ).copy()
        new_row_mask = parts_to_save["id"].isna() | parts_to_save["id"].astype(str).str.strip().eq("")
        parts_to_save.loc[new_row_mask, "id"] = [str(uuid4()) for _ in range(int(new_row_mask.sum()))]
        edited_parts = edited_parts.copy()
        edited_parts.loc[new_row_mask, "id"] = parts_to_save.loc[new_row_mask, "id"]
        parts_to_save.loc[new_row_mask, "quantity"] = 1
        parts_to_save.loc[new_row_mask, "model_applicability"] = "All"
        parts_to_save.loc[new_row_mask, "source"] = "Manual"
        count = update_part_rows(project_id, parts_to_save)
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
            project_id, "Parts", "Save & refresh", count,
            st.session_state.get("current_editor", ""),
        )
        request_table_editor_reset(parts_editor_key)
        st.toast(f"Saved {count} parts", icon=":material/check_circle:")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

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
                "created_at": st.column_config.DatetimeColumn("When", format="MMM DD, YYYY HH:mm"),
            },
        )

if parts.empty:
    st.info("Add the first part in the blank row above, then select Save part table.")
    st.stop()

valid_part_ids = set(parts["id"].astype(str))
if st.session_state.get(selected_part_key) not in valid_part_ids:
    st.session_state[selected_part_key] = str(parts.iloc[0]["id"])
part = parts.loc[parts["id"].astype(str) == st.session_state[selected_part_key]].iloc[0].to_dict()
st.subheader(f"Part details · {part['part_number']}")
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

    st.caption("Or press Win+Shift+S, select a region, and paste it here—no intermediate file needed.")
    primary_clipboard_key = f"clipboard_primary_{part['id']}"
    primary_pending_key = f"pending_primary_{part['id']}"
    pasted = clipboard_image(key=primary_clipboard_key)
    pasted_payload = getattr(pasted, "image", None)
    if pasted_payload:
        try:
            st.session_state[primary_pending_key] = decode_clipboard_image(pasted_payload)
        except ValueError as exc:
            st.error(str(exc))
    pending_primary = st.session_state.get(primary_pending_key)
    if pending_primary:
        st.image(pending_primary["bytes"], caption="Pasted screenshot preview")
        with st.container(horizontal=True):
            if st.button("Save pasted screenshot", type="primary", icon=":material/save:", key=f"save_pasted_{part['id']}"):
                set_part_image(part["id"], as_uploaded_file(pending_primary))
                del st.session_state[primary_pending_key]
                st.toast("Screenshot saved as the primary CAD image", icon=":material/check_circle:")
                st.rerun()
            if st.button("Discard", icon=":material/delete:", key=f"discard_pasted_{part['id']}"):
                del st.session_state[primary_pending_key]
                st.rerun()

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
    st.write(part["description"] or "No description")
    detail_cols = st.columns(2)
    detail_cols[0].metric("Revision", part["revision"] or "—")
    detail_cols[1].metric("Source", part["source"])
    st.markdown(f"**Feature applicability:** {readable_feature_applicability(part['id'], part['model_applicability'])}")
    if part["notes"]:
        st.write(part["notes"])
