from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.table_filters import (
    apply_pending_table_editor_reset,
    request_table_editor_reset,
)
from utils.scope_ui import page_title_with_scope
from utils.table_ui import editable_table_footer, editable_table_heading


def render_functional_review_shell(
    *, title: str, description: str, key_prefix: str
) -> None:
    """Render a non-persistent Functional Reviews placeholder page."""
    project_id = st.session_state.get("project_id")
    if not project_id:
        st.stop()

    page_title_with_scope(title, scope="project")
    st.caption(description)
    st.info(
        "This page is a shell. Review fields and permanent storage will be defined in a future step.",
        icon=":material/construction:",
    )

    editor_key = f"functional_review_{key_prefix}_editor_{project_id}"
    description_key = f"functional_review_{key_prefix}_description_{project_id}"
    saved_description_key = f"{description_key}_saved"
    reset_description_key = f"{description_key}_reset"

    st.session_state.setdefault(saved_description_key, "")
    if st.session_state.pop(reset_description_key, False):
        st.session_state[description_key] = st.session_state[saved_description_key]
    apply_pending_table_editor_reset(editor_key)

    review_description = st.text_area(
        "Review description",
        key=description_key,
        placeholder="Add a short description for this review.",
        help="Use this temporary area to outline the review. It is kept only in this browser session.",
        height=100,
    )
    description_changed = (
        review_description != st.session_state[saved_description_key]
    )

    editable_table_heading("Review items")
    st.data_editor(
        pd.DataFrame(),
        key=editor_key,
        num_rows="delete",
        hide_index=True,
        height=180,
        disabled=True,
    )
    actions = editable_table_footer(
        editor_key=editor_key,
        key_prefix=f"functional_review_{key_prefix}_{project_id}",
        undo_available=description_changed,
        native_row_selection=True,
        additional_unsaved_changes=description_changed,
    )
    if actions.undo:
        st.session_state[reset_description_key] = True
        request_table_editor_reset(editor_key)
        st.rerun()

    if actions.save_and_refresh:
        st.session_state[saved_description_key] = review_description
        request_table_editor_reset(editor_key)
        st.toast(
            "Saved for this browser session. Permanent review storage has not been defined yet.",
            icon=":material/check_circle:",
        )
        st.rerun()

    with st.expander("History", icon=":material/history:"):
        st.caption(
            "No persisted review data or history exists yet. History will begin when permanent review fields are approved."
        )
