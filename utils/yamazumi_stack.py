from __future__ import annotations

from copy import deepcopy
from typing import Iterable, Mapping


UNASSIGNED_STACK_ID = "__unassigned__"


def stack_id(pitch_id: object) -> str:
    """Return the stable draft key for a pitch or the Unassigned stack."""
    if pitch_id is None:
        return UNASSIGNED_STACK_ID
    value = str(pitch_id).strip()
    if not value or value.casefold() in {"nan", "none", "<na>"}:
        return UNASSIGNED_STACK_ID
    return value


def build_stack_draft(elements: Iterable[Mapping[str, object]]) -> dict[str, list[str]]:
    """Build complete centerline-outward stacks from persisted element rows."""
    ordered = sorted(
        (dict(element) for element in elements),
        key=lambda element: (
            int(element.get("sequence") or 0),
            str(element.get("description") or "").casefold(),
            str(element.get("id") or ""),
        ),
    )
    stacks: dict[str, list[str]] = {}
    for element in ordered:
        element_id = str(element.get("id") or "").strip()
        if not element_id:
            continue
        stacks.setdefault(stack_id(element.get("pitch_id")), []).append(element_id)
    return stacks


def apply_stack_drop(
    stacks: Mapping[str, list[str]],
    *,
    element_id: str,
    pitch_id: object,
    before_element_id: object = None,
    after_element_id: object = None,
    insert_index: object = None,
) -> dict[str, list[str]]:
    """Return a complete draft with one element moved at the requested anchor."""
    draft = deepcopy(dict(stacks))
    element_id = str(element_id or "").strip()
    occurrences = [key for key, values in draft.items() if element_id in values]
    if not element_id or len(occurrences) != 1:
        raise ValueError("That work element is not uniquely present in the board draft.")

    source_key = occurrences[0]
    draft[source_key].remove(element_id)
    destination_key = stack_id(pitch_id)
    destination = draft.setdefault(destination_key, [])
    before = str(before_element_id or "").strip()
    after = str(after_element_id or "").strip()
    if before and before != element_id and before in destination:
        insertion = destination.index(before)
    elif after and after != element_id and after in destination:
        insertion = destination.index(after) + 1
    elif before:
        insertion = 0
    elif insert_index is not None:
        try:
            insertion = max(0, min(int(insert_index), len(destination)))
        except (TypeError, ValueError):
            insertion = len(destination)
    else:
        insertion = len(destination)
    destination.insert(insertion, element_id)

    # Empty stacks carry no ordering information and need not be sent to storage.
    return {key: values for key, values in draft.items() if values}


def draft_differs(
    elements: Iterable[Mapping[str, object]], stacks: Mapping[str, list[str]]
) -> bool:
    return build_stack_draft(elements) != dict(stacks)


def remove_element_from_stack_draft(
    stacks: Mapping[str, list[str]], element_id: str
) -> dict[str, list[str]]:
    """Remove one deleted element while preserving every other drafted position."""
    target_id = str(element_id or "").strip()
    return {
        key: [value for value in values if str(value) != target_id]
        for key, values in stacks.items()
        if any(str(value) != target_id for value in values)
    }


def reconcile_stack_draft(
    stacks: Mapping[str, list[str]] | None,
    elements: Iterable[Mapping[str, object]],
    *,
    valid_pitch_ids: Iterable[object] | None = None,
) -> dict[str, list[str]]:
    """Reconcile an in-flight stack draft with current persisted elements.

    Preserves drafted user ordering for existing elements while:
    1. Removing stale/deleted element IDs that no longer exist in storage.
    2. Inserting newly created or missing elements into their persisted pitch
       (or __unassigned__) stack at their designated sequence position.
    3. Re-pointing elements from non-existent pitches to __unassigned__.
    4. Removing empty stacks.
    """
    elements_list = [dict(e) for e in elements]
    element_by_id = {
        str(e.get("id") or "").strip(): e
        for e in elements_list
        if str(e.get("id") or "").strip()
    }
    if not stacks:
        return build_stack_draft(elements_list)

    valid_pitches = (
        None
        if valid_pitch_ids is None
        else {str(p or "").strip() for p in valid_pitch_ids if str(p or "").strip()}
    )

    # 1. Clean existing stacks: drop stale/deleted element IDs and deduplicate
    seen_ids: set[str] = set()
    cleaned_stacks: dict[str, list[str]] = {}

    for raw_stack_key, element_ids in stacks.items():
        stack_key = stack_id(raw_stack_key)
        dest_key = (
            UNASSIGNED_STACK_ID
            if (
                valid_pitches is not None
                and stack_key != UNASSIGNED_STACK_ID
                and stack_key not in valid_pitches
            )
            else stack_key
        )
        dest_list = cleaned_stacks.setdefault(dest_key, [])
        for raw_id in element_ids:
            eid = str(raw_id or "").strip()
            if eid and eid in element_by_id and eid not in seen_ids:
                seen_ids.add(eid)
                dest_list.append(eid)

    # 2. Find any elements currently in storage that are missing from draft
    missing_elements = [
        e
        for e in elements_list
        if str(e.get("id") or "").strip() not in seen_ids
    ]
    missing_elements.sort(
        key=lambda e: (
            int(e.get("sequence") or 0)
            if str(e.get("sequence") or "").isdigit()
            else 0,
            str(e.get("description") or "").casefold(),
            str(e.get("id") or ""),
        )
    )

    for element in missing_elements:
        eid = str(element.get("id") or "").strip()
        if not eid:
            continue
        dest_key = stack_id(element.get("pitch_id"))
        if (
            valid_pitches is not None
            and dest_key != UNASSIGNED_STACK_ID
            and dest_key not in valid_pitches
        ):
            dest_key = UNASSIGNED_STACK_ID
        cleaned_stacks.setdefault(dest_key, []).append(eid)
        seen_ids.add(eid)

    return {k: v for k, v in cleaned_stacks.items() if v}


def apply_stack_draft_to_elements(
    elements: Iterable[Mapping[str, object]], stacks: Mapping[str, list[str]]
) -> list[dict]:
    """Overlay a complete draft for browser rendering without persisting it."""
    by_id = {
        str(element.get("id") or ""): dict(element) for element in elements
    }
    rendered: list[dict] = []
    rendered_ids: set[str] = set()
    for key, element_ids in stacks.items():
        pitch_id = None if key == UNASSIGNED_STACK_ID else key
        for position, element_id in enumerate(element_ids, start=1):
            if element_id not in by_id:
                continue
            row = dict(by_id[element_id])
            row["pitch_id"] = pitch_id
            row["sequence"] = position * 10
            rendered.append(row)
            rendered_ids.add(element_id)
    # Ensure any elements not explicitly sequenced in stacks remain visible on board
    for element in elements:
        eid = str(element.get("id") or "")
        if eid and eid not in rendered_ids:
            rendered.append(dict(element))
    return rendered

