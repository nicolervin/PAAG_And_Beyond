from __future__ import annotations

import re
from dataclasses import dataclass


LINE_CODE_PATTERN = re.compile(r"^[A-Z0-9]{2}$")
SECTION_CODE_PATTERN = re.compile(r"^[A-Z0-9&]{3}$")
PITCH_ADDRESS_PATTERN = re.compile(
    r"^(?P<line>[A-Z0-9]{2})-(?P<section>[A-Z0-9&]{3})-(?P<number>\d+)$",
    re.IGNORECASE,
)
LINE_PREFIX_PATTERN = re.compile(r"^(?P<line>[A-Z0-9]{2})-", re.IGNORECASE)
ORDINAL_CHARACTERS = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class PitchAddressParts:
    line_code: str
    section_code: str
    number: int


def normalize_yamazumi_line_code(value: object, *, allow_blank: bool = False) -> str:
    code = str(value or "").strip().upper()
    if not code and allow_blank:
        return ""
    if not LINE_CODE_PATTERN.fullmatch(code):
        raise ValueError("Project line code must be exactly two letters or numbers.")
    return code


def normalize_yamazumi_section_code(value: object) -> str:
    code = str(value or "").strip().upper()
    if not SECTION_CODE_PATTERN.fullmatch(code):
        raise ValueError(
            "Fishbone section code must be exactly three letters, numbers, or ampersands."
        )
    return code


def parse_yamazumi_pitch_address(value: object) -> PitchAddressParts | None:
    match = PITCH_ADDRESS_PATTERN.fullmatch(str(value or "").strip())
    if not match:
        return None
    return PitchAddressParts(
        line_code=match.group("line").upper(),
        section_code=match.group("section").upper(),
        number=int(match.group("number")),
    )


def yamazumi_line_prefix(value: object) -> str | None:
    match = LINE_PREFIX_PATTERN.match(str(value or "").strip())
    return match.group("line").upper() if match else None


def format_yamazumi_pitch_address(
    line_code: object, section_code: object, number: object
) -> str:
    normalized_line = normalize_yamazumi_line_code(line_code)
    normalized_section = normalize_yamazumi_section_code(section_code)
    try:
        normalized_number = int(number)
    except (TypeError, ValueError) as exc:
        raise ValueError("Pitch sequence number must be a whole number.") from exc
    if normalized_number < 1:
        raise ValueError("Pitch sequence number must be at least 1.")
    return f"{normalized_line}-{normalized_section}-{normalized_number:03d}"


def suggest_yamazumi_section_code(
    section_name: object, used_codes: set[str] | None = None
) -> str:
    used = {str(code).strip().upper() for code in (used_codes or set())}
    tokens = re.findall(r"[A-Za-z0-9]+", str(section_name or ""))
    words = [token for token in tokens if not token.isdigit()]
    trailing_number = tokens[-1] if tokens and tokens[-1].isdigit() else ""

    if len(words) >= 2:
        stem = "".join(word[0] for word in words[:2]).upper()
    elif words:
        cleaned = re.sub(r"[^A-Za-z0-9]", "", words[0]).upper()
        stem = (cleaned[:2] + "X")[:2]
    else:
        stem = "XX"

    if trailing_number:
        if len(words) == 1 and len(trailing_number) >= 2:
            candidate = (stem[:1] + trailing_number[-2:])[-3:]
        else:
            candidate = stem + trailing_number[-1]
        if candidate not in used:
            return candidate

    for ordinal in ORDINAL_CHARACTERS:
        candidate = stem + ordinal
        if candidate not in used:
            return candidate
    raise ValueError(
        "No unused three-character suggestion is available for this Fishbone section. "
        "Enter a section code manually."
    )
