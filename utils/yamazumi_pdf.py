"""Parser for Yamazumi report PDFs exported from yamazumi.sc.geappl.io.

Extracts balancing metadata, takt time, pitches, variants, work elements,
cycle times, and work regions directly from the native vector text streams.
"""

from __future__ import annotations

import io
import re
import zlib
from typing import Any

import pandas as pd


_RGB_FILL_PATTERN = re.compile(
    r"([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+rg"
)
_FLUCTUATION_RGB = (1.0, 0.0, 0.0)
_PERIODIC_RGB = (1.0, 1.0, 0.0)
_WORK_TYPE_COLOR_TOLERANCE = 0.13
_TIME_LABEL_PATTERN = re.compile(r"^[0-9.]+\s*s$")
_WORK_ROW_Y_TOLERANCE = 1.5
_WORK_ROW_MAX_LABEL_GAP = 190.0


def _last_rgb_fill_before(
    content: str, stream_index: int
) -> tuple[float, float, float] | None:
    """Return the last RGB non-stroking color before one PDF text item."""
    last_match = None
    for match in _RGB_FILL_PATTERN.finditer(content, 0, max(0, stream_index)):
        last_match = match
    if last_match is None:
        return None
    return tuple(float(value) for value in last_match.groups())


def _work_type_from_fill_color(
    fill_rgb: tuple[float, float, float] | None,
) -> str:
    """Map the approved Yamazumi element fill colors to work types."""
    if fill_rgb is None:
        return "Cycle"

    def matches(target: tuple[float, float, float]) -> bool:
        return all(
            abs(actual - expected) <= _WORK_TYPE_COLOR_TOLERANCE
            for actual, expected in zip(fill_rgb, target)
        )

    if matches(_FLUCTUATION_RGB):
        return "Fluctuation"
    if matches(_PERIODIC_RGB):
        return "Periodic"
    return "Cycle"


def _work_item_anchor_x(
    time_item: dict[str, Any], text_items: list[dict[str, Any]]
) -> float | None:
    """Return the description-column anchor paired with one duration label.

    Yamazumi right-aligns durations near the edge of each grid cell. Header-text
    midpoint boundaries can therefore place the duration in the next pitch even
    though its description remains in the correct pitch. Pairing on the shared
    first-line y coordinate recovers the visual row's actual owner.
    """
    time_x = float(time_item["x"])
    time_y = float(time_item["y"])
    candidates = [
        item
        for item in text_items
        if not _TIME_LABEL_PATTERN.match(str(item["text"]))
        and 0 < time_x - float(item["x"]) <= _WORK_ROW_MAX_LABEL_GAP
        and abs(float(item["y"]) - time_y) <= _WORK_ROW_Y_TOLERANCE
    ]
    if not candidates:
        return None
    return float(max(candidates, key=lambda item: float(item["x"]))["x"])


def _extract_pdf_streams(data: bytes) -> list[bytes]:
    """Extract stream byte blocks from a PDF using their /Length dictionary entries.

    Using exact /Length prevents zlib decompression errors (Error -5) caused by
    binary streams that happen to end in newline characters.
    """
    streams: list[bytes] = []
    # Pattern to match stream dictionary containing /Length <int> followed by stream\r\n or \n
    length_matches = list(
        re.finditer(rb"/Length\s+(\d+)\s*(?:/[^\s>]+)*\s*>>\s*stream(?:\r\n|\n|\r)", data)
    )
    for match in length_matches:
        length = int(match.group(1))
        stream_start = match.end()
        raw_stream = data[stream_start : stream_start + length]
        streams.append(raw_stream)

    # Fallback to regex delimiter if /Length was not matched
    if not streams:
        for match in re.finditer(rb"stream(?:\r\n|\n)(.*?)(?:\r\n|\n)endstream", data, re.DOTALL):
            streams.append(match.group(1))

    return streams


def _decompress_pdf_stream(raw_stream: bytes) -> bytes:
    """Decompress a Flate stream, tolerating stripped terminal PDF whitespace.

    Some delimiter-based PDF readers remove a final CR/LF byte even when that
    byte belongs to the zlib payload.  Retrying only those PDF whitespace bytes
    recovers that known case without accepting arbitrary truncated content.
    """
    try:
        return zlib.decompress(raw_stream)
    except zlib.error as original_error:
        for suffix in (b"\n", b"\r", b"\r\n"):
            try:
                return zlib.decompress(raw_stream + suffix)
            except zlib.error:
                continue
        raise original_error


