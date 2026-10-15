import streamlit as st

from utils.scope_ui import page_title_with_scope

page_title_with_scope("Assembly grid", scope="project")

st.info(
    "The Assembly grid has been retired in favor of the Model Tree (BOM Tree). "
    "Please use the Model Tree to view and manage model hierarchies and assembly structures."
)
