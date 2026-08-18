"""Shared display-unit conversions for the imperial PAAG interface."""

from __future__ import annotations

import pandas as pd


MM_PER_INCH = 25.4


def millimeters_to_inches(value: object) -> float | None:
    """Convert an optional millimeter value to inches."""
    if value is None or pd.isna(value):
        return None
    return float(value) / MM_PER_INCH


def inches_to_millimeters(value: object) -> float | None:
    """Convert an optional inch value to millimeters for legacy storage."""
    if value is None or pd.isna(value):
        return None
    return float(value) * MM_PER_INCH


def imperialize_work_element_dimensions(frame: pd.DataFrame) -> pd.DataFrame:
    """Replace internal millimeter columns with inch columns for display/export."""
    result = frame.copy()
    for source, target in {
        "conveyor_height_mm": "conveyor_height_in",
        "platform_height_mm": "platform_height_in",
        "pit_depth_mm": "pit_depth_in",
    }.items():
        if source in result.columns:
            result[target] = pd.to_numeric(result[source], errors="coerce") / MM_PER_INCH
            result = result.drop(columns=source)
    return result
