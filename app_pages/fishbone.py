import json

import altair as alt
import pandas as pd
import streamlit as st

from utils.store import (
    apply_pits_updates,
    pits_records,
    project_models,
    project_table,
    replace_fishbone_nodes,
    set_mbom_review_status,
    sync_confirmed_mbom_parts,
)


project_id = st.session_state.get("project_id")
st.title("PITS to assembly fishbone")
st.caption("Review the rough PITS list, move useful content onto the fishbone, then shape the Manufacturing BOM order below.")
if not project_id:
    st.stop()

all_columns = [
    "id", "sequence", "depth", "part_number", "description", "quantity", "branch_name",
    "subsystem", "model_feature", "comments", "tracker_status", "review_status", "source_row",
    "parent_id", "source", "raw_levels", "pits_id", "applicable_models", "source_changed",
]
nodes = project_table("fishbone_nodes", project_id, "sequence")
nodes = pd.DataFrame(columns=all_columns) if nodes.empty else nodes.reindex(columns=all_columns)
source = pits_records(project_id)
models_df = project_models(project_id)
model_options = models_df["model_number"].tolist() if not models_df.empty else []


def parse_models(value):
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


nodes["applicable_models"] = nodes["applicable_models"].apply(parse_models)

metrics = st.columns(4)
metrics[0].metric("PITS candidates", len(source) if not source.empty else int(nodes["pits_id"].fillna("").ne("").sum()), border=True)
metrics[1].metric("Awaiting review", int(nodes["review_status"].fillna("Needs review").eq("Needs review").sum()), border=True)
metrics[2].metric("On fishbone", int(nodes["review_status"].fillna("").eq("Confirmed").sum()), border=True)
metrics[3].metric("Excluded", int(nodes["review_status"].fillna("").eq("Excluded").sum()), border=True)

st.header("1 · Review the PITS list")
st.caption("Select one or more rows, then move them to the fishbone, exclude them, or return them for later review.")

if source.empty:
    candidate_table = nodes[nodes["pits_id"].fillna("").ne("")].copy().rename(columns={"id": "node_id"})
else:
    decisions = nodes[["id", "pits_id", "review_status", "source_changed"]].rename(columns={"id": "node_id"})
    candidate_table = source.merge(decisions, on="pits_id", how="left")

if candidate_table.empty:
    st.info("Import the ID-based PITS workbook from Import PITS & export to begin.")
else:
    controls = st.container(horizontal=True)
    status_filter = controls.segmented_control(
        "Show", ["Awaiting review", "On fishbone", "Excluded", "All"], default="Awaiting review"
    )
    search = controls.text_input("Search PITS", placeholder="ID, part number, description, or subsystem")
    status_map = {"Awaiting review": "Needs review", "On fishbone": "Confirmed", "Excluded": "Excluded"}
    visible_candidates = candidate_table.copy()
    if status_filter != "All":
        visible_candidates = visible_candidates[visible_candidates["review_status"] == status_map[status_filter]]
    if search:
        searchable = visible_candidates.astype(str).agg(" ".join, axis=1)
        visible_candidates = visible_candidates[searchable.str.contains(search, case=False, na=False, regex=False)]

    source_columns = [
        column for column in ["node_id", "pits_id", "used_bom", "part_number", "description", "status",
                              "subsystem", "design_maturity", "workstation", "revision_no", "review_status", "source_changed"]
        if column in visible_candidates.columns
    ]
    event = st.dataframe(
        visible_candidates[source_columns],
        key="pits_candidate_table",
        hide_index=True,
        height=330,
        on_select="rerun",
        selection_mode="multi-row",
        column_config={
            "node_id": None,
            "pits_id": st.column_config.TextColumn("PITS ID", pinned=True),
            "used_bom": st.column_config.TextColumn("Used BOM"),
            "part_number": st.column_config.TextColumn("Part number", pinned=True),
            "design_maturity": st.column_config.TextColumn("Design maturity"),
            "revision_no": st.column_config.NumberColumn("PITS revision"),
            "review_status": st.column_config.TextColumn("IE decision"),
            "source_changed": st.column_config.CheckboxColumn("PITS revised"),
        },
    )
    selected_rows = event.selection.rows
    selected_node_ids = visible_candidates.iloc[selected_rows]["node_id"].dropna().astype(str).tolist() if selected_rows else []
    with st.container(horizontal=True):
        if st.button("Move to fishbone", type="primary", icon=":material/arrow_downward:", disabled=not selected_node_ids):
            count = set_mbom_review_status(project_id, selected_node_ids, "Confirmed")
            sync_confirmed_mbom_parts(project_id)
            st.toast(f"Moved {count} parts to the fishbone", icon=":material/check_circle:")
            st.rerun()
        if st.button("Exclude", icon=":material/block:", disabled=not selected_node_ids):
            count = set_mbom_review_status(project_id, selected_node_ids, "Excluded")
            st.toast(f"Excluded {count} PITS candidates", icon=":material/check_circle:")
            st.rerun()
        if st.button("Return to review", icon=":material/undo:", disabled=not selected_node_ids):
            count = set_mbom_review_status(project_id, selected_node_ids, "Needs review")
            st.toast(f"Returned {count} candidates to review", icon=":material/check_circle:")
            st.rerun()

