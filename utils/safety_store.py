"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import json
import sys as _sys
from pathlib import Path
from typing import Any, Iterable
from utils import db_core as _db_core
from utils.cache_store import cached_store_read
from utils.recycle_bin_store import capture_deletion_to_recycle_bin

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

ASSETS_DIR = Path(ROOT) / "assets"
PPE_ICONS_DIR = ASSETS_DIR / "ppe_icons"
JSA_ICONS_DIR = ASSETS_DIR / "jsa_icons"
EHS_LOGO_PATH = ASSETS_DIR / "ehs_icon" / "LOGO.png"

_SAFETY_STORE_HOT_RELOAD_REV = 6

STANDARD_BASELINE_PPE: list[str] = [
    "Cut Level 2 Gloves",
    "Safety Glasses",
    "Sturdy Closed Toe and Heel Shoes",
]

_RAW_PPE_CATALOG: list[dict[str, Any]] = [
    {
        "name": "Cut Level 2 Gloves",
        "image_filename": "Cut 2 Gloves.png",
        "jsa_image_filename": "jsa_cut_2_gloves.png",
        "hazard": "LACERATION from material handling.",
        "mitigation": "Correctly wear CUT LEVEL 2 GLOVES.",
        "category_group": "cut_gloves",
        "category_label": "Cut Gloves",
        "hierarchy_rank": 2,
    },
    {
        "name": "Safety Glasses",
        "image_filename": "Safety Glasses.png",
        "jsa_image_filename": "jsa_safety_glasses.png",
        "hazard": "EYE INJURY OR IRRITATION from airborne particles.",
        "mitigation": "Wear APPROVED SAFETY GLASSES with fixed side shields.",
        "category_group": "eye_protection",
        "category_label": "Eye Protection",
        "hierarchy_rank": 1,
    },
    {
        "name": "Sturdy Closed Toe and Heel Shoes",
        "image_filename": "Normal Shoes.png",
        "jsa_image_filename": "",
        "hazard": "SLIP OR TRIP on walking/working surface.",
        "mitigation": "Wear sturdy CLOSED TOE AND HEEL SHOES with good traction.",
        "category_group": "footwear",
        "category_label": "Footwear",
        "hierarchy_rank": 1,
    },
    {
        "name": "Cut Level 1 Gloves",
        "image_filename": "Cut 1 Gloves.png",
        "jsa_image_filename": "jsa_cut_1_gloves.png",
        "hazard": "MINOR ABRASION OR LACERATION from light material handling.",
        "mitigation": "Correctly wear CUT LEVEL 1 OR HIGHER GLOVES.",
        "category_group": "cut_gloves",
        "category_label": "Cut Gloves",
        "hierarchy_rank": 1,
    },
    {
        "name": "Cut Level 3 Gloves",
        "image_filename": "Cut 3 Gloves.png",
        "jsa_image_filename": "jsa_cut_3_gloves.png",
        "hazard": "LACERATION to hands from moderate sharp edges.",
        "mitigation": "Correctly wear CUT LEVEL 3 OR HIGHER GLOVES.",
        "category_group": "cut_gloves",
        "category_label": "Cut Gloves",
        "hierarchy_rank": 3,
    },
    {
        "name": "Cut Level 4 Gloves",
        "image_filename": "Cut 4 Gloves.png",
        "jsa_image_filename": "jsa_cut_4_gloves.png",
        "hazard": "LACERATION to hands from exposure to sharp materials.",
        "mitigation": "Correctly wear CUT LEVEL 4 OR HIGHER GLOVES.",
        "category_group": "cut_gloves",
        "category_label": "Cut Gloves",
        "hierarchy_rank": 4,
    },
    {
        "name": "Cut Level 5 Gloves",
        "image_filename": "Cut 5 Gloves.png",
        "jsa_image_filename": "jsa_cut_5_gloves.png",
        "hazard": "SEVERE LACERATION to hands from sharp sheet metal or components.",
        "mitigation": "Correctly wear CUT LEVEL 5 OR HIGHER GLOVES.",
        "category_group": "cut_gloves",
        "category_label": "Cut Gloves",
        "hierarchy_rank": 5,
    },
    {
        "name": "Cut Level 6 Gloves",
        "image_filename": "Cut 6 Gloves.png",
        "jsa_image_filename": "",
        "hazard": "LACERATION to hands from exposure to sharp materials.",
        "mitigation": "Correctly wear CUT LEVEL 6 OR HIGHER GLOVES.",
        "category_group": "cut_gloves",
        "category_label": "Cut Gloves",
        "hierarchy_rank": 6,
    },
    {
        "name": "Long Pants",
        "image_filename": "Long Pants.png",
        "jsa_image_filename": "",
        "hazard": "LACERATION to legs from exposure to sharp materials.",
        "mitigation": "Wear LONG PANTS made of denim, khaki or cotton blend.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Safety Toe Shoes",
        "image_filename": "Safety Shoes.png",
        "jsa_image_filename": "jsa_steel_toe_shoes.png",
        "hazard": "CRUSHING INJURY from handling/moving heavy materials.",
        "mitigation": "Wear SAFETY TOE SHOES.",
        "category_group": "footwear",
        "category_label": "Footwear",
        "hierarchy_rank": 2,
    },
    {
        "name": "Cut Resistant Arm Guards / Sleeves",
        "image_filename": "Sleeves.png",
        "jsa_image_filename": "jsa_cut_resistant_sleeve.png",
        "hazard": "LACERATION to arms from exposure to sharp materials.",
        "mitigation": "Correctly wear CUT RESISTANT ARM GUARDS.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Tinted Safety Glasses",
        "image_filename": "Tinted Safety Glasses.png",
        "jsa_image_filename": "",
        "hazard": "INTENSE LIGHT while performing hot work tasks.",
        "mitigation": "Wear APPROVED TINTED SAFETY GLASSES with fixed side shields.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Welding Gloves",
        "image_filename": "Welding Gloves.png",
        "jsa_image_filename": "jsa_welding_gloves.png",
        "hazard": "EXTREME HEAT exposure to hands while performing hot work tasks.",
        "mitigation": "Correctly wear WELDING GLOVES.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Welding Jacket",
        "image_filename": "Welding Jacket.png",
        "jsa_image_filename": "",
        "hazard": "EXTREME HEAT exposure to body while performing hot work tasks.",
        "mitigation": "Correctly wear WELDING JACKET.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Welding Mask",
        "image_filename": "Welding Mask.png",
        "jsa_image_filename": "jsa_weld_helmet.png",
        "hazard": "INTENSE LIGHT while performing welding tasks.",
        "mitigation": "Wear WELDING MASK when performing welding tasks.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Chemical Resistant Gloves",
        "image_filename": "Chem Gloves.png",
        "jsa_image_filename": "",
        "hazard": "Exposure to CHEMICALS.",
        "mitigation": "Correctly wear CHEMICAL RESISTANT GLOVES.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Hearing Protection",
        "image_filename": "Hearing Protection.png",
        "jsa_image_filename": "jsa_hearing_protection.png",
        "hazard": "Exposure to LOUD NOISES from machinery, tools, etc.",
        "mitigation": "Wear approved HEARING PROTECTION.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Leather Gloves",
        "image_filename": "Leather Gloves.png",
        "jsa_image_filename": "",
        "hazard": "Exposure to EXTREME COLD when handling dry ice.",
        "mitigation": "Correctly wear LEATHER GLOVES.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Respiratory Protection",
        "image_filename": "Respiratory Protection.png",
        "jsa_image_filename": "",
        "hazard": "Exposure to airborne contaminants, dust, or fumes.",
        "mitigation": "Wear approved RESPIRATORY PROTECTION suitable for the hazard.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "N95 Filtering Facepiece Respirator",
        "image_filename": "N95 Respirator.png",
        "jsa_image_filename": "jsa_n95_respirator.png",
        "hazard": "Exposure to airborne particulates or nuisance dust.",
        "mitigation": "Wear approved N95 FILTERING FACEPIECE RESPIRATOR.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Brazing Gauntlets",
        "image_filename": "Brazing Gauntlets.png",
        "jsa_image_filename": "",
        "hazard": "Exposure to EXTREME HEAT when performing brazing tasks.",
        "mitigation": "Correctly wear BRAZING GAUNTLETS.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Foam Lined Safety Glasses",
        "image_filename": "Foam Safety Glasses.png",
        "jsa_image_filename": "",
        "hazard": "EYE INJURY OR IRRITATION from airborne particles when using dry ice guns.",
        "mitigation": "Wear approved FOAM LINED SAFETY GLASSES with fixed side shields.",
        "category_group": "eye_protection",
        "category_label": "Eye Protection",
        "hierarchy_rank": 2,
    },
    {
        "name": "Chemical Splash Apron",
        "image_filename": "Chemical Splash Apron.png",
        "jsa_image_filename": "",
        "hazard": "Exposure to CHEMICALS.",
        "mitigation": "Wear approved CHEMICAL SPLASH APRON.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Chemical Resistant Coverall",
        "image_filename": "Chemical Resistant Coverall.png",
        "jsa_image_filename": "jsa_chemical_coverall.png",
        "hazard": "Full-body exposure to CHEMICALS or splashes.",
        "mitigation": "Wear approved CHEMICAL RESISTANT COVERALL.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Chemical Resistant Face Shield",
        "image_filename": "Chemical Face Shield.png",
        "jsa_image_filename": "jsa_face_shield.png",
        "hazard": "Eye and face exposure to CHEMICALS.",
        "mitigation": "Wear approved CHEMICAL RESISTANT FACE SHIELD",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Chemical Resistant Galoshes",
        "image_filename": "Chemical Resistant Galoshes.png",
        "jsa_image_filename": "jsa_chemical_boots.png",
        "hazard": "Exposure to CHEMICALS",
        "mitigation": "Wear approved CHEMICAL RESISTANT GALOSHES",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "High Visibility Vest",
        "image_filename": "High Visibility Vest.png",
        "jsa_image_filename": "jsa_high_visibility_vest.png",
        "hazard": "STRUCK-BY HAZARD from mobile equipment or low visibility.",
        "mitigation": "Wear approved HIGH VISIBILITY VEST.",
        "category_group": "",
        "category_label": "",
        "hierarchy_rank": 0,
    },
    {
        "name": "Bump Cap",
        "image_filename": "Bump Cap.png",
        "jsa_image_filename": "jsa_bump_cap.png",
        "hazard": "HEAD BUMP OR LACERATION from low overhead clearance or fixtures.",
        "mitigation": "Wear approved BUMP CAP.",
        "category_group": "head_protection",
        "category_label": "Head Protection",
        "hierarchy_rank": 1,
    },
    {
        "name": "Hard Hat",
        "image_filename": "Hard Hat.png",
        "jsa_image_filename": "jsa_hard_hat.png",
        "hazard": "HEAD INJURY from falling objects or overhead lifting hazards.",
        "mitigation": "Wear approved ANSI-rated HARD HAT.",
        "category_group": "head_protection",
        "category_label": "Head Protection",
        "hierarchy_rank": 2,
    },
]

PPE_CATALOG: list[dict[str, Any]] = [
    {
        **item,
        "image_path": str(PPE_ICONS_DIR / item["image_filename"]),
        "jsa_image_path": (
            str(JSA_ICONS_DIR / item["jsa_image_filename"])
            if item.get("jsa_image_filename")
            else str(PPE_ICONS_DIR / item["image_filename"])
        ),
        "catalog_index": idx,
    }
    for idx, item in enumerate(_RAW_PPE_CATALOG)
]

_PPE_BY_CASEFOLD: dict[str, dict[str, Any]] = {
    item["name"].casefold(): item for item in PPE_CATALOG
}

PPE_LEGACY_ALIASES: dict[str, str] = {
    "cut-resistant gloves": "Cut Level 2 Gloves",
    "cut resistant gloves": "Cut Level 2 Gloves",
    "cut 1 gloves": "Cut Level 1 Gloves",
    "cut level 1 glove": "Cut Level 1 Gloves",
    "cut 2 gloves": "Cut Level 2 Gloves",
    "cut level 2 glove": "Cut Level 2 Gloves",
    "cut 3 gloves": "Cut Level 3 Gloves",
    "cut level 3 glove": "Cut Level 3 Gloves",
    "cut 4 gloves": "Cut Level 4 Gloves",
    "cut level 4 glove": "Cut Level 4 Gloves",
    "cut 5 gloves": "Cut Level 5 Gloves",
    "cut level 5 glove": "Cut Level 5 Gloves",
    "cut 6 gloves": "Cut Level 6 Gloves",
    "cut level 6 glove": "Cut Level 6 Gloves",
    "steel-toe shoes": "Safety Toe Shoes",
    "steel toe shoes": "Safety Toe Shoes",
    "safety shoes": "Safety Toe Shoes",
    "normal shoes": "Sturdy Closed Toe and Heel Shoes",
    "closed toe shoes": "Sturdy Closed Toe and Heel Shoes",
    "chemical gloves": "Chemical Resistant Gloves",
    "chem gloves": "Chemical Resistant Gloves",
    "chemical apron": "Chemical Splash Apron",
    "chemical coverall": "Chemical Resistant Coverall",
    "chemical resistant boots": "Chemical Resistant Galoshes",
    "respirator / dust mask": "Respiratory Protection",
    "n95": "N95 Filtering Facepiece Respirator",
    "n95 respirator": "N95 Filtering Facepiece Respirator",
    "filtering facepiece respirator": "N95 Filtering Facepiece Respirator",
    "face shield": "Chemical Resistant Face Shield",
    "ansi rated face shield": "Chemical Resistant Face Shield",
    "chemical face shield": "Chemical Resistant Face Shield",
    "safety glasses with side shields": "Safety Glasses",
    "heat-resistant gloves": "Welding Gloves",
    "heat resistant welding gloves": "Welding Gloves",
    "weld helmet": "Welding Mask",
    "foam safety glasses": "Foam Lined Safety Glasses",
    "sleeves": "Cut Resistant Arm Guards / Sleeves",
    "cut resistant sleeve": "Cut Resistant Arm Guards / Sleeves",
    "arm guards": "Cut Resistant Arm Guards / Sleeves",
    "hi-vis vest": "High Visibility Vest",
    "high-visibility vest": "High Visibility Vest",
    "hearing protection required": "Hearing Protection",
    "chemiclal resistant galoshes": "Chemical Resistant Galoshes",
}

