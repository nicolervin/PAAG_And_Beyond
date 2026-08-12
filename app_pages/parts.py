from pathlib import Path

import streamlit as st

from utils.clipboard_image import as_uploaded_file, clipboard_image, decode_clipboard_image
from utils.store import add_part_image, part_images, project_models, project_table, set_part_image, update_part_rows, upsert_part
from utils.table_filters import filter_table


project_id = st.session_state.get("project_id")
st.title("Part catalog")
st.caption("Connect official part numbers to CAD screenshots, quantities, revisions, and model applicability.")
if not project_id:
    st.stop()

parts = project_table("parts", project_id, "part_number")
models = project_models(project_id)
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
    return [model.strip() for model in text.split(",") if model.strip()]


def readable_model_applicability(value) -> str:
    selected = split_model_applicability(value)
    if selected == ["All models"]:
        return "All models"
    return ", ".join(model_labels.get(model, model) for model in selected)

with st.expander("Add part", icon=":material/add:", expanded=parts.empty):
    new_part_clipboard_key = f"clipboard_new_part_{project_id}"
    new_part_pending_key = f"pending_new_part_image_{project_id}"
    part_form_version_key = f"part_form_version_{project_id}"
    st.session_state.setdefault(part_form_version_key, 0)
    with st.form(f"part_form_{st.session_state[part_form_version_key]}"):
        row = st.columns([2, 3, 1, 1])
        part_number = row[0].text_input("Part number")
        description = row[1].text_input("Description")
        quantity = row[2].number_input("Quantity", min_value=0, value=1, step=1)
        revision = row[3].text_input("Revision")
        applies_to_all_models = st.checkbox("Applies to all models", value=True)
        selected_models = st.multiselect(
            "Applicable models when not universal",
            options=active_model_numbers,
            format_func=lambda model_number: model_labels.get(model_number, model_number),
            placeholder="Choose one or more models",
            help="This selection is used only when Applies to all models is unchecked.",
        )
        if not active_model_numbers:
            st.caption("No active models are defined yet. Add them on Model definitions, or leave this part applicable to all models.")
        notes = st.text_area("Notes")
        primary_photo = st.file_uploader(
            "Or upload the primary CAD image",
            type=["png", "jpg", "jpeg", "webp"],
            help="Optional. An uploaded file takes priority over a pasted screenshot; the image can be replaced later.",
        )
        st.caption("Press Win+Shift+S, select a region, then paste it below—no intermediate file needed.")
        new_part_pasted = clipboard_image(key=new_part_clipboard_key)
        new_part_payload = getattr(new_part_pasted, "image", None)
        if new_part_payload:
            try:
                st.session_state[new_part_pending_key] = decode_clipboard_image(new_part_payload)
            except ValueError as exc:
                st.error(str(exc))

        pending_new_part_image = st.session_state.get(new_part_pending_key)
        if pending_new_part_image:
            st.image(pending_new_part_image["bytes"], caption="Pasted primary image preview")
            discard_pasted_image = st.form_submit_button("Discard pasted image", icon=":material/delete:")
        else:
            discard_pasted_image = False

        save_part = st.form_submit_button("Save part", type="primary", icon=":material/save:")
        if discard_pasted_image:
            del st.session_state[new_part_pending_key]
            st.rerun()
        if save_part:
            if not part_number.strip():
                st.error("Part number is required.")
            elif not applies_to_all_models and not selected_models:
                st.error("Choose at least one applicable model, or select Applies to all models.")
            else:
                model_applicability = "All" if applies_to_all_models else selected_models
                part_id = upsert_part(project_id, {"part_number": part_number, "description": description, "quantity": quantity, "revision": revision, "source": "Manual", "model_applicability": model_applicability, "notes": notes})
                if primary_photo:
                    set_part_image(part_id, primary_photo)
                elif pending_new_part_image:
                    set_part_image(part_id, as_uploaded_file(pending_new_part_image))
                if new_part_pending_key in st.session_state:
                    del st.session_state[new_part_pending_key]
                st.session_state[part_form_version_key] += 1
                st.toast("Part saved", icon=":material/check_circle:")
                st.rerun()

if parts.empty:
    st.info("No parts yet. Add one above or import a BOM draft from Import & export.")
    st.stop()

