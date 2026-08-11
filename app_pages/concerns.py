import pandas as pd
import streamlit as st

from utils.store import project_table, replace_concerns


project_id = st.session_state.get("project_id")
st.title("Questions and concerns")
st.caption("Keep unresolved assumptions and cross-functional decisions visible as the process changes.")
if not project_id:
    st.stop()

concerns = project_table("concerns", project_id, "created_at DESC")
columns = ["id", "category", "subject", "detail", "owner", "priority", "status", "related_part", "related_station", "created_at"]
if concerns.empty:
    concerns = pd.DataFrame(columns=columns)
else:
    concerns = concerns.reindex(columns=columns)

edited = st.data_editor(
    concerns, key="concerns_editor", num_rows="dynamic", hide_index=True, height=430,
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
with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("Save concerns", type="primary", icon=":material/save:"):
        replace_concerns(project_id, edited)
        st.toast("Concerns saved", icon=":material/check_circle:")
        st.rerun()

