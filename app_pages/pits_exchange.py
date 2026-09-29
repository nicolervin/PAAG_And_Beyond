import streamlit as st

from utils.exchange_ui import (
    render_part_data_exchange,
    render_pits_exchange_history,
)
from utils.scope_ui import page_title_with_scope


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
page_title_with_scope("Import/Export PITS", scope="project")
if not project_id:
    st.stop()

st.caption(
    "Import PITS or BOM source data and export a stable planning snapshot for Excel or Lucid data linking."
)
render_part_data_exchange(project_id, scenario_id)
render_pits_exchange_history(project_id)
