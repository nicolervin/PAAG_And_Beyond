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


import json
import os
import subprocess
import tempfile
from PIL import Image

_YAMAZUMI_PDF_HOT_RELOAD_REV = 1

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
            pitch_variant_by_key: dict[str, str] = {}
            if len(variants) <= 1:
                raw_v_name = str(variants[0]["text"] if variants else "Base").strip() or "Base"
                v_name = pitch_variant_by_key.setdefault(raw_v_name.casefold(), raw_v_name)
                var_ranges.append((col_left, col_right, v_name))
            else:
                for vi, v in enumerate(variants):
                    v_left = col_left if vi == 0 else (variants[vi - 1]["x"] + v["x"]) / 2
                    v_right = col_right if vi == len(variants) - 1 else (v["x"] + variants[vi + 1]["x"]) / 2
                    raw_v_name = str(v["text"] or "").strip() or "Base"
                    v_name = pitch_variant_by_key.setdefault(raw_v_name.casefold(), raw_v_name)
                    var_ranges.append((v_left, v_right, v_name))

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
                "Model_variants": list(pitch_variant_by_key.values()),
            })

            for vx_min, vx_max, v_name in var_ranges:
                v_texts = [
                    t
                    for t in p_texts
                    if vx_min <= t["x"] < vx_max
                    and t["text"] != full_pitch_txt
                    and t["text"] != p_code
                    and t["text"] != p_name
                    and t["text"].strip().casefold() != v_name.casefold()
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

    detected_variants: list[str] = []
    for p_row in detected_pitches:
        for v_item in p_row.get("Model_variants") or []:
            v_str = str(v_item or "").strip()
            if v_str and v_str not in detected_variants:
                detected_variants.append(v_str)
    for e_row in all_elements:
        v_str = str(e_row.get("Model_variant") or "").strip()
        if v_str and v_str not in detected_variants:
            detected_variants.append(v_str)

    return {
        "metadata": {
            "plant": plant,
            "line": line,
            "subline": subline,
            "takt_time": takt_time,
            "region_map": region_map,
            "variants": detected_variants,
        },
        "pitches": detected_pitches,
        "pitch_dataframe": pitch_df,
        "dataframe": df,
    }


_SCREENSHOT_PITCH_CODE_RE = re.compile(
    r"\b([0O]\d-[A-Za-z0-9]{2,6}-\d{2,4}(?:\([A-Za-z0-9]+\))?|\d{2}-[A-Za-z0-9]{2,6}-\d{2,4}(?:\([A-Za-z0-9]+\))?)\b"
)
_SCREENSHOT_TIME_TOKEN_RE = re.compile(
    r"^([0-9]+(?:\.[0-9]+)?)\s*[sS]$"
)
_SCREENSHOT_INLINE_TIME_RE = re.compile(
    r"^(.*?)\s+([0-9]+(?:\.[0-9]+)?)\s*[sS]\s*$"
)


def _run_windows_ocr(image_bytes: bytes) -> list[dict[str, Any]]:
    """Run Windows built-in WinRT OCR on PNG bytes and return lines with word boxes."""
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name
        ps_script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }})[0]
