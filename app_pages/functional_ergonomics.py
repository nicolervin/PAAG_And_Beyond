from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.scope_ui import page_title_with_scope
from utils.store import (
    ERGONOMICS_RISK_CLASSIFICATIONS,
    ERGONOMICS_REVIEW_STATUSES,
    delete_ergonomics_reviews,
    ergonomic_hazard_options,
    ergonomics_review_audit_history,
    ergonomics_review_save_plan,
    ergonomics_reviews,
    ergonomics_work_elements,
    get_planning_scenario,
    record_audit_event,
    save_ergonomics_review_rows,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    direct_entry_editor_rows,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    selectable_dataframe,
    stage_native_delete_confirmation,
)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _date_value(value: object) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    return str(value).strip() or None


def _id_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(_clean_text(item) for item in value if _clean_text(item)))


project_id = _clean_text(st.session_state.get("project_id"))
scenario_id = _clean_text(st.session_state.get("scenario_id"))
scenario = get_planning_scenario(project_id, scenario_id) if project_id and scenario_id else None

page_title_with_scope(
    "Ergonomics",
    scope="scenario",
    scenario_name=_clean_text((scenario or {}).get("name")),
)
st.caption(
    "Review ergonomic concerns for the active planning scenario, including concerns "
    "captured before a Process at a Glance step is available."
)
if not project_id or not scenario:
    st.info("Select an active planning scenario to manage Ergonomics reviews.")
    st.stop()

logical_editor_key = f"ergonomics_reviews_editor_{project_id}_{scenario_id}"
editor_key = apply_pending_table_editor_reset(logical_editor_key)
pending_delete_key = f"ergonomics_reviews_pending_delete_{project_id}_{scenario_id}"
pending_merge_key = f"ergonomics_reviews_pending_merge_{project_id}_{scenario_id}"

reviews = ergonomics_reviews(project_id, scenario_id).copy()
if reviews.empty:
    reviews = pd.DataFrame(
        {
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "scenario_id": pd.Series(dtype="string"),
            "work_element_id": pd.Series(dtype="string"),
            "process_part_option_id": pd.Series(dtype="string"),
            "status": pd.Series(dtype="string"),
            "risk_classification": pd.Series(dtype="string"),
            "reviewer": pd.Series(dtype="string"),
            "notes": pd.Series(dtype="string"),
            "requested_due_date": pd.Series(dtype="string"),
            "created_at": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "hazard_option_ids": pd.Series(dtype="object"),
            "hazard_labels": pd.Series(dtype="object"),
            "work_element_label": pd.Series(dtype="string"),
            "pitch": pd.Series(dtype="string"),
        }
    )

reviews["link_filter"] = reviews["work_element_id"].apply(
    lambda value: "Unlinked" if not _clean_text(value) else "Linked"
)
reviews["link_status"] = reviews["link_filter"].apply(lambda value: [value])
reviews["hazard_option_ids"] = reviews["hazard_option_ids"].apply(_id_list)
reviews["requested_due_date"] = pd.to_datetime(
    reviews["requested_due_date"], errors="coerce"
)

work_elements = ergonomics_work_elements(project_id, scenario_id)
work_label_by_id = {
    _clean_text(row["id"]): " · ".join(
        value
        for value in [_clean_text(row["work_element_label"]), _clean_text(row["pitch"])]
        if value
    )
    or _clean_text(row["id"])
    for _, row in work_elements.iterrows()
}
work_options = ["", *work_label_by_id]

hazards = ergonomic_hazard_options(project_id)
hazard_label_by_id = {
    _clean_text(row["id"]): _clean_text(row["label"])
    for _, row in hazards.iterrows()
}
saved_hazard_ids = list(
    dict.fromkeys(
        hazard_id
        for values in reviews["hazard_option_ids"]
        for hazard_id in _id_list(values)
    )
)
active_hazard_ids = [
    _clean_text(row["id"])
    for _, row in hazards.iterrows()
    if bool(row["active"])
]
hazard_options = list(dict.fromkeys([*active_hazard_ids, *saved_hazard_ids]))

editable_table_heading("Ergonomics reviews")
st.caption(
    "**Unlinked** identifies a legacy item or pre-PAAG concern that does not yet "
    "reference a Process step. Choose a Work Element to link it. If that step already "
    "has its automatic review, the empty placeholder is merged silently; when both "
    "reviews contain real content, you must choose which review survives."
)
st.caption(
    "**Favorable Red** and **Favorable Green** mean the assessment used a "
    "non-production-intent part and still needs confirmation on the production-intent "
    "part. **Red** and **Green** are confirmed on the production-intent part. Review "
    "status and risk classification are set independently."
)

