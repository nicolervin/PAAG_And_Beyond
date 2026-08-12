import json

import altair as alt
import pandas as pd
import streamlit as st

from utils.store import project_models, project_table
from utils.table_filters import filter_table


project_id = st.session_state.get("project_id")
st.title("Assembly fishbone")
st.caption("Arrange confirmed Manufacturing BOM content into a visual assembly order before assigning work to stations or pitches.")
if not project_id:
    st.stop()

nodes = project_table("fishbone_nodes", project_id, "sequence")
if nodes.empty:
    st.info("Import PITS candidates and develop the Manufacturing BOM first.")
    st.stop()

confirmed = nodes[nodes["review_status"] == "Confirmed"].copy()
pending = int((nodes["review_status"] == "Needs review").sum())
if confirmed.empty:
    st.warning("No MBOM occurrences have been confirmed yet. Review candidates in Manufacturing BOM before building the fishbone.", icon=":material/rule:")
    st.stop()

metric_cols = st.columns(3)
metric_cols[0].metric("Confirmed occurrences", len(confirmed), border=True)
metric_cols[1].metric("Named branches", int(confirmed["branch_name"].fillna("").ne("").sum()), border=True)
metric_cols[2].metric("Still awaiting MBOM review", pending, border=True)

models_df = project_models(project_id)
model_options = models_df["model_number"].tolist() if not models_df.empty else []
model_names = {
    str(row["model_number"]): (str(row["display_name"]).strip() or "Familiar name not defined")
    for _, row in models_df.iterrows()
}
subsystems = sorted(value for value in confirmed["subsystem"].dropna().unique().tolist() if value)
filters = st.container(horizontal=True)
selected_subsystem = filters.selectbox("Subsystem", ["All"] + subsystems)
selected_model = filters.selectbox(
    "Model",
    ["All models"] + model_options,
    format_func=lambda value: "All models" if value == "All models" else model_names.get(str(value), "Familiar name not defined"),
)
visible = confirmed if selected_subsystem == "All" else confirmed[confirmed["subsystem"] == selected_subsystem]


def assigned_models(value):
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


if selected_model != "All models":
    visible = visible[visible["applicable_models"].apply(lambda value: not assigned_models(value) or selected_model in assigned_models(value))]

visible = visible.sort_values("sequence").copy()
visible["depth"] = pd.to_numeric(visible["depth"], errors="coerce").fillna(1).astype(int)
visible["node"] = visible["description"].where(visible["description"].fillna("") != "", visible["part_number"])

with st.container(border=True):
    st.subheader("Fishbone layout")
    st.caption("The horizontal direction is assembly order; vertical position is the IE-confirmed subassembly depth.")
    if visible.empty:
        st.info("No confirmed MBOM content applies to the selected filters.")
    else:
        base = alt.Chart(visible).encode(
            x=alt.X("sequence:Q", title="Assembly order"),
            y=alt.Y("depth:O", title="Subassembly depth", sort="ascending"),
            tooltip=[
                alt.Tooltip("pits_id:N", title="PITS ID"),
                alt.Tooltip("sequence:Q", title="Order"),
                alt.Tooltip("depth:O", title="Depth"),
                alt.Tooltip("part_number:N", title="Part number"),
                alt.Tooltip("node:N", title="Description"),
                alt.Tooltip("branch_name:N", title="Branch"),
                alt.Tooltip("subsystem:N", title="Subsystem"),
            ],
        )
        spine = base.mark_line(color="#9AA7B2", strokeWidth=2).encode(detail="depth:N")
        points = base.mark_circle(size=140).encode(color=alt.Color("subsystem:N", title="Subsystem"))
        st.altair_chart(spine + points)

visible["assembly hierarchy"] = visible.apply(
    lambda row: f"{'    ' * max(row['depth'] - 1, 0)}{'-> ' if row['depth'] > 1 else ''}{row['node']}", axis=1
)
visible["models"] = visible["applicable_models"].apply(
    lambda value: (
        ", ".join(model_names.get(str(model), "Familiar name not defined") for model in assigned_models(value))
        if assigned_models(value)
        else "All models"
    )
)
visible = filter_table(
    visible,
    key="legacy_assembly_filters",
    dropdown_columns=["branch_name"],
    search_columns=["pits_id", "part_number", "description", "branch_name", "subsystem", "comments"],
    labels={"branch_name": "Subassembly branch"},
)
st.dataframe(
    visible[["pits_id", "sequence", "assembly hierarchy", "part_number", "quantity", "branch_name", "subsystem", "models", "comments"]],
    hide_index=True,
    height=520,
    column_config={
        "pits_id": st.column_config.TextColumn("PITS ID", pinned=True),
        "sequence": st.column_config.NumberColumn("Order", pinned=True),
        "assembly hierarchy": st.column_config.TextColumn(width="large", pinned=True),
        "quantity": st.column_config.NumberColumn("MBOM quantity", format="%.2f"),
        "branch_name": st.column_config.TextColumn("Subassembly branch"),
        "comments": st.column_config.TextColumn(width="large"),
    },
)
st.caption("Edit order, hierarchy depth, branch names, quantities, and model applicability in Manufacturing BOM. This view intentionally contains no station assignments.")
