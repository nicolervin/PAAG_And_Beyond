from __future__ import annotations

import base64
from datetime import date, datetime
import hashlib
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.clipboard_image import clipboard_image, decode_clipboard_image
from utils.image_annotator import decode_data_url, image_annotator
from utils.equipment_store import conveyor_zones, scenario_pitches_ergonomics_geometry
from utils.equipment_ui import render_functional_equipment_tab
from utils.ergonomics_slide_visual import (
    render_ergonomics_presentation_deck,
    render_ergonomics_slide,
    render_printable_ergonomics_deck,
)
from utils.time_units import format_seconds
from utils.scope_ui import page_title_with_scope
from utils.store import (
    ERGONOMICS_RISK_CLASSIFICATIONS,
    ERGONOMICS_REVIEW_STATUSES,
    create_legacy_ergonomics_review,
    create_or_get_ergonomic_hazard_option,
    delete_ergonomics_reviews,
    delete_ergonomics_visual_media,
    delete_unlinked_ergonomics_reviews,
    ensure_default_ergonomic_hazard_options,
    ergonomic_hazard_options,
    ergonomics_review_audit_history,
    ergonomics_review_save_plan,
    ergonomics_reviews,
    ergonomics_slide_summary,
    ergonomics_work_elements,
    format_eastern_timestamp,
    get_ergonomics_visual_media,
    get_planning_scenario,
    link_legacy_concern_to_work_element,
    record_audit_event,
    save_ergonomic_hazard_option_rows,
    save_ergonomics_review_rows,
    save_ergonomics_visual_media,
    update_ergonomics_visual_annotations,
    update_ergonomics_visual_media,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    can_redo_last_table_edit,
    can_undo_last_table_edit,
    last_table_undo_redo_message,
    has_unsaved_table_changes,
    redo_last_table_edit,
    undo_last_table_edit,
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
    guarded_tabs,
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

reviews = ergonomics_reviews(project_id, scenario_id).copy()
work_elements = ergonomics_work_elements(project_id, scenario_id)

# Top 5-card readiness banner
total_reviews = len(reviews)
if not reviews.empty:
    closed_count = int(
        sum(1 for s in reviews["status"] if _clean_text(s).startswith("Closed"))
    )
    in_review_count = int(
        sum(
            1
            for s in reviews["status"]
            if _clean_text(s) in ("Pending", "Validation")
        )
    )
    open_count = int(
        sum(
            1
            for s in reviews["status"]
            if _clean_text(s) in ("Started", "Open", "")
        )
    )
    active_open_count = total_reviews - closed_count
    today_ts = pd.Timestamp(date.today())
    overdue_count = 0
    for _, r in reviews.iterrows():
        if not _clean_text(r.get("status")).startswith("Closed"):
            due_dt = pd.to_datetime(r.get("requested_due_date"), errors="coerce")
            if pd.notna(due_dt) and due_dt < today_ts:
                overdue_count += 1

    red_count = int(
        sum(1 for rc in reviews["risk_classification"] if _clean_text(rc) == "Red")
    )
    fav_red_count = int(
        sum(
            1
            for rc in reviews["risk_classification"]
            if _clean_text(rc) == "Favorable Red"
        )
    )
    fav_green_count = int(
        sum(
            1
            for rc in reviews["risk_classification"]
            if _clean_text(rc) == "Favorable Green"
        )
    )
    green_count = int(
        sum(1 for rc in reviews["risk_classification"] if _clean_text(rc) == "Green")
    )
    open_red_count = int(
        sum(
            1
            for s, rc in zip(reviews["status"], reviews["risk_classification"])
            if not _clean_text(s).startswith("Closed") and _clean_text(rc) == "Red"
        )
    )
    open_fav_red_count = int(
        sum(
            1
            for s, rc in zip(reviews["status"], reviews["risk_classification"])
            if not _clean_text(s).startswith("Closed")
            and _clean_text(rc) == "Favorable Red"
        )
    )
    open_high_risk = open_red_count + open_fav_red_count

    linked_reviews = int(
        sum(1 for w in reviews["work_element_id"] if _clean_text(w))
    )
    unlinked_reviews = total_reviews - linked_reviews
    assessed_steps = len(
        {
            _clean_text(w)
            for w, rc in zip(reviews["work_element_id"], reviews["risk_classification"])
            if _clean_text(w) and _clean_text(rc) not in ("", "Not yet assessed")
        }
    )

    hazard_tagged_count = int(
        sum(1 for h in reviews["hazard_option_ids"] if len(_id_list(h)) > 0)
    )
    unassigned_open = int(
        sum(
            1
            for s, rev in zip(reviews["status"], reviews["reviewer"])
            if not _clean_text(s).startswith("Closed") and not _clean_text(rev)
        )
    )
    hazard_counts: dict[str, int] = {}
    for h_list in reviews.get("hazard_labels", []):
        if isinstance(h_list, (list, tuple, set)):
            for h_lbl in h_list:
                clean_h = _clean_text(h_lbl)
                if clean_h:
                    hazard_counts[clean_h] = hazard_counts.get(clean_h, 0) + 1
    if hazard_counts:
        top_raw = max(hazard_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
        top_short = top_raw.split("(")[0].strip() or top_raw
        if len(top_short) > 22:
            top_short = top_short[:20].rstrip() + "…"
        top_hazard_label = f"{top_short} ({hazard_counts[top_raw]})"
    else:
        top_hazard_label = "None tagged"
else:
    closed_count = 0
    in_review_count = 0
    open_count = 0
    active_open_count = 0
    overdue_count = 0
    red_count = 0
    fav_red_count = 0
    fav_green_count = 0
    green_count = 0
    open_red_count = 0
    open_fav_red_count = 0
    open_high_risk = 0
    linked_reviews = 0
    unlinked_reviews = 0
    assessed_steps = 0
    hazard_tagged_count = 0
    unassigned_open = 0
    top_hazard_label = "None tagged"

closure_pct = (closed_count / total_reviews * 100.0) if total_reviews > 0 else 100.0
total_steps = len(work_elements)
step_cov_pct = (assessed_steps / total_steps * 100.0) if total_steps > 0 else 0.0

ergo_zones_df = conveyor_zones(project_id, scenario_id)
ergo_zone_count = len(ergo_zones_df)
pitches_geom_df = scenario_pitches_ergonomics_geometry(project_id, scenario_id)
if not pitches_geom_df.empty:
    elev_pitch_count = int(
        sum(
            1
            for _, pr in pitches_geom_df.iterrows()
            if float(pr.get("platform_height_in") or 0.0) > 0.0
            or float(pr.get("pit_depth_in") or 0.0) > 0.0
        )
    )
else:
    elev_pitch_count = 0

ergo_kpi_cols = st.columns(5)

# Card 1: Ergonomics review status & closure
if total_reviews == 0:
    close_val = "🟢 0 open"
    close_delta = "No ergonomic concerns logged"
    close_delta_color = "off"
else:
    if active_open_count == 0 and overdue_count == 0:
        close_icon = "🟢"
        close_delta_color = "normal"
    elif overdue_count > 0 or closure_pct < 50.0:
        close_icon = "🔴" if overdue_count > 0 else "🟡"
        close_delta_color = "inverse" if overdue_count > 0 else "off"
    else:
        close_icon = "🟡"
        close_delta_color = "off"
    close_val = f"{close_icon} {closure_pct:.0f}% ({closed_count}/{total_reviews})"
    close_delta = f"{open_count} started/open · {in_review_count} pending/val · {overdue_count} overdue"

ergo_kpi_cols[0].metric(
    "Ergonomics review closure",
    close_val,
    delta=close_delta,
    delta_color=close_delta_color,
    help=(
        "Active-scenario Ergonomics review progress across Open, In Review, "
        "and Closed statuses, highlighting non-closed reviews past their "
        "requested due date."
    ),
)

# Card 2: Ergonomic risk profile
if open_high_risk == 0:
    risk_icon = "🟢"
    risk_delta_color = "normal" if total_reviews > 0 else "off"
elif open_red_count > 0:
    risk_icon = "🔴"
    risk_delta_color = "inverse"
else:
    risk_icon = "🟡"
    risk_delta_color = "inverse"

ergo_kpi_cols[1].metric(
    "Ergonomic risk profile",
    f"{risk_icon} {open_high_risk} high-risk",
    delta=(
        f"{red_count} Red · {fav_red_count} Fav. Red · "
        f"{fav_green_count} Fav. Green · {green_count} Green"
    ),
    delta_color=risk_delta_color,
    help=(
        "Breakdown of Ergonomics reviews by controlled risk classification "
        "(Red, Favorable Red, Favorable Green, Green), highlighting open Red "
        "and Favorable Red items requiring mitigation."
    ),
)

# Card 3: Process step linkage & coverage
if total_reviews == 0:
    link_icon = "🟡"
    link_delta = f"0 unlinked · 0/{total_steps} Process steps (0%)"
    link_delta_color = "off"
elif unlinked_reviews == 0:
    link_icon = "🟢"
    link_delta = f"0 unlinked · {assessed_steps}/{total_steps} steps ({step_cov_pct:.0f}%)"
    link_delta_color = "normal"
else:
    link_icon = "🟡"
    link_delta = (
        f"{unlinked_reviews} unlinked legacy · "
        f"{assessed_steps}/{total_steps} steps ({step_cov_pct:.0f}%)"
    )
    link_delta_color = "inverse"

ergo_kpi_cols[2].metric(
    "Process step linkage",
    f"{link_icon} {linked_reviews} / {total_reviews}",
    delta=link_delta,
    delta_color=link_delta_color,
    help=(
        "Tracks how many Ergonomics reviews are linked to an active Process at a "
        "Glance step versus preserved as unlinked legacy concerns, plus overall "
        "Process step assessment coverage."
    ),
)

# Card 4: Top hazards & reviewer assignment
if total_reviews == 0:
    haz_icon = "🟡"
    haz_delta_color = "off"
elif hazard_tagged_count == total_reviews and unassigned_open == 0:
    haz_icon = "🟢"
    haz_delta_color = "normal"
else:
    haz_icon = "🟡"
    haz_delta_color = "inverse" if unassigned_open > 0 else "off"

ergo_kpi_cols[3].metric(
    "Top hazards & reviewers",
    f"{haz_icon} {hazard_tagged_count} / {total_reviews}",
    delta=f"{unassigned_open} unassigned open · Top: {top_hazard_label}",
    delta_color=haz_delta_color,
    help=(
        "Completeness of ergonomic hazard tagging, reviewer assignment on open "
        "reviews, and the most frequently cited ergonomic hazard in the active scenario."
    ),
)

# Card 5: Scenario takt & workstation geometry
takt_s = float(scenario.get("takt_time_s") or 0.0)
takt_icon = "🟢" if takt_s > 0 else "🟡"
takt_str = format_seconds(scenario["takt_time_s"], scenario["takt_time_unit"])
ergo_kpi_cols[4].metric(
    "Scenario takt & geometry",
    f"{takt_icon} {takt_str}",
    delta=(
        f"{ergo_zone_count} conveyor zone{'s' if ergo_zone_count != 1 else ''} · "
        f"{elev_pitch_count} pitch{'es' if elev_pitch_count != 1 else ''} w/ platform/pit"
    ),
    delta_color="normal" if (ergo_zone_count > 0 or elev_pitch_count > 0) else "off",
    help=(
        "Use the active scenario's takt time to judge whether frequency-driven "
        "ergonomic risks apply under this timing, alongside Conveyor Zone and "
        "workstation platform/pit elevation coverage."
    ),
)

review_tab, equipment_tab = guarded_tabs(
    ["Review", "Equipment"],
    key=f"ergonomics_page_tabs_{project_id}",
)
if equipment_tab.open:
    with equipment_tab:
        render_functional_equipment_tab(
            project_id, scenario_id, "Ergonomics"
        )
    st.stop()
review_tab.__enter__()

logical_editor_key = f"ergonomics_reviews_editor_{project_id}_{scenario_id}"
editor_key = apply_pending_table_editor_reset(logical_editor_key)
pending_delete_key = f"ergonomics_reviews_pending_delete_{project_id}_{scenario_id}"
pending_merge_key = f"ergonomics_reviews_pending_merge_{project_id}_{scenario_id}"

if reviews.empty:
    reviews = pd.DataFrame(
        {
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "scenario_id": pd.Series(dtype="string"),
            "work_element_id": pd.Series(dtype="string"),
            "process_part_option_id": pd.Series(dtype="string"),
            "legacy_description": pd.Series(dtype="string"),
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

if "legacy_description" not in reviews.columns:
    reviews["legacy_description"] = ""
reviews["legacy_description"] = reviews["legacy_description"].fillna("").astype(str)
reviews["link_filter"] = pd.Series(
    [
        "Unlinked" if not _clean_text(value) else "Linked"
        for value in reviews["work_element_id"]
    ],
    index=reviews.index,
    dtype="string",
)
reviews["link_status"] = pd.Series(
    [[value] for value in reviews["link_filter"]],
    index=reviews.index,
    dtype="object",
)
reviews["hazard_option_ids"] = pd.Series(
    [_id_list(value) for value in reviews["hazard_option_ids"]],
    index=reviews.index,
    dtype="object",
)
reviews["requested_due_date"] = pd.to_datetime(
    reviews["requested_due_date"], errors="coerce"
)
reviews["view_slide"] = "View Slide"
reviews["work_element_label"] = pd.Series(
    [
        (
            _clean_text(we_lbl)
            or (
                f"Unlinked · {_clean_text(leg_desc)}"
                if _clean_text(leg_desc)
                else "Unlinked — no Process step"
            )
        )
        if not _clean_text(we_id)
        else _clean_text(we_lbl)
        for we_id, we_lbl, leg_desc in zip(
            reviews["work_element_id"],
            reviews["work_element_label"],
            reviews["legacy_description"],
        )
    ],
    index=reviews.index,
    dtype="string",
)

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
if hazards.empty:
    ensure_default_ergonomic_hazard_options(project_id)
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

top_actions = st.container(horizontal=True)
if top_actions.button(
    "Add legacy concern",
    icon=":material/add:",
    key=f"add_legacy_concern_btn_{scenario_id}",
):
    st.session_state[f"show_add_legacy_dialog_{scenario_id}"] = True

unlinked_count = int((reviews["link_filter"] == "Unlinked").sum())
if unlinked_count > 0:
    if top_actions.button(
        "Link legacy concern",
        icon=":material/link:",
        key=f"link_legacy_concern_btn_{scenario_id}",
    ):
        st.session_state[f"show_link_legacy_dialog_{scenario_id}"] = True

    if top_actions.button(
        f"Delete unlinked reviews ({unlinked_count})",
        icon=":material/delete_sweep:",
        key=f"destructive_delete_unlinked_btn_{scenario_id}",
    ):
        st.session_state[f"show_delete_unlinked_dialog_{scenario_id}"] = True

if top_actions.button(
    "Manage hazard tags",
    icon=":material/label:",
    key=f"manage_hazards_btn_{project_id}",
):
    st.session_state[f"show_manage_hazards_dialog_{project_id}"] = True

visible_reviews = filter_table(
    reviews,
    key=f"ergonomics_reviews_filters_{project_id}_{scenario_id}",
    dropdown_columns=["link_filter", "status", "risk_classification", "reviewer"],
    search_columns=["work_element_label", "legacy_description", "pitch", "reviewer", "notes", "hazard_labels"],
    labels={
        "link_filter": "Link status",
        "status": "Status",
        "risk_classification": "Risk classification",
        "reviewer": "Reviewer",
    },
    reset_widget_keys=[editor_key],
)


def open_ergo_slide() -> None:
    click = st.session_state.get(f"ergo_reviews_view_slide_{scenario_id}")
    if click and 0 <= click.get("row", -1) < len(reviews_for_editing):
        row_id = str(reviews_for_editing.iloc[click["row"]]["id"]).strip()
        st.session_state[f"ergo_slide_selected_review_{scenario_id}"] = row_id
        st.session_state["ergo_scroll_to_slides"] = True


reviews_for_editing = direct_entry_editor_rows(
    visible_reviews,
    editor_key=editor_key,
    sort_columns=[
        "link_filter",
        "work_element_label",
        "legacy_description",
        "status",
        "risk_classification",
        "reviewer",
        "requested_due_date",
        "updated_at",
    ],
    labels={
        "link_filter": "Link status",
        "work_element_label": "Process step description",
        "legacy_description": "Legacy concern / title",
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
        "view_slide",
        "work_element_id",
        "legacy_description",
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
        "view_slide": st.column_config.ButtonColumn(
            "Slide",
            help="Navigate directly to this review's 16:9 Ergonomics slide below.",
            key=f"ergo_reviews_view_slide_{scenario_id}",
            on_click=open_ergo_slide,
            type="secondary",
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
        "legacy_description": st.column_config.TextColumn(
            "Legacy concern / title",
            help="Title or description of legacy ergonomics concern before linking to a Process step.",
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
    data=lambda: dataframe_to_excel(
        visible_reviews[
            [
                "link_filter",
                "work_element_label",
                "legacy_description",
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
                "legacy_description": "Legacy concern / title",
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
                "legacy_description": _clean_text(values.get("legacy_description")),
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
    legacy = _clean_text(values.get("legacy_description"))
    if work_id:
        return work_label_by_id.get(work_id, work_id)
    if legacy:
        return f"Unlinked · {legacy}"
    return "Unlinked — no Process step"


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
                format_eastern_timestamp(_clean_text(values.get("created_at"))) or "Not saved yet",
                format_eastern_timestamp(_clean_text(values.get("updated_at"))) or "Not saved yet",
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
    _ergo_parts: list[str] = []
    if result.get("created_ids"):
        _ergo_parts.append(f"{len(result['created_ids'])} created")
    if result.get("updated_ids"):
        _ergo_parts.append(f"{len(result['updated_ids'])} updated")
    if result.get("discarded_ids"):
        _ergo_parts.append(f"{len(result['discarded_ids'])} merged/discarded")
    _ergo_detail = f" ({', '.join(_ergo_parts)})" if _ergo_parts else ""
    st.toast(f"Saved {int(result['row_count'])} Ergonomics review(s){_ergo_detail}", icon=":material/check_circle:")
    st.rerun()


selected_reviews = native_selected_rows(reviews_for_editing, editor_key=editor_key)
if not selected_reviews.empty:
    st.session_state[pending_delete_key] = [
        {"id": _clean_text(row["id"]), "summary": _review_summary(row)}
        for _, row in selected_reviews.iterrows()
    ]
    stage_native_delete_confirmation(editor_key)


@st.dialog("Add legacy Ergonomics concern", dismissible=False)
def _add_legacy_dialog() -> None:
    st.markdown(
        "Create an unlinked Ergonomics concern for legacy or pre-PAAG items that can later be paired to a Process step."
    )
    legacy_title = st.text_input(
        "Concern title / description *",
        key=f"legacy_input_title_{scenario_id}",
    )
    col_s1, col_s2 = st.columns(2)
    init_status = col_s1.selectbox(
        "Status",
        list(ERGONOMICS_REVIEW_STATUSES),
        index=0,
        key=f"legacy_input_status_{scenario_id}",
    )
    init_risk = col_s2.selectbox(
        "Risk classification",
        list(ERGONOMICS_RISK_CLASSIFICATIONS),
        index=0,
        key=f"legacy_input_risk_{scenario_id}",
    )
    col_s3, col_s4 = st.columns(2)
    init_reviewer = col_s3.text_input(
        "Reviewer",
        value=_clean_text(st.session_state.get("current_editor")),
        key=f"legacy_input_reviewer_{scenario_id}",
    )
    init_due_date = col_s4.date_input(
        "Requested due date (optional)",
        value=None,
        key=f"legacy_input_due_{scenario_id}",
    )
    init_hazards = st.multiselect(
        "Hazard tags",
        options=hazard_options,
        format_func=lambda value: hazard_label_by_id.get(value, value),
        key=f"legacy_input_hazards_{scenario_id}",
    )
    new_hazards_input = st.text_input(
        "Add new hazard tag(s)",
        placeholder="e.g. Awkward reaching, Sharp edge (comma-separated)",
        help="Type new hazard tags separated by commas. They will be added to the project and tagged to this concern.",
        key=f"legacy_new_hazards_input_{scenario_id}",
    )
    init_notes = st.text_area("Notes", key=f"legacy_input_notes_{scenario_id}")

    act_row = st.container(horizontal=True)
    if act_row.button("Cancel", key=f"cancel_add_legacy_{scenario_id}"):
        st.session_state.pop(f"show_add_legacy_dialog_{scenario_id}", None)
        st.rerun()
    if act_row.button(
        "Save concern",
        type="primary",
        icon=":material/check:",
        key=f"save_add_legacy_{scenario_id}",
    ):
        clean_title = legacy_title.strip()
        if not clean_title:
            st.error("Please enter a concern title or description.")
            return
        try:
            assigned_hazard_ids = list(init_hazards)
            if new_hazards_input.strip():
                for tag in new_hazards_input.split(","):
                    tag_clean = tag.strip()
                    if tag_clean:
                        tag_id = create_or_get_ergonomic_hazard_option(project_id, tag_clean)
                        if tag_id not in assigned_hazard_ids:
                            assigned_hazard_ids.append(tag_id)
            res = create_legacy_ergonomics_review(
                project_id,
                scenario_id,
                clean_title,
                status=init_status,
                risk_classification=init_risk,
                reviewer=init_reviewer,
                hazard_option_ids=assigned_hazard_ids,
                notes=init_notes,
                requested_due_date=init_due_date.isoformat() if init_due_date else None,
                editor_name=_clean_text(st.session_state.get("current_editor")),
            )
            st.session_state[f"ergo_slide_selected_review_{scenario_id}"] = res["id"]
            st.session_state["ergo_scroll_to_slides"] = True
            st.session_state.pop(f"show_add_legacy_dialog_{scenario_id}", None)
            request_table_editor_reset(editor_key)
            st.toast("Legacy Ergonomics concern created", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Delete unlinked Ergonomics reviews?", dismissible=False)
def _delete_unlinked_dialog() -> None:
    unlinked_df = reviews[
        reviews["work_element_id"].isna()
        | reviews["work_element_id"].astype(str).str.strip().eq("")
    ]
    if unlinked_df.empty:
        st.info("No unlinked Ergonomics reviews found.")
        if st.button("Close", key=f"close_empty_del_unlinked_{scenario_id}"):
            st.session_state.pop(f"show_delete_unlinked_dialog_{scenario_id}", None)
            st.rerun()
        return

    st.warning(
        f"Permanently remove {len(unlinked_df)} unlinked review(s)? "
        "Hazard selections and visual aids will also be deleted."
    )
    unlinked_options = {
        str(row["id"]): (
            f"{_clean_text(row.get('legacy_description')) or _clean_text(row.get('reviewer')) or 'Untitled review'} "
            f"({_clean_text(row.get('risk_classification')) or 'Not assessed'}, ID: {str(row['id'])[:8]})"
        )
        for _, row in unlinked_df.iterrows()
    }
    selected_to_delete = st.multiselect(
        "Select reviews to delete (leave all selected to purge all unlinked)",
        options=list(unlinked_options.keys()),
        default=list(unlinked_options.keys()),
        format_func=lambda rid: unlinked_options.get(rid, rid),
        key=f"unlinked_delete_selection_{scenario_id}",
    )
    act_row = st.container(horizontal=True)
    if act_row.button("Cancel", key=f"cancel_del_unlinked_{scenario_id}"):
        st.session_state.pop(f"show_delete_unlinked_dialog_{scenario_id}", None)
        st.rerun()
    if act_row.button(
        f"Delete selected ({len(selected_to_delete)})",
        type="primary",
        icon=":material/delete_sweep:",
        key=f"destructive_confirm_del_unlinked_{scenario_id}",
        disabled=len(selected_to_delete) == 0,
    ):
        try:
            res = delete_unlinked_ergonomics_reviews(
                project_id,
                scenario_id,
                review_ids=selected_to_delete,
                editor_name=_clean_text(st.session_state.get("current_editor")),
            )
            st.session_state.pop(f"show_delete_unlinked_dialog_{scenario_id}", None)
            request_table_editor_reset(editor_key)
            st.toast(
                f"Deleted {res.get('row_count', len(selected_to_delete))} unlinked review(s)",
                icon=":material/delete:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Manage Ergonomics hazard tags", dismissible=False)
def _manage_hazards_dialog() -> None:
    st.caption("Manage reusable Ergonomics hazard tags available across this project.")
    cur_hazards = ergonomic_hazard_options(project_id)

    st.markdown("##### Add new hazard tag")
    add_col1, add_col2 = st.columns([3, 1], vertical_alignment="bottom")
    new_tag_label = add_col1.text_input(
        "Hazard tag label",
        placeholder="e.g. Excessive pinch force",
        key=f"new_hazard_tag_input_{project_id}",
    )
    if add_col2.button("Add tag", icon=":material/add:", key=f"btn_add_hazard_{project_id}", width="stretch"):
        if not new_tag_label.strip():
            st.error("Please enter a label for the hazard tag.")
        else:
            try:
                create_or_get_ergonomic_hazard_option(project_id, new_tag_label.strip())
                st.toast(f"Added hazard tag '{new_tag_label.strip()}'", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.markdown("##### Active hazard tags")
    if cur_hazards.empty:
        st.info("No hazard tags created yet.")
        if st.button("Seed standard hazard tags", icon=":material/auto_fix:", key=f"seed_hazards_{project_id}"):
            ensure_default_ergonomic_hazard_options(project_id)
            st.toast("Standard hazard tags created", icon=":material/check_circle:")
            st.rerun()
    else:
        tags_editor_key = apply_pending_table_editor_reset(f"hazard_options_editor_{project_id}")
        edited_tags = st.data_editor(
            cur_hazards[["id", "label", "active", "selection_count"]],
            key=tags_editor_key,
            hide_index=True,
            column_config={
                "id": None,
                "label": st.column_config.TextColumn("Tag label", required=True),
                "active": st.column_config.CheckboxColumn("Active"),
                "selection_count": st.column_config.NumberColumn("Used in reviews", disabled=True),
            },
            width="stretch",
        )

        edit_c1, edit_c2, edit_c3 = st.columns(3)
        if edit_c1.button(
            "Undo last edit",
            icon=":material/undo:",
            disabled=not can_undo_last_table_edit(tags_editor_key),
            help="Revert the most recent cell edit while keeping earlier unsaved changes.",
            key=f"undo_last_hazard_tags_{project_id}",
            width="stretch",
        ):
            if undo_last_table_edit(tags_editor_key):
                st.toast(last_table_undo_redo_message(tags_editor_key, default="Reverted the last cell edit."), icon=":material/undo:")
                st.rerun()
        if edit_c2.button(
            "Redo last edit",
            icon=":material/redo:",
            disabled=not can_redo_last_table_edit(tags_editor_key),
            help="Reapply the most recently undone cell edit.",
            key=f"redo_last_hazard_tags_{project_id}",
            width="stretch",
        ):
            if redo_last_table_edit(tags_editor_key):
                st.toast(last_table_undo_redo_message(tags_editor_key, default="Reapplied the last undone cell edit."), icon=":material/redo:")
                st.rerun()
        if edit_c3.button(
            "Discard all edits",
            icon=":material/restart_alt:",
            disabled=not has_unsaved_table_changes(tags_editor_key),
            help="Discard all unsaved changes in this table and restore the last saved values.",
            key=f"discard_hazard_tags_{project_id}",
            width="stretch",
        ):
            request_table_editor_reset(tags_editor_key)
            st.toast("Discarded unsaved hazard tag edits.", icon=":material/restart_alt:")
            st.rerun()

        btn_c1, btn_c2 = st.columns(2)
        if btn_c1.button("Save changes", type="primary", icon=":material/save:", key=f"save_hazard_tags_{project_id}", width="stretch"):
            try:
                save_ergonomic_hazard_option_rows(project_id, edited_tags)
                request_table_editor_reset(tags_editor_key)
                st.toast("Hazard tags updated", icon=":material/check_circle:")
                st.session_state.pop(f"show_manage_hazards_dialog_{project_id}", None)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if btn_c2.button("Close", key=f"close_hazard_tags_{project_id}", width="stretch"):
            st.session_state.pop(f"show_manage_hazards_dialog_{project_id}", None)
            st.rerun()


@st.dialog("Link Legacy concern to Process Step", dismissible=False)
def _link_legacy_dialog() -> None:
    st.caption(
        "Pair an unlinked legacy Ergonomics concern with a Process step review. "
        "Hazard tags, solutions, notes, and legacy titles from both will be preserved and merged."
    )
    unlinked_df = reviews[
        reviews["work_element_id"].isna()
        | reviews["work_element_id"].astype(str).str.strip().eq("")
    ]
    if unlinked_df.empty:
        st.info("There are no unlinked legacy concerns to link.")
        if st.button("Close", key=f"close_empty_link_{scenario_id}"):
            st.session_state.pop(f"show_link_legacy_dialog_{scenario_id}", None)
            st.rerun()
        return

    unlinked_map: dict[str, dict] = {}
    for _, row in unlinked_df.iterrows():
        r_id = _clean_text(row["id"])
        desc = _clean_text(row.get("legacy_description")) or _clean_text(row.get("notes")) or "Legacy concern"
        risk = _clean_text(row.get("risk_classification")) or "Not yet assessed"
        unlinked_map[r_id] = {
            "label": f"{desc} [{risk}]",
            "row": dict(row),
        }

    selected_legacy_id = st.session_state.get(f"ergo_link_target_legacy_id_{scenario_id}")
    if selected_legacy_id not in unlinked_map:
        selected_legacy_id = list(unlinked_map.keys())[0]

    chosen_legacy_id = st.selectbox(
        "Select legacy concern",
        options=list(unlinked_map.keys()),
        index=list(unlinked_map.keys()).index(selected_legacy_id),
        format_func=lambda vid: unlinked_map[vid]["label"],
        key=f"select_legacy_concern_{scenario_id}",
    )
    legacy_info = unlinked_map[chosen_legacy_id]["row"]

    step_options = [w_id for w_id in work_label_by_id.keys() if w_id]
    if not step_options:
        st.warning("No Process steps exist in this scenario yet. Create Process steps in PAAG first.")
        if st.button("Close", key=f"close_no_steps_link_{scenario_id}"):
            st.session_state.pop(f"show_link_legacy_dialog_{scenario_id}", None)
            st.rerun()
        return

    chosen_step_id = st.selectbox(
        "Select target Process step",
        options=step_options,
        format_func=lambda vid: work_label_by_id.get(vid, vid),
        key=f"select_target_step_{scenario_id}",
    )

    target_reviews = reviews[reviews["work_element_id"] == chosen_step_id]
    target_info = dict(target_reviews.iloc[0]) if not target_reviews.empty else {}

    st.markdown("---")
    st.markdown("##### Comparison preview")
    col_leg, col_step = st.columns(2)

    with col_leg:
        st.markdown("**Legacy concern to link**")
        l_desc = _clean_text(legacy_info.get("legacy_description")) or "—"
        l_risk = _clean_text(legacy_info.get("risk_classification")) or "Not yet assessed"
        l_status = _clean_text(legacy_info.get("status")) or "Started"
        l_notes = _clean_text(legacy_info.get("notes")) or "—"
        l_hazards = [
            hazard_label_by_id.get(hid, hid)
            for hid in _id_list(legacy_info.get("hazard_option_ids"))
        ]
        st.markdown(f"**Title:** {l_desc}")
        st.markdown(f"**Risk:** {l_risk} | **Status:** {l_status}")
        st.markdown(f"**Hazards:** {', '.join(l_hazards) if l_hazards else '—'}")
        st.caption(f"Notes: {l_notes}")

    with col_step:
        st.markdown("**Target Process step**")
        s_label = work_label_by_id.get(chosen_step_id, chosen_step_id)
        s_risk = _clean_text(target_info.get("risk_classification")) or "Not yet assessed"
        s_status = _clean_text(target_info.get("status")) or "Started"
        s_notes = _clean_text(target_info.get("notes")) or "—"
        s_hazards = [
            hazard_label_by_id.get(hid, hid)
            for hid in _id_list(target_info.get("hazard_option_ids"))
        ]
        st.markdown(f"**Step:** {s_label}")
        st.markdown(f"**Current Risk:** {s_risk} | **Status:** {s_status}")
        st.markdown(f"**Hazards:** {', '.join(s_hazards) if s_hazards else '—'}")
        st.caption(f"Existing notes: {s_notes}")

    st.info(
        "Merging preserves and combines hazard tags, notes, and solutions from both records into a single unified review for the Process step."
    )

    btn_row = st.container(horizontal=True)
    if btn_row.button("Cancel", key=f"cancel_link_legacy_{scenario_id}"):
        st.session_state.pop(f"show_link_legacy_dialog_{scenario_id}", None)
        st.session_state.pop(f"ergo_link_target_legacy_id_{scenario_id}", None)
        st.rerun()

    if btn_row.button(
        "Confirm link & merge",
        type="primary",
        icon=":material/link:",
        key=f"confirm_link_legacy_{scenario_id}",
    ):
        try:
            res = link_legacy_concern_to_work_element(
                project_id=project_id,
                scenario_id=scenario_id,
                legacy_review_id=chosen_legacy_id,
                target_work_element_id=chosen_step_id,
                editor_name=_clean_text(st.session_state.get("current_editor")),
            )
            surviving_id = res["surviving_id"]
            st.session_state[f"ergo_slide_selected_review_{scenario_id}"] = surviving_id
            st.session_state["ergo_scroll_to_slides"] = True
            st.session_state.pop(f"show_link_legacy_dialog_{scenario_id}", None)
            st.session_state.pop(f"ergo_link_target_legacy_id_{scenario_id}", None)
            request_table_editor_reset(editor_key)
            st.toast("Legacy concern linked to Process step!", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


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


@st.dialog("Ergonomics Review Presentation Mode", width="large")
def ergo_presentation_dialog(
    project_id: str,
    scenario_id: str,
    review_options: list[tuple[str, str]],
    initial_review_id: str = "",
) -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stDialog"] div[role="dialog"] {
            width: 96vw !important;
            max-width: 96vw !important;
            max-height: 96vh !important;
        }
        div[data-testid="stDialog"] div[data-testid="stDialogHeader"] {
            padding-bottom: 2px !important;
        }
        div[data-testid="stDialog"] button[aria-label="Close"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    review_ids = [rid for rid, _ in review_options]
    if not review_ids:
        st.info("No Ergonomics reviews available to present.")
        if st.button("Close"):
            st.session_state[f"ergo_present_active_{scenario_id}"] = False
            st.rerun()
        return

    slides_data = []
    for rid, rlabel in review_options:
        try:
            summary = ergonomics_slide_summary(project_id, scenario_id, rid)
            s_html = render_ergonomics_slide(summary, presentation_mode=True)
            slides_data.append({
                "review_id": rid,
                "review_label": rlabel,
                "slide_html": s_html,
            })
        except Exception:
            continue

    deck_html = render_ergonomics_presentation_deck(
        slides_data=slides_data,
        initial_review_id=initial_review_id,
    )
    st.html(deck_html)

    cols = st.columns([8, 2])
    with cols[1]:
        if st.button("✕ Close Presentation", key=f"close_ergo_pres_{scenario_id}", width="stretch"):
            st.session_state[f"ergo_present_active_{scenario_id}"] = False
            st.rerun()


@st.dialog("Export & Print Ergonomics Slides", width="large")
def ergo_print_dialog(
    project_id: str,
    scenario_id: str,
    scenario_name: str,
    review_options: list[tuple[str, str]],
    selected_review_id: str,
) -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stDialog"] button[aria-label="Close"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### Export & Print Ergonomics Assessment Slides")
    st.caption("Generate high-resolution printable 16:9 slides for engineering reviews or physical shop-floor postings.")

    ctrl_c1, ctrl_c2, ctrl_c3 = st.columns(3)
    with ctrl_c1:
        print_scope = st.radio(
            "Print Scope",
            options=["current", "all"],
            format_func=lambda s: "Current review slide only" if s == "current" else f"All reviews ({len(review_options)} slides)",
            key=f"ergo_print_scope_{scenario_id}",
        )
    with ctrl_c2:
        paper_size = st.selectbox(
            "Paper Size",
            options=["tabloid", "letter"],
            format_func=lambda s: "11 × 17 in (Tabloid Landscape)" if s == "tabloid" else "8.5 × 11 in (Letter Landscape)",
            key=f"ergo_print_paper_{scenario_id}",
        )
    with ctrl_c3:
        image_fit = st.selectbox(
            "Visual Aids Fit",
            options=["contain", "fill", "cover"],
            key=f"ergo_print_fit_{scenario_id}",
        )

    target_ids = [selected_review_id] if print_scope == "current" else [rid for rid, _ in review_options]

    slides_html = []
    for rid in target_ids:
        try:
            summary = ergonomics_slide_summary(project_id, scenario_id, rid)
            s_html = render_ergonomics_slide(
                summary,
                print_format=paper_size,
                image_fit=image_fit,
            )
            slides_html.append(s_html)
        except Exception:
            continue

    if not slides_html:
        st.warning("No slides to generate.")
        if st.button("Close"):
            st.session_state[f"ergo_print_active_{scenario_id}"] = False
            st.rerun()
        return

    full_html = render_printable_ergonomics_deck(
        slides_html=slides_html,
        paper_size=paper_size,
        image_fit=image_fit,
        title=f"Ergonomics Assessment - {scenario_name}",
    )

    st.download_button(
        label="📥 Download Printable HTML Deck",
        data=full_html,
        file_name=f"Ergonomics_Slides_{scenario_id}_{paper_size}.html",
        mime="text/html",
        type="primary",
        key=f"download_ergo_html_{scenario_id}",
    )

    b64_html = base64.b64encode(full_html.encode("utf-8")).decode("ascii")
    st.markdown(
        f'<div style="margin-top: 10px;"><a href="data:text/html;base64,{b64_html}" target="_blank" style="display:inline-block; padding:8px 16px; background:#1e40af; color:#ffffff; border-radius:6px; text-decoration:none; font-weight:600;">🖨️ Open Print View in New Tab</a></div>',
        unsafe_allow_html=True,
    )

    st.write("")
    if st.button("Close", key=f"close_ergo_print_{scenario_id}"):
        st.session_state[f"ergo_print_active_{scenario_id}"] = False
        st.rerun()


@st.dialog("Annotate Ergonomics Visual Aid", width="large")
def annotate_existing_ergo_media_dialog(
    project_id: str,
    scenario_id: str,
    media_id: str,
    media_item: dict,
) -> None:
    file_path = Path(media_item.get("file_path", ""))
    orig_path = Path(media_item.get("original_file_path") or str(file_path))
    source_path = orig_path if orig_path.exists() and orig_path.is_file() else file_path

    if not source_path.exists() or not source_path.is_file():
        st.error("Underlying image file could not be found on disk.")
        if st.button("Close"):
            st.session_state.pop(f"ergo_annotate_active_{scenario_id}", None)
            st.rerun()
        return

    st.markdown(f"#### Annotate Visual Aid: {media_item.get('caption') or 'Visual Aid'}")
    st.caption(
        "Crop, rotate in 90° increments, or add directional arrows, callout text boxes, focus boxes/circles, "
        "step number badges (1, 2, 3), and freehand pen markup non-destructively. "
        "Click **💾 Apply & Save Markup** when finished."
    )

    raw_bytes = source_path.read_bytes()
    suffix = source_path.suffix.lower()
    if raw_bytes.startswith(b"\x89PNG"):
        mime = "image/png"
    else:
        mime = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    annotator_res = image_annotator(
        image_data_url=data_url,
        annotations_json=media_item.get("annotations_json") or "",
        key=f"annotator_existing_ergo_{media_id}",
    )

    save_payload = getattr(annotator_res, "save", None)
    if save_payload:
        try:
            new_annotations = save_payload.get("annotations_json", "")
            new_data_url = save_payload.get("data_url", "")
            composite_bytes = decode_data_url(new_data_url) if new_data_url else None
            update_ergonomics_visual_annotations(
                project_id=project_id,
                scenario_id=scenario_id,
                media_id=media_id,
                annotations_json=new_annotations,
                composite_image_bytes=composite_bytes,
                current_editor=_clean_text(st.session_state.get("current_editor")) or "Collaborator",
            )
            st.toast("Annotations saved!", icon=":material/check_circle:")
            st.session_state.pop(f"ergo_annotate_active_{scenario_id}", None)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.caption("Tip: Select existing shapes to move, recolor, or delete them, or use Crop and Rotate 90° in the toolbar. Click 'Apply & Save Markup' inside the canvas to apply changes.")
    if st.button("Close without saving", key=f"btn_close_ergo_annotator_{media_id}"):
        st.session_state.pop(f"ergo_annotate_active_{scenario_id}", None)
        st.rerun()


@st.dialog("Annotate Staged Ergonomics Visual Aid", width="large")
def annotate_staged_ergo_media_dialog(review_id: str, scenario_id: str) -> None:
    staged_key = f"ergo_staged_media_{review_id}"
    staged = st.session_state.get(staged_key)
    if not staged or not staged.get("original_bytes"):
        st.info("No staged image found to annotate.")
        if st.button("Close"):
            st.session_state.pop(f"ergo_annotate_staged_active_{scenario_id}", None)
            st.rerun()
        return

    st.markdown("#### Annotate Staged Visual Aid")
    st.caption(
        "Crop, rotate in 90° increments, or add arrows, callouts, shapes, and badges to this image "
        "before attaching it to the Ergonomics review slide. Click **💾 Apply & Save Markup** to apply your changes."
    )

    raw_bytes = staged["original_bytes"]
    mime = staged.get("mime_type", "image/png")
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    annotator_res = image_annotator(
        image_data_url=data_url,
        annotations_json=staged.get("annotations_json", ""),
        key=f"annotator_staged_ergo_{review_id}",
    )

    save_payload = getattr(annotator_res, "save", None)
    if save_payload:
        try:
            new_annotations = save_payload.get("annotations_json", "")
            new_data_url = save_payload.get("data_url", "")
            composite_bytes = decode_data_url(new_data_url) if new_data_url else raw_bytes
            staged["composite_bytes"] = composite_bytes
            staged["annotations_json"] = new_annotations
            st.session_state[staged_key] = staged
            st.session_state.pop(f"ergo_annotate_staged_active_{scenario_id}", None)
            st.toast("Markup applied to staged image!", icon=":material/check_circle:")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if st.button("Close without saving", key=f"btn_close_staged_ergo_{review_id}"):
        st.session_state.pop(f"ergo_annotate_staged_active_{scenario_id}", None)
        st.rerun()


@st.dialog("Delete Visual Aid", width="medium", dismissible=False)
def confirm_delete_ergo_media_dialog(
    project_id: str,
    scenario_id: str,
    media_id: str,
    caption: str,
) -> None:
    st.warning(f"Are you sure you want to permanently delete this visual aid ({caption or 'Untitled'})?")
    st.caption(
        "Downstream effects: This permanently deletes the visual aid file from this Ergonomics review and removes it from Ergonomics slide presentation and print views. "
        "The Ergonomics review record itself and its linked Process step / Pitch remain intact."
    )
    d_c1, d_c2 = st.columns(2)
    with d_c1:
        if st.button("Cancel", key=f"cancel_del_media_{media_id}", width="stretch"):
            st.session_state.pop(f"ergo_del_media_target_{scenario_id}", None)
            st.rerun()
    with d_c2:
        if st.button("Delete Permanently", type="primary", icon=":material/delete:", key=f"destructive_confirm_del_media_{media_id}", width="stretch"):
            try:
                delete_ergonomics_visual_media(
                    project_id=project_id,
                    scenario_id=scenario_id,
                    media_id=media_id,
                    current_editor=_clean_text(st.session_state.get("current_editor")) or "Collaborator",
                )
                st.toast("Visual aid deleted.", icon=":material/delete:")
                st.session_state.pop(f"ergo_del_media_target_{scenario_id}", None)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


if st.session_state.get(f"show_add_legacy_dialog_{scenario_id}"):
    _add_legacy_dialog()
elif st.session_state.get(f"show_link_legacy_dialog_{scenario_id}"):
    _link_legacy_dialog()
elif st.session_state.get(f"show_manage_hazards_dialog_{project_id}"):
    _manage_hazards_dialog()
elif st.session_state.get(f"show_delete_unlinked_dialog_{scenario_id}"):
    _delete_unlinked_dialog()
elif st.session_state.get(pending_delete_key):
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
                "legacy_description",
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


st.html('<div id="ergo-slides-section"></div>')
st.divider()
st.subheader("Ergonomics Review Slides", anchor="ergonomics-slides")
if st.session_state.pop("ergo_scroll_to_slides", False):
    st.html(
        """<script>
        function scrollToErgoSlides() {
            try {
                const parentDoc = window.parent ? window.parent.document : document;
                const elem = (parentDoc && parentDoc.getElementById('ergo-slides-section')) || document.getElementById('ergo-slides-section');
                if (elem) {
                    elem.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    return true;
                }
            } catch (e) {
                const elem = document.getElementById('ergo-slides-section');
                if (elem) {
                    elem.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    return true;
                }
            }
            return false;
        }
        setTimeout(scrollToErgoSlides, 150);
        setTimeout(scrollToErgoSlides, 450);
        </script>""",
        unsafe_allow_javascript=True,
    )

review_options: list[tuple[str, str]] = []
for _, r_row in reviews.iterrows():
    rid = _clean_text(r_row.get("id"))
    if not rid:
        continue
    pitch_txt = _clean_text(r_row.get("pitch")) or "Unlinked"
    legacy_txt = _clean_text(r_row.get("legacy_description"))
    we_label = _clean_text(r_row.get("work_element_label"))
    if we_label and legacy_txt:
        op_txt = f"{we_label} [Legacy: {legacy_txt}]"
    else:
        op_txt = we_label or legacy_txt or _clean_text(r_row.get("reviewer")) or rid[:8]
    risk_txt = _clean_text(r_row.get("risk_classification")) or "Not assessed"
    review_options.append((rid, f"{pitch_txt} · {op_txt} ({risk_txt})"))

if not review_options:
    st.info("No saved Ergonomics reviews exist for this planning scenario yet. Add or link a review in the table above to view and present Ergonomics slides.")
else:
    selected_rid_key = f"ergo_slide_selected_review_{scenario_id}"
    if selected_rid_key not in st.session_state or st.session_state[selected_rid_key] not in dict(review_options):
        st.session_state[selected_rid_key] = review_options[0][0]

    curr_rid = st.session_state[selected_rid_key]
    review_ids = [rid for rid, _ in review_options]
    curr_idx = review_ids.index(curr_rid) if curr_rid in review_ids else 0

    if st.session_state.get(f"ergo_present_active_{scenario_id}"):
        ergo_presentation_dialog(
            project_id=project_id,
            scenario_id=scenario_id,
            review_options=review_options,
            initial_review_id=curr_rid,
        )
    elif st.session_state.get(f"ergo_print_active_{scenario_id}"):
        ergo_print_dialog(
            project_id=project_id,
            scenario_id=scenario_id,
            scenario_name=str((scenario or {}).get("name") or "Scenario"),
            review_options=review_options,
            selected_review_id=curr_rid,
        )
    elif st.session_state.get(f"ergo_annotate_active_{scenario_id}"):
        target_item = st.session_state[f"ergo_annotate_active_{scenario_id}"]
        annotate_existing_ergo_media_dialog(
            project_id=project_id,
            scenario_id=scenario_id,
            media_id=target_item["id"],
            media_item=target_item,
        )
    elif st.session_state.get(f"ergo_annotate_staged_active_{scenario_id}"):
        staged_rid = str(st.session_state[f"ergo_annotate_staged_active_{scenario_id}"] or curr_rid)
        annotate_staged_ergo_media_dialog(review_id=staged_rid, scenario_id=scenario_id)
    elif st.session_state.get(f"ergo_del_media_target_{scenario_id}"):
        del_target = st.session_state[f"ergo_del_media_target_{scenario_id}"]
        confirm_delete_ergo_media_dialog(
            project_id=project_id,
            scenario_id=scenario_id,
            media_id=del_target["id"],
            caption=del_target.get("caption", ""),
        )
    elif st.session_state.get(f"ergo_pending_discard_staged_{scenario_id}"):
        discard_rid = str(st.session_state[f"ergo_pending_discard_staged_{scenario_id}"] or curr_rid)

        @st.dialog("Delete Staged Visual Aid?", width="medium", dismissible=False)
        def confirm_discard_staged_ergo_media() -> None:
            st.warning("Delete this staged visual aid before attaching?")
            st.caption(
                "Downstream effects: This discards the unsaved image upload or clipboard capture and any unsaved markup, crop, or rotation. "
                "The Ergonomics review and its already-attached visual aids remain unchanged."
            )
            d_c1, d_c2 = st.columns(2)
            with d_c1:
                if st.button("Cancel", key=f"cancel_discard_staged_ergo_{discard_rid}", width="stretch"):
                    st.session_state.pop(f"ergo_pending_discard_staged_{scenario_id}", None)
                    st.rerun()
            with d_c2:
                if st.button(
                    "Delete",
                    type="primary",
                    icon=":material/delete:",
                    key=f"destructive_confirm_discard_staged_ergo_{discard_rid}",
                    width="stretch",
                ):
                    st_key = f"ergo_staged_media_{discard_rid}"
                    disc_up_key = f"_discarded_ergo_up_{discard_rid}"
                    st.toast("Discarded staged visual aid", icon=":material/delete:")
                    cur_st = st.session_state.get(st_key)
                    if isinstance(cur_st, dict) and cur_st.get("source") == "upload":
                        st.session_state[disc_up_key] = cur_st.get("hash")
                    st.session_state.pop(st_key, None)
                    st.session_state.pop(f"ergo_pending_discard_staged_{scenario_id}", None)
                    st.rerun()

        confirm_discard_staged_ergo_media()

    ergo_sel_col, ergo_act_col = st.columns([2.2, 2.8], vertical_alignment="center")
    with ergo_sel_col:
        new_sel = st.selectbox(
            "Jump to Review",
            options=review_ids,
            index=curr_idx,
            format_func=lambda rid: dict(review_options).get(rid, rid),
            key=f"ergo_slide_select_{scenario_id}",
            label_visibility="collapsed",
        )
        if new_sel != curr_rid:
            st.session_state[selected_rid_key] = new_sel
            st.rerun()

    with ergo_act_col:
        ergo_nav_bar = st.container(horizontal=True, vertical_alignment="center")
        if ergo_nav_bar.button("◀ Back", disabled=(curr_idx == 0), key=f"ergo_slide_prev_{scenario_id}"):
            st.session_state[selected_rid_key] = review_ids[curr_idx - 1]
            st.rerun()
        if ergo_nav_bar.button("Next ▶", disabled=(curr_idx >= len(review_ids) - 1), key=f"ergo_slide_next_{scenario_id}"):
            st.session_state[selected_rid_key] = review_ids[curr_idx + 1]
            st.rerun()
        if ergo_nav_bar.button("Present", icon=":material/slideshow:", key=f"btn_ergo_present_{scenario_id}", help="Full-screen PowerPoint presentation mode"):
            st.session_state[f"ergo_present_active_{scenario_id}"] = True
            st.rerun()
        if ergo_nav_bar.button("Print", icon=":material/print:", key=f"btn_ergo_print_{scenario_id}", help="Export or print 11x17 or 8.5x11 slides"):
            st.session_state[f"ergo_print_active_{scenario_id}"] = True
            st.rerun()
        ergo_nav_bar.markdown(
            f'<span style="font-weight:700; color:#0369a1; font-size:0.88rem; white-space:nowrap;">Slide {curr_idx + 1} of {len(review_ids)}</span>',
            unsafe_allow_html=True,
        )

    curr_rev_data = reviews[reviews["id"] == curr_rid]
    if not curr_rev_data.empty:
        curr_row = dict(curr_rev_data.iloc[0])
        if not _clean_text(curr_row.get("work_element_id")):
            slide_top_c1, slide_top_c2 = st.columns([3, 1], vertical_alignment="center")
            slide_top_c1.info("💡 Unlinked legacy concern. Pair this item with a Process step to merge reviews.")
            if slide_top_c2.button(
                "Link to Process step",
                icon=":material/link:",
                key=f"btn_link_slide_{curr_rid}",
                width="stretch",
            ):
                st.session_state[f"ergo_link_target_legacy_id_{scenario_id}"] = curr_rid
                st.session_state[f"show_link_legacy_dialog_{scenario_id}"] = True
                st.rerun()

    try:
        slide_summary = ergonomics_slide_summary(project_id, scenario_id, curr_rid)
        slide_html = render_ergonomics_slide(slide_summary)
        st.html(slide_html)
    except Exception as exc:
        st.error(f"Error rendering slide: {exc}")
        slide_summary = {}

    attached_media = slide_summary.get("media", [])
    with st.expander(
        f"Visual Aids Manager ({len(attached_media)} attached)",
        expanded=False,
        icon=":material/photo_library:",
    ):
        st.markdown("##### Add Visual Aid")
        st.caption(
            "Upload photos, paste screenshots, or attach short video clips to display on this Ergonomics review slide. "
            "Images can be cropped, rotated in 90° increments, and annotated with arrows, callouts, boxes, circles, and step badges before or after attaching."
        )

        up_c1, up_c2 = st.columns([1.5, 1])
        with up_c1:
            uploaded_file = st.file_uploader(
                "Upload photo or video clip (PNG, JPG, WEBP max 10MB / MP4, MOV, WEBM max 25MB)",
                type=["png", "jpg", "jpeg", "webp", "mp4", "mov", "webm"],
                key=f"ergo_file_upload_{curr_rid}",
            )
            st.caption("Or take a photo with your camera / paste a screenshot (Win+Shift+S / Ctrl+V):")
            pasted = clipboard_image(key=f"ergo_paste_{curr_rid}")

        with up_c2:
            new_caption = st.text_input(
                "Caption / Yellow Callout Note",
                key=f"ergo_new_caption_{curr_rid}",
                placeholder="e.g. Ensure 2-hand palm button clear of pinch hazard",
            )
            new_seq = st.number_input(
                "Sequence Order",
                min_value=1,
                value=(len(attached_media) + 1) * 10,
                step=5,
                key=f"ergo_new_seq_{curr_rid}",
            )

        staged_ergo_key = f"ergo_staged_media_{curr_rid}"
        last_ergo_paste_hash_key = f"last_ergo_paste_hash_{curr_rid}"
        last_ergo_upload_hash_key = f"last_ergo_upload_hash_{curr_rid}"
        discarded_ergo_up_key = f"_discarded_ergo_up_{curr_rid}"
        current_staged = st.session_state.get(staged_ergo_key)

        pasted_payload = getattr(pasted, "image", None)
        if pasted_payload:
            try:
                decoded = decode_clipboard_image(pasted_payload, max_bytes=10 * 1024 * 1024)
                clip_bytes = decoded["bytes"]
                clip_hash = hashlib.sha256(clip_bytes).hexdigest()
                if st.session_state.get(last_ergo_paste_hash_key) != clip_hash:
                    st.session_state[last_ergo_paste_hash_key] = clip_hash
                    st.session_state[staged_ergo_key] = {
                        "source": "clipboard",
                        "hash": clip_hash,
                        "filename": decoded["name"],
                        "original_bytes": clip_bytes,
                        "composite_bytes": clip_bytes,
                        "mime_type": decoded.get("mime_type", "image/png"),
                        "annotations_json": "",
                    }
                    current_staged = st.session_state[staged_ergo_key]
            except Exception as pe:
                st.error(str(pe))

        is_uploaded_video = False
        if uploaded_file is not None:
            up_suffix = Path(uploaded_file.name).suffix.lower()
            if up_suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                up_bytes = uploaded_file.getvalue()
                up_hash = hashlib.sha256(up_bytes).hexdigest()
                if st.session_state.get(last_ergo_upload_hash_key) != up_hash or (
                    not isinstance(current_staged, dict)
                    and st.session_state.get(discarded_ergo_up_key) != up_hash
                ):
                    st.session_state[last_ergo_upload_hash_key] = up_hash
                    st.session_state.pop(discarded_ergo_up_key, None)
                    up_mime = "image/png" if up_suffix == ".png" else "image/webp" if up_suffix == ".webp" else "image/jpeg"
                    st.session_state[staged_ergo_key] = {
                        "source": "upload",
                        "hash": up_hash,
                        "filename": uploaded_file.name,
                        "original_bytes": up_bytes,
                        "composite_bytes": up_bytes,
                        "mime_type": up_mime,
                        "annotations_json": "",
                    }
                    current_staged = st.session_state[staged_ergo_key]
            elif up_suffix in {".mp4", ".mov", ".webm"}:
                is_uploaded_video = True
        else:
            st.session_state.pop(last_ergo_upload_hash_key, None)
            st.session_state.pop(discarded_ergo_up_key, None)
            if isinstance(current_staged, dict) and current_staged.get("source") == "upload":
                st.session_state.pop(staged_ergo_key, None)
                current_staged = None

        if isinstance(current_staged, dict) and current_staged.get("composite_bytes"):
            with st.container(border=True):
                st.markdown(f"**Image Ready:** `{current_staged.get('filename')}`")
                sp1, sp2 = st.columns([1, 2.5])
                with sp1:
                    st.image(current_staged["composite_bytes"], width=150)
                with sp2:
                    raw_ann_str = str(current_staged.get("annotations_json") or "").strip()
                    has_ann = bool(raw_ann_str and raw_ann_str != "[]")
                    if has_ann:
                        st.success("Markup / crop / rotation applied", icon=":material/draw:")
                    else:
                        st.caption(
                            "No annotations added yet. Click below to crop, rotate 90°, or add arrows, focus boxes, callouts, or step numbers."
                        )
                    staged_ergo_btns = st.container(horizontal=True)
                    if staged_ergo_btns.button(
                        "Annotate / Add Shapes",
                        icon=":material/draw:",
                        key=f"btn_ann_staged_ergo_{curr_rid}",
                        type="secondary",
                    ):
                        st.session_state[f"ergo_annotate_staged_active_{scenario_id}"] = curr_rid
                        st.rerun()
                    if staged_ergo_btns.button(
                        "Delete",
                        icon=":material/delete:",
                        key=f"destructive_btn_discard_staged_ergo_{curr_rid}",
                    ):
                        st.session_state[f"ergo_pending_discard_staged_{scenario_id}"] = curr_rid
                        st.rerun()

        has_ready_media = (isinstance(current_staged, dict) and bool(current_staged.get("composite_bytes"))) or is_uploaded_video
        if st.button(
            "Attach Visual Aid",
            type="primary",
            icon=":material/add_photo_alternate:",
            disabled=not has_ready_media,
            key=f"btn_attach_media_{curr_rid}",
        ):
            if isinstance(current_staged, dict) and current_staged.get("composite_bytes"):
                try:
                    save_ergonomics_visual_media(
                        project_id=project_id,
                        scenario_id=scenario_id,
                        review_id=curr_rid,
                        filename=current_staged["filename"],
                        file_bytes=current_staged["composite_bytes"],
                        original_file_bytes=current_staged["original_bytes"],
                        annotations_json=current_staged.get("annotations_json", ""),
                        caption=new_caption,
                        sequence=int(new_seq),
                        current_editor=_clean_text(st.session_state.get("current_editor")) or "Collaborator",
                    )
                    if current_staged.get("source") == "upload":
                        st.session_state[discarded_ergo_up_key] = current_staged.get("hash")
                    st.session_state.pop(staged_ergo_key, None)
                    st.toast("Visual aid attached successfully!", icon=":material/check_circle:")
                    st.rerun()
                except Exception as save_err:
                    st.error(str(save_err))
            elif uploaded_file is not None and is_uploaded_video:
                try:
                    save_ergonomics_visual_media(
                        project_id=project_id,
                        scenario_id=scenario_id,
                        review_id=curr_rid,
                        filename=uploaded_file.name,
                        file_bytes=uploaded_file.getvalue(),
                        caption=new_caption,
                        sequence=int(new_seq),
                        current_editor=_clean_text(st.session_state.get("current_editor")) or "Collaborator",
                    )
                    st.toast("Visual aid attached successfully!", icon=":material/check_circle:")
                    st.rerun()
                except Exception as save_err:
                    st.error(str(save_err))

        if attached_media:
            st.markdown("##### Attached Visual Aids")
            for media_item in attached_media:
                m_id = media_item["id"]
                m_type = media_item.get("media_type", "image")
                with st.container(border=True):
                    m_c1, m_c2 = st.columns([1.2, 2.5])
                    with m_c1:
                        d_url = media_item.get("data_url") or media_item.get("file_path", "")
                        if m_type == "video":
                            st.video(d_url)
                        else:
                            st.image(d_url, width="stretch")
                    with m_c2:
                        card_cap = st.text_input("Caption", value=media_item.get("caption", ""), key=f"cap_edit_{m_id}")
                        card_seq = st.number_input("Sequence", value=int(media_item.get("sequence", 10)), step=5, key=f"seq_edit_{m_id}")
                        raw_item_ann = str(media_item.get("annotations_json") or "").strip()
                        if raw_item_ann and raw_item_ann != "[]":
                            st.caption("Markup: :material/draw: **Annotated** (editable shapes, crop & rotation)")
                        ergo_card_btns = st.container(horizontal=True)
                        if ergo_card_btns.button("Save", key=f"btn_save_media_{m_id}"):
                            try:
                                update_ergonomics_visual_media(
                                    project_id=project_id,
                                    scenario_id=scenario_id,
                                    media_id=m_id,
                                    caption=card_cap,
                                    sequence=int(card_seq),
                                    current_editor=_clean_text(st.session_state.get("current_editor")) or "Collaborator",
                                )
                                st.toast("Visual aid updated.", icon=":material/check_circle:")
                                st.rerun()
                            except Exception as ue:
                                st.error(str(ue))
                        if m_type == "image":
                            if ergo_card_btns.button(
                                "Annotate",
                                icon=":material/draw:",
                                key=f"btn_annot_media_{m_id}",
                                help="Crop, rotate 90°, or add/edit arrows, text callouts, shapes, and badges",
                            ):
                                st.session_state[f"ergo_annotate_active_{scenario_id}"] = media_item
                                st.rerun()
                        if ergo_card_btns.button("Delete", icon=":material/delete:", key=f"destructive_btn_del_media_{m_id}"):
                            st.session_state[f"ergo_del_media_target_{scenario_id}"] = media_item
                            st.rerun()


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
                    "When", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
                ),
            },
        )