changed = nodes[nodes["source_changed"].fillna(0).astype(bool) & nodes["pits_id"].fillna("").ne("")]
if not changed.empty and not source.empty:
    with st.expander(f"Reconcile {len(changed)} revised PITS IDs", icon=":material/update:"):
        comparison = changed[["pits_id", "part_number", "description", "subsystem", "comments"]].merge(
            source[["pits_id", "part_number", "description", "subsystem", "comments", "revision_no"]],
            on="pits_id", how="left", suffixes=("_current_mbom", "_new_pits"),
        )
        update_event = st.dataframe(comparison, hide_index=True, on_select="rerun", selection_mode="multi-row")
        update_ids = comparison.iloc[update_event.selection.rows]["pits_id"].astype(str).tolist() if update_event.selection.rows else []
        if st.button("Apply selected PITS revisions", type="primary", icon=":material/sync:", disabled=not update_ids):
            count = apply_pits_updates(project_id, update_ids)
            st.toast(f"Applied {count} PITS revisions; review them again before approval", icon=":material/check_circle:")
            st.rerun()

confirmed = nodes[nodes["review_status"] == "Confirmed"].copy()
st.header("2 · Shape the assembly fishbone")
st.caption("Each approved PITS item appears here. Order runs left to right; the vertical lanes represent main assembly and subassembly depth.")

if confirmed.empty:
    st.info("Select PITS rows above and choose Move to fishbone.")
else:
    filter_row = st.container(horizontal=True)
    subsystem_options = sorted(value for value in confirmed["subsystem"].dropna().unique().tolist() if value)
    fishbone_subsystem = filter_row.selectbox("Fishbone subsystem", ["All"] + subsystem_options)
    fishbone_model = filter_row.selectbox("Fishbone model", ["All models"] + model_options)
    visual = confirmed if fishbone_subsystem == "All" else confirmed[confirmed["subsystem"] == fishbone_subsystem]
    if fishbone_model != "All models":
        visual = visual[visual["applicable_models"].apply(lambda assigned: not assigned or fishbone_model in assigned)]
    visual = visual.sort_values("sequence").copy()
    visual["depth"] = pd.to_numeric(visual["depth"], errors="coerce").fillna(1).astype(int)
    visual["node"] = visual["description"].where(visual["description"].fillna("") != "", visual["part_number"])
    if visual.empty:
        st.info("No approved parts match these fishbone filters.")
    else:
        chart_base = alt.Chart(visual).encode(
            x=alt.X("sequence:Q", title="Assembly order"),
            y=alt.Y("depth:O", title="Assembly level", sort="ascending"),
            tooltip=[
                alt.Tooltip("pits_id:N", title="PITS ID"),
                alt.Tooltip("sequence:Q", title="Order"),
                alt.Tooltip("part_number:N", title="Part number"),
                alt.Tooltip("node:N", title="Description"),
                alt.Tooltip("branch_name:N", title="Branch"),
                alt.Tooltip("subsystem:N", title="Subsystem"),
            ],
        )
        spines = chart_base.mark_line(color="#9AA7B2", strokeWidth=2).encode(detail="depth:N")
        points = chart_base.mark_circle(size=150).encode(color=alt.Color("subsystem:N", title="Subsystem"))
        st.altair_chart(spines + points)