visible_reviews = filter_table(
    reviews,
    key=f"ergonomics_reviews_filters_{project_id}_{scenario_id}",
    dropdown_columns=["link_filter", "status", "risk_classification", "reviewer"],
    search_columns=["work_element_label", "pitch", "reviewer", "notes", "hazard_labels"],
    labels={
        "link_filter": "Link status",
        "status": "Status",
        "risk_classification": "Risk classification",
        "reviewer": "Reviewer",
    },
    reset_widget_keys=[editor_key],
)
reviews_for_editing = direct_entry_editor_rows(
    visible_reviews,
    editor_key=editor_key,
    sort_columns=[
        "link_filter",
        "work_element_label",
        "status",
        "risk_classification",
        "reviewer",
        "requested_due_date",
        "updated_at",
    ],
    labels={
        "link_filter": "Link status",
        "work_element_label": "Process step description",
        "requested_due_date": "Requested due date",
    },
)

edited = st.data_editor(
    reviews_for_editing,
    key=editor_key,
    num_rows="dynamic",
    hide_index=True,
    height=470,
    column_order=[
        "link_status",
        "work_element_id",
        "status",
        "risk_classification",
        "reviewer",
        "hazard_option_ids",
        "notes",
        "requested_due_date",
    ],
    disabled=[
        "id",
        "project_id",
        "scenario_id",
        "link_status",
        "link_filter",
        "process_part_option_id",
        "created_at",
        "updated_at",
        "hazard_labels",
        "work_element_label",
        "pitch",
    ],
    column_config={
        "id": None,
        "project_id": None,
        "scenario_id": None,
        "link_filter": None,
        "process_part_option_id": None,
        "created_at": None,
        "updated_at": None,
        "hazard_labels": None,
        "work_element_label": None,
        "pitch": None,
        "link_status": st.column_config.MultiselectColumn(
            "Link",
            options=["Linked", "Unlinked"],
            color=["blue", "orange"],
            disabled=True,
            width="small",
            help="Unlinked reviews have no Process at a Glance Work Element yet.",
        ),
        "work_element_id": st.column_config.SelectboxColumn(
            "Process step description",
            options=work_options,
            format_func=lambda value: (
                "Unlinked — no Process step" if not value else work_label_by_id.get(value, value)
            ),
            help=(
                "Leave blank for a legacy item or pre-PAAG concern. Linking to a step "
                "may merge this review with the step's automatic review."
            ),
            width="large",
        ),
        "status": st.column_config.SelectboxColumn(
            "Status",
            options=list(ERGONOMICS_REVIEW_STATUSES),
            default="Started",
            required=True,
        ),
        "risk_classification": st.column_config.SelectboxColumn(
            "Risk classification",
            options=list(ERGONOMICS_RISK_CLASSIFICATIONS),
            default="Not yet assessed",
            required=True,
            help=(
                "Favorable Red and Favorable Green are assessments on a "
                "non-production-intent part awaiting confirmation. Red and Green are "
                "confirmed on the production-intent part."
            ),
        ),
        "reviewer": st.column_config.TextColumn(
            "Reviewer",
            default=_clean_text(st.session_state.get("current_editor")),
            help="Free-text attribution. New manual rows start with Current editor.",
        ),
        "hazard_option_ids": st.column_config.MultiselectColumn(
            "Hazard tags",
            options=hazard_options,
            format_func=lambda value: hazard_label_by_id.get(value, value),
            color="orange",
            help="Choose one or more active project-wide Ergonomics hazard tags.",
            width="large",
        ),
        "notes": st.column_config.TextColumn("Notes", width="large"),
        "requested_due_date": st.column_config.DateColumn(
            "Requested due date",
            help="Optional target date requested for this review.",
        ),
    },
)

footer = editable_table_footer(
    editor_key=editor_key,
    key_prefix=f"ergonomics_reviews_{project_id}_{scenario_id}",
    native_row_selection=True,
)
st.download_button(
    "Export filtered rows",
    data=dataframe_to_excel(
        visible_reviews[
            [
                "link_filter",
                "work_element_label",
                "pitch",
                "status",
                "risk_classification",
                "reviewer",
                "hazard_labels",
                "notes",
                "requested_due_date",
            ]
        ].rename(
            columns={
                "link_filter": "Link status",
                "work_element_label": "Process step description",
                "pitch": "Pitch",
                "status": "Status",
                "risk_classification": "Risk classification",
                "reviewer": "Reviewer",
                "hazard_labels": "Hazard tags",
                "notes": "Notes",
                "requested_due_date": "Requested due date",
            }
        ),
        "Ergonomics reviews",
    ),
    file_name="ergonomics_reviews.xlsx",
    key=f"ergonomics_reviews_export_{project_id}_{scenario_id}",
    icon=":material/download:",
)
if footer.undo:
    st.session_state.pop(pending_merge_key, None)
    request_table_editor_reset(editor_key)
    st.toast("Discarded the unsaved Ergonomics review edits", icon=":material/undo:")
    st.rerun()