st.subheader("All parts")
st.caption("Edit catalog fields directly, then save. Select View details on a row to open its photos and full information below.")
editable_columns = ["id", "part_number", "description", "quantity", "revision", "model_applicability", "notes", "source", "updated_at"]
parts_for_editing = parts.reindex(columns=editable_columns).copy()
parts_for_editing["model_applicability"] = parts_for_editing["model_applicability"].apply(split_model_applicability)
assigned_model_numbers = {
    model_number
    for assigned in parts_for_editing["model_applicability"]
    for model_number in assigned
    if model_number != "All models"
}
all_defined_model_numbers = models["model_number"].fillna("").astype(str).tolist() if not models.empty else []
available_model_numbers = list(dict.fromkeys(active_model_numbers + all_defined_model_numbers + sorted(assigned_model_numbers)))
model_choice_labels = {model_number: model_labels.get(model_number, model_number) for model_number in available_model_numbers}
model_number_by_label = {label: model_number for model_number, label in model_choice_labels.items()}
parts_for_editing["model_applicability"] = parts_for_editing["model_applicability"].apply(
    lambda assigned: [model_choice_labels.get(model_number, model_number) for model_number in assigned]
)
parts_for_editing["view_details"] = ":material/visibility: View details"
parts_for_editing = filter_table(
    parts_for_editing,
    key="part_catalog_filters",
    dropdown_columns=["source", "revision", "model_applicability"],
    search_columns=["part_number", "description", "model_applicability", "notes", "source"],
    labels={"model_applicability": "Model"},
    reset_widget_keys=["parts_catalog_editor"],
    multi_value_columns=["model_applicability"],
    universal_values={"model_applicability": ["All", "All models", ""]},
)
editor_model_options = ["All models", *model_choice_labels.values()]
selected_part_key = f"parts_selected_id_{project_id}"


def open_part_details() -> None:
    click = st.session_state.get("parts_view_details")
    if click and 0 <= click["row"] < len(parts_for_editing):
        st.session_state[selected_part_key] = str(parts_for_editing.iloc[click["row"]]["id"])


edited_parts = st.data_editor(
    parts_for_editing,
    key="parts_catalog_editor",
    hide_index=True,
    num_rows="fixed",
    height=430,
    disabled=["id", "source", "updated_at"],
    column_order=["view_details", "part_number", "description", "quantity", "revision", "model_applicability", "notes", "source", "updated_at"],
    column_config={
        "id": None,
        "view_details": st.column_config.ButtonColumn(
            "Details",
            pinned=True,
            type="tertiary",
            on_click=open_part_details,
            key="parts_view_details",
        ),
        "part_number": st.column_config.TextColumn("Part number", required=True, pinned=True),
        "description": st.column_config.TextColumn("Description", width="large"),
        "quantity": st.column_config.NumberColumn("Quantity", min_value=0, step=1, format="%d"),
        "revision": st.column_config.TextColumn("Revision"),
        "model_applicability": st.column_config.MultiselectColumn(
            "Model applicability",
            options=editor_model_options,
            help="Choose All models or one or more familiar model names.",
            width="large",
        ),
        "notes": st.column_config.TextColumn("Notes", width="large"),
        "source": st.column_config.TextColumn("Source"),
        "updated_at": st.column_config.DatetimeColumn("Updated", format="MMM DD, YYYY HH:mm"),
    },
)
with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("Save part table", type="primary", icon=":material/save:"):
        try:
            parts_to_save = edited_parts.drop(columns=["view_details"]).copy()
            parts_to_save["model_applicability"] = parts_to_save["model_applicability"].apply(
                lambda assigned: [model_number_by_label.get(label, label) for label in assigned]
            )
            count = update_part_rows(project_id, parts_to_save)
            st.toast(f"Saved {count} parts", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

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
    detail_cols = st.columns(3)
    detail_cols[0].metric("Quantity", f"{float(part['quantity']):g}" if part["quantity"] is not None else "Unknown")
    detail_cols[1].metric("Revision", part["revision"] or "—")
    detail_cols[2].metric("Source", part["source"])
    st.markdown(f"**Model applicability:** {readable_model_applicability(part['model_applicability'])}")
    if part["notes"]:
        st.write(part["notes"])
