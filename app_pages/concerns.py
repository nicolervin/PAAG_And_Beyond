import pandas as pd
import streamlit as st

from utils.store import project_table, replace_concerns
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    has_unsaved_table_changes,
    merge_filtered_edits,
    request_table_editor_reset,
)


project_id = st.session_state.get("project_id")
st.title("Questions and concerns")
st.caption("Keep unresolved assumptions and cross-functional decisions visible as the process changes.")
if not project_id:
    st.stop()
apply_pending_table_editor_reset("concerns_editor")

concerns = project_table("concerns", project_id, "created_at DESC")
columns = ["id", "category", "subject", "detail", "owner", "priority", "status", "related_part", "related_station", "created_at"]
if concerns.empty:
    concerns = pd.DataFrame(columns=columns)
else:
    concerns = concerns.reindex(columns=columns)

visible_concerns = filter_table(
    concerns,
    key="concerns_filters",
    dropdown_columns=["category", "priority", "status", "owner"],
    search_columns=["subject", "detail", "owner", "related_part", "related_station"],
    reset_widget_keys=["concerns_editor"],
)
edited = st.data_editor(
    visible_concerns, key="concerns_editor", num_rows="dynamic", hide_index=True, height=430,
    disabled=["id", "created_at"], column_order=[column for column in columns if column != "id"],
    column_config={
        "id": None,
        "category": st.column_config.SelectboxColumn(options=["Question", "Concern", "Decision", "Assumption"]),
        "subject": st.column_config.TextColumn(required=True, pinned=True),
        "detail": st.column_config.TextColumn(width="large"),
        "priority": st.column_config.SelectboxColumn(options=["Low", "Medium", "High", "Critical"]),
        "status": st.column_config.SelectboxColumn(options=["Open", "Investigating", "Waiting", "Resolved", "Closed"]),
        "created_at": st.column_config.DatetimeColumn("Created", format="MMM DD, YYYY HH:mm"),
    },
)
with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
    if has_unsaved_table_changes("concerns_editor"):
        st.markdown(":orange[:material/warning: **Unsaved changes**]")
    if st.button("Save concerns", type="primary", icon=":material/save:"):
        combined_concerns = merge_filtered_edits(concerns, visible_concerns, edited)
        replace_concerns(project_id, combined_concerns)
        request_table_editor_reset("concerns_editor")
        st.toast("Concerns saved", icon=":material/check_circle:")
        st.rerun()
