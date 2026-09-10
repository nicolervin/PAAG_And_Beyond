from __future__ import annotations

from copy import deepcopy
from typing import Iterable, Mapping


UNASSIGNED_STACK_ID = "__unassigned__"


def stack_id(pitch_id: object) -> str:
    """Return the stable draft key for a pitch or the Unassigned stack."""
    value = str(pitch_id or "").strip()
    return value or UNASSIGNED_STACK_ID


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


def apply_stack_draft_to_elements(
    elements: Iterable[Mapping[str, object]], stacks: Mapping[str, list[str]]
) -> list[dict]:
    """Overlay a complete draft for browser rendering without persisting it."""
    by_id = {
        str(element.get("id") or ""): dict(element) for element in elements
    }
    rendered: list[dict] = []
    for key, element_ids in stacks.items():
        pitch_id = None if key == UNASSIGNED_STACK_ID else key
        for position, element_id in enumerate(element_ids, start=1):
            if element_id not in by_id:
                continue
            row = dict(by_id[element_id])
            row["pitch_id"] = pitch_id
            row["sequence"] = position * 10
            rendered.append(row)
    return rendered