def parse_yamazumi_pdf(pdf_source: bytes | io.BytesIO | str) -> dict[str, Any]:
    """Parse a Yamazumi PDF report into structured metadata and an import DataFrame.

    The returned `dataframe` contains validated work elements and conforms to
    the schema expected by `import_yamazumi_rows`:
    - Sub-Line: str
    - Pitch_number: str
    - Pitch_status: str ("Active")
    - Pitch_name: str
    - Pitch_Takt_time: float | None
    - Model_variant: str
    - Work_Type: str ("Cycle", "Periodic", or "Fluctuation")
    - Work_Description: str
    - Work_Time_to_complete: float
    - Work_region: str

    The returned `pitch_dataframe` contains every detected pitch header,
    including pitches that have no validated work-element rows.
    """
    if isinstance(pdf_source, str):
        with open(pdf_source, "rb") as f:
            data = f.read()
    elif hasattr(pdf_source, "getvalue"):
        data = pdf_source.getvalue()
    elif hasattr(pdf_source, "read"):
        data = pdf_source.read()
    elif isinstance(pdf_source, (bytes, bytearray)):
        data = bytes(pdf_source)
    else:
        raise TypeError(f"Unsupported PDF source type: {type(pdf_source)}")

    if not data or not data.startswith(b"%PDF"):
        raise ValueError("The uploaded file is not a valid PDF document.")

    streams = _extract_pdf_streams(data)
    if not streams:
        raise ValueError("Could not find readable content streams in the uploaded PDF.")

    # 1. Parse Metadata from Page 1
    try:
        p1_content = _decompress_pdf_stream(streams[0]).decode("latin1", errors="ignore")
    except Exception as exc:
        raise ValueError(f"Failed to decompress PDF page 1: {exc}") from exc

    plant_match = re.search(r"Plant Name:\s*([^\)]+)", p1_content)
    line_match = re.search(r"Line:\s*([^\)]+)", p1_content)
    subline_match = re.search(r"Sub Line:\s*([^\)]+)", p1_content)
    takt_match = re.search(r"Tak(?:t)? Time:\s*([0-9.]+)", p1_content)

    plant = plant_match.group(1).strip() if plant_match else ""
    line = line_match.group(1).strip() if line_match else ""
    subline = subline_match.group(1).strip() if subline_match else ""
    takt_time = float(takt_match.group(1)) if takt_match else None

    # Parse Region Details on Page 1
    text_pattern = re.compile(
        r"BT\s*(?:/[^\s]+\s+[0-9.]+\s+Tf\s*)?([0-9.]+)\s+([0-9.]+)\s+Td\s*(?:[0-9.]+\s+[0-9.]+\s+[0-9.]+\s+rg\s*)?(?:[0-9.]+\s+g\s*)?\((.*?)\)\s*Tj",
        re.DOTALL,
    )
    rect_color_pattern = re.compile(
        r"([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+rg\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.-]+)\s+([0-9.-]+)\s+re\s+[fB]",
        re.DOTALL,
    )

    p1_texts = []
    for m in text_pattern.finditer(p1_content):
        x, y, txt = (
            float(m.group(1)),
            float(m.group(2)),
            m.group(3).replace(r"\(", "(").replace(r"\)", ")").strip(),
        )
        p1_texts.append((x, y, txt))

    p1_rects = []
    for m in rect_color_pattern.finditer(p1_content):
        r, g, b, rx, ry, rw, rh = [float(v) for v in m.groups()]
        p1_rects.append((r, g, b, rx, ry, rw, rh))

    region_map: dict[tuple[float, float, float], str] = {}
    for x, y, txt in p1_texts:
        if 50 < y < 400 and x < 200 and txt not in ["Region Details", "Generated", "Page", "No regions defined"]:
            for r, g, b, rx, ry, rw, rh in p1_rects:
                if abs(ry - y) < 40:
                    c_key = (round(r, 2), round(g, 2), round(b, 2))
                    region_map[c_key] = txt

    all_elements: list[dict[str, Any]] = []
    detected_pitches: list[dict[str, Any]] = []

    # Iterate through content pages (Page 2..N)
    for p_idx in range(1, len(streams)):
        try:
            p_content = _decompress_pdf_stream(streams[p_idx]).decode("latin1", errors="ignore")
        except Exception:
            continue

        # Extract all text items on this page
        texts: list[dict[str, Any]] = []
        for m in text_pattern.finditer(p_content):
            x, y, txt = (
                float(m.group(1)),
                float(m.group(2)),
                m.group(3).replace(r"\(", "(").replace(r"\)", ")").strip(),
            )
            if txt:
                texts.append(
                    {
                        "x": x,
                        "y": y,
                        "text": txt,
                        "stream_index": m.start(),
                    }
                )

        # Extract pitch codes on this page (e.g., 01-PED-003, 01-AY1-014(A))
        # Exclude footer items like "Generated 2026-10-02..."
        pitch_codes: list[dict[str, Any]] = []
        for t in texts:
            clean_txt = t["text"]
            if re.search(r"^\d{2}-[A-Za-z0-9]+-\d+", clean_txt) and not clean_txt.startswith("Generated"):
                pitch_codes.append(t)

        if not pitch_codes:
            continue

        is_top = any(p["y"] > 500 for p in pitch_codes)
        pitch_codes.sort(key=lambda it: it["x"])

        for i, p_info in enumerate(pitch_codes):
            full_pitch_txt = p_info["text"]
            # Clean off any trailing indicators (e.g. diamonds, crosses, or notes)
            match_code = re.search(r"\d{2}-[A-Za-z0-9]+-\d+(\([A-Za-z0-9]+\))?", full_pitch_txt)
            p_code = match_code.group(0) if match_code else full_pitch_txt.split()[0]

            # Dynamic column bounds based on adjacent pitch x positions
            col_left = 0.0 if i == 0 else (pitch_codes[i - 1]["x"] + p_info["x"]) / 2
            col_right = 1300.0 if i == len(pitch_codes) - 1 else (p_info["x"] + pitch_codes[i + 1]["x"]) / 2

            p_texts = [t for t in texts if col_left <= t["x"] < col_right]

            # Look for pitch friendly name (e.g. "Bottom Pack" at y around 25..45 if bottom pitch, or y > 720 if top pitch)
            p_name = ""
            for t in p_texts:
                if not is_top and 25 <= t["y"] <= 45 and not re.search(r"\d{2}-", t["text"]) and not t["text"].startswith("Generated"):
                    p_name = t["text"]
                elif is_top and t["y"] > p_info["y"] and not re.search(r"\d{2}-", t["text"]):
                    p_name = t["text"]

            # Detect variant headers for this pitch
            var_y = 682.92 if is_top else 80.84
            variants = [t for t in p_texts if abs(t["y"] - var_y) < 15]
            variants.sort(key=lambda it: it["x"])

            var_ranges: list[tuple[float, float, str]] = []
            if len(variants) <= 1:
                v_name = variants[0]["text"] if variants else "Base"
                var_ranges.append((col_left, col_right, v_name))
            else:
                for vi, v in enumerate(variants):
                    v_left = col_left if vi == 0 else (variants[vi - 1]["x"] + v["x"]) / 2
                    v_right = col_right if vi == len(variants) - 1 else (v["x"] + variants[vi + 1]["x"]) / 2
                    var_ranges.append((v_left, v_right, v["text"]))

            detected_pitches.append({
                "pitch_number": p_code,
                "pitch_name": p_name,
                "page": p_idx + 1,
                "orientation": "South" if is_top else "North",
                "Sub-Line": subline,
                "Pitch_number": p_code,
                "Pitch_status": "Active",
                "Pitch_name": p_name,
                "Pitch_Takt_time": takt_time,
                "Model_variants": [
                    variant_name for _, _, variant_name in var_ranges
                ],
            })

            for vx_min, vx_max, v_name in var_ranges:
                v_texts = [
                    t
                    for t in p_texts
                    if vx_min <= t["x"] < vx_max
                    and t["text"] != full_pitch_txt
                    and t["text"] != p_code
                    and t["text"] != p_name
                    and t["text"] != v_name
                    and not t["text"].startswith("Generated")
                    and not t["text"].startswith("Page")
                    and not (is_top and t["y"] > 675)
                    and not (not is_top and t["y"] < 95)
                    and not (
                        t["y"] > 740
                        and any(k in t["text"] for k in ["Takt", "Theoretical", "Actual", "CT:"])
                    )
                    and t["text"] != "S"
                ]

                non_times = [
                    t for t in v_texts if not _TIME_LABEL_PATTERN.match(t["text"])
                ]
                time_items = []
                for candidate_time in texts:
                    if not _TIME_LABEL_PATTERN.match(candidate_time["text"]):
                        continue
                    if is_top and candidate_time["y"] > 675:
                        continue
                    if not is_top and candidate_time["y"] < 95:
                        continue
                    anchor_x = _work_item_anchor_x(candidate_time, texts)
                    if anchor_x is not None and vx_min <= anchor_x < vx_max:
                        time_items.append(candidate_time)

                # Sort times in stack order (North: bottom-to-top; South: top-to-bottom)
                if is_top:
                    time_items.sort(key=lambda it: -it["y"])
                else:
                    time_items.sort(key=lambda it: it["y"])

                for ti, t_item in enumerate(time_items):
                    t_val = float(t_item["text"].rstrip("s").strip())
                    ty = t_item["y"]

                    # Bound text lines by adjacent items in stack order
                    if is_top:
                        min_y = (time_items[ti + 1]["y"] + 0.1) if ti < len(time_items) - 1 else (ty - 35)
                    else:
                        min_y = (time_items[ti - 1]["y"] + 0.1) if ti > 0 else (ty - 35)
                    max_y = ty + 1.5

                    element_lines = [d for d in non_times if min_y <= d["y"] <= max_y]
                    element_lines.sort(key=lambda it: -it["y"])
                    desc = " ".join(d["text"] for d in element_lines).strip()
                    if not desc:
                        # Empty pitch columns can still contain chart time labels.
                        # A duration without description text is not enough evidence
                        # that a work-element block exists in this pitch.
                        continue

                    # The element background fill remains the last RGB color
                    # before its text cells. Use the exact stream position so
                    # repeated time labels cannot resolve to an earlier row.
                    fill_rgb = _last_rgb_fill_before(
                        p_content, int(t_item["stream_index"])
                    )
                    work_type = _work_type_from_fill_color(fill_rgb)
                    region = "None"
                    if fill_rgb is not None:
                        c_key = tuple(round(value, 2) for value in fill_rgb)
                        region = region_map.get(c_key, "None")

                    all_elements.append({
                        "Sub-Line": subline,
                        "Pitch_number": p_code,
                        "Pitch_status": "Active",
                        "Pitch_name": p_name,
                        "Pitch_Takt_time": takt_time,
                        "Model_variant": v_name,
                        "Work_Type": work_type,
                        "Work_Description": desc,
                        "Work_Time_to_complete": t_val,
                        "Work_region": region,
                    })

    df = pd.DataFrame(all_elements)
    if df.empty:
        df = pd.DataFrame(columns=[
            "Sub-Line", "Pitch_number", "Pitch_status", "Pitch_name",
            "Pitch_Takt_time", "Model_variant", "Work_Type",
            "Work_Description", "Work_Time_to_complete", "Work_region",
        ])

    pitch_columns = [
        "Sub-Line", "Pitch_number", "Pitch_status", "Pitch_name",
        "Pitch_Takt_time", "Model_variants",
    ]
    pitch_df = pd.DataFrame(detected_pitches)
    if pitch_df.empty:
        pitch_df = pd.DataFrame(columns=pitch_columns)
    else:
        pitch_df = (
            pitch_df[pitch_columns]
            .drop_duplicates(subset=["Sub-Line", "Pitch_number"], keep="first")
            .reset_index(drop=True)
        )

    return {
        "metadata": {
            "plant": plant,
            "line": line,
            "subline": subline,
            "takt_time": takt_time,
            "region_map": region_map,
        },
        "pitches": detected_pitches,
        "pitch_dataframe": pitch_df,
        "dataframe": df,
    }