STANDARD_PPE_OPTIONS: list[str] = [item["name"] for item in PPE_CATALOG]

JSA_HAZARD_PRESETS: list[str] = list(
    dict.fromkeys(
        [
            "Slip, trip, and fall hazards",
            "Pinch point / caught-between hazard during part placement",
            "Laceration from sharp edges or sheet metal handling",
            "Crushing injury from heavy part or subassembly handling",
            "Ergonomic strain from awkward posture, reaching, or lifting",
            "Eye injury or irritation from airborne particles or fasteners",
            "Dropped part or tool hazard",
            "Torque reaction / powered hand-tool kickback",
            "Struck-by hazard from manipulator, hoist, or mobile equipment",
            "Exposure to loud noise from tools or presses",
            "Exposure to chemicals, adhesives, or sealants",
            "Extreme heat / hot work exposure",
            *[str(item["hazard"]) for item in PPE_CATALOG if item.get("hazard")],
        ]
    )
)

JSA_ACTION_PRESETS: list[str] = list(
    dict.fromkeys(
        [
            "Ensure area is free of debris, damaged ergo matting, cords, dropped parts and trash.",
            "Keep hands and fingers clear of pinch points and mating surfaces.",
            "Inspect lift / manipulator controls and rigging before moving load.",
            "Maintain two-hand control and proper body positioning when operating torque tools.",
            "Use mechanical lift assist or two-person lift for heavy/awkward components.",
            *[str(item["mitigation"]) for item in PPE_CATALOG if item.get("mitigation")],
        ]
    )
)


_AUTO_PPE_CATALOG_PHRASES: list[str] = sorted(
    {
        phrase
        for item in PPE_CATALOG
        for phrase in (
            str(item.get("hazard") or "").strip(),
            str(item.get("mitigation") or "").strip(),
        )
        if phrase
    },
    key=len,
    reverse=True,
)


def _strip_auto_ppe_text(value: object, *, is_auto_ppe_row: bool = False) -> str:
    """Return empty string if value is auto-populated PPE catalog boilerplate rather than EHS-entered text."""
    s = str(value or "").strip()
    if not s:
        return ""
    if is_auto_ppe_row:
        if s.casefold() in {
            "none",
            "n/a",
            "safety glasses, cut-resistant gloves, and required workstation footwear.",
            "safety toed shoes, safety glasses, cut-resistant gloves",
        }:
            return ""
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if parts and all(normalize_ppe_name(p).casefold() in _PPE_BY_CASEFOLD for p in parts):
            return ""
    rem = s
    for phrase in _AUTO_PPE_CATALOG_PHRASES:
        if phrase in rem:
            rem = rem.replace(phrase, "")
    rem_clean = rem.strip(" \t\r\n|,;.-")
    if not rem_clean:
        return ""
    return s


def _strip_yamazumi_area_text(val: object) -> str:
    """Remove auto-generated 'Yamazumi area: ...' text or suffixes from job steps and descriptions."""
    s = str(val or "").strip()
    if not s:
        return ""
    if s.casefold().startswith("yamazumi area:"):
        return ""
    for sep in (" — ", " - ", " —", " -", "—", "-"):
        marker = f"{sep}yamazumi area:"
        idx = s.casefold().find(marker)
        if idx >= 0:
            return s[:idx].strip()
    return s


def derive_ppe_hazards_and_actions(raw_ppe: object) -> tuple[str, str]:
    """Derive default JSA Potential Errors / Hazards and Action strings from a step's PPE."""
    rollup = resolve_pitch_ppe_rollup(raw_ppe)
    hazards: list[str] = []
    actions: list[str] = []
    for item in rollup.get("effective_items", []):
        h = str(item.get("hazard") or "").strip()
        m = str(item.get("mitigation") or "").strip()
        if h and h not in hazards:
            hazards.append(h)
        if m and m not in actions:
            actions.append(m)
    return (" ".join(hazards), " ".join(actions))


def normalize_ppe_name(name: object) -> str:
    """Return canonical PPE name from catalog or legacy alias, preserving custom names."""
    raw = str(name or "").strip()
    if not raw:
        return ""
    key = raw.casefold()
    if key in PPE_LEGACY_ALIASES:
        return PPE_LEGACY_ALIASES[key]
    if key in _PPE_BY_CASEFOLD:
        return str(_PPE_BY_CASEFOLD[key]["name"])
    return raw


def get_ppe_catalog_item(name: object) -> dict[str, Any] | None:
    """Return catalog metadata dict for a PPE item if it belongs to PPE_CATALOG (or maps via alias)."""
    norm = normalize_ppe_name(name)
    if not norm:
        return None
    return _PPE_BY_CASEFOLD.get(norm.casefold())


_STANDARD_BASELINE_PPE_CASEFOLD: frozenset[str] = frozenset(
    n.casefold() for n in STANDARD_BASELINE_PPE
)


def is_barney_zone_ppe_item(name: object) -> bool:
    """Return True if a PPE item is outside the 3 standard baseline PPE items
    (Safety Glasses, Sturdy Closed Toe and Heel Shoes, Cut Level 2 Gloves)."""
    canon = normalize_ppe_name(name)
    if not canon:
        return False
    return canon.casefold() not in _STANDARD_BASELINE_PPE_CASEFOLD


def extract_barney_zone_ppe(raw_ppe_values: Iterable[object] | object) -> list[str]:
    """Return deduplicated list of non-standard (Barney Zone) PPE names from raw PPE input."""
    flat_names: list[str] = []
    if isinstance(raw_ppe_values, (str, bytes)):
        flat_names.extend(parse_ppe(raw_ppe_values))
    elif isinstance(raw_ppe_values, Iterable):
        for entry in raw_ppe_values:
            flat_names.extend(parse_ppe(entry))
    else:
        flat_names.extend(parse_ppe(raw_ppe_values))
    barney_names: list[str] = []
    seen_canon: set[str] = set()
    for raw_name in flat_names:
        canon = normalize_ppe_name(raw_name)
        if not canon or not is_barney_zone_ppe_item(canon):
            continue
        ckey = canon.casefold()
        if ckey not in seen_canon:
            seen_canon.add(ckey)
            barney_names.append(canon)
    return barney_names


