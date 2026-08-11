import pandas as pd
import streamlit as st

from utils.store import add_project_model, project_models, update_project_model_rows
from utils.table_filters import filter_table


project_id = st.session_state.get("project_id")
st.title("Model definitions")
st.caption("Translate official model numbers into the names and descriptions the IE and lean team use during planning.")
if not project_id:
    st.stop()

with st.expander("Add a model", icon=":material/add:", expanded=False):
    with st.form("add_project_model"):
        model_number = st.text_input("Official model number")
        display_name = st.text_input("Familiar name", help="A short team-friendly name, such as 12K heat pump or Premium 230 V.")
        description = st.text_area("Description", help="Describe the model or the differences the planning team needs to recognize.")
        if st.form_submit_button("Add model", type="primary", icon=":material/save:"):
            try:
                add_project_model(project_id, model_number, display_name, description)
                st.toast("Model added", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

models = project_models(project_id)
if models.empty:
    st.info("No models are defined yet. Add the first model above or import the PITS workbook model tab.")
    st.stop()

active_count = int(models["active"].fillna(1).astype(bool).sum())
summary = st.columns(3)
summary[0].metric("Defined models", len(models))
summary[1].metric("Active for planning", active_count)
summary[2].metric("Imported from PITS", int(models["source_payload"].fillna("{}").ne("{}").sum()))

st.subheader("Planning definitions")
st.caption("Model number stays tied to the official source. Edit the team-facing definition and turn off models that should not appear on the Parts page.")
definition_columns = [
    "id", "model_number", "display_name", "description", "active", "notes",
    "platform_size", "package_type", "appearance", "base_model", "updated_at",
]
for column in definition_columns:
    if column not in models.columns:
        models[column] = pd.NA

models_for_editing = models.reindex(columns=definition_columns)
visible_models = filter_table(
    models_for_editing,
    key="model_definition_filters",
    dropdown_columns=["active", "platform_size", "package_type", "base_model"],
    search_columns=["model_number", "display_name", "description", "notes", "appearance"],
    labels={"active": "Planning status"},
    reset_widget_keys=["model_definitions_editor"],
)
edited_models = st.data_editor(
    visible_models,
    key="model_definitions_editor",
    hide_index=True,
    num_rows="fixed",
    height=500,
    disabled=["id", "model_number", "platform_size", "package_type", "appearance", "base_model", "updated_at"],
    column_order=[
        "active", "model_number", "display_name", "description", "notes",
        "platform_size", "package_type", "appearance", "base_model", "updated_at",
    ],
    column_config={
        "id": None,
        "active": st.column_config.CheckboxColumn("Use in planning", help="Active models appear as choices on the Parts page."),
        "model_number": st.column_config.TextColumn("Official model number", pinned=True),
        "display_name": st.column_config.TextColumn("Familiar name", width="medium"),
        "description": st.column_config.TextColumn("Team description", width="large"),
        "notes": st.column_config.TextColumn("Planning notes", width="large"),
        "platform_size": st.column_config.TextColumn("Platform size"),
        "package_type": st.column_config.TextColumn("Package type"),
        "appearance": st.column_config.TextColumn("Appearance"),
        "base_model": st.column_config.TextColumn("Base model"),
        "updated_at": st.column_config.DatetimeColumn("Updated", format="MMM DD, YYYY HH:mm"),
    },
)

with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("Save model definitions", type="primary", icon=":material/save:"):
        count = update_project_model_rows(project_id, edited_models)
        st.toast(f"Saved {count} model definitions", icon=":material/check_circle:")
        st.rerun()
