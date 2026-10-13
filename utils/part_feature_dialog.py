"""Dialog for reviewing multiple feature applicability assignments."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from utils.db_core import connection, record_audit_event
from utils.model_part_store import update_part_feature_rules
from utils.table_filters import (
    apply_pending_table_editor_reset,
    request_table_editor_reset,
)


@st.dialog("Review multiple feature applicabilities", width="large", dismissible=False)
def review_multi_feature_applicability_dialog(project_id: str) -> None:
    """Pop-up modal allowing the user to review and modify parts with multiple inferred feature rules."""
    state_key = f"pending_multi_feature_review_{project_id}"
    review_data = st.session_state.get(state_key)
    if not review_data:
        return

    preview = review_data.get("preview") or {}
    review_list = preview.get("review") or []
    direct_to_apply = preview.get("direct") or {}
    feature_options = preview.get("feature_options") or []
    feature_token_by_label = preview.get("feature_token_by_label") or {}
    parts_editor_key = review_data.get("parts_editor_key")

    if not review_list:
        st.session_state.pop(state_key, None)
        st.rerun()
        return

    st.write(
        f"**{len(review_list)} part(s)** occur in models with multiple matching feature choices in the Complexity Tree. "
        "Review each part's detected features below and adjust or remove chips as you see fit."
    )
    if direct_to_apply:
        st.caption(
            f":material/info: {len(direct_to_apply)} unambiguous part(s) (single-feature or All models) "
            "will also be applied alongside your reviewed choices."
        )

    # Prepare DataFrame
    review_rows = []
    for item in review_list:
        review_rows.append({
            "part_id": str(item["part_id"]),
            "part_number": str(item["part_number"]),
            "description": str(item["description"]),
            "models": str(item["models"]),
            "feature_applicability": list(item.get("feature_applicability") or []),
        })

    df = pd.DataFrame(review_rows)

    editor_base_key = f"multi_feature_review_editor_{project_id}"
    review_editor_instance_key = apply_pending_table_editor_reset(editor_base_key)

    edited_df = st.data_editor(
        df,
        key=review_editor_instance_key,
        column_config={
            "part_id": None,
            "part_number": st.column_config.TextColumn("Part number", disabled=True, width="medium"),
            "description": st.column_config.TextColumn("Part description", disabled=True, width="large"),
            "models": st.column_config.TextColumn(
                "Occurring models",
                disabled=True,
                help="Models where this part is used according to BOM occurrences or model applicability.",
                width="large",
            ),
            "feature_applicability": st.column_config.MultiselectColumn(
                "Feature applicability",
                options=feature_options,
                help="Choose 'All models' alone, or specific feature choices. Remove chips that do not apply.",
                width="large",
            ),
        },
        hide_index=True,
        height=380,
    )

    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_multi_feature_review_btn_{project_id}"):
        st.session_state.pop(state_key, None)
        request_table_editor_reset(editor_base_key)
        st.rerun()

    if actions.button(
        "Apply feature assignments",
        type="primary",
        icon=":material/auto_awesome:",
        key=f"apply_multi_feature_review_btn_{project_id}",
    ):
        # Validate selections
        validation_error = None
        reviewed_to_apply: dict[str, list[str]] = {}

        for _, row in edited_df.iterrows():
            part_id = str(row["part_id"])
            part_number = str(row["part_number"])
            selected_labels = row.get("feature_applicability") or []
            if not isinstance(selected_labels, list):
                selected_labels = [selected_labels] if selected_labels else []

            if "All models" in selected_labels and len(selected_labels) > 1:
                validation_error = (
                    f"Part **{part_number}**: Choose 'All models' by itself, or choose specific feature choices."
                )
                break

            if "All models" in selected_labels:
                reviewed_to_apply[part_id] = ["All models"]
            elif selected_labels:
                tokens = []
                for label in selected_labels:
                    token = feature_token_by_label.get(str(label).strip())
                    if token:
                        tokens.append(token)
                if tokens:
                    reviewed_to_apply[part_id] = tokens
            else:
                # User removed all chips: leave unassigned / do not set rules
                pass

        if validation_error:
            st.error(validation_error)
            return

        all_to_apply = dict(direct_to_apply)
        all_to_apply.update(reviewed_to_apply)

        if not all_to_apply:
            st.warning("No feature assignments to apply.")
            return

        try:
            editor_name = st.session_state.get("current_editor", "")
            with connection() as conn:
                updated_count = update_part_feature_rules(project_id, all_to_apply, _conn=conn)
                record_audit_event(
                    project_id,
                    "Parts",
                    "Auto-assign from Complexity tree (Reviewed)",
                    updated_count,
                    editor_name,
                    {
                        "parts_updated": updated_count,
                        "reviewed_parts_count": len(reviewed_to_apply),
                        "direct_parts_count": len(direct_to_apply),
                    },
                    _conn=conn,
                )

            st.session_state.pop(state_key, None)
            request_table_editor_reset(editor_base_key)
            if parts_editor_key:
                request_table_editor_reset(parts_editor_key)

            st.toast(
                f"Auto-assigned feature applicability for {updated_count} parts ({len(reviewed_to_apply)} reviewed)",
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