def parse_ppe(val: object) -> list[str]:
    """Parse stored PPE value into a deduplicated list of strings."""
    if val is None:
        return []
    try:
        if bool(pd.isna(val)):
            return []
    except (TypeError, ValueError):
        pass
    raw_items: list[str] = []
    if isinstance(val, (list, tuple, set)):
        raw_items = [str(item).strip() for item in val if str(item).strip()]
    else:
        s = str(val).strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    raw_items = [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                raw_items = [p.strip() for p in s.split(",") if p.strip()]
        else:
            raw_items = [p.strip() for p in s.split(",") if p.strip()]

    unique_items: list[str] = []
    seen_casefold: set[str] = set()
    for item in raw_items:
        cleaned = "Chemical Resistant Galoshes" if item.casefold() == "chemiclal resistant galoshes" else item
        if not cleaned:
            continue
        k = cleaned.casefold()
        if k not in seen_casefold:
            seen_casefold.add(k)
            unique_items.append(cleaned)
    return unique_items


def serialize_ppe(val: object) -> str:
    """Serialize PPE list or string into stored JSON string."""
    items = parse_ppe(val)
    return json.dumps(items) if items else ""


def resolve_pitch_ppe_rollup(raw_ppe_values: Iterable[object] | object) -> dict[str, Any]:
    """Deduplicate PPE across a pitch and apply category hierarchy overrides.

    Hierarchy rules:
    - Cut Gloves: Cut Level 6 Gloves > Cut Level 4 Gloves > Cut Level 2 Gloves
    - Footwear: Safety Toe Shoes > Sturdy Closed Toe and Heel Shoes
    - Eye Protection: Foam Lined Safety Glasses > Safety Glasses
    """
    flat_names: list[str] = []
    if isinstance(raw_ppe_values, (str, bytes)):
        flat_names.extend(parse_ppe(raw_ppe_values))
    elif isinstance(raw_ppe_values, Iterable):
        for entry in raw_ppe_values:
            flat_names.extend(parse_ppe(entry))
    else:
        flat_names.extend(parse_ppe(raw_ppe_values))

    # Deduplicate by canonical catalog identity while remembering display label if only a legacy alias was used
    canonical_to_display: dict[str, str] = {}
    raw_unique_names: list[str] = []
    seen_canonical_casefold: set[str] = set()
    for raw_name in flat_names:
        canon = normalize_ppe_name(raw_name)
        if not canon:
            continue
        ckey = canon.casefold()
        # If the exact canonical name appears anywhere on the pitch, prefer the canonical name
        if ckey not in canonical_to_display or raw_name.casefold() == ckey:
            canonical_to_display[ckey] = canon if raw_name.casefold() == ckey else raw_name
        if ckey not in seen_canonical_casefold:
            seen_canonical_casefold.add(ckey)
            raw_unique_names.append(canon)

    highest_by_group: dict[str, dict[str, Any]] = {}
    items_by_group: dict[str, list[dict[str, Any]]] = {}
    for name in raw_unique_names:
        cat_item = get_ppe_catalog_item(name)
        if not cat_item:
            continue
        grp = str(cat_item.get("category_group") or "").strip()
        rank = int(cat_item.get("hierarchy_rank") or 0)
        if grp and rank > 0:
            items_by_group.setdefault(grp, []).append(cat_item)
            prev_best = highest_by_group.get(grp)
            if prev_best is None or rank > int(prev_best.get("hierarchy_rank") or 0):
                highest_by_group[grp] = cat_item

    overridden_names_casefold: set[str] = set()
    overridden_items: list[dict[str, str]] = []
    overrides: list[dict[str, Any]] = []
    for grp, grp_items in items_by_group.items():
        winner = highest_by_group.get(grp)
        if not winner or len(grp_items) <= 1:
            continue
        lower_names: list[str] = []
        cat_label = str(winner.get("category_label") or grp)
        winner_name = str(winner["name"])
        for item in sorted(grp_items, key=lambda x: int(x.get("hierarchy_rank") or 0)):
            if item["name"].casefold() != winner_name.casefold():
                overridden_names_casefold.add(item["name"].casefold())
                lower_names.append(str(item["name"]))
                overridden_items.append(
                    {
                        "item": str(item["name"]),
                        "overridden_by": winner_name,
                        "category": cat_label,
                    }
                )
        if lower_names:
            overrides.append(
                {
                    "category_group": grp,
                    "category_label": cat_label,
                    "winner": winner_name,
                    "overridden_items": lower_names,
                    "summary": f"{winner_name} overrides {', '.join(lower_names)} ({cat_label})",
                }
            )

    surviving_casefold = {
        n.casefold() for n in raw_unique_names if n.casefold() not in overridden_names_casefold
    }

    _group_primary_slot: dict[str, int] = {}
    for cat_item in PPE_CATALOG:
        grp = str(cat_item.get("category_group") or "").strip()
        c_idx = int(cat_item.get("catalog_index") or 0)
        if grp and grp not in _group_primary_slot:
            _group_primary_slot[grp] = c_idx

    ordered_catalog = sorted(
        PPE_CATALOG,
        key=lambda item: (
            _group_primary_slot.get(
                str(item.get("category_group") or "").strip(),
                int(item.get("catalog_index") or 0),
            ),
            int(item.get("catalog_index") or 0),
        ),
    )

    effective_items: list[dict[str, Any]] = []
    for cat_item in ordered_catalog:
        ckey = cat_item["name"].casefold()
        if ckey in surviving_casefold:
            display_name = canonical_to_display.get(ckey, str(cat_item["name"]))
            effective_items.append(
                {
                    "name": display_name,
                    "canonical_name": str(cat_item["name"]),
                    "image_filename": str(cat_item["image_filename"]),
                    "image_path": str(cat_item["image_path"]),
                    "jsa_image_filename": str(cat_item.get("jsa_image_filename") or ""),
                    "jsa_image_path": str(cat_item.get("jsa_image_path") or cat_item["image_path"]),
                    "hazard": str(cat_item["hazard"]),
                    "mitigation": str(cat_item["mitigation"]),
                    "category_group": str(cat_item["category_group"]),
                    "is_catalog": True,
                    "is_barney_zone_ppe": is_barney_zone_ppe_item(cat_item["name"]),
                }
            )

    catalog_casefold = {item["name"].casefold() for item in PPE_CATALOG}
    for name in raw_unique_names:
        k = name.casefold()
        if k in surviving_casefold and k not in catalog_casefold:
            effective_items.append(
                {
                    "name": canonical_to_display.get(k, name),
                    "canonical_name": name,
                    "image_filename": "",
                    "image_path": "",
                    "jsa_image_filename": "",
                    "jsa_image_path": "",
                    "hazard": "Task-specific workplace hazard.",
                    "mitigation": f"Correctly wear approved {name.upper()}.",
                    "category_group": "",
                    "is_catalog": False,
                    "is_barney_zone_ppe": is_barney_zone_ppe_item(name),
                }
            )

    effective_names = [item["name"] for item in effective_items]
    effective_canonical_names = [item["canonical_name"] for item in effective_items]
    baseline_set = {n.casefold() for n in STANDARD_BASELINE_PPE}
    effective_set = {n.casefold() for n in effective_canonical_names}
    barney_zone_items = [item for item in effective_items if item.get("is_barney_zone_ppe")]
    barney_zone_names = [str(item["name"]) for item in barney_zone_items]
    seen_barney_casefold = {str(item["canonical_name"]).casefold() for item in barney_zone_items}
    for raw_n in raw_unique_names:
        if is_barney_zone_ppe_item(raw_n) and raw_n.casefold() not in seen_barney_casefold:
            seen_barney_casefold.add(raw_n.casefold())
            barney_zone_names.append(canonical_to_display.get(raw_n.casefold(), raw_n))
    is_barney_zone = bool(barney_zone_names)
    is_standard_mode = bool(effective_set == baseline_set and not is_barney_zone)
    is_standard_only = bool(effective_set and effective_set.issubset(baseline_set) and not is_barney_zone)

    return {
        "effective_names": effective_names,
        "effective_canonical_names": effective_canonical_names,
        "effective_items": effective_items,
        "effective_ppe": effective_items,
        "overridden_items": overridden_items,
        "overrides": overrides,
        "raw_unique_names": raw_unique_names,
        "is_standard_mode": is_standard_mode,
        "is_standard_baseline": is_standard_mode,
        "is_standard_only": is_standard_only,
        "is_barney_zone": is_barney_zone,
        "barney_zone_names": barney_zone_names,
        "barney_zone_items": barney_zone_items,
    }


@cached_store_read
def safety_requirements(
    project_id: str,
    scenario_id: str,
    include_unassigned_steps: bool = False,
) -> pd.DataFrame:
    """Load scenario-specific Safety requirements with current Process labels.
    When include_unassigned_steps=True, every PAAG work element in the scenario is pre-populated."""
    columns = [
        "id", "project_id", "scenario_id", "work_element_id",
        "requirement_description", "ppe", "potential_hazards", "proposed_actions",
        "active",
        "source_snapshot_json", "source_acknowledged_at",
        "created_at", "updated_at",
        "work_element_label", "section_name", "pitch", "pitch_id",
        "sync_status", "upstream_changed", "upstream_diff_summary",
    ]
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")

        pitch_rows = conn.execute(
            """SELECT p.id, p.pitch_number,
                      COALESCE(NULLIF(TRIM(sec.name), ''), NULLIF(TRIM(a.name), ''), '') AS section_name
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id = p.area_id
               LEFT JOIN assembly_sections sec ON sec.id = a.section_id
               WHERE p.project_id = ? AND a.scenario_id = ?""",
            (project_id, scenario_id),
        ).fetchall()
        pitch_id_by_num = {
            str(r["pitch_number"] or "").strip(): str(r["id"])
            for r in pitch_rows
            if str(r["pitch_number"] or "").strip()
        }
        pitch_num_by_id = {
            str(r["id"]): str(r["pitch_number"] or "").strip()
            for r in pitch_rows
        }
        pitch_sec_by_id = {
            str(r["id"]): str(r["section_name"] or "").strip()
            for r in pitch_rows
        }
        pitch_sec_by_num = {
            str(r["pitch_number"] or "").strip(): str(r["section_name"] or "").strip()
            for r in pitch_rows
            if str(r["pitch_number"] or "").strip()
        }

        rows = conn.execute(
            """SELECT requirement.*,
                      COALESCE(requirement.ppe, '') AS ppe,
                      COALESCE(requirement.potential_hazards, '') AS potential_hazards,
                      COALESCE(requirement.proposed_actions, '') AS proposed_actions,
                      COALESCE(
                          (SELECT NULLIF(TRIM(yamazumi.description), '')
                           FROM yamazumi_elements yamazumi
                           WHERE yamazumi.project_id=requirement.project_id
                             AND yamazumi.process_element_id=requirement.work_element_id
                           ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                          NULLIF(TRIM(work.operation), ''), '') AS work_element_label,
                      COALESCE(
                          (SELECT NULLIF(TRIM(yamazumi.pitch_id), '')
                           FROM yamazumi_elements yamazumi
                           WHERE yamazumi.project_id=requirement.project_id
                             AND yamazumi.process_element_id=requirement.work_element_id
                           ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                          ''
                      ) AS yamazumi_pitch_id,
                      COALESCE(work.station, '') AS pitch,
                      work.sequence AS work_sequence,
                      COALESCE(
                          (SELECT yamazumi.time_s
                           FROM yamazumi_elements yamazumi
                           WHERE yamazumi.project_id=requirement.project_id
                             AND yamazumi.process_element_id=requirement.work_element_id
                           ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                          work.cycle_time_s,
                          0.0
                      ) AS cycle_time_s,
                      COALESCE(work.unit_orientation, '') AS unit_orientation,
                      work.conveyor_height_in AS conveyor_height_in,
                      work.platform_height_in AS platform_height_in,
                      work.pit_depth_in AS pit_depth_in,
                      COALESCE(work.resource_type, 'Human') AS resource_type,
                      COALESCE(work.resource_detail, '') AS resource_detail,
                      COALESCE(
                          (SELECT COALESCE(NULLIF(TRIM(sec.name), ''), NULLIF(TRIM(a.name), ''), '')
                           FROM yamazumi_elements yamazumi
                           JOIN yamazumi_areas a ON a.id = yamazumi.area_id
                           LEFT JOIN assembly_sections sec ON sec.id = a.section_id
                           WHERE yamazumi.project_id = requirement.project_id
                             AND yamazumi.process_element_id = requirement.work_element_id
                           ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                          ''
                      ) AS work_section_name
               FROM safety_requirements requirement
               JOIN work_elements work
                 ON work.id=requirement.work_element_id
                AND work.project_id=requirement.project_id
                AND work.scenario_id=requirement.scenario_id
               WHERE requirement.project_id=? AND requirement.scenario_id=?
               ORDER BY work.sequence, requirement.created_at, requirement.id""",
            (project_id, scenario_id),
        ).fetchall()

        all_we_rows = (
            conn.execute(
                """SELECT work.id AS work_element_id,
                          work.sequence AS work_sequence,
                          COALESCE(
                              (SELECT NULLIF(TRIM(yamazumi.description), '')
                               FROM yamazumi_elements yamazumi
                               WHERE yamazumi.project_id=work.project_id
                                 AND yamazumi.process_element_id=work.id
                               ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                              NULLIF(TRIM(work.operation), ''), '') AS work_element_label,
                          COALESCE(
                              (SELECT NULLIF(TRIM(yamazumi.pitch_id), '')
                               FROM yamazumi_elements yamazumi
                               WHERE yamazumi.project_id=work.project_id
                                 AND yamazumi.process_element_id=work.id
                               ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                              ''
                          ) AS yamazumi_pitch_id,
                          COALESCE(work.station, '') AS pitch,
                          COALESCE(
                              (SELECT COALESCE(NULLIF(TRIM(sec.name), ''), NULLIF(TRIM(a.name), ''), '')
                               FROM yamazumi_elements yamazumi
                               JOIN yamazumi_areas a ON a.id = yamazumi.area_id
                               LEFT JOIN assembly_sections sec ON sec.id = a.section_id
                               WHERE yamazumi.project_id = work.project_id
                                 AND yamazumi.process_element_id = work.id
                               ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                              ''
                          ) AS work_section_name
                   FROM work_elements work
                   WHERE work.project_id=? AND work.scenario_id=?
                   ORDER BY work.sequence, work.id""",
                (project_id, scenario_id),
            ).fetchall()
            if include_unassigned_steps
            else []
        )

    result_rows: list[dict[str, Any]] = []
    covered_work_element_ids: set[str] = set()
    for row in rows:
        d = dict(row)
        we_id = str(d.get("work_element_id") or "").strip()
        if we_id:
            covered_work_element_ids.add(we_id)
        y_pid = str(d.get("yamazumi_pitch_id") or "").strip()
        raw_pitch = str(d.get("pitch") or "").strip()
        if y_pid and y_pid in pitch_num_by_id:
            d["pitch_id"] = y_pid
            if not raw_pitch:
                d["pitch"] = pitch_num_by_id[y_pid]
        else:
            d["pitch_id"] = pitch_id_by_num.get(raw_pitch, "")
        d["section_name"] = (
            pitch_sec_by_id.get(d["pitch_id"], "")
            or pitch_sec_by_num.get(str(d.get("pitch") or "").strip(), "")
            or str(d.get("work_section_name") or "").strip()
        )
        d["ppe"] = parse_ppe(d.get("ppe"))
        d["potential_hazards"] = _strip_auto_ppe_text(d.get("potential_hazards"))
        d["proposed_actions"] = _strip_auto_ppe_text(d.get("proposed_actions"))
        d["source_snapshot_json"] = str(d.get("source_snapshot_json") or "")
        d["source_acknowledged_at"] = str(d.get("source_acknowledged_at") or "")
        live_snap = build_safety_process_snapshot(d)
        diffs = format_process_snapshot_diff(d["source_snapshot_json"], live_snap)
        d["upstream_changed"] = bool(diffs)
        d["upstream_diff_summary"] = " · ".join(diffs)
        barney_ppe = extract_barney_zone_ppe(d["ppe"])
        d["is_barney_zone"] = bool(barney_ppe)
        d["barney_zone_ppe"] = barney_ppe
        if diffs:
            d["sync_status"] = "⚠️ Upstream change"
        elif not d["ppe"]:
            d["sync_status"] = "⚠️ Needs PPE"
        else:
            d["sync_status"] = "🟣 Barney Zone" if barney_ppe else "Synced"
        result_rows.append(d)

    if include_unassigned_steps:
        for we_row in all_we_rows:
            we_id = str(we_row["work_element_id"] or "").strip()
            if not we_id or we_id in covered_work_element_ids:
                continue
            y_pid = str(we_row["yamazumi_pitch_id"] or "").strip()
            raw_pitch = str(we_row["pitch"] or "").strip()
            if y_pid and y_pid in pitch_num_by_id:
                resolved_pid = y_pid
                resolved_pitch = raw_pitch or pitch_num_by_id[y_pid]
            else:
                resolved_pid = pitch_id_by_num.get(raw_pitch, "")
                resolved_pitch = raw_pitch
            resolved_sec = (
                pitch_sec_by_id.get(resolved_pid, "")
                or pitch_sec_by_num.get(resolved_pitch, "")
                or str(we_row["work_section_name"] or "").strip()
            )
            result_rows.append(
                {
                    "id": f"__unassigned__::{we_id}",
                    "project_id": project_id,
                    "scenario_id": scenario_id,
                    "work_element_id": we_id,
                    "requirement_description": "",
                    "ppe": [],
                    "potential_hazards": "",
                    "proposed_actions": "",
                    "active": True,
                    "source_snapshot_json": "",
                    "source_acknowledged_at": "",
                    "created_at": "",
                    "updated_at": "",
                    "work_element_label": str(we_row["work_element_label"] or ""),
                    "section_name": resolved_sec,
                    "pitch": resolved_pitch,
                    "pitch_id": resolved_pid,
                    "work_sequence": int(we_row["work_sequence"] or 0),
                    "sync_status": "⚠️ Needs PPE",
                    "upstream_changed": False,
                    "upstream_diff_summary": "",
                }
            )
        result_rows.sort(
            key=lambda r: (
                0 if str(r.get("pitch") or "").strip() else 1,
                str(r.get("pitch") or "").strip().casefold(),
                int(r.get("work_sequence") or 0),
                0 if not str(r.get("id") or "").startswith("__unassigned__::") else 1,
                str(r.get("created_at") or ""),
                str(r.get("id") or ""),
            )
        )

    if not result_rows:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "scenario_id": pd.Series(dtype="string"),
            "work_element_id": pd.Series(dtype="string"),
            "requirement_description": pd.Series(dtype="string"),
            "ppe": pd.Series(dtype="object"),
            "potential_hazards": pd.Series(dtype="string"),
            "proposed_actions": pd.Series(dtype="string"),
            "active": pd.Series(dtype="bool"),
            "source_snapshot_json": pd.Series(dtype="string"),
            "source_acknowledged_at": pd.Series(dtype="string"),
            "created_at": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "work_element_label": pd.Series(dtype="string"),
            "section_name": pd.Series(dtype="string"),
            "pitch": pd.Series(dtype="string"),
            "pitch_id": pd.Series(dtype="string"),
            "sync_status": pd.Series(dtype="string"),
            "upstream_changed": pd.Series(dtype="bool"),
            "upstream_diff_summary": pd.Series(dtype="string"),
        })
    return pd.DataFrame(result_rows, columns=columns)


