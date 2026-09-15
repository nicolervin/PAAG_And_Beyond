from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from typing import Any

import pandas as pd
import streamlit as st

from utils.store import (
    assembly_section_walk_order,
    pin_map_for_scenario,
    yamazumi_areas,
)


ALL_ACTIVE_SECTIONS = "__all_active_sections__"
FISHBONE_LINKED_PAGES = {
    "Assembly grid",
    "Parts to fishbone",
    "Yamazumi",
    "Process at a Glance",
    "Pin Map",
}


def normalized_id(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def section_breadcrumb_labels(sections: pd.DataFrame) -> dict[str, str]:
    """Return accessible ancestry labels for a Fishbone walk."""
    if sections.empty:
        return {}
    records = {
        str(row["id"]): row.to_dict() for _, row in sections.iterrows()
    }
    labels: dict[str, str] = {}

    def label_for(section_id: str, trail: set[str] | None = None) -> str:
        if section_id in labels:
            return labels[section_id]
        row = records[section_id]
        name = str(row.get("name") or section_id)
        parent_id = normalized_id(row.get("parent_id"))
        visited = set(trail or ())
        if parent_id in records and parent_id not in visited and parent_id != section_id:
            visited.add(section_id)
            label = f"{label_for(parent_id, visited)} › {name}"
        else:
            label = name
        labels[section_id] = label
        return label

    for section_id in records:
        label_for(section_id)
    return labels


def ordered_section_ids(
    sections: pd.DataFrame,
    *,
    active_only: bool = False,
    retain_ids: Iterable[str] = (),
) -> list[str]:
    """Return walk-ordered IDs while preserving explicitly retained current values."""
    retained = {str(value) for value in retain_ids if str(value)}
    result: list[str] = []
    for _, row in sections.iterrows():
        section_id = str(row["id"])
        is_active = bool(row.get("active", True))
        if not active_only or is_active or section_id in retained:
            result.append(section_id)
    return result


def ordered_yamazumi_area_ids(
    areas: pd.DataFrame, section_ids: Iterable[str]
) -> list[str]:
    """Order linked areas by Fishbone walk and unlinked areas alphabetically last."""
    if areas.empty:
        return []
    section_position = {
        str(section_id): index for index, section_id in enumerate(section_ids)
    }

    def sort_key(row: pd.Series) -> tuple[int, int, str, str]:
        section_id = normalized_id(row.get("section_id"))
        if section_id in section_position:
            return (
                0,
                section_position[section_id],
                str(row.get("name") or "").casefold(),
                str(row["id"]),
            )
        return (
            1,
            len(section_position),
            str(row.get("name") or "").casefold(),
            str(row["id"]),
        )

    records = sorted(
        (row for _, row in areas.iterrows()),
        key=sort_key,
    )
    return [str(row["id"]) for row in records]


def preferred_section_keys(project_id: str) -> tuple[str, str]:
    return (
        f"fishbone_preferred_section_{project_id}",
        f"fishbone_preferred_ordinal_{project_id}",
    )


def remember_preferred_section(
    state: MutableMapping[str, Any],
    project_id: str,
    section_id: str,
    all_section_ids: list[str],
) -> None:
    if section_id not in all_section_ids:
        return
    section_key, ordinal_key = preferred_section_keys(project_id)
    state[section_key] = section_id
    state[ordinal_key] = all_section_ids.index(section_id)


def nearest_valid_section(
    state: MutableMapping[str, Any],
    project_id: str,
    all_section_ids: list[str],
    valid_section_ids: Iterable[str],
) -> str | None:
    """Choose the remembered section, then scan forward and backward in walk order."""
    valid = {str(value) for value in valid_section_ids}
    if not all_section_ids or not valid:
        return None
    section_key, ordinal_key = preferred_section_keys(project_id)
    preferred_id = str(state.get(section_key) or "")
    if preferred_id in valid:
        return preferred_id
    if preferred_id in all_section_ids:
        start = all_section_ids.index(preferred_id)
    else:
        try:
            start = int(state.get(ordinal_key, 0))
        except (TypeError, ValueError):
            start = 0
        start = max(0, min(start, len(all_section_ids) - 1))
    for index in range(start, len(all_section_ids)):
        if all_section_ids[index] in valid:
            return all_section_ids[index]
    for index in range(start - 1, -1, -1):
        if all_section_ids[index] in valid:
            return all_section_ids[index]
    return next((section_id for section_id in all_section_ids if section_id in valid), None)


def fishbone_context_label(
    selected_section_ids: Iterable[str],
    active_section_ids: list[str],
    labels: dict[str, str],
    *,
    all_selected: bool = False,
    unlinked: bool = False,
) -> str:
    if unlinked:
        return "Unlinked"
    selected = list(dict.fromkeys(str(value) for value in selected_section_ids))
    if all_selected or (active_section_ids and selected == active_section_ids):
        return "All active sections"
    if len(selected) == 1:
        return labels.get(selected[0], selected[0])
    if selected:
        return f"{len(selected)} sections selected"
    return "All active sections"


def _linked_area_maps(areas: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    section_to_area: dict[str, str] = {}
    area_to_section: dict[str, str] = {}
    if areas.empty:
        return section_to_area, area_to_section
    for _, row in areas.iterrows():
        area_id = str(row["id"])
        section_id = normalized_id(row.get("section_id"))
        if section_id:
            area_to_section[area_id] = section_id
            section_to_area.setdefault(section_id, area_id)
    return section_to_area, area_to_section


def _set_sidebar_page_scope(
    selector_key: str,
    page_title: str,
    project_id: str,
    scenario_id: str | None,
    section_to_area: dict[str, str],
    all_section_ids: list[str],
) -> None:
    value = st.session_state.get(selector_key)
    if not value:
        return
    if value != ALL_ACTIVE_SECTIONS:
        remember_preferred_section(
            st.session_state, project_id, str(value), all_section_ids
        )
    if page_title == "Assembly grid":
        st.session_state[f"assembly_grid_sections_{project_id}"] = [value]
    elif page_title == "Process at a Glance" and scenario_id:
        st.session_state[f"process_pairing_section_{scenario_id}"] = str(value)
    elif page_title == "Yamazumi" and scenario_id:
        area_id = section_to_area.get(str(value))
        if area_id:
            st.session_state[f"yamazumi_area_{scenario_id}"] = area_id
    elif page_title == "Pin Map" and scenario_id:
        st.session_state[f"pin_map_areas_{scenario_id}"] = (
            []
            if value == ALL_ACTIVE_SECTIONS
            else [section_to_area[str(value)]]
        )


def render_fishbone_sidebar_context(
    parent,
    *,
    page_title: str,
    project_id: str,
    scenario_id: str | None,
) -> None:
    """Render and synchronize the page-aware Fishbone view in the sidebar."""
    if page_title not in FISHBONE_LINKED_PAGES:
        return
    sections = assembly_section_walk_order(project_id)
    if sections.empty:
        return
    labels = section_breadcrumb_labels(sections)
    all_section_ids = sections["id"].astype(str).tolist()
    active_section_ids = ordered_section_ids(sections, active_only=True)
    areas = (
        yamazumi_areas(project_id, scenario_id)
        if scenario_id and page_title in {"Yamazumi", "Pin Map"}
        else pd.DataFrame()
    )
    if page_title == "Pin Map" and scenario_id and not areas.empty:
        pin_map = pin_map_for_scenario(project_id, scenario_id)
        mapped_area_ids = (
            set(pin_map["area_id"].astype(str)) if not pin_map.empty else set()
        )
        areas = areas.loc[areas["id"].astype(str).isin(mapped_area_ids)].copy()
    section_to_area, area_to_section = _linked_area_maps(areas)
    selected_ids: list[str] = []
    all_selected = False
    unlinked = False
    selected_count_override: int | None = None
    valid_ids = list(active_section_ids)

    if page_title == "Assembly grid":
        target_key = f"assembly_grid_sections_{project_id}"
        stored = st.session_state.get(target_key)
        preferred_key, _ = preferred_section_keys(project_id)
        if stored is None and st.session_state.get(preferred_key):
            preferred = nearest_valid_section(
                st.session_state, project_id, all_section_ids, valid_ids
            )
            if preferred:
                stored = [preferred]
                st.session_state[target_key] = stored
        values = list(stored) if isinstance(stored, (list, tuple)) else []
        if values and ALL_ACTIVE_SECTIONS not in values:
            retained_values = [
                section_id for section_id in active_section_ids
                if section_id in values
            ]
            if not retained_values:
                fallback = nearest_valid_section(
                    st.session_state, project_id, all_section_ids, valid_ids
                )
                retained_values = [fallback] if fallback else []
            if retained_values != values:
                values = retained_values
                st.session_state[target_key] = (
                    values if values else [ALL_ACTIVE_SECTIONS]
                )
        all_selected = not values or ALL_ACTIVE_SECTIONS in values
        selected_ids = (
            active_section_ids
            if all_selected
            else [value for value in active_section_ids if value in values]
        )
    elif page_title == "Process at a Glance" and scenario_id:
        target_key = f"process_pairing_section_{scenario_id}"
        current = str(st.session_state.get(target_key) or "")
        if current not in valid_ids:
            current = nearest_valid_section(
                st.session_state, project_id, all_section_ids, valid_ids
            ) or ""
            if current:
                st.session_state[target_key] = current
        selected_ids = [current] if current else []
    elif page_title == "Yamazumi" and scenario_id:
        valid_ids = [
            section_id for section_id in active_section_ids
            if section_id in section_to_area
        ]
        target_key = f"yamazumi_area_{scenario_id}"
        current_area = str(st.session_state.get(target_key) or "")
        current_section = area_to_section.get(current_area, "")
        area_ids = set(areas["id"].astype(str)) if not areas.empty else set()
        if current_area in area_ids and not current_section:
            unlinked = True
        elif current_section not in valid_ids:
            fallback = nearest_valid_section(
                st.session_state, project_id, all_section_ids, valid_ids
            )
            if fallback:
                current_section = fallback
                st.session_state[target_key] = section_to_area[fallback]
            else:
                unlinked = bool(current_area)
        selected_ids = [current_section] if current_section else []
    elif page_title == "Pin Map" and scenario_id:
        valid_ids = [
            section_id for section_id in active_section_ids
            if section_id in section_to_area
        ]
        target_key = f"pin_map_areas_{scenario_id}"
        stored = st.session_state.get(target_key)
        preferred_key, _ = preferred_section_keys(project_id)
        if stored is None and st.session_state.get(preferred_key):
            preferred = nearest_valid_section(
                st.session_state, project_id, all_section_ids, valid_ids
            )
            if preferred:
                stored = [section_to_area[preferred]]
                st.session_state[target_key] = stored
        selected_areas = list(stored) if isinstance(stored, (list, tuple)) else []
        area_ids = set(areas["id"].astype(str)) if not areas.empty else set()
        retained_areas = [area_id for area_id in selected_areas if area_id in area_ids]
        if selected_areas and not retained_areas:
            fallback = nearest_valid_section(
                st.session_state, project_id, all_section_ids, valid_ids
            )
            retained_areas = [section_to_area[fallback]] if fallback else []
        if retained_areas != selected_areas:
            selected_areas = retained_areas
            st.session_state[target_key] = selected_areas
        all_selected = not selected_areas
        selected_ids = [
            area_to_section[area_id]
            for area_id in selected_areas
            if area_id in area_to_section
        ]
        unlinked = bool(selected_areas) and not selected_ids
        if len(selected_areas) > 1:
            selected_count_override = len(selected_areas)
    else:
        all_selected = True
        selected_ids = active_section_ids

    if len(selected_ids) == 1:
        remember_preferred_section(
            st.session_state, project_id, selected_ids[0], all_section_ids
        )
    context = (
        f"{selected_count_override} sections selected"
        if selected_count_override is not None
        else fishbone_context_label(
            selected_ids,
            active_section_ids,
            labels,
            all_selected=all_selected,
            unlinked=unlinked,
        )
    )
    parent.caption("Fishbone view")
    parent.markdown(f"**{context}**")
    if page_title == "Parts to fishbone" or not valid_ids:
        return

    options = list(valid_ids)
    if page_title in {"Assembly grid", "Pin Map"}:
        options.insert(0, ALL_ACTIVE_SECTIONS)
    selector_key = (
        f"fishbone_sidebar_select_{project_id}_{scenario_id or 'project'}_"
        f"{page_title.casefold().replace(' ', '_')}"
    )
    st.session_state[selector_key] = None
    parent.selectbox(
        "Change Fishbone view",
        options,
        index=None,
        placeholder="Choose a view",
        format_func=lambda value: (
            "All active sections"
            if value == ALL_ACTIVE_SECTIONS else labels.get(value, value)
        ),
        key=selector_key,
        on_change=_set_sidebar_page_scope,
        args=(
            selector_key,
            page_title,
            project_id,
            scenario_id,
            section_to_area,
            all_section_ids,
        ),
    )
