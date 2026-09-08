from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Integral, Real


def json_safe(value):
    """Return a strictly JSON-compatible component payload with no NaN values."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def is_empty_unsaved_grid_category(category: Mapping) -> bool:
    """Return whether a new grid row is only an untouched blank placeholder."""
    if str(category.get("id") or "").strip():
        return False
    if any(
        str(category.get(field) or "").strip()
        for field in (
            "ebom_name",
            "display_name",
            "installed_section_id",
        )
    ):
        return False
    return not any(
        str(cell.get("assembly_number") or "").strip()
        for cell in dict(category.get("cells") or {}).values()
    )