def save_safety_requirements(
    project_id: str,
    scenario_id: str,
    edited: pd.DataFrame,
    editor_name: str,
) -> dict:
    """Atomically validate and save Safety rows without deleting omitted rows."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before saving Safety requirements.")
    timestamp = now_iso()
    prepared: list[dict] = []
    for _, row in edited.iterrows():
        raw_id = row.get("id")
        raw_id_str = (
            str(raw_id).strip()
            if raw_id is not None and not pd.isna(raw_id)
            else ""
        )
        is_unassigned_placeholder = raw_id_str.startswith("__unassigned__::")
        work_element_id = str(row.get("work_element_id") or "").strip()
        if not work_element_id and is_unassigned_placeholder:
            work_element_id = raw_id_str.split("__unassigned__::", 1)[1].strip()
        description = (
            ""
            if row.get("requirement_description") is None or pd.isna(row.get("requirement_description"))
            else str(row.get("requirement_description") or "").strip()
        )
        raw_ppe = row.get("ppe")
        ppe_list = parse_ppe(raw_ppe)
        ppe_str = serialize_ppe(ppe_list)
        raw_hazards = row.get("potential_hazards")
        potential_hazards = (
            ""
            if raw_hazards is None or pd.isna(raw_hazards)
            else str(raw_hazards).strip()
        )
        raw_actions = row.get("proposed_actions")
        proposed_actions = (
            ""
            if raw_actions is None or pd.isna(raw_actions)
            else str(raw_actions).strip()
        )
        if is_unassigned_placeholder and (
            not description
            and not ppe_list
            and not potential_hazards
            and not proposed_actions
        ):
            continue
        if (
            not work_element_id
            and not description
            and not ppe_list
            and not potential_hazards
            and not proposed_actions
        ):
            continue
        if not work_element_id:
            raise ValueError("Process Function is required for every Safety requirement.")
        if (not description or description.startswith("PPE:")) and ppe_list:
            description = f"PPE: {', '.join(ppe_list)}"
        elif not description and (potential_hazards or proposed_actions):
            description = potential_hazards or proposed_actions
        elif not description:
            raise ValueError("Requirement description or PPE is required for every Safety requirement.")
        requirement_id = (
            raw_id_str
            if raw_id_str and not is_unassigned_placeholder
            else str(uuid4())
        )
        raw_active = row.get("active", True)
        active = 1 if raw_active is None or pd.isna(raw_active) else int(bool(raw_active))
        prepared.append({
            "id": requirement_id,
            "work_element_id": work_element_id,
            "requirement_description": description,
            "ppe": ppe_str,
            "potential_hazards": potential_hazards,
            "proposed_actions": proposed_actions,
            "has_hazards_col": "potential_hazards" in row.index,
            "has_actions_col": "proposed_actions" in row.index,
            "active": active,
        })
    if len({row["id"] for row in prepared}) != len(prepared):
        raise ValueError("Safety requirement identities must be unique.")
    changed_ids: list[str] = []
    created_ids: list[str] = []
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        valid_work_ids = {
            str(row["id"])
            for row in conn.execute(
                """SELECT id FROM work_elements
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        if any(row["work_element_id"] not in valid_work_ids for row in prepared):
            raise ValueError(
                "Every Process Function must belong to the active project and scenario."
            )
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM safety_requirements
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        we_inputs = _fetch_work_element_snapshot_inputs(
            conn,
            project_id,
            scenario_id,
            [str(r["work_element_id"]) for r in prepared if r.get("work_element_id")],
        )
        for row in prepared:
            previous = existing.get(row["id"])
            we_row = we_inputs.get(str(row["work_element_id"]))
            live_snap_json = (
                json.dumps(build_safety_process_snapshot(we_row), sort_keys=True)
                if we_row
                else ""
            )
            if previous:
                prev_ppe_norm = serialize_ppe(previous.get("ppe"))
                prev_haz = str(previous.get("potential_hazards") or "")
                prev_act = str(previous.get("proposed_actions") or "")
                eff_haz = row["potential_hazards"] if row["has_hazards_col"] else prev_haz
                eff_act = row["proposed_actions"] if row["has_actions_col"] else prev_act
                changed = (
                    previous.get("work_element_id") != row["work_element_id"]
                    or previous.get("requirement_description") != row["requirement_description"]
                    or prev_ppe_norm != (row["ppe"] or "")
                    or prev_haz != eff_haz
                    or prev_act != eff_act
                    or int(previous.get("active") or 0) != int(row["active"] or 0)
                )
                if not changed:
                    continue
                conn.execute(
                    """UPDATE safety_requirements
                       SET work_element_id=?, requirement_description=?, ppe=?,
                           potential_hazards=?, proposed_actions=?, active=?,
                           source_snapshot_json=?, source_acknowledged_at=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        row["work_element_id"], row["requirement_description"],
                        row["ppe"], eff_haz, eff_act, row["active"],
                        live_snap_json, timestamp, timestamp,
                        row["id"], project_id, scenario_id,
                    ),
                )
                changed_ids.append(row["id"])
            else:
                conn.execute(
                    """INSERT INTO safety_requirements
                       (id, project_id, scenario_id, work_element_id,
                        requirement_description, ppe, potential_hazards, proposed_actions,
                        active, source_snapshot_json, source_acknowledged_at,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"], project_id, scenario_id, row["work_element_id"],
                        row["requirement_description"], row["ppe"],
                        row["potential_hazards"], row["proposed_actions"],
                        row["active"], live_snap_json, timestamp,
                        timestamp, timestamp,
                    ),
                )
                created_ids.append(row["id"])
        row_count = len(created_ids) + len(changed_ids)
        if row_count:
            record_audit_event(
                project_id,
                "Safety requirements",
                "Save & Refresh",
                row_count,
                editor,
                {
                    "scenario_id": scenario_id,
                    "created_ids": created_ids,
                    "updated_ids": changed_ids,
                    "updated_at": timestamp,
                },
                _conn=conn,
            )
    return {
        "row_count": len(created_ids) + len(changed_ids),
        "created_ids": created_ids,
        "updated_ids": changed_ids,
        "timestamp": timestamp,
    }


