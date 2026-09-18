from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TimeUnit:
    key: str
    label: str
    suffix: str
    seconds_per_unit: float
    decimals: int
    step: float


TIME_UNITS = {
    "seconds": TimeUnit("seconds", "Seconds", "s", 1.0, 1, 0.1),
    "minutes": TimeUnit("minutes", "Minutes", "min", 60.0, 3, 0.001),
    "hours": TimeUnit("hours", "Hours", "hr", 3600.0, 4, 0.0001),
}


def normalize_time_unit(value: object) -> str:
    unit = str(value or "seconds").strip().casefold()
    if unit not in TIME_UNITS:
        raise ValueError("Choose Seconds, Minutes, or Hours for the time unit.")
    return unit


def time_unit(value: object) -> TimeUnit:
    return TIME_UNITS[normalize_time_unit(value)]


def _finite_number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number.")
    return number


def seconds_to_display(value: object, unit: object) -> float:
    number = _finite_number(value, "Time")
    return number / time_unit(unit).seconds_per_unit


def display_to_seconds(value: object, unit: object) -> float:
    number = _finite_number(value, "Time")
    if number < 0:
        raise ValueError("Time must be zero or greater.")
    return number * time_unit(unit).seconds_per_unit


def format_seconds(value: object, unit: object) -> str:
    config = time_unit(unit)
    converted = seconds_to_display(value, config.key)
    return f"{converted:.{config.decimals}f} {config.suffix}"