function Await($WinRtTask, $ResultType) {{
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}}
$fs = [System.IO.File]::OpenRead({json.dumps(tmp_path)})
$stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fs)
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$stream.Dispose()
$fs.Dispose()
$lines = @()
foreach ($line in $result.Lines) {{
    $words = @()
    foreach ($w in $line.Words) {{
        $r = $w.BoundingRect
        $words += @{{ t = $w.Text; x = [double]$r.X; y = [double]$r.Y; w = [double]$r.Width; h = [double]$r.Height }}
    }}
    $lines += @{{ text = $line.Text; words = $words }}
}}
ConvertTo-Json -InputObject @{{ lines = $lines }} -Depth 6 -Compress
"""
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=25,
        )
        raw_out = (proc.stdout or "").strip()
        if not raw_out:
            return []
        json_start = raw_out.find("{")
        if json_start < 0:
            return []
        payload = json.loads(raw_out[json_start:])
        raw_lines = payload.get("lines") or []
        if isinstance(raw_lines, dict):
            raw_lines = [raw_lines]
        parsed_lines: list[dict[str, Any]] = []
        for l_obj in raw_lines:
            words = l_obj.get("words") or []
            if isinstance(words, dict):
                words = [words]
            if not words:
                continue
            x0 = min(float(w.get("x", 0.0)) for w in words)
            y0 = min(float(w.get("y", 0.0)) for w in words)
            x1 = max(float(w.get("x", 0.0)) + float(w.get("w", 0.0)) for w in words)
            y1 = max(float(w.get("y", 0.0)) + float(w.get("h", 0.0)) for w in words)
            parsed_lines.append(
                {
                    "text": str(l_obj.get("text") or "").strip(),
                    "x": x0,
                    "y": y0,
                    "w": max(1.0, x1 - x0),
                    "h": max(1.0, y1 - y0),
                    "words": words,
                }
            )
        return parsed_lines
    except Exception:
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _sample_element_fill_rgb(
    img: Image.Image,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> tuple[float, float, float] | None:
    """Sample dominant non-text background RGB (0..1) inside a work element bounding box."""
    w, h = img.size
    ix0 = max(0, min(w - 1, int(x0)))
    iy0 = max(0, min(h - 1, int(y0)))
    ix1 = max(ix0 + 1, min(w, int(x1)))
    iy1 = max(iy0 + 1, min(h, int(y1)))
    step_x = max(1, (ix1 - ix0) // 12)
    step_y = max(1, (iy1 - iy0) // 6)
    samples: list[tuple[float, float, float]] = []
    for py in range(iy0, iy1, step_y):
        for px in range(ix0, ix1, step_x):
            r, g, b = img.getpixel((px, py))[:3]
            if r < 45 and g < 45 and b < 45:
                continue
            if r > 242 and g > 242 and b > 242:
                continue
            samples.append((r / 255.0, g / 255.0, b / 255.0))
    if not samples:
        return None
    for s_rgb in samples:
        if _work_type_from_fill_color(s_rgb) in ("Fluctuation", "Periodic"):
            return s_rgb
    avg_r = sum(s[0] for s in samples) / len(samples)
    avg_g = sum(s[1] for s in samples) / len(samples)
    avg_b = sum(s[2] for s in samples) / len(samples)
    return (avg_r, avg_g, avg_b)


def parse_yamazumi_screenshot(image_source: bytes | io.BytesIO | str) -> dict[str, Any]:
    """Parse a pasted or uploaded Yamazumi screenshot into metadata, pitches, and work elements."""
    if isinstance(image_source, str):
        with open(image_source, "rb") as f:
            data = f.read()
    elif hasattr(image_source, "getvalue"):
        data = image_source.getvalue()
    elif hasattr(image_source, "read"):
        data = image_source.read()
    elif isinstance(image_source, (bytes, bytearray)):
        data = bytes(image_source)
    else:
        raise TypeError(f"Unsupported image source type: {type(image_source)}")

    if not data:
        raise ValueError("The screenshot image is empty.")

    try:
        pil_img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise ValueError(f"Could not open screenshot image: {exc}") from exc

    orig_w, orig_h = pil_img.size
    scale = 2.0 if orig_w < 1500 else 1.0
    if scale > 1.0:
        ocr_img = pil_img.resize(
            (int(orig_w * scale), int(orig_h * scale)),
            Image.Resampling.LANCZOS,
        )
    else:
        ocr_img = pil_img

    buf = io.BytesIO()
    ocr_img.save(buf, format="PNG")
    ocr_lines = _run_windows_ocr(buf.getvalue())

    if scale != 1.0:
        for line_item in ocr_lines:
            line_item["x"] = float(line_item["x"]) / scale
            line_item["y"] = float(line_item["y"]) / scale
            line_item["w"] = float(line_item["w"]) / scale
            line_item["h"] = float(line_item["h"]) / scale
            for w_item in line_item.get("words") or []:
                w_item["x"] = float(w_item["x"]) / scale
                w_item["y"] = float(w_item["y"]) / scale
                w_item["w"] = float(w_item["w"]) / scale
                w_item["h"] = float(w_item["h"]) / scale

    full_text = "\n".join(str(item.get("text") or "") for item in ocr_lines)
    plant_match = re.search(r"Plant Name:\s*([^\n\r|]+)", full_text, re.IGNORECASE)
    line_match = re.search(r"(?:^|\n)\s*Line:\s*([^\n\r|]+)", full_text, re.IGNORECASE)
    subline_match = re.search(r"Sub\s*[-]?\s*Line:\s*([^\n\r|]+)", full_text, re.IGNORECASE)
    takt_match = re.search(r"Tak(?:t)?\s*Time:\s*([0-9]+(?:\.[0-9]+)?)", full_text, re.IGNORECASE)

    plant = plant_match.group(1).strip() if plant_match else ""
    line = line_match.group(1).strip() if line_match else ""
    subline = subline_match.group(1).strip() if subline_match else ""
    takt_time = float(takt_match.group(1)) if takt_match else None

    items: list[dict[str, Any]] = []
    for l_obj in ocr_lines:
        l_text = str(l_obj.get("text") or "").strip()
        if not l_text:
            continue
        words = l_obj.get("words") or []
        if len(words) >= 2:
            last_two = f"{words[-2].get('t', '')} {words[-1].get('t', '')}".strip()
            last_one = str(words[-1].get("t", "")).strip()
            if _SCREENSHOT_TIME_TOKEN_RE.match(last_two) and len(words) > 2:
                desc_words = words[:-2]
                time_words = words[-2:]
                dx0 = min(float(w["x"]) for w in desc_words)
                dy0 = min(float(w["y"]) for w in desc_words)
                dx1 = max(float(w["x"]) + float(w["w"]) for w in desc_words)
                dy1 = max(float(w["y"]) + float(w["h"]) for w in desc_words)
                items.append({
                    "text": " ".join(str(w.get("t", "")) for w in desc_words).strip(),
                    "x": dx0,
                    "y": dy0,
                    "w": max(1.0, dx1 - dx0),
                    "h": max(1.0, dy1 - dy0),
                })
                tx0 = min(float(w["x"]) for w in time_words)
                ty0 = min(float(w["y"]) for w in time_words)
                tx1 = max(float(w["x"]) + float(w["w"]) for w in time_words)
                ty1 = max(float(w["y"]) + float(w["h"]) for w in time_words)
                items.append({
                    "text": last_two,
                    "x": tx0,
                    "y": ty0,
                    "w": max(1.0, tx1 - tx0),
                    "h": max(1.0, ty1 - ty0),
                })
                continue
            elif _SCREENSHOT_TIME_TOKEN_RE.match(last_one):
                desc_words = words[:-1]
                time_words = words[-1:]
                dx0 = min(float(w["x"]) for w in desc_words)
                dy0 = min(float(w["y"]) for w in desc_words)
                dx1 = max(float(w["x"]) + float(w["w"]) for w in desc_words)
                dy1 = max(float(w["y"]) + float(w["h"]) for w in desc_words)
                items.append({
                    "text": " ".join(str(w.get("t", "")) for w in desc_words).strip(),
                    "x": dx0,
                    "y": dy0,
                    "w": max(1.0, dx1 - dx0),
                    "h": max(1.0, dy1 - dy0),
                })
                tx0 = float(time_words[0]["x"])
                ty0 = float(time_words[0]["y"])
                tx1 = tx0 + float(time_words[0]["w"])
                ty1 = ty0 + float(time_words[0]["h"])
                items.append({
                    "text": last_one,
                    "x": tx0,
                    "y": ty0,
                    "w": max(1.0, tx1 - tx0),
                    "h": max(1.0, ty1 - ty0),
                })
                continue
        items.append({
            "text": l_text,
            "x": float(l_obj["x"]),
            "y": float(l_obj["y"]),
            "w": float(l_obj["w"]),
            "h": float(l_obj["h"]),
            "words": words,
        })

    pitch_headers: list[dict[str, Any]] = []
    for l_obj in ocr_lines:
        l_text = str(l_obj.get("text") or "").strip()
        if l_text.startswith("Generated"):
            continue
        words = l_obj.get("words") or []
        found_in_words = False
        for w_obj in words:
            w_txt = str(w_obj.get("t") or "").strip()
            m_code = _SCREENSHOT_PITCH_CODE_RE.search(w_txt)
            if m_code:
                raw_code = m_code.group(1)
                if raw_code.upper().startswith("O"):
                    raw_code = "0" + raw_code[1:]
                pitch_headers.append({
                    "code": raw_code,
                    "x": float(w_obj["x"]),
                    "y": float(w_obj["y"]),
                    "w": float(w_obj["w"]),
                    "h": float(w_obj["h"]),
                    "full_text": l_text,
                })
                found_in_words = True
        if not found_in_words:
            for m_code in _SCREENSHOT_PITCH_CODE_RE.finditer(l_text):
                raw_code = m_code.group(1)
                if raw_code.upper().startswith("O"):
                    raw_code = "0" + raw_code[1:]
                pitch_headers.append({
                    "code": raw_code,
                    "x": float(l_obj["x"]),
                    "y": float(l_obj["y"]),
                    "w": float(l_obj["w"]),
                    "h": float(l_obj["h"]),
                    "full_text": l_text,
                })

    all_elements: list[dict[str, Any]] = []
    detected_pitches: list[dict[str, Any]] = []

    if pitch_headers:
        pitch_headers.sort(key=lambda p: p["y"])
        bands: list[list[dict[str, Any]]] = []
        band_y_tol = max(36.0, orig_h * 0.08)
        for ph in pitch_headers:
            if not bands or abs(ph["y"] - (sum(x["y"] for x in bands[-1]) / len(bands[-1]))) > band_y_tol:
                bands.append([ph])
            else:
                bands[-1].append(ph)

        band_centers = [sum(x["y"] for x in b) / len(b) for b in bands]
        for b_idx, band in enumerate(bands):
            band.sort(key=lambda p: p["x"])
            dedup_band: list[dict[str, Any]] = []
            for ph in band:
                if dedup_band and dedup_band[-1]["code"].casefold() == ph["code"].casefold() and abs(ph["x"] - dedup_band[-1]["x"]) < 60:
                    continue
                dedup_band.append(ph)
            band = dedup_band
            band_y = band_centers[b_idx]
            band_top = 0.0 if b_idx == 0 else (band_centers[b_idx - 1] + band_y) / 2.0
            band_bottom = float(orig_h) if b_idx == len(bands) - 1 else (band_y + band_centers[b_idx + 1]) / 2.0

            is_header_at_bottom = (band_y - band_top) > (band_bottom - band_y)

            for i, p_info in enumerate(band):
                p_code = p_info["code"]
                p_cx = p_info["x"] + p_info["w"] / 2.0
                prev_cx = (band[i - 1]["x"] + band[i - 1]["w"] / 2.0) if i > 0 else 0.0
                next_cx = (band[i + 1]["x"] + band[i + 1]["w"] / 2.0) if i < len(band) - 1 else float(orig_w)
                col_left = 0.0 if i == 0 else (prev_cx + p_cx) / 2.0
                col_right = float(orig_w) if i == len(band) - 1 else (p_cx + next_cx) / 2.0

                col_items = [
                    it for it in items
                    if col_left <= (it["x"] + it["w"] / 2.0) < col_right
                    and band_top <= it["y"] <= band_bottom
                ]

                p_name = ""
                for it in col_items:
                    txt = it["text"].strip()
                    if (
                        txt
                        and p_code not in txt
                        and not _SCREENSHOT_PITCH_CODE_RE.search(txt)
                        and not _SCREENSHOT_TIME_TOKEN_RE.match(txt)
                        and txt.casefold() not in ("base", "all models", "s")
                        and not txt.startswith("Generated")
                        and abs(it["y"] - p_info["y"]) <= max(65.0, orig_h * 0.10)
                    ):
                        if is_header_at_bottom and it["y"] > p_info["y"]:
                            p_name = txt
                            break
                        elif not is_header_at_bottom and it["y"] < p_info["y"]:
                            p_name = txt
                            break

                detected_pitches.append({
                    "pitch_number": p_code,
                    "pitch_name": p_name,
                    "page": 1,
                    "orientation": "North" if is_header_at_bottom else "South",
                    "Sub-Line": subline,
                    "Pitch_number": p_code,
                    "Pitch_status": "Active",
                    "Pitch_name": p_name,
                    "Pitch_Takt_time": takt_time,
                    "Model_variants": ["Base"],
                })

                time_items: list[dict[str, Any]] = []
                non_time_items: list[dict[str, Any]] = []
                for it in col_items:
                    txt = it["text"].strip()
                    if not txt or p_code in txt or txt == p_name:
                        continue
                    if txt.startswith("Generated") or txt.startswith("Page"):
                        continue
                    if any(k in txt for k in ("Takt", "Theoretical", "Actual", "CT:", "Plant Name", "Sub Line")):
                        continue
                    if abs(it["y"] - p_info["y"]) < max(18.0, p_info["h"] * 0.9):
                        continue
                    m_time = _SCREENSHOT_TIME_TOKEN_RE.match(txt)
                    if m_time:
                        time_items.append({**it, "time_val": float(m_time.group(1))})
                    else:
                        non_time_items.append(it)

                if is_header_at_bottom:
                    time_items.sort(key=lambda it: -(it["y"]))
                else:
                    time_items.sort(key=lambda it: it["y"])

                for ti, t_item in enumerate(time_items):
                    ty = float(t_item["y"])
                    th = float(t_item["h"])
                    if is_header_at_bottom:
                        upper_bound = (
                            (float(time_items[ti + 1]["y"]) + float(time_items[ti + 1]["h"]))
                            if ti < len(time_items) - 1
                            else max(band_top, ty - max(60.0, orig_h * 0.12))
                        )
                        lower_bound = ty + th + 6.0
                    else:
                        upper_bound = (
                            (float(time_items[ti - 1]["y"]) + float(time_items[ti - 1]["h"]))
                            if ti > 0
                            else max(band_top, ty - max(45.0, orig_h * 0.08))
                        )
                        lower_bound = ty + th + 6.0

                    row_lines = [
                        d for d in non_time_items
                        if upper_bound - 4.0 <= float(d["y"]) <= lower_bound
                        and d["text"].strip().casefold() not in ("base", "all models", "s")
                    ]
                    row_lines.sort(key=lambda d: (float(d["y"]), float(d["x"])))
                    desc = " ".join(d["text"].strip() for d in row_lines if d["text"].strip()).strip()
                    if not desc:
                        continue

                    fill_rgb = _sample_element_fill_rgb(
                        pil_img,
                        col_left + 4.0,
                        min(ty, upper_bound),
                        col_right - 4.0,
                        lower_bound,
                    )
                    work_type = _work_type_from_fill_color(fill_rgb)
                    all_elements.append({
                        "Sub-Line": subline,
                        "Pitch_number": p_code,
                        "Pitch_status": "Active",
                        "Pitch_name": p_name,
                        "Pitch_Takt_time": takt_time,
                        "Model_variant": "Base",
                        "Work_Type": work_type,
                        "Work_Description": desc,
                        "Work_Time_to_complete": float(t_item["time_val"]),
                        "Work_region": "None",
                    })

    if not all_elements and ocr_lines:
        current_pitch = pitch_headers[0]["code"] if pitch_headers else "01-ASM-001"
        current_pitch_name = ""
        for l_obj in sorted(ocr_lines, key=lambda item: (float(item["y"]), float(item["x"]))):
            l_text = str(l_obj.get("text") or "").strip()
            if not l_text:
                continue
            m_code = _SCREENSHOT_PITCH_CODE_RE.search(l_text)
            if m_code:
                raw_code = m_code.group(1)
                if raw_code.upper().startswith("O"):
                    raw_code = "0" + raw_code[1:]
                current_pitch = raw_code
                rem = l_text.replace(m_code.group(0), "").strip(" -·:|")
                if rem and not _SCREENSHOT_TIME_TOKEN_RE.match(rem):
                    current_pitch_name = rem
                if not any(p["Pitch_number"] == current_pitch for p in detected_pitches):
                    detected_pitches.append({
                        "pitch_number": current_pitch,
                        "pitch_name": current_pitch_name,
                        "page": 1,
                        "orientation": "North",
                        "Sub-Line": subline,
                        "Pitch_number": current_pitch,
                        "Pitch_status": "Active",
                        "Pitch_name": current_pitch_name,
                        "Pitch_Takt_time": takt_time,
                        "Model_variants": ["Base"],
                    })
                continue
            m_inline = _SCREENSHOT_INLINE_TIME_RE.match(l_text)
            if m_inline:
                desc_txt = m_inline.group(1).strip(" -·:|")
                t_val = float(m_inline.group(2))
                if desc_txt and not any(k in desc_txt for k in ("Takt Time", "Tak Time", "Actual CT", "Theoretical")):
                    if not any(p["Pitch_number"] == current_pitch for p in detected_pitches):
                        detected_pitches.append({
                            "pitch_number": current_pitch,
                            "pitch_name": current_pitch_name,
                            "page": 1,
                            "orientation": "North",
                            "Sub-Line": subline,
                            "Pitch_number": current_pitch,
                            "Pitch_status": "Active",
                            "Pitch_name": current_pitch_name,
                            "Pitch_Takt_time": takt_time,
                            "Model_variants": ["Base"],
                        })
                    all_elements.append({
                        "Sub-Line": subline,
                        "Pitch_number": current_pitch,
                        "Pitch_status": "Active",
                        "Pitch_name": current_pitch_name,
                        "Pitch_Takt_time": takt_time,
                        "Model_variant": "Base",
                        "Work_Type": "Cycle",
                        "Work_Description": desc_txt,
                        "Work_Time_to_complete": t_val,
                        "Work_region": "None",
                    })

    if not detected_pitches and not all_elements:
        default_pitch = "01-ASM-001"
        detected_pitches.append({
            "pitch_number": default_pitch,
            "pitch_name": "",
            "page": 1,
            "orientation": "North",
            "Sub-Line": subline,
            "Pitch_number": default_pitch,
            "Pitch_status": "Active",
            "Pitch_name": "",
            "Pitch_Takt_time": takt_time,
            "Model_variants": ["Base"],
        })
        fallback_desc = (
            ocr_lines[0]["text"].strip()
            if ocr_lines and str(ocr_lines[0].get("text") or "").strip()
            else "Screenshot work element"
        )
        all_elements.append({
            "Sub-Line": subline,
            "Pitch_number": default_pitch,
            "Pitch_status": "Active",
            "Pitch_name": "",
            "Pitch_Takt_time": takt_time,
            "Model_variant": "Base",
            "Work_Type": "Cycle",
            "Work_Description": fallback_desc,
            "Work_Time_to_complete": 0.0,
            "Work_region": "None",
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

    detected_variants: list[str] = []
    for p_row in detected_pitches:
        for v_item in p_row.get("Model_variants") or []:
            v_str = str(v_item or "").strip()
            if v_str and v_str not in detected_variants:
                detected_variants.append(v_str)
    for e_row in all_elements:
        v_str = str(e_row.get("Model_variant") or "").strip()
        if v_str and v_str not in detected_variants:
            detected_variants.append(v_str)

    return {
        "metadata": {
            "plant": plant,
            "line": line,
            "subline": subline,
            "takt_time": takt_time,
            "region_map": {},
            "variants": detected_variants,
        },
        "pitches": detected_pitches,
        "pitch_dataframe": pitch_df,
        "dataframe": df,
    }