def apply_standard_baseline_ppe(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | None = None,
    editor_name: str = "Collaborator",
) -> dict[str, Any]:
    """Assign Standard Baseline PPE (Cut Level 2 Gloves, Safety Glasses, Sturdy Closed Toe and Heel Shoes)
    to scenario work elements that currently lack active PPE assignments."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before applying Standard Baseline PPE.")
    timestamp = now_iso()
    baseline_ppe_json = serialize_ppe(STANDARD_BASELINE_PPE)
    baseline_desc = f"PPE: {', '.join(STANDARD_BASELINE_PPE)}"

    target_filter_ids = (
        {str(wid).strip() for wid in work_element_ids if str(wid).strip()}
        if work_element_ids is not None
        else None
    )

    created_ids: list[str] = []
    updated_ids: list[str] = []

    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")

        we_rows = conn.execute(
            """SELECT id FROM work_elements
               WHERE project_id=? AND scenario_id=?
               ORDER BY sequence, id""",
            (project_id, scenario_id),
        ).fetchall()
        all_work_ids = [
            str(r["id"])
            for r in we_rows
            if target_filter_ids is None or str(r["id"]) in target_filter_ids
        ]
        if not all_work_ids:
            return {
                "row_count": 0,
                "created_ids": [],
                "updated_ids": [],
                "timestamp": timestamp,
            }

        req_rows = conn.execute(
            """SELECT id, work_element_id, requirement_description, ppe, active
               FROM safety_requirements
               WHERE project_id=? AND scenario_id=?
               ORDER BY created_at, id""",
            (project_id, scenario_id),
        ).fetchall()

        reqs_by_we: dict[str, list[dict[str, Any]]] = {}
        for r in req_rows:
            reqs_by_we.setdefault(str(r["work_element_id"]), []).append(dict(r))

        we_inputs = _fetch_work_element_snapshot_inputs(
            conn, project_id, scenario_id, all_work_ids
        )

        for we_id in all_work_ids:
            existing_reqs = reqs_by_we.get(we_id, [])
            has_active_ppe = any(
                int(r.get("active") or 0) == 1 and bool(parse_ppe(r.get("ppe")))
                for r in existing_reqs
            )
            if has_active_ppe:
                continue

            we_row = we_inputs.get(we_id)
            live_snap_json = (
                json.dumps(build_safety_process_snapshot(we_row), sort_keys=True)
                if we_row
                else ""
            )

            # Check if there is an active row without PPE we can populate in place
            active_blank_row = next(
                (r for r in existing_reqs if int(r.get("active") or 0) == 1 and not parse_ppe(r.get("ppe"))),
                None,
            )
            if active_blank_row is not None:
                req_id = str(active_blank_row["id"])
                new_desc = str(active_blank_row.get("requirement_description") or "").strip() or baseline_desc
                conn.execute(
                    """UPDATE safety_requirements
                       SET requirement_description=?, ppe=?,
                           source_snapshot_json=?, source_acknowledged_at=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        new_desc,
                        baseline_ppe_json,
                        live_snap_json,
                        timestamp,
                        timestamp,
                        req_id,
                        project_id,
                        scenario_id,
                    ),
                )
                updated_ids.append(req_id)
            else:
                req_id = str(uuid4())
                conn.execute(
                    """INSERT INTO safety_requirements
                       (id, project_id, scenario_id, work_element_id,
                        requirement_description, ppe, active,
                        source_snapshot_json, source_acknowledged_at,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                    (
                        req_id,
                        project_id,
                        scenario_id,
                        we_id,
                        baseline_desc,
                        baseline_ppe_json,
                        live_snap_json,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                created_ids.append(req_id)

        total_changed = len(created_ids) + len(updated_ids)
        if total_changed:
            record_audit_event(
                project_id,
                "Safety requirements",
                "Apply baseline PPE",
                total_changed,
                editor,
                {
                    "scenario_id": scenario_id,
                    "baseline_ppe": list(STANDARD_BASELINE_PPE),
                    "created_ids": created_ids,
                    "updated_ids": updated_ids,
                    "updated_at": timestamp,
                },
                _conn=conn,
            )

    return {
        "row_count": len(created_ids) + len(updated_ids),
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "timestamp": timestamp,
    }


@cached_store_read(scope="scenario")
def pitch_ppe_poster_summary(
    project_id: str,
    scenario_id: str,
    pitch_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return per-pitch PPE rollup, hierarchy overrides, work-element breakdown, and poster metadata."""
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            return []

        pitch_filter_sql = "AND p.id = ?" if pitch_id else ""
        pitch_params: tuple[Any, ...] = (
            (project_id, scenario_id, str(pitch_id))
            if pitch_id
            else (project_id, scenario_id)
        )
        pitch_rows = conn.execute(
            f"""SELECT p.id AS pitch_id,
                       p.pitch_number,
                       COALESCE(p.pitch_name, '') AS pitch_name,
                       p.status AS pitch_status,
                       p.sequence AS pitch_sequence,
                       COALESCE(p.ppe_poster_job_override, '') AS ppe_poster_job_override,
                       COALESCE(p.ppe_poster_workstation_override, '') AS ppe_poster_workstation_override,
                       COALESCE(p.ppe_poster_section_override, '') AS ppe_poster_section_override,
                       COALESCE(p.jsa_rows_override_json, '') AS jsa_rows_override_json,
                       a.id AS area_id,
                       a.name AS area_name,
                       COALESCE(sec.name, '') AS section_name,
                       COALESCE(sec.sequence, 9999) AS section_sequence
                FROM yamazumi_pitches p
                JOIN yamazumi_areas a ON a.id = p.area_id
                LEFT JOIN assembly_sections sec ON sec.id = a.section_id
                WHERE p.project_id = ? AND a.scenario_id = ? {pitch_filter_sql}
                ORDER BY COALESCE(sec.sequence, 9999), a.name, p.sequence, p.pitch_number""",
            pitch_params,
        ).fetchall()

        if not pitch_rows:
            return []

        # Fetch all work elements and their pitch links in this scenario
        we_rows = conn.execute(
            """SELECT w.id AS work_element_id,
                      w.sequence AS work_sequence,
                      COALESCE(w.station, '') AS station,
                      COALESCE(w.operation, '') AS operation,
                      COALESCE(w.description, '') AS description,
                      y.pitch_id AS yamazumi_pitch_id,
                      COALESCE(y.description, '') AS yamazumi_description,
                      COALESCE(y.sequence, w.sequence) AS elem_sequence
               FROM work_elements w
               LEFT JOIN yamazumi_elements y
                 ON y.project_id = w.project_id
                AND y.process_element_id = w.id
               WHERE w.project_id = ? AND w.scenario_id = ?
               ORDER BY COALESCE(y.sequence, w.sequence), w.sequence, w.id""",
            (project_id, scenario_id),
        ).fetchall()

        safety_rows = conn.execute(
            """SELECT id, work_element_id, requirement_description, ppe, active
               FROM safety_requirements
               WHERE project_id = ? AND scenario_id = ? AND active = 1
               ORDER BY created_at, id""",
            (project_id, scenario_id),
        ).fetchall()

    safety_by_we: dict[str, list[dict[str, Any]]] = {}
    for srow in safety_rows:
        safety_by_we.setdefault(str(srow["work_element_id"]), []).append(dict(srow))

    pitch_id_by_number: dict[str, str] = {
        str(p["pitch_number"] or "").strip().casefold(): str(p["pitch_id"])
        for p in pitch_rows
        if str(p["pitch_number"] or "").strip()
    }

    elements_by_pitch: dict[str, list[dict[str, Any]]] = {}
    seen_pitch_we: set[tuple[str, str]] = set()
    for wrow in we_rows:
        we_id = str(wrow["work_element_id"])
        resolved_pitch_id = str(wrow["yamazumi_pitch_id"] or "").strip()
        if not resolved_pitch_id:
            st_key = str(wrow["station"] or "").strip().casefold()
            resolved_pitch_id = pitch_id_by_number.get(st_key, "")
        if not resolved_pitch_id:
            continue
        pair_key = (resolved_pitch_id, we_id)
        if pair_key in seen_pitch_we:
            continue
        seen_pitch_we.add(pair_key)

        label = (
            _strip_yamazumi_area_text(wrow["yamazumi_description"])
            or _strip_yamazumi_area_text(wrow["operation"])
            or _strip_yamazumi_area_text(wrow["description"])
            or "Work element"
        )
        we_reqs = safety_by_we.get(we_id, [])
        we_ppe_raw: list[str] = []
        we_notes: list[str] = []
        for req in we_reqs:
            we_ppe_raw.extend(parse_ppe(req.get("ppe")))
            desc = str(req.get("requirement_description") or "").strip()
            if desc and not desc.startswith("PPE:"):
                we_notes.append(desc)
        we_ppe_unique = parse_ppe(we_ppe_raw)
        pitch_elem_list = elements_by_pitch.setdefault(resolved_pitch_id, [])
        pitch_elem_list.append(
            {
                "step_number": len(pitch_elem_list) + 1,
                "work_element_id": we_id,
                "label": label,
                "operation": label,
                "ppe": we_ppe_unique,
                "has_ppe": bool(we_ppe_unique),
                "safety_notes": we_notes,
            }
        )

    summaries: list[dict[str, Any]] = []
    for prow in pitch_rows:
        pid = str(prow["pitch_id"])
        p_num = str(prow["pitch_number"] or "").strip()
        p_name = str(prow["pitch_name"] or "").strip()
        sec_name = str(prow["section_name"] or "").strip()
        area_name = str(prow["area_name"] or "").strip()

        pitch_elements = elements_by_pitch.get(pid, [])
        all_pitch_ppe_lists = [el["ppe"] for el in pitch_elements if el["ppe"]]
        raw_jsa_override = str(prow["jsa_rows_override_json"] or "").strip()
        if not all_pitch_ppe_lists and raw_jsa_override:
            try:
                parsed_jsa_ov = json.loads(raw_jsa_override)
                if isinstance(parsed_jsa_ov, dict) and "effective_ppe" in parsed_jsa_ov:
                    ov_ppe = parse_ppe(parsed_jsa_ov.get("effective_ppe"))
                    if ov_ppe:
                        all_pitch_ppe_lists = [ov_ppe]
            except Exception:
                pass
        rollup = resolve_pitch_ppe_rollup(all_pitch_ppe_lists)

        unassigned_elements = [el["label"] for el in pitch_elements if not el["has_ppe"]]
        assigned_count = sum(1 for el in pitch_elements if el["has_ppe"])

        default_job = p_name or p_num
        default_workstation = p_num
        default_section = sec_name or area_name

        job_override = str(prow["ppe_poster_job_override"] or "").strip()
        ws_override = str(prow["ppe_poster_workstation_override"] or "").strip()
        sec_override = str(prow["ppe_poster_section_override"] or "").strip()

        summaries.append(
            {
                "pitch_id": pid,
                "pitch_number": p_num,
                "pitch_name": p_name,
                "pitch_display_label": f"{p_num} — {p_name}" if p_name else p_num,
                "area_name": area_name,
                "section_name": sec_name,
                "default_job": default_job,
                "default_workstation": default_workstation,
                "default_section": default_section,
                "job_override": job_override,
                "workstation_override": ws_override,
                "section_override": sec_override,
                "ppe_poster_job_override": job_override,
                "ppe_poster_workstation_override": ws_override,
                "ppe_poster_section_override": sec_override,
                "effective_job": job_override or default_job,
                "effective_workstation": ws_override or default_workstation,
                "effective_section": sec_override or default_section,
                "job_name": job_override or default_job,
                "workstation": ws_override or default_workstation,
                "section": sec_override or default_section,
                "work_elements": pitch_elements,
                "elements": pitch_elements,
                "unassigned_elements": unassigned_elements,
                "assigned_element_count": assigned_count,
                "unassigned_element_count": len(unassigned_elements),
                "rollup": rollup,
                "effective_ppe_names": rollup["effective_names"],
                "effective_ppe_items": rollup["effective_items"],
                "effective_ppe": rollup["effective_items"],
                "overridden_ppe_items": rollup["overridden_items"],
                "overrides": rollup["overrides"],
                "raw_unique_ppe_names": rollup["raw_unique_names"],
                "is_standard_mode": rollup["is_standard_mode"],
                "is_standard_baseline": rollup["is_standard_mode"],
                "is_standard_only": rollup["is_standard_only"],
                "is_barney_zone": rollup["is_barney_zone"],
                "barney_zone_names": rollup["barney_zone_names"],
                "barney_zone_items": rollup["barney_zone_items"],
            }
        )
    return summaries


def save_pitch_ppe_poster_overrides(
    project_id: str,
    scenario_id: str,
    pitch_id: str,
    job_override: str = "",
    workstation_override: str = "",
    section_override: str = "",
    editor_name: str = "Collaborator",
) -> dict[str, Any]:
    """Persist per-pitch PPE Poster header overrides (Job, Workstation, Section) with audit logging."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before saving PPE Poster header overrides.")
    pid = str(pitch_id or "").strip()
    if not pid:
        raise ValueError("Select a valid pitch before saving PPE Poster header overrides.")

    clean_job = str(job_override or "").strip()
    clean_ws = str(workstation_override or "").strip()
    clean_sec = str(section_override or "").strip()
    timestamp = now_iso()

    with connection() as conn:
        row = conn.execute(
            """SELECT p.id, p.pitch_number,
                      COALESCE(p.ppe_poster_job_override, '') AS old_job,
                      COALESCE(p.ppe_poster_workstation_override, '') AS old_ws,
                      COALESCE(p.ppe_poster_section_override, '') AS old_sec
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id = p.area_id
               WHERE p.id = ? AND p.project_id = ? AND a.scenario_id = ?""",
            (pid, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("The selected pitch no longer belongs to the active scenario.")

        changed = (
            str(row["old_job"]) != clean_job
            or str(row["old_ws"]) != clean_ws
            or str(row["old_sec"]) != clean_sec
        )
        if changed:
            conn.execute(
                """UPDATE yamazumi_pitches
                   SET ppe_poster_job_override = ?,
                       ppe_poster_workstation_override = ?,
                       ppe_poster_section_override = ?,
                       updated_at = ?
                   WHERE id = ? AND project_id = ?""",
                (clean_job, clean_ws, clean_sec, timestamp, pid, project_id),
            )
            record_audit_event(
                project_id,
                "Safety requirements",
                "Update PPE poster header",
                1,
                editor,
                {
                    "scenario_id": scenario_id,
                    "pitch_id": pid,
                    "pitch_number": str(row["pitch_number"] or ""),
                    "job_override": clean_job,
                    "workstation_override": clean_ws,
                    "section_override": clean_sec,
                    "updated_at": timestamp,
                },
                _conn=conn,
            )

    return {
        "changed": changed,
        "pitch_id": pid,
        "job_override": clean_job,
        "workstation_override": clean_ws,
        "section_override": clean_sec,
        "timestamp": timestamp,
    }


@cached_store_read(scope="scenario")
def pitch_jsa_poster_summary(
    project_id: str,
    scenario_id: str,
    pitch_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return per-pitch Job Safety Analysis (JSA) poster summary, pre-populated from PAAG steps, PPE rollup, and pitch photos."""
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            return []

        proj_row = conn.execute(
            "SELECT building_location FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        default_building_loc = (
            str(proj_row["building_location"] or "").strip() if proj_row else ""
        )

        pitch_filter_sql = "AND p.id = ?" if pitch_id else ""
        pitch_params: tuple[Any, ...] = (
            (project_id, scenario_id, str(pitch_id))
            if pitch_id
            else (project_id, scenario_id)
        )
        pitch_rows = conn.execute(
            f"""SELECT p.id AS pitch_id,
                       p.pitch_number,
                       COALESCE(p.pitch_name, '') AS pitch_name,
                       p.status AS pitch_status,
                       p.sequence AS pitch_sequence,
                       COALESCE(p.jsa_job_title_override, '') AS jsa_job_title_override,
                       COALESCE(NULLIF(TRIM(p.jsa_plant_code), ''), '') AS jsa_plant_code,
                       COALESCE(p.jsa_important_notice, '') AS jsa_important_notice,
                       COALESCE(p.jsa_include_pitch_photos, 1) AS jsa_include_pitch_photos,
                       COALESCE(p.jsa_rows_override_json, '') AS jsa_rows_override_json,
                       a.id AS area_id,
                       a.name AS area_name,
                       COALESCE(sec.name, '') AS section_name,
                       COALESCE(sec.sequence, 9999) AS section_sequence
                FROM yamazumi_pitches p
                JOIN yamazumi_areas a ON a.id = p.area_id
                LEFT JOIN assembly_sections sec ON sec.id = a.section_id
                WHERE p.project_id = ? AND a.scenario_id = ? {pitch_filter_sql}
                ORDER BY COALESCE(sec.sequence, 9999), a.name, p.sequence, p.pitch_number""",
            pitch_params,
        ).fetchall()

        if not pitch_rows:
            return []

        we_rows = conn.execute(
            """SELECT w.id AS work_element_id,
                      w.sequence AS work_sequence,
                      COALESCE(w.station, '') AS station,
                      COALESCE(w.operation, '') AS operation,
                      COALESCE(w.description, '') AS description,
                      COALESCE(w.tool, '') AS tool,
                      COALESCE(w.torque, '') AS torque,
                      y.pitch_id AS yamazumi_pitch_id,
                      COALESCE(y.description, '') AS yamazumi_description,
                      COALESCE(y.sequence, w.sequence) AS elem_sequence
               FROM work_elements w
               LEFT JOIN yamazumi_elements y
                 ON y.project_id = w.project_id
                AND y.process_element_id = w.id
               WHERE w.project_id = ? AND w.scenario_id = ?
               ORDER BY COALESCE(y.sequence, w.sequence), w.sequence, w.id""",
            (project_id, scenario_id),
        ).fetchall()

        safety_rows = conn.execute(
            """SELECT id, work_element_id, requirement_description, ppe,
                      COALESCE(potential_hazards, '') AS potential_hazards,
                      COALESCE(proposed_actions, '') AS proposed_actions,
                      active
               FROM safety_requirements
               WHERE project_id = ? AND scenario_id = ? AND active = 1
               ORDER BY created_at, id""",
            (project_id, scenario_id),
        ).fetchall()

        media_rows = conn.execute(
            """SELECT m.id, m.pitch_id, m.media_type, m.file_path, m.caption, m.sequence
               FROM process_visual_media m
               WHERE m.project_id = ? AND m.scenario_id = ? AND m.media_type = 'image'
               ORDER BY m.sequence, m.created_at, m.id""",
            (project_id, scenario_id),
        ).fetchall()

        media_tags_rows = conn.execute(
            """SELECT media_id, work_element_id
               FROM process_visual_media_tags
               WHERE project_id = ? AND scenario_id = ?""",
            (project_id, scenario_id),
        ).fetchall()

    safety_by_we: dict[str, list[dict[str, Any]]] = {}
    for srow in safety_rows:
        safety_by_we.setdefault(str(srow["work_element_id"]), []).append(dict(srow))

    tags_by_media: dict[str, set[str]] = {}
    for trow in media_tags_rows:
        tags_by_media.setdefault(str(trow["media_id"]), set()).add(str(trow["work_element_id"]))

    pitch_id_by_number: dict[str, str] = {
        str(p["pitch_number"] or "").strip().casefold(): str(p["pitch_id"])
        for p in pitch_rows
        if str(p["pitch_number"] or "").strip()
    }

    elements_by_pitch: dict[str, list[dict[str, Any]]] = {}
    seen_pitch_we: set[tuple[str, str]] = set()
    for wrow in we_rows:
        we_id = str(wrow["work_element_id"])
        resolved_pitch_id = str(wrow["yamazumi_pitch_id"] or "").strip()
        if not resolved_pitch_id:
            st_key = str(wrow["station"] or "").strip().casefold()
            resolved_pitch_id = pitch_id_by_number.get(st_key, "")
        if not resolved_pitch_id:
            continue
        pair_key = (resolved_pitch_id, we_id)
        if pair_key in seen_pitch_we:
            continue
        seen_pitch_we.add(pair_key)

        op_label = (
            _strip_yamazumi_area_text(wrow["yamazumi_description"])
            or _strip_yamazumi_area_text(wrow["operation"])
            or _strip_yamazumi_area_text(wrow["description"])
            or "Work element"
        )
        proc_desc = _strip_yamazumi_area_text(wrow["description"])
        if proc_desc and proc_desc.casefold() != op_label.casefold():
            job_step_text = f"{op_label} — {proc_desc}"
        else:
            job_step_text = op_label

        we_reqs = safety_by_we.get(we_id, [])
        we_ppe_raw: list[str] = []
        stored_hazards_list: list[str] = []
        stored_actions_list: list[str] = []
        req_desc_list: list[str] = []
        primary_req_id = str(we_reqs[0]["id"]) if we_reqs else ""
        for req in we_reqs:
            we_ppe_raw.extend(parse_ppe(req.get("ppe")))
            hz = _strip_auto_ppe_text(req.get("potential_hazards"))
            if hz and hz not in stored_hazards_list:
                stored_hazards_list.append(hz)
            ac = _strip_auto_ppe_text(req.get("proposed_actions"))
            if ac and ac not in stored_actions_list:
                stored_actions_list.append(ac)

        we_ppe_unique = parse_ppe(we_ppe_raw)
        auto_hazards, auto_actions = ("", "")
        stored_hazards = " | ".join(stored_hazards_list)
        stored_actions = " | ".join(stored_actions_list)
        effective_hazards = stored_hazards
        effective_actions = stored_actions

        pitch_elem_list = elements_by_pitch.setdefault(resolved_pitch_id, [])
        pitch_elem_list.append(
            {
                "step_number": len(pitch_elem_list) + 1,
                "work_element_id": we_id,
                "requirement_id": primary_req_id,
                "job_step": job_step_text,
                "operation": op_label,
                "description": proc_desc,
                "tool": str(wrow["tool"] or "").strip(),
                "torque": str(wrow["torque"] or "").strip(),
                "ppe": we_ppe_unique,
                "has_ppe": bool(we_ppe_unique),
                "stored_potential_hazards": stored_hazards,
                "stored_proposed_actions": stored_actions,
                "auto_potential_hazards": auto_hazards,
                "auto_proposed_actions": auto_actions,
                "potential_hazards": effective_hazards,
                "proposed_actions": effective_actions,
                "is_auto_ppe_row": False,
            }
        )

    summaries: list[dict[str, Any]] = []
    for prow in pitch_rows:
        pid = str(prow["pitch_id"])
        p_num = str(prow["pitch_number"] or "").strip()
        p_name = str(prow["pitch_name"] or "").strip()
        sec_name = str(prow["section_name"] or "").strip()
        area_name = str(prow["area_name"] or "").strip()

        pitch_elements = elements_by_pitch.get(pid, [])
        pitch_we_ids = {el["work_element_id"] for el in pitch_elements}
        all_pitch_ppe_lists = [el["ppe"] for el in pitch_elements if el["ppe"]]
        raw_override_json_pre = str(prow["jsa_rows_override_json"] or "").strip()
        if not all_pitch_ppe_lists and raw_override_json_pre:
            try:
                parsed_ov_pre = json.loads(raw_override_json_pre)
                if isinstance(parsed_ov_pre, dict) and "effective_ppe" in parsed_ov_pre:
                    ov_ppe_pre = parse_ppe(parsed_ov_pre.get("effective_ppe"))
                    if ov_ppe_pre:
                        all_pitch_ppe_lists = [ov_ppe_pre]
            except Exception:
                pass
        rollup = resolve_pitch_ppe_rollup(all_pitch_ppe_lists)

        # Collect PAAG pitch visual aid photos for this pitch
        pitch_photos: list[dict[str, Any]] = []
        for mrow in media_rows:
            mid = str(mrow["id"])
            m_tags = tags_by_media.get(mid, set())
            if (m_tags and (m_tags & pitch_we_ids)) or (not m_tags and str(mrow["pitch_id"]) == pid):
                pitch_photos.append(
                    {
                        "id": mid,
                        "file_path": str(mrow["file_path"] or ""),
                        "caption": str(mrow["caption"] or "").strip() or f"{p_num} Visual Aid",
                    }
                )

        default_job_title = f"{p_num} — {p_name}" if (p_num and p_name) else (p_name or p_num)
        job_title_override = str(prow["jsa_job_title_override"] or "").strip()
        effective_job_title = job_title_override or default_job_title

        raw_plant_override = str(prow["jsa_plant_code"] or "").strip()
        if raw_plant_override == "AP1" and default_building_loc:
            plant_code_override = ""
        else:
            plant_code_override = raw_plant_override
        effective_plant_code = plant_code_override or default_building_loc or "AP1"

        target_op_name = p_name or p_num or "workstation"
        default_important_notice = (
            f"The JSA should be reviewed by all employees operating {target_op_name}. "
            "This JSA should be reviewed & updated when changes to equipment / processes occur."
        )
        important_notice_override = str(prow["jsa_important_notice"] or "").strip()
        effective_important_notice = important_notice_override or default_important_notice

        include_pitch_photos = bool(int(prow["jsa_include_pitch_photos"] or 0))

        eff_ppe_names = rollup["effective_names"]
        put_on_ppe_action = ", ".join(eff_ppe_names) if eff_ppe_names else ""
        for el in pitch_elements:
            if not str(el.get("section_name") or "").strip():
                el["section_name"] = sec_name
        auto_ppe_row = {
            "step_number": 0,
            "work_element_id": "",
            "requirement_id": "",
            "section_name": sec_name,
            "job_step": "Put on PPE",
            "operation": "Put on PPE",
            "description": "",
            "tool": "",
            "torque": "",
            "ppe": eff_ppe_names,
            "has_ppe": bool(eff_ppe_names),
            "stored_potential_hazards": "",
            "stored_proposed_actions": "",
            "auto_potential_hazards": "",
            "auto_proposed_actions": "",
            "potential_hazards": "",
            "proposed_actions": "",
            "is_auto_ppe_row": True,
        }

        jsa_table_rows = [auto_ppe_row, *pitch_elements]
        raw_override_json = str(prow["jsa_rows_override_json"] or "").strip()
        if raw_override_json:
            try:
                parsed_override = json.loads(raw_override_json)
                if isinstance(parsed_override, dict):
                    saved_rows_list = parsed_override.get("rows") or []
                    known_we_ids = set(str(x) for x in (parsed_override.get("known_we_ids") or []) if str(x).strip())
                elif isinstance(parsed_override, list):
                    saved_rows_list = parsed_override
                    known_we_ids = set()
                else:
                    saved_rows_list = []
                    known_we_ids = set()
                if saved_rows_list:
                    elem_by_we = {str(el["work_element_id"]): el for el in pitch_elements}
                    reconstructed: list[dict[str, Any]] = []
                    seen_saved_we: set[str] = set()
                    for idx_r, s_row in enumerate(saved_rows_list):
                        if not isinstance(s_row, dict):
                            continue
                        we_id_val = str(s_row.get("work_element_id") or "").strip()
                        is_auto = bool(s_row.get("is_auto_ppe_row"))
                        if we_id_val and we_id_val not in elem_by_we and we_id_val in known_we_ids:
                            # This work element was moved off this pitch in Yamazumi
                            continue
                        if we_id_val:
                            seen_saved_we.add(we_id_val)
                        base_elem = elem_by_we.get(we_id_val, {})
                        reconstructed.append(
                            {
                                **base_elem,
                                "step_number": idx_r,
                                "work_element_id": we_id_val,
                                "section_name": str(s_row.get("section_name") or base_elem.get("section_name") or sec_name or ""),
                                "job_step": _strip_yamazumi_area_text(s_row.get("job_step")),
                                "potential_hazards": _strip_auto_ppe_text(
                                    s_row.get("potential_hazards"),
                                    is_auto_ppe_row=is_auto,
                                ),
                                "proposed_actions": _strip_auto_ppe_text(
                                    s_row.get("proposed_actions"),
                                    is_auto_ppe_row=is_auto,
                                ),
                                "is_auto_ppe_row": is_auto,
                            }
                        )
                    # Append any newly rebalanced PAAG work elements not previously in known_we_ids
                    for el in pitch_elements:
                        w_id = str(el["work_element_id"])
                        if w_id not in seen_saved_we and w_id not in known_we_ids:
                            reconstructed.append(el)
                    if reconstructed:
                        jsa_table_rows = reconstructed
            except Exception:
                pass

        summaries.append(
            {
                "pitch_id": pid,
                "pitch_number": p_num,
                "pitch_name": p_name,
                "pitch_display_label": default_job_title,
                "area_name": area_name,
                "section_name": sec_name,
                "default_job_title": default_job_title,
                "job_title_override": job_title_override,
                "job_title": effective_job_title,
                "plant_code": effective_plant_code,
                "default_important_notice": default_important_notice,
                "important_notice_override": important_notice_override,
                "important_notice": effective_important_notice,
                "include_pitch_photos": include_pitch_photos,
                "pitch_photos": pitch_photos,
                "work_elements": pitch_elements,
                "jsa_rows": jsa_table_rows,
                "rollup": rollup,
                "effective_ppe": rollup["effective_items"],
                "effective_ppe_names": rollup["effective_names"],
                "overrides": rollup["overrides"],
                "is_standard_baseline": rollup["is_standard_mode"],
                "is_standard_only": rollup["is_standard_only"],
                "is_barney_zone": rollup["is_barney_zone"],
                "barney_zone_names": rollup["barney_zone_names"],
                "barney_zone_items": rollup["barney_zone_items"],
            }
        )
    return summaries


def save_pitch_jsa_poster_settings(
    project_id: str,
    scenario_id: str,
    pitch_id: str,
    job_title_override: str = "",
    plant_code: str = "AP1",
    important_notice_override: str = "",
    important_notice: str = "",
    include_pitch_photos: bool = True,
    editor_name: str = "Collaborator",
) -> dict[str, Any]:
    """Persist per-pitch JSA Poster header settings (Job Title, Plant Code, Important Notice, Photo Toggle)."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before saving JSA Poster settings.")
    pid = str(pitch_id or "").strip()
    if not pid:
        raise ValueError("Select a valid pitch before saving JSA Poster settings.")

    clean_title = str(job_title_override or "").strip()
    clean_plant = str(plant_code or "").strip() or "AP1"
    clean_notice = str(important_notice_override or important_notice or "").strip()
    clean_photos = 1 if include_pitch_photos else 0
    timestamp = now_iso()

    with connection() as conn:
        row = conn.execute(
            """SELECT p.id, p.pitch_number,
                      COALESCE(p.jsa_job_title_override, '') AS old_title,
                      COALESCE(p.jsa_plant_code, 'AP1') AS old_plant,
                      COALESCE(p.jsa_important_notice, '') AS old_notice,
                      COALESCE(p.jsa_include_pitch_photos, 1) AS old_photos
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id = p.area_id
               WHERE p.id = ? AND p.project_id = ? AND a.scenario_id = ?""",
            (pid, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("The selected pitch no longer belongs to the active scenario.")

        changed = (
            str(row["old_title"]) != clean_title
            or str(row["old_plant"]) != clean_plant
            or str(row["old_notice"]) != clean_notice
            or int(row["old_photos"] or 0) != clean_photos
        )
        if changed:
            conn.execute(
                """UPDATE yamazumi_pitches
                   SET jsa_job_title_override = ?,
                       jsa_plant_code = ?,
                       jsa_important_notice = ?,
                       jsa_include_pitch_photos = ?,
                       updated_at = ?
                   WHERE id = ? AND project_id = ?""",
                (clean_title, clean_plant, clean_notice, clean_photos, timestamp, pid, project_id),
            )
            record_audit_event(
                project_id,
                "Safety requirements",
                "Update JSA poster header",
                1,
                editor,
                {
                    "scenario_id": scenario_id,
                    "pitch_id": pid,
                    "pitch_number": str(row["pitch_number"] or ""),
                    "job_title_override": clean_title,
                    "plant_code": clean_plant,
                    "important_notice_override": clean_notice,
                    "include_pitch_photos": bool(clean_photos),
                    "updated_at": timestamp,
                },
                _conn=conn,
            )

    return {
        "changed": changed,
        "pitch_id": pid,
        "job_title_override": clean_title,
        "plant_code": clean_plant,
        "important_notice_override": clean_notice,
        "include_pitch_photos": bool(clean_photos),
        "timestamp": timestamp,
    }


def save_pitch_jsa_poster_full(
    project_id: str,
    scenario_id: str,
    pitch_id: str,
    payload: dict[str, Any],
    editor_name: str = "Collaborator",
) -> dict[str, Any]:
    """Persist full JSA Poster edits (header fields, PPE selection, step hazards/actions, and custom rows)."""
    editor = str(editor_name or "").strip() or "Collaborator"
    pid = str(pitch_id or "").strip()
    if not pid:
        raise ValueError("Select a valid pitch before saving the JSA Poster.")
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSA Poster save payload.")

    clean_plant = str(payload.get("plantCode") or "").strip()
    clean_title = str(payload.get("jobTitle") or "").strip()
    clean_notice = str(payload.get("importantNotice") or "").strip()
    raw_steps = payload.get("steps")
    steps_list = raw_steps if isinstance(raw_steps, list) else []
    raw_eff_ppe = payload.get("effectivePPE")
    selected_jsa_ppe = parse_ppe(raw_eff_ppe) if isinstance(raw_eff_ppe, list) else None
    raw_ppe_by_we = payload.get("ppeByWorkElement")
    ppe_by_we_map: dict[str, list[str]] | None = None
    if isinstance(raw_ppe_by_we, dict):
        ppe_by_we_map = {
            str(k).strip(): parse_ppe(v if isinstance(v, list) else [])
            for k, v in raw_ppe_by_we.items()
            if str(k).strip()
        }

    timestamp = now_iso()

    with connection() as conn:
        prow = conn.execute(
            """SELECT p.id, p.pitch_number, COALESCE(p.pitch_name, '') AS pitch_name
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id = p.area_id
               WHERE p.id = ? AND p.project_id = ? AND a.scenario_id = ?""",
            (pid, project_id, scenario_id),
        ).fetchone()
        if not prow:
            raise ValueError("The selected pitch no longer belongs to the active scenario.")

        # Determine all PAAG work elements currently on this pitch
        we_on_pitch_rows = conn.execute(
            """SELECT w.id AS work_element_id
               FROM work_elements w
               LEFT JOIN yamazumi_elements y
                 ON y.project_id = w.project_id AND y.process_element_id = w.id
               WHERE w.project_id = ? AND w.scenario_id = ?
                 AND (y.pitch_id = ? OR LOWER(TRIM(COALESCE(w.station, ''))) = LOWER(TRIM(?)))""",
            (project_id, scenario_id, pid, str(prow["pitch_number"] or "")),
        ).fetchall()
        known_we_ids = [str(r["work_element_id"]) for r in we_on_pitch_rows if str(r["work_element_id"] or "").strip()]

        normalized_rows: list[dict[str, Any]] = []
        we_step_updates: list[dict[str, Any]] = []
        for s in steps_list:
            if not isinstance(s, dict):
                continue
            s_sec = str(s.get("section_name") or "").strip()
            j_step = _strip_yamazumi_area_text(s.get("job_step"))
            p_haz = str(s.get("potential_hazards") or "").strip()
            p_act = str(s.get("proposed_actions") or "").strip()
            we_id = str(s.get("work_element_id") or "").strip()
            is_auto = bool(s.get("is_auto_ppe_row"))
            # Skip trailing completely empty blank rows unless they are the only row
            if not j_step and not p_haz and not p_act and not we_id and not is_auto:
                continue
            normalized_rows.append(
                {
                    "work_element_id": we_id,
                    "section_name": s_sec,
                    "job_step": j_step,
                    "potential_hazards": p_haz,
                    "proposed_actions": p_act,
                    "is_auto_ppe_row": is_auto,
                }
            )
            if we_id:
                we_step_updates.append(
                    {
                        "work_element_id": we_id,
                        "potential_hazards": p_haz,
                        "proposed_actions": p_act,
                    }
                )

        ppe_only_mode = bool(payload.get("ppeOnly"))
        if not ppe_only_mode:
            override_payload_dict: dict[str, Any] = {
                "rows": normalized_rows,
                "known_we_ids": known_we_ids,
            }
            # Only store pitch-level effective_ppe fallback when the pitch has no PAAG work elements;
            # when work elements exist on the pitch, PPE is stored per work_element_id so it moves with the task.
            if selected_jsa_ppe is not None and not known_we_ids:
                override_payload_dict["effective_ppe"] = selected_jsa_ppe
            override_payload_json = json.dumps(
                override_payload_dict,
                ensure_ascii=False,
            )

            conn.execute(
                """UPDATE yamazumi_pitches
                   SET jsa_job_title_override = ?,
                       jsa_plant_code = ?,
                       jsa_important_notice = ?,
                       jsa_rows_override_json = ?,
                       updated_at = ?
                   WHERE id = ? AND project_id = ?""",
                (clean_title, clean_plant, clean_notice, override_payload_json, timestamp, pid, project_id),
            )

        # Also update safety_requirements for any linked PAAG work elements edited in the JSA table
        updated_req_count = 0
        if we_step_updates:
            valid_we_ids = {str(w["work_element_id"]) for w in we_step_updates}
            we_inputs = _fetch_work_element_snapshot_inputs(
                conn, project_id, scenario_id, list(valid_we_ids)
            )
            for item in we_step_updates:
                w_id = item["work_element_id"]
                haz_val = item["potential_hazards"]
                act_val = item["proposed_actions"]
                existing_req = conn.execute(
                    """SELECT * FROM safety_requirements
                       WHERE project_id = ? AND scenario_id = ? AND work_element_id = ?
                       ORDER BY active DESC, created_at, id LIMIT 1""",
                    (project_id, scenario_id, w_id),
                ).fetchone()
                we_row = we_inputs.get(w_id)
                live_snap_json = (
                    json.dumps(build_safety_process_snapshot(we_row), sort_keys=True)
                    if we_row
                    else ""
                )
                if existing_req:
                    conn.execute(
                        """UPDATE safety_requirements
                           SET potential_hazards = ?,
                               proposed_actions = ?,
                               source_snapshot_json = ?,
                               source_acknowledged_at = ?,
                               updated_at = ?
                           WHERE id = ? AND project_id = ? AND scenario_id = ?""",
                        (
                            haz_val,
                            act_val,
                            live_snap_json,
                            timestamp,
                            timestamp,
                            str(existing_req["id"]),
                            project_id,
                            scenario_id,
                        ),
                    )
                    updated_req_count += 1
                elif haz_val or act_val:
                    req_id = str(uuid4())
                    conn.execute(
                        """INSERT INTO safety_requirements
                           (id, project_id, scenario_id, work_element_id,
                            requirement_description, ppe, potential_hazards, proposed_actions,
                            active, source_snapshot_json, source_acknowledged_at,
                            created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, '', ?, ?, 1, ?, ?, ?, ?)""",
                        (
                            req_id,
                            project_id,
                            scenario_id,
                            w_id,
                            haz_val or act_val or "JSA step requirement",
                            haz_val,
                            act_val,
                            live_snap_json,
                            timestamp,
                            timestamp,
                            timestamp,
                        ),
                    )
                    updated_req_count += 1

        # Synchronize per-task PPE selections (ppeByWorkElement) or fallback pitch PPE to safety_requirements
        if ppe_by_we_map is not None and known_we_ids:
            we_placeholders = ",".join("?" for _ in known_we_ids)
            pitch_req_rows = conn.execute(
                f"""SELECT id, work_element_id, ppe, COALESCE(potential_hazards, '') AS potential_hazards,
                           COALESCE(proposed_actions, '') AS proposed_actions
                    FROM safety_requirements
                    WHERE project_id = ? AND scenario_id = ? AND active = 1
                      AND work_element_id IN ({we_placeholders})
                    ORDER BY created_at, id""",
                [project_id, scenario_id, *known_we_ids],
            ).fetchall()
            reqs_by_we: dict[str, list[dict[str, Any]]] = {}
            for r in pitch_req_rows:
                reqs_by_we.setdefault(str(r["work_element_id"]), []).append(dict(r))
            we_inputs_all = _fetch_work_element_snapshot_inputs(
                conn, project_id, scenario_id, list(known_we_ids)
            )
            for w_id in known_we_ids:
                if w_id not in ppe_by_we_map:
                    continue
                new_ppe_list = parse_ppe(ppe_by_we_map.get(w_id) or [])
                ex_list = reqs_by_we.get(w_id, [])
                ex = ex_list[0] if ex_list else None
                existing_ppe_list = parse_ppe([p for row_r in ex_list for p in parse_ppe(row_r.get("ppe"))])
                if set(new_ppe_list) == set(existing_ppe_list) and len(ex_list) <= 1:
                    continue
                ppe_serialized = serialize_ppe(new_ppe_list)
                we_row = we_inputs_all.get(w_id)
                live_snap_json = (
                    json.dumps(build_safety_process_snapshot(we_row), sort_keys=True)
                    if we_row
                    else ""
                )
                if ex:
                    next_h = _strip_auto_ppe_text(ex.get("potential_hazards"))
                    next_a = _strip_auto_ppe_text(ex.get("proposed_actions"))
                    conn.execute(
                        """UPDATE safety_requirements
                           SET ppe = ?, potential_hazards = ?, proposed_actions = ?,
                               source_snapshot_json = ?, source_acknowledged_at = ?, updated_at = ?
                           WHERE id = ? AND project_id = ? AND scenario_id = ?""",
                        (
                            ppe_serialized,
                            next_h,
                            next_a,
                            live_snap_json,
                            timestamp,
                            timestamp,
                            str(ex["id"]),
                            project_id,
                            scenario_id,
                        ),
                    )
                    for extra_row in ex_list[1:]:
                        if str(extra_row.get("ppe") or "").strip():
                            conn.execute(
                                """UPDATE safety_requirements
                                   SET ppe = '', updated_at = ?
                                   WHERE id = ? AND project_id = ? AND scenario_id = ?""",
                                (timestamp, str(extra_row["id"]), project_id, scenario_id),
                            )
                    updated_req_count += 1
                elif new_ppe_list:
                    conn.execute(
                        """INSERT INTO safety_requirements
                           (id, project_id, scenario_id, work_element_id,
                            requirement_description, ppe, potential_hazards, proposed_actions,
                            active, source_snapshot_json, source_acknowledged_at,
                            created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, '', '', 1, ?, ?, ?, ?)""",
                        (
                            str(uuid4()),
                            project_id,
                            scenario_id,
                            w_id,
                            f"PPE: {', '.join(new_ppe_list)}",
                            ppe_serialized,
                            live_snap_json,
                            timestamp,
                            timestamp,
                            timestamp,
                        ),
                    )
                    updated_req_count += 1
        elif selected_jsa_ppe is not None and known_we_ids:
            we_placeholders = ",".join("?" for _ in known_we_ids)
            pitch_req_rows = conn.execute(
                f"""SELECT id, work_element_id, ppe, COALESCE(potential_hazards, '') AS potential_hazards,
                           COALESCE(proposed_actions, '') AS proposed_actions
                    FROM safety_requirements
                    WHERE project_id = ? AND scenario_id = ? AND active = 1
                      AND work_element_id IN ({we_placeholders})
                    ORDER BY created_at, id""",
                [project_id, scenario_id, *known_we_ids],
            ).fetchall()
            current_all_ppe: list[list[str]] = [parse_ppe(r["ppe"]) for r in pitch_req_rows if parse_ppe(r["ppe"])]
            current_eff_names = set(resolve_pitch_ppe_rollup(current_all_ppe)["effective_names"])
            desired_eff_names = set(selected_jsa_ppe)
            added_ppe = [p for p in selected_jsa_ppe if p not in current_eff_names]
            removed_ppe = {p for p in current_eff_names if p not in desired_eff_names}
            if added_ppe or removed_ppe:
                we_inputs_all = _fetch_work_element_snapshot_inputs(
                    conn, project_id, scenario_id, list(known_we_ids)
                )
                req_by_we = {}
                for r in pitch_req_rows:
                    req_by_we.setdefault(str(r["work_element_id"]), dict(r))
                for w_id in known_we_ids:
                    ex = req_by_we.get(w_id)
                    existing_ppe_list = parse_ppe(ex["ppe"]) if ex else []
                    new_ppe_list = [p for p in existing_ppe_list if p not in removed_ppe]
                    for ap in added_ppe:
                        if ap not in new_ppe_list:
                            new_ppe_list.append(ap)
                    new_ppe_list = parse_ppe(new_ppe_list)
                    if set(new_ppe_list) == set(existing_ppe_list):
                        continue
                    ppe_serialized = serialize_ppe(new_ppe_list)
                    we_row = we_inputs_all.get(w_id)
                    live_snap_json = (
                        json.dumps(build_safety_process_snapshot(we_row), sort_keys=True)
                        if we_row
                        else ""
                    )
                    if ex:
                        conn.execute(
                            """UPDATE safety_requirements
                               SET ppe = ?, source_snapshot_json = ?, source_acknowledged_at = ?, updated_at = ?
                               WHERE id = ? AND project_id = ? AND scenario_id = ?""",
                            (ppe_serialized, live_snap_json, timestamp, timestamp, str(ex["id"]), project_id, scenario_id),
                        )
                        updated_req_count += 1
                    elif new_ppe_list:
                        conn.execute(
                            """INSERT INTO safety_requirements
                               (id, project_id, scenario_id, work_element_id,
                                requirement_description, ppe, potential_hazards, proposed_actions,
                                active, source_snapshot_json, source_acknowledged_at,
                                created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, '', '', 1, ?, ?, ?, ?)""",
                            (
                                str(uuid4()),
                                project_id,
                                scenario_id,
                                w_id,
                                f"PPE: {', '.join(new_ppe_list)}",
                                ppe_serialized,
                                live_snap_json,
                                timestamp,
                                timestamp,
                                timestamp,
                            ),
                        )
                        updated_req_count += 1

        record_audit_event(
            project_id,
            "Safety requirements",
            "Save JSA poster",
            max(1, len(normalized_rows)),
            editor,
            {
                "scenario_id": scenario_id,
                "pitch_id": pid,
                "pitch_number": str(prow["pitch_number"] or ""),
                "job_title": clean_title,
                "plant_code": clean_plant,
                "row_count": len(normalized_rows),
                "updated_paag_steps": updated_req_count,
                "updated_at": timestamp,
            },
            _conn=conn,
        )

    return {
        "pitch_id": pid,
        "row_count": len(normalized_rows),
        "updated_paag_steps": updated_req_count,
        "timestamp": timestamp,
    }


def save_pitch_jsa_steps(
    project_id: str,
    scenario_id: str,
    edited_steps: pd.DataFrame,
    editor_name: str = "Collaborator",
) -> dict[str, Any]:
    """Save JSA step edits (PPE, Potential Errors / Hazards, Action) back to safety_requirements for each PAAG step."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before saving JSA job steps.")
    timestamp = now_iso()

    created_ids: list[str] = []
    updated_ids: list[str] = []

    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")

        valid_work_ids = {
            str(r["id"])
            for r in conn.execute(
                "SELECT id FROM work_elements WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }

        existing_rows = conn.execute(
            """SELECT * FROM safety_requirements
               WHERE project_id=? AND scenario_id=?
               ORDER BY active DESC, created_at, id""",
            (project_id, scenario_id),
        ).fetchall()
        reqs_by_we: dict[str, list[dict[str, Any]]] = {}
        for r in existing_rows:
            reqs_by_we.setdefault(str(r["work_element_id"]), []).append(dict(r))

        we_inputs = _fetch_work_element_snapshot_inputs(
            conn,
            project_id,
            scenario_id,
            list(valid_work_ids),
        )

        for _, row in edited_steps.iterrows():
            we_id = str(row.get("work_element_id") or "").strip()
            if not we_id or we_id not in valid_work_ids:
                continue
            ppe_list = parse_ppe(row.get("ppe"))
            ppe_str = serialize_ppe(ppe_list)
            raw_haz = row.get("potential_hazards")
            haz_str = "" if raw_haz is None or pd.isna(raw_haz) else str(raw_haz).strip()
            raw_act = row.get("proposed_actions")
            act_str = "" if raw_act is None or pd.isna(raw_act) else str(raw_act).strip()

            existing_for_we = reqs_by_we.get(we_id, [])
            primary = existing_for_we[0] if existing_for_we else None

            we_row = we_inputs.get(we_id)
            live_snap_json = (
                json.dumps(build_safety_process_snapshot(we_row), sort_keys=True)
                if we_row
                else ""
            )

            if primary is not None:
                req_id = str(primary["id"])
                prev_ppe = serialize_ppe(primary.get("ppe"))
                prev_haz = str(primary.get("potential_hazards") or "").strip()
                prev_act = str(primary.get("proposed_actions") or "").strip()
                prev_desc = str(primary.get("requirement_description") or "").strip()
                new_desc = prev_desc
                if not new_desc or new_desc.startswith("PPE:"):
                    if ppe_list:
                        new_desc = f"PPE: {', '.join(ppe_list)}"
                    elif haz_str or act_str:
                        new_desc = haz_str or act_str
                if (
                    prev_ppe == ppe_str
                    and prev_haz == haz_str
                    and prev_act == act_str
                    and prev_desc == new_desc
                    and int(primary.get("active") or 0) == 1
                ):
                    continue
                conn.execute(
                    """UPDATE safety_requirements
                       SET requirement_description=?, ppe=?, potential_hazards=?, proposed_actions=?,
                           active=1, source_snapshot_json=?, source_acknowledged_at=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        new_desc or "Safety requirement",
                        ppe_str,
                        haz_str,
                        act_str,
                        live_snap_json,
                        timestamp,
                        timestamp,
                        req_id,
                        project_id,
                        scenario_id,
                    ),
                )
                updated_ids.append(req_id)
            else:
                if not ppe_list and not haz_str and not act_str:
                    continue
                req_id = str(uuid4())
                desc = (
                    f"PPE: {', '.join(ppe_list)}"
                    if ppe_list
                    else (haz_str or act_str or "Safety requirement")
                )
                conn.execute(
                    """INSERT INTO safety_requirements
                       (id, project_id, scenario_id, work_element_id,
                        requirement_description, ppe, potential_hazards, proposed_actions,
                        active, source_snapshot_json, source_acknowledged_at,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                    (
                        req_id,
                        project_id,
                        scenario_id,
                        we_id,
                        desc,
                        ppe_str,
                        haz_str,
                        act_str,
                        live_snap_json,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                created_ids.append(req_id)

        total_count = len(created_ids) + len(updated_ids)
        if total_count:
            record_audit_event(
                project_id,
                "Safety requirements",
                "Save JSA steps",
                total_count,
                editor,
                {
                    "scenario_id": scenario_id,
                    "created_ids": created_ids,
                    "updated_ids": updated_ids,
                    "updated_at": timestamp,
                },
                _conn=conn,
            )

    return {
        "row_count": len(created_ids) + len(updated_ids),
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "timestamp": timestamp,
    }


def autofill_blank_jsa_hazards_from_ppe(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | None = None,
    editor_name: str = "Collaborator",
) -> dict[str, Any]:
    """Populate blank potential_hazards and proposed_actions on safety_requirements from each step's assigned PPE."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before auto-filling JSA hazards and actions.")
    timestamp = now_iso()
    filter_ids = (
        {str(wid).strip() for wid in work_element_ids if str(wid).strip()}
        if work_element_ids is not None
        else None
    )
    updated_ids: list[str] = []

    with connection() as conn:
        rows = conn.execute(
            """SELECT id, work_element_id, ppe,
                      COALESCE(potential_hazards, '') AS potential_hazards,
                      COALESCE(proposed_actions, '') AS proposed_actions
               FROM safety_requirements
               WHERE project_id=? AND scenario_id=? AND active=1""",
            (project_id, scenario_id),
        ).fetchall()
        for r in rows:
            we_id = str(r["work_element_id"])
            if filter_ids is not None and we_id not in filter_ids:
                continue
            ppe_items = parse_ppe(r["ppe"])
            if not ppe_items:
                continue
            auto_haz, auto_act = derive_ppe_hazards_and_actions(ppe_items)
            cur_haz = str(r["potential_hazards"] or "").strip()
            cur_act = str(r["proposed_actions"] or "").strip()
            new_haz = cur_haz or auto_haz
            new_act = cur_act or auto_act
            if new_haz != cur_haz or new_act != cur_act:
                req_id = str(r["id"])
                conn.execute(
                    """UPDATE safety_requirements
                       SET potential_hazards=?, proposed_actions=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (new_haz, new_act, timestamp, req_id, project_id, scenario_id),
                )
                updated_ids.append(req_id)
        if updated_ids:
            record_audit_event(
                project_id,
                "Safety requirements",
                "Auto-fill JSA hazards & actions from PPE",
                len(updated_ids),
                editor,
                {
                    "scenario_id": scenario_id,
                    "updated_ids": updated_ids,
                    "updated_at": timestamp,
                },
                _conn=conn,
            )

    return {"row_count": len(updated_ids), "updated_ids": updated_ids, "timestamp": timestamp}


def tag_ppe_to_work_elements(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str],
    ppe_items: list[str],
    potential_hazards: str = "",
    proposed_actions: str = "",
    mode: str = "add",
    editor_name: str = "Collaborator",
) -> dict[str, Any]:
    """Tag (add, replace, or remove) one or more PPE items across multiple PAAG work elements (similar to Visual Aid tagging)."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before tagging PPE to work elements.")
    target_wids = list(
        dict.fromkeys(str(wid).strip() for wid in (work_element_ids or []) if str(wid).strip())
    )
    if not target_wids:
        raise ValueError("Select at least one PAAG work element to tag.")
    clean_ppe = parse_ppe(ppe_items)
    if not clean_ppe and mode in ("add", "remove"):
        raise ValueError("Select at least one PPE item.")

    clean_haz = str(potential_hazards or "").strip()
    clean_act = str(proposed_actions or "").strip()
    timestamp = now_iso()
    created_ids: list[str] = []
    updated_ids: list[str] = []

    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")

        valid_work_ids = {
            str(r["id"])
            for r in conn.execute(
                "SELECT id FROM work_elements WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }
        target_wids = [wid for wid in target_wids if wid in valid_work_ids]
        if not target_wids:
            raise ValueError("Selected work elements no longer belong to the active scenario.")

        existing_rows = conn.execute(
            """SELECT * FROM safety_requirements
               WHERE project_id=? AND scenario_id=?
               ORDER BY active DESC, created_at, id""",
            (project_id, scenario_id),
        ).fetchall()
        reqs_by_we: dict[str, list[dict[str, Any]]] = {}
        for r in existing_rows:
            reqs_by_we.setdefault(str(r["work_element_id"]), []).append(dict(r))

        we_inputs = _fetch_work_element_snapshot_inputs(
            conn, project_id, scenario_id, target_wids
        )

        for we_id in target_wids:
            existing_for_we = reqs_by_we.get(we_id, [])
            primary = existing_for_we[0] if existing_for_we else None
            cur_ppe = parse_ppe(primary.get("ppe")) if primary else []

            if mode == "replace":
                new_ppe = list(clean_ppe)
            elif mode == "remove":
                remove_cf = {normalize_ppe_name(p).casefold() for p in clean_ppe}
                new_ppe = [p for p in cur_ppe if normalize_ppe_name(p).casefold() not in remove_cf]
            else:
                new_ppe = list(cur_ppe)
                seen_cf = {normalize_ppe_name(p).casefold() for p in new_ppe}
                for p in clean_ppe:
                    canon_p = normalize_ppe_name(p)
                    if canon_p.casefold() not in seen_cf:
                        seen_cf.add(canon_p.casefold())
                        new_ppe.append(canon_p)

            ppe_str = serialize_ppe(new_ppe)
            we_row = we_inputs.get(we_id)
            live_snap_json = (
                json.dumps(build_safety_process_snapshot(we_row), sort_keys=True)
                if we_row
                else ""
            )

            if primary is not None:
                req_id = str(primary["id"])
                prev_ppe = serialize_ppe(primary.get("ppe"))
                prev_haz = str(primary.get("potential_hazards") or "").strip()
                prev_act = str(primary.get("proposed_actions") or "").strip()
                prev_desc = str(primary.get("requirement_description") or "").strip()

                eff_haz = prev_haz
                if clean_haz:
                    if not prev_haz:
                        eff_haz = clean_haz
                    elif clean_haz not in prev_haz:
                        eff_haz = f"{prev_haz} | {clean_haz}"

                eff_act = prev_act
                if clean_act:
                    if not prev_act:
                        eff_act = clean_act
                    elif clean_act not in prev_act:
                        eff_act = f"{prev_act} | {clean_act}"

                eff_desc = prev_desc
                if not eff_desc or eff_desc.startswith("PPE:"):
                    if new_ppe:
                        eff_desc = f"PPE: {', '.join(new_ppe)}"
                    elif eff_haz or eff_act:
                        eff_desc = eff_haz or eff_act
                    else:
                        eff_desc = "Safety requirement"

                if (
                    prev_ppe == ppe_str
                    and prev_haz == eff_haz
                    and prev_act == eff_act
                    and prev_desc == eff_desc
                    and int(primary.get("active") or 0) == 1
                ):
                    continue

                conn.execute(
                    """UPDATE safety_requirements
                       SET requirement_description=?, ppe=?, potential_hazards=?, proposed_actions=?,
                           active=1, source_snapshot_json=?, source_acknowledged_at=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        eff_desc,
                        ppe_str,
                        eff_haz,
                        eff_act,
                        live_snap_json,
                        timestamp,
                        timestamp,
                        req_id,
                        project_id,
                        scenario_id,
                    ),
                )
                updated_ids.append(req_id)
            else:
                if not new_ppe and not clean_haz and not clean_act:
                    continue
                req_id = str(uuid4())
                desc = (
                    f"PPE: {', '.join(new_ppe)}"
                    if new_ppe
                    else (clean_haz or clean_act or "Safety requirement")
                )
                conn.execute(
                    """INSERT INTO safety_requirements
                       (id, project_id, scenario_id, work_element_id,
                        requirement_description, ppe, potential_hazards, proposed_actions,
                        active, source_snapshot_json, source_acknowledged_at,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                    (
                        req_id,
                        project_id,
                        scenario_id,
                        we_id,
                        desc,
                        ppe_str,
                        clean_haz,
                        clean_act,
                        live_snap_json,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                created_ids.append(req_id)

        total_count = len(created_ids) + len(updated_ids)
        if total_count:
            record_audit_event(
                project_id,
                "Safety requirements",
                "Tag PPE to work elements",
                total_count,
                editor,
                {
                    "scenario_id": scenario_id,
                    "ppe_items": clean_ppe,
                    "mode": mode,
                    "work_element_count": len(target_wids),
                    "created_ids": created_ids,
                    "updated_ids": updated_ids,
                    "updated_at": timestamp,
                },
                _conn=conn,
            )

    return {
        "row_count": len(created_ids) + len(updated_ids),
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "timestamp": timestamp,
    }


def update_ppe_item_element_tags_on_pitch(
    project_id: str,
    scenario_id: str,
    pitch_work_element_ids: list[str],
    ppe_name: str,
    tagged_work_element_ids: list[str],
    editor_name: str = "Collaborator",
) -> dict[str, Any]:
    """Synchronize which PAAG work elements on a pitch have a specific PPE item tagged (like editing tagged steps on a Visual Aid card)."""
    canon_ppe = normalize_ppe_name(ppe_name)
    if not canon_ppe:
        raise ValueError("Select a valid PPE item.")
    all_pitch_wids = [str(w).strip() for w in (pitch_work_element_ids or []) if str(w).strip()]
    tagged_set = {str(w).strip() for w in (tagged_work_element_ids or []) if str(w).strip()}
    add_wids = [w for w in all_pitch_wids if w in tagged_set]
    rem_wids = [w for w in all_pitch_wids if w not in tagged_set]
    total_changed = 0
    if add_wids:
        res_add = tag_ppe_to_work_elements(
            project_id,
            scenario_id,
            add_wids,
            [canon_ppe],
            mode="add",
            editor_name=editor_name,
        )
        total_changed += int(res_add.get("row_count") or 0)
    if rem_wids:
        res_rem = tag_ppe_to_work_elements(
            project_id,
            scenario_id,
            rem_wids,
            [canon_ppe],
            mode="remove",
            editor_name=editor_name,
        )
        total_changed += int(res_rem.get("row_count") or 0)
    return {"row_count": total_changed, "ppe_name": canon_ppe}


def delete_safety_requirements(
    project_id: str,
    scenario_id: str,
    requirement_ids: list[str],
    editor_name: str,
) -> dict:
    """Delete selected Safety rows with boundary validation and one audit event."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before deleting Safety requirements.")
    ids = list(dict.fromkeys(str(value).strip() for value in requirement_ids if str(value).strip()))
    timestamp = now_iso()
    if not ids:
        return {"row_count": 0, "timestamp": timestamp}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        found = conn.execute(
            f"""SELECT id FROM safety_requirements
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchall()
        if len(found) != len(ids):
            raise ValueError(
                "One or more Safety requirements changed or no longer belong to the active scenario."
            )
        with capture_deletion_to_recycle_bin(
            conn,
            project_id=project_id,
            scenario_id=scenario_id,
            entity_type="Safety Requirement",
            entity_table="safety_requirements",
            entity_id=ids[0] if len(ids) == 1 else "",
            entity_label=f"{len(ids)} Safety requirement(s)",
            deleted_by=editor,
        ):
            conn.execute(
                f"""DELETE FROM safety_requirements
                    WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
                (project_id, scenario_id, *ids),
            )
        record_audit_event(
            project_id,
            "Safety requirements",
            "Delete" if len(ids) == 1 else "Bulk delete",
            len(ids),
            editor,
            {"scenario_id": scenario_id, "requirement_ids": ids, "updated_at": timestamp},
            _conn=conn,
        )
    return {"row_count": len(ids), "timestamp": timestamp}


def safety_requirement_delete_impact(
    project_id: str, scenario_id: str, work_element_ids: list[str]
) -> dict:
    """Describe Safety rows that would cascade with Process-step deletion."""
    ids = list(dict.fromkeys(str(value).strip() for value in work_element_ids if str(value).strip()))
    if not ids:
        return {"requirement_count": 0, "work_element_count": 0}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        valid_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM work_elements
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchone()[0])
        if valid_count != len(ids):
            raise ValueError(
                "One or more Process steps changed or no longer belong to the active scenario."
            )
        row = conn.execute(
            f"""SELECT COUNT(*) AS requirement_count,
                       COUNT(DISTINCT work_element_id) AS work_element_count
                FROM safety_requirements
                WHERE project_id=? AND scenario_id=?
                  AND work_element_id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchone()
    return {
        "requirement_count": int(row["requirement_count"] or 0),
        "work_element_count": int(row["work_element_count"] or 0),
    }


@cached_store_read(scope="scenario")
def safety_requirement_history(
    project_id: str, scenario_id: str, limit: int = 50
) -> pd.DataFrame:
    rows = query(
        """SELECT action, row_count, editor_name, details, created_at
           FROM audit_log
           WHERE project_id=? AND table_name='Safety requirements'
             AND json_extract(details, '$.scenario_id')=?
           ORDER BY datetime(created_at) DESC, created_at DESC LIMIT ?""",
        (project_id, scenario_id, int(limit)),
    )
    df = pd.DataFrame(rows)
    if not df.empty and "created_at" in df.columns:
        df["created_at"] = df["created_at"].map(to_eastern_iso)
    return _db_core.enrich_audit_history_dataframe(df)


def acknowledge_safety_upstream_changes(
    project_id: str,
    scenario_id: str,
    requirement_ids: list[str],
    editor_name: str = "Collaborator",
) -> dict:
    """Refresh stored upstream Process snapshots for selected Safety requirements and log history."""
    editor = str(editor_name or "").strip() or "Collaborator"
    ids = list(dict.fromkeys(str(v).strip() for v in requirement_ids if str(v).strip()))
    timestamp = now_iso()
    if not ids:
        return {"row_count": 0, "acknowledged_ids": [], "timestamp": timestamp}
    placeholders = ",".join("?" for _ in ids)
    acknowledged_ids: list[str] = []
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        rows = conn.execute(
            f"""SELECT id, work_element_id
                FROM safety_requirements
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchall()
        we_inputs = _fetch_work_element_snapshot_inputs(
            conn,
            project_id,
            scenario_id,
            [str(r["work_element_id"]) for r in rows if r["work_element_id"]],
        )
        for row in rows:
            we_id = str(row["work_element_id"] or "").strip()
            if not we_id or we_id not in we_inputs:
                continue
            snap_json = json.dumps(
                build_safety_process_snapshot(we_inputs[we_id]), sort_keys=True
            )
            conn.execute(
                """UPDATE safety_requirements
                   SET source_snapshot_json=?, source_acknowledged_at=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (snap_json, timestamp, timestamp, str(row["id"]), project_id, scenario_id),
            )
            acknowledged_ids.append(str(row["id"]))
        if acknowledged_ids:
            record_audit_event(
                project_id,
                "Safety requirements",
                "Acknowledge upstream change",
                len(acknowledged_ids),
                editor,
                {
                    "scenario_id": scenario_id,
                    "acknowledged_requirement_ids": acknowledged_ids,
                },
                _conn=conn,
            )
    return {
        "row_count": len(acknowledged_ids),
        "acknowledged_ids": acknowledged_ids,
        "timestamp": timestamp,
    }


__domain_exports__ = [
    'safety_requirements', 'save_safety_requirements', 'delete_safety_requirements',
    'safety_requirement_delete_impact', 'safety_requirement_history',
    'acknowledge_safety_upstream_changes',
    'apply_standard_baseline_ppe', 'pitch_ppe_poster_summary',
    'save_pitch_ppe_poster_overrides', 'resolve_pitch_ppe_rollup',
    'pitch_jsa_poster_summary', 'save_pitch_jsa_poster_settings',
    'save_pitch_jsa_poster_full',
    'save_pitch_jsa_steps', 'autofill_blank_jsa_hazards_from_ppe',
    'tag_ppe_to_work_elements', 'update_ppe_item_element_tags_on_pitch',
    'derive_ppe_hazards_and_actions',
    'normalize_ppe_name', 'get_ppe_catalog_item',
    'is_barney_zone_ppe_item', 'extract_barney_zone_ppe',
    'PPE_CATALOG', 'STANDARD_BASELINE_PPE', 'STANDARD_PPE_OPTIONS',
    'JSA_HAZARD_PRESETS', 'JSA_ACTION_PRESETS',
    'PPE_ICONS_DIR', 'JSA_ICONS_DIR', 'EHS_LOGO_PATH',
    'parse_ppe', 'serialize_ppe',
]
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