def _normalized_rows(dataframe: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for values in dataframe.to_dict("records"):
        rows.append(
            {
                "id": _clean_text(values.get("id")) or str(uuid4()),
                "work_element_id": _clean_text(values.get("work_element_id")) or None,
                "process_part_option_id": (
                    _clean_text(values.get("process_part_option_id")) or None
                ),
                "status": _clean_text(values.get("status")) or "Started",
                "risk_classification": (
                    _clean_text(values.get("risk_classification"))
                    or "Not yet assessed"
                ),
                "reviewer": _clean_text(values.get("reviewer")),
                "hazard_option_ids": _id_list(values.get("hazard_option_ids")),
                "notes": _clean_text(values.get("notes")),
                "requested_due_date": _date_value(values.get("requested_due_date")),
                "created_at": _clean_text(values.get("created_at")),
                "updated_at": _clean_text(values.get("updated_at")),
            }
        )
    return rows


def _review_summary(values: dict) -> str:
    work_id = _clean_text(values.get("work_element_id"))
    return work_label_by_id.get(work_id, "Unlinked — no Process step")


def _review_detail_frame(values: dict) -> pd.DataFrame:
    hazard_labels = [
        hazard_label_by_id.get(value, value)
        for value in _id_list(values.get("hazard_option_ids"))
    ]
    return pd.DataFrame(
        {
            "Field": [
                "Review ID",
                "Process step",
                "Status",
                "Risk classification",
                "Reviewer",
                "Hazard tags",
                "Notes",
                "Requested due date",
                "Process part-use ID",
                "Created",
                "Updated",
            ],
            "Value": [
                _clean_text(values.get("id")),
                _review_summary(values),
                _clean_text(values.get("status")) or "Started",
                _clean_text(values.get("risk_classification")) or "Not yet assessed",
                _clean_text(values.get("reviewer")) or "—",
                ", ".join(hazard_labels) or "—",
                _clean_text(values.get("notes")) or "—",
                _clean_text(values.get("requested_due_date")) or "—",
                _clean_text(values.get("process_part_option_id")) or "—",
                _clean_text(values.get("created_at")) or "Not saved yet",
                _clean_text(values.get("updated_at")) or "Not saved yet",
            ],
        }
    )


def _save_rows(
    rows: list[dict],
    candidate_ids: list[str],
    merge_survivors: dict[str, str] | None = None,
) -> None:
    result = save_ergonomics_review_rows(
        project_id,
        scenario_id,
        rows,
        link_candidate_ids=candidate_ids,
        merge_survivors=merge_survivors,
        editor_name=_clean_text(st.session_state.get("current_editor")),
    )
    record_audit_event(
        project_id,
        "Ergonomics reviews",
        "Save & Refresh",
        int(result["row_count"]),
        _clean_text(st.session_state.get("current_editor")),
        {
            "scenario_id": scenario_id,
            "created_ids": result["created_ids"],
            "updated_ids": result["updated_ids"],
            "discarded_ids": result["discarded_ids"],
            "store_timestamp": result["timestamp"],
        },
    )
    st.session_state.pop(pending_merge_key, None)
    request_table_editor_reset(editor_key)
    st.toast("Ergonomics reviews saved", icon=":material/check_circle:")
    st.rerun()


selected_reviews = native_selected_rows(reviews_for_editing, editor_key=editor_key)
if not selected_reviews.empty:
    st.session_state[pending_delete_key] = [
        {"id": _clean_text(row["id"]), "summary": _review_summary(row)}
        for _, row in selected_reviews.iterrows()
    ]
    stage_native_delete_confirmation(editor_key)


@st.dialog("Delete selected Ergonomics reviews?", dismissible=False)
def _confirm_delete() -> None:
    pending = list(st.session_state.get(pending_delete_key) or [])
    st.warning(
        f"Delete {len(pending)} selected review(s)? Their hazard-tag selections will "
        "also be removed. Linked Process steps are not deleted."
    )
    for item in pending:
        st.write(f"- {item['summary']} (Review ID: {item['id']})")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_ergonomics_delete_{scenario_id}"):
        st.session_state.pop(pending_delete_key, None)
        request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Delete",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_confirm_ergonomics_delete_{scenario_id}",
    ):
        try:
            result = delete_ergonomics_reviews(
                project_id, scenario_id, [item["id"] for item in pending]
            )
            record_audit_event(
                project_id,
                "Ergonomics reviews",
                "Bulk delete",
                int(result["row_count"]),
                _clean_text(st.session_state.get("current_editor")),
                {
                    "scenario_id": scenario_id,
                    "review_ids": [item["id"] for item in pending],
                    "hazard_selection_count": result["hazard_selection_count"],
                    "store_timestamp": result["timestamp"],
                },
            )
            st.session_state.pop(pending_delete_key, None)
            request_table_editor_reset(editor_key)
            st.toast(f"Deleted {len(pending)} review(s)", icon=":material/delete:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Choose the Ergonomics review to keep", dismissible=False, width="large")