st.header("3 · Build the Manufacturing BOM order")
st.caption("Edit approved content directly. Create levels and named branches, set quantities and model applicability, and reorder the main assembly sequence.")

if confirmed.empty:
    st.caption("The MBOM table will appear after the first PITS item is moved to the fishbone.")
else:
    editor = confirmed.copy()
    edited = st.data_editor(
        editor,
        key="mbom_order_editor",
        num_rows="dynamic",
        hide_index=True,
        height=460,
        disabled=["id", "pits_id", "source", "source_row", "source_changed", "review_status"],
        column_order=[
            "pits_id", "sequence", "depth", "branch_name", "part_number", "description", "quantity",
            "subsystem", "applicable_models", "comments", "source_changed",
        ],
        column_config={
            "id": None,
            "pits_id": st.column_config.TextColumn("PITS ID", pinned=True),
            "sequence": st.column_config.NumberColumn("MBOM order", min_value=1, step=1, pinned=True),
            "depth": st.column_config.NumberColumn("Assembly level", min_value=1, max_value=20, step=1, pinned=True),
            "branch_name": st.column_config.TextColumn("Section / branch", pinned=True),
            "part_number": st.column_config.TextColumn("Part number", pinned=True),
            "description": st.column_config.TextColumn(width="large", required=True),
            "quantity": st.column_config.NumberColumn("Qty", min_value=0.0, format="%.2f"),
            "applicable_models": st.column_config.MultiselectColumn(
                "Applicable models", options=model_options, help="Leave empty when the item applies to all models."
            ),
            "comments": st.column_config.TextColumn("IE notes", width="large"),
            "source_changed": st.column_config.CheckboxColumn("PITS revised"),
        },
    )
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Save fishbone and MBOM order", type="primary", icon=":material/save:"):
            original_ids = set(confirmed["id"].dropna().astype(str))
            edited_ids = set(edited["id"].dropna().astype(str)) if "id" in edited else set()
            removed_ids = original_ids - edited_ids
            preserved = nodes[~nodes["id"].astype(str).isin(original_ids)].copy()
            removed = confirmed[confirmed["id"].astype(str).isin(removed_ids)].copy()
            removed["review_status"] = "Excluded"
            edited["review_status"] = "Confirmed"
            for column, default in {
                "parent_id": None, "raw_levels": "{}", "pits_id": "", "source": "Manual",
                "source_row": None, "source_changed": 0, "model_feature": "", "tracker_status": "",
            }.items():
                if column not in edited:
                    edited[column] = default
            combined = pd.concat([preserved, removed, edited], ignore_index=True, sort=False).reindex(columns=all_columns)
            replace_fishbone_nodes(project_id, combined)
            synced = sync_confirmed_mbom_parts(project_id)
            st.toast(f"Fishbone saved · {synced} confirmed parts synchronized", icon=":material/check_circle:")
            st.rerun()
    st.caption("Deleting an imported row from this lower table marks it Excluded; its PITS ID and source history are retained.")

if not models_df.empty:
    with st.expander("Project model catalog", icon=":material/precision_manufacturing:"):
        st.dataframe(
            models_df.drop(columns=["id", "project_id", "source_payload"], errors="ignore"),
            hide_index=True,
            column_config={
                "model_number": st.column_config.TextColumn("Model number", pinned=True),
                "eau": st.column_config.NumberColumn("EAU", format="%.0f"),
            },
        )
