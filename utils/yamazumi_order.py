from __future__ import annotations

import re

import pandas as pd


_NATURAL_PARTS = re.compile(r"(\d+)")
_FEEDER_TYPES = {"subassembly", "kitter"}


def _natural_key(value: object) -> tuple[tuple[int, object], ...]:
    """Return a case-insensitive key that keeps numeric address parts sequential."""
    text = str(value or "").strip().casefold()
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in _NATURAL_PARTS.split(text)
        if part
    )


def order_yamazumi_pitches_for_board(pitches: pd.DataFrame) -> pd.DataFrame:
    """Order pitch stacks by address, placing feeder chains before their target.

    A Yamazumi board shows one area, so every complete Op ID on that board has
    the same Fishbone prefix. Pitch address is therefore its pitch-level Op ID
    order. Subassembly and Kitter feed relationships refine that order by
    keeping each complete upstream chain immediately before its receiving
    pitch. The ordering is derived for presentation and never changes the
    persisted ``sequence`` or feed relationship.
    """
    if pitches.empty:
        return pitches.copy()

    records = {
        str(row["id"]): row.to_dict()
        for _, row in pitches.iterrows()
    }

    def sort_key(pitch_id: str) -> tuple:
        row = records[pitch_id]
        raw_sequence = row.get("sequence")
        sequence = (
            int(raw_sequence)
            if raw_sequence is not None and not pd.isna(raw_sequence)
            else 0
        )
        return (
            _natural_key(row.get("pitch_number")),
            _natural_key(row.get("pitch_name")),
            sequence,
            pitch_id,
        )

    incoming: dict[str, list[str]] = {}
    valid_target_by_source: dict[str, str] = {}
    for pitch_id, row in records.items():
        if str(row.get("pitch_type") or "").strip().casefold() not in _FEEDER_TYPES:
            continue
        raw_target_id = row.get("feeds_into_pitch_id")
        target_id = (
            ""
            if raw_target_id is None or pd.isna(raw_target_id)
            else str(raw_target_id).strip()
        )
        if not target_id or target_id == pitch_id or target_id not in records:
            continue
        valid_target_by_source[pitch_id] = target_id
        incoming.setdefault(target_id, []).append(pitch_id)
    for feeder_ids in incoming.values():
        feeder_ids.sort(key=sort_key)

    ordered_ids: list[str] = []
    emitted: set[str] = set()
    visiting: set[str] = set()

    def emit_with_feeders(pitch_id: str) -> None:
        if pitch_id in emitted or pitch_id in visiting:
            return
        visiting.add(pitch_id)
        for feeder_id in incoming.get(pitch_id, []):
            emit_with_feeders(feeder_id)
        visiting.remove(pitch_id)
        if pitch_id not in emitted:
            emitted.add(pitch_id)
            ordered_ids.append(pitch_id)

    terminal_ids = [
        pitch_id for pitch_id in records
        if pitch_id not in valid_target_by_source
    ]
    for pitch_id in sorted(terminal_ids, key=sort_key):
        emit_with_feeders(pitch_id)
    # Invalid legacy cycles or malformed relationships cannot suppress a card.
    for pitch_id in sorted(records, key=sort_key):
        emit_with_feeders(pitch_id)

    indexed = pitches.copy()
    indexed.index = indexed["id"].astype(str)
    return indexed.loc[ordered_ids].reset_index(drop=True)