def _confirm_merge() -> None:
    pending = dict(st.session_state.get(pending_merge_key) or {})
    conflicts = list(pending.get("conflicts") or [])
    st.warning(
        "Both reviews contain real content. Compare their full contents and explicitly "
        "choose the one that will survive each merge. The other review will be deleted."
    )
    decisions: dict[str, str] = {}
    choices_complete = True
    for index, conflict in enumerate(conflicts):
        st.subheader(_review_summary(conflict["candidate"]))
        left, right = st.columns(2)
        with left:
            st.markdown("**Review being linked**")
            st.dataframe(_review_detail_frame(conflict["candidate"]), hide_index=True)
        with right:
            st.markdown("**Existing review for this Process step**")
            st.dataframe(_review_detail_frame(conflict["existing"]), hide_index=True)
        choice = st.radio(
            "Review to keep",
            options=[conflict["candidate_id"], conflict["existing_id"]],
            index=None,
            format_func=lambda value, item=conflict: (
                "Keep the review being linked"
                if value == item["candidate_id"]
                else "Keep the existing Process-step review"
            ),
            key=f"ergonomics_merge_survivor_{scenario_id}_{index}",
        )
        if choice:
            decisions[conflict["candidate_id"]] = choice
        else:
            choices_complete = False
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_ergonomics_merge_{scenario_id}"):
        st.session_state.pop(pending_merge_key, None)
        request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Merge and save",
        type="primary",
        icon=":material/merge:",
        disabled=not choices_complete,
        key=f"destructive_confirm_ergonomics_merge_{scenario_id}",
    ):
        try:
            _save_rows(
                list(pending.get("rows") or []),
                list(pending.get("candidate_ids") or []),
                decisions,
            )
        except ValueError as exc:
            st.error(str(exc))


if st.session_state.get(pending_delete_key):
    _confirm_delete()
elif st.session_state.get(pending_merge_key):
    _confirm_merge()

if footer.save_and_refresh:
    if not selected_reviews.empty:
        st.warning("Clear selected rows before saving Ergonomics review edits.")
    else:
        edited = drop_untouched_new_rows(
            edited,
            identifying_columns=[
                "work_element_id",
                "status",
                "risk_classification",
                "reviewer",
                "hazard_option_ids",
                "notes",
                "requested_due_date",
            ],
        )
        combined = merge_filtered_edits(reviews, visible_reviews, edited)
        rows = _normalized_rows(combined)
        original_work_by_id = {
            _clean_text(row["id"]): _clean_text(row["work_element_id"])
            for _, row in reviews.iterrows()
        }
        candidate_ids = [
            row["id"]
            for row in rows
            if row["work_element_id"]
            and original_work_by_id.get(row["id"], "") != row["work_element_id"]
        ]
        try:
            plan = ergonomics_review_save_plan(
                project_id, scenario_id, rows, candidate_ids
            )
            if plan["conflicts"]:
                st.session_state[pending_merge_key] = {
                    "rows": rows,
                    "candidate_ids": candidate_ids,
                    "conflicts": plan["conflicts"],
                }
                st.rerun()
            _save_rows(rows, candidate_ids)
        except ValueError as exc:
            st.error(str(exc))


with st.expander("History", icon=":material/history:"):
    history = ergonomics_review_audit_history(project_id, scenario_id, limit=50)
    if history.empty:
        st.caption("No Ergonomics review history has been recorded yet.")
    else:
        selectable_dataframe(
            history.drop(columns=["details"], errors="ignore"),
            key=f"ergonomics_reviews_history_{project_id}_{scenario_id}",
            hide_index=True,
            column_config={
                "action": "Action",
                "row_count": "Rows",
                "editor_name": "Editor",
                "created_at": st.column_config.DatetimeColumn(
                    "When", format="MMM DD, YYYY HH:mm"
                ),
            },
        )
