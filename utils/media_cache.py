from __future__ import annotations

import base64
from io import BytesIO
import mimetypes
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from utils.cache_store import get_data_cache
import utils.db_core as _db_core
from utils.gcp_storage import resolve_upload_path


def _resolve_media_path(path: str | Path | None) -> Optional[Path]:
    if not path:
        return None
    try:
        candidate = Path(path)
        if not candidate.exists() or not candidate.is_file():
            rebased = resolve_upload_path(path, _db_core.UPLOAD_DIR)
            if rebased is not None:
                return rebased.resolve()
            return None
        return candidate.resolve()
    except OSError:
        return None


def _file_stat_key(resolved: Path) -> Optional[tuple[str, int, int]]:
    try:
        st = resolved.stat()
        return (str(resolved), int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        return None


def _guess_mime(resolved: Path, output_format: Optional[str]) -> str:
    if output_format:
        fmt = output_format.upper()
        if fmt == "WEBP":
            return "image/webp"
        if fmt in ("JPEG", "JPG"):
            return "image/jpeg"
        if fmt == "PNG":
            return "image/png"
    guessed, _ = mimetypes.guess_type(str(resolved))
    if guessed and guessed.startswith("image/"):
        return guessed
    ext = resolved.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    if ext == ".svg":
        return "image/svg+xml"
    return "image/png"


def cached_image_bytes(
    path: str | Path | None,
    *,
    max_dim: Optional[int] = 1200,
    output_format: Optional[str] = "WEBP",
    quality: int = 82,
) -> Optional[bytes]:
    """Return cached image bytes (optionally resized and encoded as WebP/PNG/JPEG).

    Keyed by (resolved_path, mtime_ns, size_bytes, max_dim, output_format, quality)
    Inside the global CompressedLRUCache so repeated reruns and tab switches do not
    re-read or re-decode images from disk.
    """
    resolved = _resolve_media_path(path)
    if resolved is None:
        return None
    stat_key = _file_stat_key(resolved)
    if stat_key is None:
        return None

    norm_fmt = output_format.upper() if output_format else None
    cache_key = ("media_bytes", stat_key, max_dim, norm_fmt, int(quality))
    cache = get_data_cache()
    hit, cached = cache.get(cache_key)
    if hit:
        return cached

    try:
        raw_bytes = resolved.read_bytes()
    except OSError:
        return None

    # Do not rasterize SVG files or when neither resize nor format conversion is requested
    if resolved.suffix.lower() == ".svg" or (max_dim is None and norm_fmt is None):
        cache.set(cache_key, raw_bytes)
        return raw_bytes

    try:
        with Image.open(BytesIO(raw_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            needs_resize = bool(max_dim and max(img.size) > max_dim)
            if not needs_resize and norm_fmt is None:
                cache.set(cache_key, raw_bytes)
                return raw_bytes

            if needs_resize and max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            target_fmt = norm_fmt or (img.format or "PNG").upper()
            if target_fmt == "JPG":
                target_fmt = "JPEG"

            if target_fmt == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            elif target_fmt == "WEBP" and img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

            buf = BytesIO()
            save_kwargs: dict = {}
            if target_fmt in ("WEBP", "JPEG"):
                save_kwargs["quality"] = int(quality)
            if target_fmt == "WEBP":
                save_kwargs["method"] = 4
            img.save(buf, format=target_fmt, **save_kwargs)
            result = buf.getvalue()
    except Exception:
        # Fallback to raw bytes if PIL cannot decode the file
        result = raw_bytes

    cache.set(cache_key, result)
    return result


def cached_image_data_url(
    path: str | Path | None,
    *,
    max_dim: Optional[int] = 1600,
    output_format: Optional[str] = "WEBP",
    quality: int = 82,
) -> Optional[str]:
    """Return a cached `data:image/...;base64,...` URL for HTML/Canvas components."""
    resolved = _resolve_media_path(path)
    if resolved is None:
        return None
    stat_key = _file_stat_key(resolved)
    if stat_key is None:
        return None

    norm_fmt = output_format.upper() if output_format else None
    cache_key = ("media_data_url", stat_key, max_dim, norm_fmt, int(quality))
    cache = get_data_cache()
    hit, cached = cache.get(cache_key)
    if hit:
        return cached

    img_bytes = cached_image_bytes(
        resolved,
        max_dim=max_dim,
        output_format=norm_fmt,
        quality=quality,
    )
    if img_bytes is None:
        return None

    # Determine actual MIME type based on magic bytes or fallback
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    elif img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif img_bytes[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    else:
        mime = _guess_mime(resolved, norm_fmt)

    encoded = base64.b64encode(img_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{encoded}"
    cache.set(cache_key, data_url)
    return data_url


def prewarm_image_cache(
    path: str | Path | None,
    *,
    byte_dims: tuple[int, ...] = (160, 360, 1200),
    data_url_dims: tuple[int, ...] = (360, 1600),
    quality: int = 82,
) -> dict[str, int]:
    """Pre-populate compressed WebP thumbnail and data-URL cache tiers on image upload."""
    resolved = _resolve_media_path(path)
    if resolved is None:
        return {"bytes_warmed": 0, "data_urls_warmed": 0}
    if resolved.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return {"bytes_warmed": 0, "data_urls_warmed": 0}

    bytes_warmed = 0
    data_urls_warmed = 0
    for dim in byte_dims:
        if cached_image_bytes(resolved, max_dim=dim, quality=quality) is not None:
            bytes_warmed += 1
    for dim in data_url_dims:
        if cached_image_data_url(resolved, max_dim=dim, quality=quality) is not None:
            data_urls_warmed += 1
    return {"bytes_warmed": bytes_warmed, "data_urls_warmed": data_urls_warmed}
