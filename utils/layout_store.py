"""Persistence, scaling math, and revision history for 2D plant floor plan layouts."""

from __future__ import annotations

import importlib
import json
import sqlite3
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from PIL import Image, ImageDraw, ImageFont, ImageOps

SUPPORTED_LAYOUT_EXTENSIONS: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".pdf",
    ".dxf",
)

LAYOUT_UNITS: tuple[str, ...] = ("feet", "inches", "yards", "miles")

UNIT_TO_INCHES: dict[str, float] = {
    "inches": 1.0,
    "in": 1.0,
    "feet": 12.0,
    "ft": 12.0,
    "yards": 36.0,
    "yd": 36.0,
    "miles": 63360.0,
    "mi": 63360.0,
}


def _store_module():
    return importlib.import_module("utils.db_core")


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _require_editor(editor_name: str) -> str:
    editor = _text(editor_name)
    if not editor:
        raise ValueError("Enter Current editor attribution before saving layout changes.")
    return editor


def _remove_owned_upload(path_value: object) -> None:
    if not path_value:
        return
    path = Path(str(path_value))
    try:
        upload_dir = _store_module().UPLOAD_DIR.resolve()
        if path.exists() and path.is_file() and upload_dir in path.resolve().parents:
            path.unlink()
    except Exception:
        pass


def to_canonical_inches(value: float, unit: str) -> float:
    """Convert any supported linear distance to canonical inches."""
    try:
        val = float(value)
    except (TypeError, ValueError):
        val = 0.0
    factor = UNIT_TO_INCHES.get(unit.lower().strip(), 12.0)
    return max(0.0, val) * factor


def from_canonical_inches(inches: float, unit: str) -> float:
    """Convert canonical inches to user-selected display unit."""
    try:
        val = float(inches)
    except (TypeError, ValueError):
        val = 0.0
    factor = UNIT_TO_INCHES.get(unit.lower().strip(), 12.0)
    if factor <= 0:
        return max(0.0, val)
    return max(0.0, val) / factor


def format_dimension(inches: float, unit: str = "feet") -> str:
    """Format dimension cleanly with unit label."""
    val = from_canonical_inches(inches, unit)
    if val.is_integer():
        return f"{int(val)} {unit}"
    return f"{val:.2f} {unit}"


def init_layout_schema(conn: sqlite3.Connection) -> None:
    """Initialize database tables for 2D plant floor plan layouts."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS layout_plans (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, name)
        );
        CREATE TABLE IF NOT EXISTS layout_revisions (
            id TEXT PRIMARY KEY,
            layout_id TEXT NOT NULL REFERENCES layout_plans(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL,
            image_path TEXT NOT NULL DEFAULT '',
            image_width_px INTEGER NOT NULL DEFAULT 0,
            image_height_px INTEGER NOT NULL DEFAULT 0,
            width_value REAL NOT NULL DEFAULT 0.0,
            height_value REAL NOT NULL DEFAULT 0.0,
            unit TEXT NOT NULL DEFAULT 'feet',
            scale_width_in REAL NOT NULL DEFAULT 0.0,
            scale_height_in REAL NOT NULL DEFAULT 0.0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL DEFAULT '',
            UNIQUE(layout_id, revision_number)
        );
        CREATE TABLE IF NOT EXISTS layout_shapes (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES layout_revisions(id) ON DELETE CASCADE,
            shape_type TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            x REAL NOT NULL DEFAULT 0.0,
            y REAL NOT NULL DEFAULT 0.0,
            width REAL NOT NULL DEFAULT 0.0,
            height REAL NOT NULL DEFAULT 0.0,
            rotation REAL NOT NULL DEFAULT 0.0,
            color TEXT NOT NULL DEFAULT '#1976d2',
            style_json TEXT NOT NULL DEFAULT '{}',
            pitch_id TEXT REFERENCES yamazumi_pitches(id) ON DELETE SET NULL,
            equipment_id TEXT REFERENCES equipment_assets(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_layout_plans_project
            ON layout_plans(project_id, name);
        CREATE INDEX IF NOT EXISTS idx_layout_revisions_layout
            ON layout_revisions(layout_id, revision_number);
        CREATE INDEX IF NOT EXISTS idx_layout_shapes_revision
            ON layout_shapes(revision_id);
        CREATE TABLE IF NOT EXISTS layout_section_pitch_standards (
            id TEXT PRIMARY KEY,
            layout_id TEXT NOT NULL REFERENCES layout_plans(id) ON DELETE CASCADE,
            section_id TEXT NOT NULL,
            pitch_width REAL NOT NULL DEFAULT 12.0,
            pitch_height REAL NOT NULL DEFAULT 8.0,
            unit TEXT NOT NULL DEFAULT 'feet',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(layout_id, section_id)
        );
        CREATE INDEX IF NOT EXISTS idx_section_pitch_standards
            ON layout_section_pitch_standards(layout_id, section_id);
        """
    )


# --- Layout Plan Operations ---


def list_layouts(project_id: str) -> list[dict[str, Any]]:
    """Return all floor plan layouts for a project, along with latest revision info."""
    store = _store_module()
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT p.*,
                   COUNT(r.id) AS revision_count,
                   COALESCE(MAX(r.revision_number), 0) AS latest_revision_number,
                   (
                       SELECT r2.image_path
                       FROM layout_revisions r2
                       WHERE r2.layout_id = p.id
                       ORDER BY r2.revision_number DESC
                       LIMIT 1
                   ) AS latest_image_path
            FROM layout_plans p
            LEFT JOIN layout_revisions r ON r.layout_id = p.id
            WHERE p.project_id = ?
            GROUP BY p.id
            ORDER BY p.name COLLATE NOCASE ASC
            """,
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_layout(project_id: str, layout_id: str) -> dict[str, Any] | None:
    """Return a single layout plan by ID."""
    store = _store_module()
    with store.connection() as conn:
        row = conn.execute(
            """
            SELECT p.*,
                   COUNT(r.id) AS revision_count,
                   COALESCE(MAX(r.revision_number), 0) AS latest_revision_number
            FROM layout_plans p
            LEFT JOIN layout_revisions r ON r.layout_id = p.id
            WHERE p.id = ? AND p.project_id = ?
            GROUP BY p.id
            """,
            (layout_id, project_id),
        ).fetchone()
        return dict(row) if row else None


def create_layout(
    project_id: str, name: str, description: str, editor_name: str
) -> dict[str, Any]:
    """Create a new named layout plan."""
    store = _store_module()
    editor = _require_editor(editor_name)
    cleaned_name = _text(name)
    if not cleaned_name:
        raise ValueError("Layout name cannot be blank.")
    timestamp = store.now_iso()
    layout_id = str(uuid4())
    with store.connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM layout_plans WHERE project_id=? AND name=? COLLATE NOCASE",
            (project_id, cleaned_name),
        ).fetchone()
        if existing:
            raise ValueError(f"A layout named '{cleaned_name}' already exists in this project.")
        conn.execute(
            """
            INSERT INTO layout_plans (id, project_id, name, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (layout_id, project_id, cleaned_name, _text(description), timestamp, timestamp),
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Create layout",
            1,
            editor,
            {"layout_id": layout_id, "name": cleaned_name},
            _conn=conn,
        )
    return {"id": layout_id, "name": cleaned_name, "created_at": timestamp}


def update_layout(
    project_id: str, layout_id: str, name: str, description: str, editor_name: str
) -> None:
    """Update layout name or description."""
    store = _store_module()
    editor = _require_editor(editor_name)
    cleaned_name = _text(name)
    if not cleaned_name:
        raise ValueError("Layout name cannot be blank.")
    timestamp = store.now_iso()
    with store.connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM layout_plans WHERE project_id=? AND name=? COLLATE NOCASE AND id!=?",
            (project_id, cleaned_name, layout_id),
        ).fetchone()
        if existing:
            raise ValueError(f"Another layout named '{cleaned_name}' already exists.")
        conn.execute(
            """
            UPDATE layout_plans
            SET name=?, description=?, updated_at=?
            WHERE id=? AND project_id=?
            """,
            (cleaned_name, _text(description), timestamp, layout_id, project_id),
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Update layout details",
            1,
            editor,
            {"layout_id": layout_id, "name": cleaned_name},
            _conn=conn,
        )


def layout_deletion_impact(project_id: str, layout_id: str) -> dict[str, Any]:
    """Calculate deletion impact for a layout."""
    store = _store_module()
    with store.connection() as conn:
        layout = conn.execute(
            "SELECT * FROM layout_plans WHERE id=? AND project_id=?", (layout_id, project_id)
        ).fetchone()
        if not layout:
            raise ValueError("That layout no longer exists.")
        revisions = conn.execute(
            "SELECT id, image_path FROM layout_revisions WHERE layout_id=?", (layout_id,)
        ).fetchall()
        rev_ids = [str(r["id"]) for r in revisions]
        image_paths = [str(r["image_path"]) for r in revisions if _text(r["image_path"])]
        shape_count = 0
        if rev_ids:
            placeholders = ",".join("?" for _ in rev_ids)
            shape_count = conn.execute(
                f"SELECT COUNT(*) FROM layout_shapes WHERE revision_id IN ({placeholders})",
                rev_ids,
            ).fetchone()[0]
        return {
            "layout_name": str(layout["name"]),
            "revision_count": len(revisions),
            "shape_count": shape_count,
            "image_count": len(image_paths),
            "image_paths": image_paths,
            "revisions_count": len(revisions),
            "shapes_count": shape_count,
            "images_count": len(image_paths),
        }


def delete_layout(project_id: str, layout_id: str, editor_name: str) -> dict[str, Any]:
    """Permanently delete a layout, its revisions, and all owned image uploads."""
    store = _store_module()
    editor = _require_editor(editor_name)
    impact = layout_deletion_impact(project_id, layout_id)
    with store.connection() as conn:
        conn.execute(
            "DELETE FROM layout_plans WHERE id=? AND project_id=?", (layout_id, project_id)
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Delete layout",
            1,
            editor,
            {"layout_id": layout_id, "layout_name": impact["layout_name"]},
            _conn=conn,
        )
    for path in impact["image_paths"]:
        _remove_owned_upload(path)
    return impact


# --- Revision Operations ---


def list_layout_revisions(layout_id: str) -> list[dict[str, Any]]:
    """Return all revisions for a layout, newest revision first."""
    store = _store_module()
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT r.*,
                   COUNT(s.id) AS shape_count
            FROM layout_revisions r
            LEFT JOIN layout_shapes s ON s.revision_id = r.id
            WHERE r.layout_id = ?
            GROUP BY r.id
            ORDER BY r.revision_number DESC
            """,
            (layout_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_layout_revision(revision_id: str) -> dict[str, Any] | None:
    """Return a single revision by ID with its shape count."""
    store = _store_module()
    with store.connection() as conn:
        row = conn.execute(
            """
            SELECT r.*,
                   p.name AS layout_name,
                   p.project_id,
                   COUNT(s.id) AS shape_count
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            LEFT JOIN layout_shapes s ON s.revision_id = r.id
            WHERE r.id = ?
            GROUP BY r.id
            """,
            (revision_id,),
        ).fetchone()
        return dict(row) if row else None


def get_latest_layout_revision(layout_id: str) -> dict[str, Any] | None:
    """Return the latest revision for a layout with its shape count."""
    store = _store_module()
    with store.connection() as conn:
        row = conn.execute(
            """
            SELECT r.*,
                   p.name AS layout_name,
                   p.project_id,
                   COUNT(s.id) AS shape_count
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            LEFT JOIN layout_shapes s ON s.revision_id = r.id
            WHERE r.layout_id = ?
            GROUP BY r.id
            ORDER BY r.revision_number DESC
            LIMIT 1
            """,
            (layout_id,),
        ).fetchone()
        return dict(row) if row else None


def get_pdf_page_count(content: bytes) -> int:
    """Return the total number of pages in a PDF document."""
    try:
        import pypdfium2 as pdfium

        with pdfium.PdfDocument(content) as pdf:
            return len(pdf)
    except Exception as exc:
        raise ValueError(f"Could not read PDF document: {exc}") from exc


def render_pdf_page_to_image(
    content: bytes, page_number: int = 1, scale: float = 2.0
) -> Image.Image:
    """Render a specific PDF page (1-based index) into a PIL RGB Image."""
    try:
        import pypdfium2 as pdfium

        with pdfium.PdfDocument(content) as pdf:
            num_pages = len(pdf)
            if num_pages == 0:
                raise ValueError("The PDF document contains no pages.")
            idx = max(0, min(page_number - 1, num_pages - 1))
            page = pdf[idx]
            pil_img = page.render(scale=scale).to_pil()
            return pil_img.convert("RGB")
    except Exception as exc:
        raise ValueError(f"Failed to render PDF page: {exc}") from exc


def render_dxf_to_image(content: bytes, dpi: int = 150) -> Image.Image:
    """Render a 2D DXF file modelspace into a PIL RGB Image."""
    try:
        import io
        import ezdxf
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        text_content = content.decode("utf-8", errors="replace")
        stream = io.StringIO(text_content)
        doc = ezdxf.read(stream)
        msp = doc.modelspace()

        fig = plt.figure()
        ax = fig.add_axes([0, 0, 1, 1])
        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        Frontend(ctx, out).draw_layout(msp, finalize=True)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return Image.open(buf).convert("RGB")
    except Exception as exc:
        raise ValueError(f"Failed to render DXF layout: {exc}") from exc


def apply_image_orientation(
    image: Image.Image, rotation_angle: int = 0
) -> Image.Image:
    """Rotate image by 0, 90, 180, or 270 degrees clockwise."""
    deg = (int(rotation_angle) % 360 + 360) % 360
    if deg == 90:
        return image.transpose(Image.Transpose.ROTATE_270)
    elif deg == 180:
        return image.transpose(Image.Transpose.ROTATE_180)
    elif deg == 270:
        return image.transpose(Image.Transpose.ROTATE_90)
    return image


def apply_image_crop(
    image: Image.Image,
    crop_left_pct: float = 0.0,
    crop_top_pct: float = 0.0,
    crop_right_pct: float = 0.0,
    crop_bottom_pct: float = 0.0,
) -> Image.Image:
    """Crop an image using edge margin percentages (0.0% to 45.0%)."""
    cl = max(0.0, min(45.0, float(crop_left_pct or 0.0)))
    ct = max(0.0, min(45.0, float(crop_top_pct or 0.0)))
    cr = max(0.0, min(45.0, float(crop_right_pct or 0.0)))
    cb = max(0.0, min(45.0, float(crop_bottom_pct or 0.0)))

    if cl <= 0.001 and ct <= 0.001 and cr <= 0.001 and cb <= 0.001:
        return image

    w, h = image.size
    left_px = int(round(w * (cl / 100.0)))
    top_px = int(round(h * (ct / 100.0)))
    right_px = int(round(w * (1.0 - (cr / 100.0))))
    bottom_px = int(round(h * (1.0 - (cb / 100.0))))

    if right_px > left_px + 20 and bottom_px > top_px + 20:
        return image.crop((left_px, top_px, right_px, bottom_px))
    return image


def auto_detect_whitespace_crop(
    image: Image.Image,
    threshold: int = 240,
    padding: int = 10,
) -> tuple[int, int, int, int]:
    """Find the bounding box of non-white content in an image with outer padding."""
    if not image:
        return (0, 0, 0, 0)
    img_rgb = image.convert("RGB") if image.mode != "RGB" else image
    gray_inv = ImageOps.invert(img_rgb.convert("L"))
    cutoff = 255 - max(0, min(255, int(threshold)))
    thresh = gray_inv.point(lambda p: 255 if p > cutoff else 0)
    bbox = thresh.getbbox()
    if not bbox:
        return (0, 0, image.width, image.height)
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    if right > left + 20 and bottom > top + 20:
        return (left, top, right, bottom)
    return (0, 0, image.width, image.height)


def _get_preview_font(size: int = 16) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Load a clean system font or fallback to default."""
    for font_name in ("arial.ttf", "calibri.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def annotate_preview_with_dimensions(
    img: Image.Image,
    width_val: float,
    height_val: float,
    unit: str,
) -> Image.Image:
    """Frame the preview image with architectural dimension lines and labels for Width and Height."""
    w = img.width
    h = img.height
    ruler = max(44, min(72, int(max(w, h) * 0.05)))
    font_size = max(12, min(20, int(ruler * 0.35)))
    font = _get_preview_font(font_size)

    total_w = w + ruler
    total_h = h + ruler

    framed = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    framed.paste(img, (ruler, ruler))
    draw = ImageDraw.Draw(framed)

    # 1. Top Ruler (Horizontal - Physical Width)
    draw.rectangle([(ruler, 0), (total_w, ruler)], fill=(227, 242, 253), outline=(144, 202, 249), width=1)
    # 2. Left Ruler (Vertical - Physical Height / Length)
    draw.rectangle([(0, ruler), (ruler, total_h)], fill=(243, 229, 245), outline=(206, 147, 216), width=1)
    # 3. Top-left corner box
    draw.rectangle([(0, 0), (ruler, ruler)], fill=(236, 239, 241), outline=(176, 190, 197), width=1)
    c_font = _get_preview_font(max(10, font_size - 2))
    draw.text((ruler // 4, ruler // 3), "(0,0)", fill=(90, 100, 110), font=c_font)

    # Drawing boundary border
    draw.rectangle([(ruler, ruler), (total_w - 1, total_h - 1)], outline=(120, 144, 156), width=1)

    # Top Arrow & Text: Horizontal Width
    w_label = f"  <-- Width: {width_val:g} {unit} ({w} px) -->  "
    arrow_y = ruler // 2
    draw.line([(ruler + 12, arrow_y), (total_w - 12, arrow_y)], fill=(13, 71, 161), width=2)
    draw.polygon([(ruler + 4, arrow_y), (ruler + 14, arrow_y - 5), (ruler + 14, arrow_y + 5)], fill=(13, 71, 161))
    draw.polygon([(total_w - 4, arrow_y), (total_w - 14, arrow_y - 5), (total_w - 14, arrow_y + 5)], fill=(13, 71, 161))

    t_box = draw.textbbox((0, 0), w_label, font=font)
    tw = t_box[2] - t_box[0]
    th = t_box[3] - t_box[1]
    tx = ruler + max(0, (w - tw) // 2)
    ty = max(0, (ruler - th) // 2)
    draw.rectangle([(tx - 6, ty - 2), (tx + tw + 6, ty + th + 2)], fill=(227, 242, 253), outline=(144, 202, 249), width=1)
    draw.text((tx, ty), w_label, fill=(13, 71, 161), font=font)

    # Left Arrow & Text: Vertical Height / Length
    arrow_x = ruler // 2
    draw.line([(arrow_x, ruler + 12), (arrow_x, total_h - 12)], fill=(74, 20, 140), width=2)
    draw.polygon([(arrow_x, ruler + 4), (arrow_x - 5, ruler + 14), (arrow_x + 5, ruler + 14)], fill=(74, 20, 140))
    draw.polygon([(arrow_x, total_h - 4), (arrow_x - 5, total_h - 14), (arrow_x + 5, total_h - 14)], fill=(74, 20, 140))

    h_label = f"  Height/Length: {height_val:g} {unit} ({h} px)  "
    txt_img = Image.new("RGBA", (max(10, h - 30), ruler), (243, 229, 245, 0))
    txt_draw = ImageDraw.Draw(txt_img)
    lh_box = txt_draw.textbbox((0, 0), h_label, font=font)
    htw = lh_box[2] - lh_box[0]
    hth = lh_box[3] - lh_box[1]
    tx_l = max(0, (txt_img.width - htw) // 2)
    ty_l = max(0, (ruler - hth) // 2)
    txt_draw.rectangle([(tx_l - 4, ty_l - 2), (tx_l + htw + 4, ty_l + hth + 2)], fill=(243, 229, 245), outline=(206, 147, 216), width=1)
    txt_draw.text((tx_l, ty_l), h_label, fill=(74, 20, 140), font=font)
    rotated = txt_img.rotate(90, expand=True)
    rx = max(0, (ruler - rotated.width) // 2)
    ry = ruler + max(0, (h - rotated.height) // 2)
    framed.paste(rotated, (rx, ry), rotated)

    return framed


def load_and_orient_layout_preview(
    image_file: Any,
    rotation_angle: int = 0,
    pdf_page: int = 1,
    crop_left_pct: float = 0.0,
    crop_top_pct: float = 0.0,
    crop_right_pct: float = 0.0,
    crop_bottom_pct: float = 0.0,
) -> Image.Image | None:
    """Load an uploaded file or clipboard image, apply page, rotation, and crop, and return PIL Image for UI preview."""
    if not image_file:
        return None
    if isinstance(image_file, Image.Image):
        img = image_file.copy().convert("RGB")
        img = apply_image_orientation(img, rotation_angle)
        return apply_image_crop(img, crop_left_pct, crop_top_pct, crop_right_pct, crop_bottom_pct)

    filename = str(getattr(image_file, "name", "screenshot.png"))
    suffix = Path(filename).suffix.lower()
    content = (
        image_file.getvalue()
        if hasattr(image_file, "getvalue")
        else image_file.read()
    )
    if not content:
        return None
    if hasattr(image_file, "seek"):
        image_file.seek(0)

    if suffix == ".pdf":
        img = render_pdf_page_to_image(content, page_number=pdf_page, scale=2.0)
    elif suffix == ".dxf":
        img = render_dxf_to_image(content, dpi=100)
    else:
        try:
            img = Image.open(BytesIO(content))
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
        except Exception as exc:
            raise ValueError(f"Could not decode image file: {exc}") from exc

    img = apply_image_orientation(img, rotation_angle)
    return apply_image_crop(img, crop_left_pct, crop_top_pct, crop_right_pct, crop_bottom_pct)


def create_layout_revision(
    project_id: str,
    layout_id: str,
    image_file: Any,
    width_value: float,
    height_value: float,
    unit: str,
    notes: str = "",
    copy_from_revision_id: str | None = None,
    editor_name: str = "",
    rotation_angle: int = 0,
    pdf_page: int = 1,
    source_shapes: list[dict[str, Any]] | None = None,
    crop_left_pct: float = 0.0,
    crop_top_pct: float = 0.0,
    crop_right_pct: float = 0.0,
    crop_bottom_pct: float = 0.0,
) -> dict[str, Any]:
    """Create a new versioned layout revision with an image/drawing and scale specifications."""
    store = _store_module()
    editor = _require_editor(editor_name)
    cleaned_unit = unit.lower().strip()
    if cleaned_unit not in LAYOUT_UNITS:
        raise ValueError(f"Invalid unit '{unit}'. Choose from: {', '.join(LAYOUT_UNITS)}.")
    try:
        w_val = float(width_value)
        h_val = float(height_value)
    except (TypeError, ValueError):
        raise ValueError("Width and Height must be positive numbers.")
    if w_val <= 0 or h_val <= 0:
        raise ValueError("Width and Height must be greater than zero.")

    # Image / document validation & processing
    normalized_rot = (int(rotation_angle) % 360 + 360) % 360
    has_crops = (
        float(crop_left_pct or 0.0) > 0.001
        or float(crop_top_pct or 0.0) > 0.001
        or float(crop_right_pct or 0.0) > 0.001
        or float(crop_bottom_pct or 0.0) > 0.001
    )
    store.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if isinstance(image_file, Image.Image):
        img = image_file.copy().convert("RGB")
        img = apply_image_orientation(img, normalized_rot)
        img = apply_image_crop(img, crop_left_pct, crop_top_pct, crop_right_pct, crop_bottom_pct)
        suffix = ".png"
        img_w_px, img_h_px = img.size
        target_path = store.UPLOAD_DIR / f"layout_{layout_id}_{uuid4()}.png"
        img.save(target_path, "PNG")
    else:
        filename = str(getattr(image_file, "name", "screenshot.png"))
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_LAYOUT_EXTENSIONS:
            allowed = ", ".join(ext.upper().lstrip(".") for ext in SUPPORTED_LAYOUT_EXTENSIONS)
            raise ValueError(f"Unsupported file type '{suffix}'. Use: {allowed}.")

        content = (
            image_file.getvalue()
            if hasattr(image_file, "getvalue")
            else image_file.read()
        )
        if not content:
            raise ValueError("Choose or paste a non-empty image or drawing.")
        if hasattr(image_file, "seek"):
            image_file.seek(0)

        if suffix == ".pdf":
            img = render_pdf_page_to_image(content, page_number=pdf_page, scale=2.0)
            img = apply_image_orientation(img, normalized_rot)
            img = apply_image_crop(img, crop_left_pct, crop_top_pct, crop_right_pct, crop_bottom_pct)
            img_w_px, img_h_px = img.size
            target_path = store.UPLOAD_DIR / f"layout_{layout_id}_{uuid4()}.png"
            img.save(target_path, "PNG")
        elif suffix == ".dxf":
            img = render_dxf_to_image(content, dpi=150)
            img = apply_image_orientation(img, normalized_rot)
            img = apply_image_crop(img, crop_left_pct, crop_top_pct, crop_right_pct, crop_bottom_pct)
            img_w_px, img_h_px = img.size
            target_path = store.UPLOAD_DIR / f"layout_{layout_id}_{uuid4()}.png"
            img.save(target_path, "PNG")
        else:
            try:
                with Image.open(BytesIO(content)) as raw_img:
                    raw_img.verify()
                with Image.open(BytesIO(content)) as loaded_img:
                    loaded_img = ImageOps.exif_transpose(loaded_img)
                    loaded_img = loaded_img.convert("RGB")
                    if normalized_rot != 0 or has_crops:
                        loaded_img = apply_image_orientation(loaded_img, normalized_rot)
                        loaded_img = apply_image_crop(
                            loaded_img,
                            crop_left_pct=crop_left_pct,
                            crop_top_pct=crop_top_pct,
                            crop_right_pct=crop_right_pct,
                            crop_bottom_pct=crop_bottom_pct,
                        )
                        img_w_px, img_h_px = loaded_img.size
                        target_path = store.UPLOAD_DIR / f"layout_{layout_id}_{uuid4()}.png"
                        loaded_img.save(target_path, "PNG")
                    else:
                        img_w_px, img_h_px = loaded_img.size
                        target_path = store.UPLOAD_DIR / f"layout_{layout_id}_{uuid4()}{suffix}"
                        target_path.write_bytes(content)
            except Exception as exc:
                raise ValueError("The provided file is not a readable image.") from exc

    scale_width_in = to_canonical_inches(w_val, cleaned_unit)
    scale_height_in = to_canonical_inches(h_val, cleaned_unit)
    timestamp = store.now_iso()
    new_revision_id = str(uuid4())

    try:
        with store.connection() as conn:
            layout = conn.execute(
                "SELECT * FROM layout_plans WHERE id=? AND project_id=?", (layout_id, project_id)
            ).fetchone()
            if not layout:
                raise ValueError("Layout not found in active project.")

            cur_max = conn.execute(
                "SELECT COALESCE(MAX(revision_number), 0) FROM layout_revisions WHERE layout_id=?",
                (layout_id,),
            ).fetchone()[0]
            new_rev_number = cur_max + 1

            conn.execute(
                """
                INSERT INTO layout_revisions
                (id, layout_id, revision_number, image_path, image_width_px, image_height_px,
                 width_value, height_value, unit, scale_width_in, scale_height_in,
                 notes, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_revision_id,
                    layout_id,
                    new_rev_number,
                    str(target_path),
                    img_w_px,
                    img_h_px,
                    w_val,
                    h_val,
                    cleaned_unit,
                    scale_width_in,
                    scale_height_in,
                    _text(notes),
                    timestamp,
                    editor,
                ),
            )

            # Copy forward shapes from previous revision if requested
            copied_shapes_count = 0
            if copy_from_revision_id:
                old_rev = conn.execute(
                    "SELECT image_width_px, image_height_px FROM layout_revisions WHERE id=?",
                    (copy_from_revision_id,),
                ).fetchone()
                scale_x = 1.0
                scale_y = 1.0
                if old_rev and old_rev["image_width_px"] and old_rev["image_height_px"]:
                    old_w = float(old_rev["image_width_px"])
                    old_h = float(old_rev["image_height_px"])
                    if old_w > 0 and old_h > 0 and img_w_px > 0 and img_h_px > 0:
                        scale_x = float(img_w_px) / old_w
                        scale_y = float(img_h_px) / old_h

                shapes_to_copy = source_shapes
                if shapes_to_copy is None:
                    shapes_to_copy = conn.execute(
                        "SELECT * FROM layout_shapes WHERE revision_id=?", (copy_from_revision_id,)
                    ).fetchall()

                for old_shape in shapes_to_copy:
                    old_s = dict(old_shape)
                    new_x = round(float(old_s.get("x") or 0.0) * scale_x, 2)
                    new_y = round(float(old_s.get("y") or 0.0) * scale_y, 2)
                    new_w = max(1.0, round(float(old_s.get("width") or 10.0) * scale_x, 2))
                    new_h = max(1.0, round(float(old_s.get("height") or 10.0) * scale_y, 2))

                    new_style_json = old_s.get("style_json")
                    if new_style_json and (abs(scale_x - 1.0) > 0.001 or abs(scale_y - 1.0) > 0.001):
                        try:
                            sdict = json.loads(new_style_json) if isinstance(new_style_json, str) else dict(new_style_json)
                            avg_scale = (scale_x + scale_y) / 2.0
                            if "stroke_width" in sdict and sdict["stroke_width"] is not None:
                                sdict["stroke_width"] = max(1, round(float(sdict["stroke_width"]) * avg_scale))
                            if "font_size" in sdict and sdict["font_size"] is not None:
                                sdict["font_size"] = max(8, round(float(sdict["font_size"]) * avg_scale))
                            new_style_json = json.dumps(sdict)
                        except Exception:
                            new_style_json = old_s.get("style_json")
                    elif isinstance(new_style_json, dict):
                        new_style_json = json.dumps(new_style_json)

                    conn.execute(
                        """
                        INSERT INTO layout_shapes
                        (id, revision_id, shape_type, label, x, y, width, height,
                         rotation, color, style_json, pitch_id, equipment_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            new_revision_id,
                            _text(old_s.get("shape_type") or "rectangle"),
                            _text(old_s.get("label")),
                            new_x,
                            new_y,
                            new_w,
                            new_h,
                            float(old_s.get("rotation") or 0.0),
                            _text(old_s.get("color") or "#1976d2"),
                            _text(new_style_json or "{}"),
                            _text(old_s.get("pitch_id")) or None,
                            _text(old_s.get("equipment_id")) or None,
                            timestamp,
                            timestamp,
                        ),
                    )
                    copied_shapes_count += 1

            conn.execute(
                "UPDATE layout_plans SET updated_at=? WHERE id=?", (timestamp, layout_id)
            )

            store.record_audit_event(
                project_id,
                "Layouts",
                "Create layout revision",
                1,
                editor,
                {
                    "layout_id": layout_id,
                    "layout_name": str(layout["name"]),
                    "revision_number": new_rev_number,
                    "width": f"{w_val} {cleaned_unit}",
                    "height": f"{h_val} {cleaned_unit}",
                    "copied_shapes_count": copied_shapes_count,
                    "orientation_deg": normalized_rot,
                    "source_format": suffix.lstrip("."),
                },
                _conn=conn,
            )
    except Exception:
        _remove_owned_upload(target_path)
        raise

    return {
        "id": new_revision_id,
        "revision_number": new_rev_number,
        "image_path": str(target_path),
        "image_width_px": img_w_px,
        "image_height_px": img_h_px,
        "width_value": w_val,
        "height_value": h_val,
        "unit": cleaned_unit,
        "scale_width_in": scale_width_in,
        "scale_height_in": scale_height_in,
        "copied_shapes_count": copied_shapes_count,
    }


def update_layout_revision_scale(
    project_id: str,
    revision_id: str,
    width_value: float,
    height_value: float,
    unit: str,
    notes: str | None,
    editor_name: str,
) -> None:
    """Update scale dimensions on an existing revision."""
    store = _store_module()
    editor = _require_editor(editor_name)
    cleaned_unit = unit.lower().strip()
    if cleaned_unit not in LAYOUT_UNITS:
        raise ValueError(f"Invalid unit '{unit}'. Choose from: {', '.join(LAYOUT_UNITS)}.")
    try:
        w_val = float(width_value)
        h_val = float(height_value)
    except (TypeError, ValueError):
        raise ValueError("Width and Height must be positive numbers.")
    if w_val <= 0 or h_val <= 0:
        raise ValueError("Width and Height must be greater than zero.")

    scale_width_in = to_canonical_inches(w_val, cleaned_unit)
    scale_height_in = to_canonical_inches(h_val, cleaned_unit)
    timestamp = store.now_iso()

    with store.connection() as conn:
        rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id=? AND p.project_id=?
            """,
            (revision_id, project_id),
        ).fetchone()
        if not rev:
            raise ValueError("Layout revision not found.")

        if notes is not None:
            conn.execute(
                """
                UPDATE layout_revisions
                SET width_value=?, height_value=?, unit=?,
                    scale_width_in=?, scale_height_in=?, notes=?
                WHERE id=?
                """,
                (w_val, h_val, cleaned_unit, scale_width_in, scale_height_in, _text(notes), revision_id),
            )
        else:
            conn.execute(
                """
                UPDATE layout_revisions
                SET width_value=?, height_value=?, unit=?,
                    scale_width_in=?, scale_height_in=?
                WHERE id=?
                """,
                (w_val, h_val, cleaned_unit, scale_width_in, scale_height_in, revision_id),
            )

        store.record_audit_event(
            project_id,
            "Layouts",
            "Update layout scale",
            1,
            editor,
            {
                "layout_id": str(rev["layout_id"]),
                "revision_number": int(rev["revision_number"]),
                "old_dimensions": f"{rev['width_value']} {rev['unit']} × {rev['height_value']} {rev['unit']}",
                "new_dimensions": f"{w_val} {cleaned_unit} × {h_val} {cleaned_unit}",
            },
            _conn=conn,
        )


def delete_layout_revision(project_id: str, revision_id: str, editor_name: str) -> None:
    """Delete an individual layout revision."""
    store = _store_module()
    editor = _require_editor(editor_name)
    with store.connection() as conn:
        rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id=? AND p.project_id=?
            """,
            (revision_id, project_id),
        ).fetchone()
        if not rev:
            raise ValueError("Revision not found.")
        image_path = str(rev["image_path"] or "")
        conn.execute("DELETE FROM layout_revisions WHERE id=?", (revision_id,))
        store.record_audit_event(
            project_id,
            "Layouts",
            "Delete layout revision",
            1,
            editor,
            {
                "layout_id": str(rev["layout_id"]),
                "revision_number": int(rev["revision_number"]),
            },
            _conn=conn,
        )
    _remove_owned_upload(image_path)


# --- Shape Operations ---


def list_layout_shapes(revision_id: str) -> list[dict[str, Any]]:
    """Return all drawn shapes and workstation/equipment footprints for a revision."""
    store = _store_module()
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT s.*,
                   yp.pitch_number,
                   yp.pitch_name,
                   ea.name AS equipment_name
            FROM layout_shapes s
            LEFT JOIN yamazumi_pitches yp ON yp.id = s.pitch_id
            LEFT JOIN equipment_assets ea ON ea.id = s.equipment_id
            WHERE s.revision_id = ?
            ORDER BY s.created_at ASC
            """,
            (revision_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def save_layout_shapes(
    project_id: str, revision_id: str, shapes: list[dict[str, Any]], editor_name: str
) -> None:
    """Atomically save the list of shapes for a layout revision."""
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()
    with store.connection() as conn:
        rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id=? AND p.project_id=?
            """,
            (revision_id, project_id),
        ).fetchone()
        if not rev:
            raise ValueError("Revision not found.")

        conn.execute("DELETE FROM layout_shapes WHERE revision_id=?", (revision_id,))
        for shape in shapes:
            shape_id = str(shape.get("id") or uuid4())
            conn.execute(
                """
                INSERT INTO layout_shapes
                (id, revision_id, shape_type, label, x, y, width, height,
                 rotation, color, style_json, pitch_id, equipment_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shape_id,
                    revision_id,
                    _text(shape.get("shape_type") or "rectangle"),
                    _text(shape.get("label")),
                    float(shape.get("x") or 0.0),
                    float(shape.get("y") or 0.0),
                    float(shape.get("width") or 0.0),
                    float(shape.get("height") or 0.0),
                    float(shape.get("rotation") or 0.0),
                    _text(shape.get("color") or "#1976d2"),
                    _text(shape.get("style_json") or "{}"),
                    _text(shape.get("pitch_id")) or None,
                    _text(shape.get("equipment_id")) or None,
                    timestamp,
                    timestamp,
                ),
            )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Save layout annotations",
            len(shapes),
            editor,
            {
                "layout_id": str(rev["layout_id"]),
                "revision_number": int(rev["revision_number"]),
                "shape_count": len(shapes),
            },
            _conn=conn,
        )


def import_shapes_from_revision(
    project_id: str,
    target_revision_id: str,
    source_revision_id: str,
    editor_name: str,
    replace_existing: bool = False,
    source_shapes: list[dict[str, Any]] | None = None,
) -> int:
    """Import and auto-scale shapes from a source revision into a target revision.

    Calculates proportional scaling between the source drawing pixel resolution and
    the target drawing pixel resolution so that equipment footprints and annotations
    land in the exact same positions and sizes on the target layout revision.
    """
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()

    with store.connection() as conn:
        target_rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id=? AND p.project_id=?
            """,
            (target_revision_id, project_id),
        ).fetchone()
        if not target_rev:
            raise ValueError("Target layout revision not found in active project.")

        source_rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id=? AND p.project_id=?
            """,
            (source_revision_id, project_id),
        ).fetchone()
        if not source_rev:
            raise ValueError("Source layout revision not found in active project.")

        if replace_existing:
            conn.execute(
                "DELETE FROM layout_shapes WHERE revision_id=?", (target_revision_id,)
            )

        target_w = float(target_rev["image_width_px"] or 1)
        target_h = float(target_rev["image_height_px"] or 1)
        source_w = float(source_rev["image_width_px"] or 1)
        source_h = float(source_rev["image_height_px"] or 1)

        scale_x = (target_w / source_w) if source_w > 0 and target_w > 0 else 1.0
        scale_y = (target_h / source_h) if source_h > 0 and target_h > 0 else 1.0

        shapes_to_copy = source_shapes
        if shapes_to_copy is None:
            shapes_to_copy = conn.execute(
                "SELECT * FROM layout_shapes WHERE revision_id=?", (source_revision_id,)
            ).fetchall()

        imported_count = 0
        for s in shapes_to_copy:
            old_s = dict(s)
            new_x = round(float(old_s.get("x") or 0.0) * scale_x, 2)
            new_y = round(float(old_s.get("y") or 0.0) * scale_y, 2)
            new_w = max(1.0, round(float(old_s.get("width") or 10.0) * scale_x, 2))
            new_h = max(1.0, round(float(old_s.get("height") or 10.0) * scale_y, 2))

            new_style_json = old_s.get("style_json")
            if new_style_json and (abs(scale_x - 1.0) > 0.001 or abs(scale_y - 1.0) > 0.001):
                try:
                    sdict = json.loads(new_style_json) if isinstance(new_style_json, str) else dict(new_style_json)
                    avg_scale = (scale_x + scale_y) / 2.0
                    if "stroke_width" in sdict and sdict["stroke_width"] is not None:
                        sdict["stroke_width"] = max(1, round(float(sdict["stroke_width"]) * avg_scale))
                    if "font_size" in sdict and sdict["font_size"] is not None:
                        sdict["font_size"] = max(8, round(float(sdict["font_size"]) * avg_scale))
                    new_style_json = json.dumps(sdict)
                except Exception:
                    new_style_json = old_s.get("style_json")
            elif isinstance(new_style_json, dict):
                new_style_json = json.dumps(new_style_json)

            conn.execute(
                """
                INSERT INTO layout_shapes
                (id, revision_id, shape_type, label, x, y, width, height,
                 rotation, color, style_json, pitch_id, equipment_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    target_revision_id,
                    _text(old_s.get("shape_type") or "rectangle"),
                    _text(old_s.get("label")),
                    new_x,
                    new_y,
                    new_w,
                    new_h,
                    float(old_s.get("rotation") or 0.0),
                    _text(old_s.get("color") or "#1976d2"),
                    _text(new_style_json or "{}"),
                    _text(old_s.get("pitch_id")) or None,
                    _text(old_s.get("equipment_id")) or None,
                    timestamp,
                    timestamp,
                ),
            )
            imported_count += 1

        store.record_audit_event(
            project_id,
            "Layouts",
            "Import layout shapes",
            imported_count,
            editor,
            {
                "layout_id": str(target_rev["layout_id"]),
                "target_revision_number": int(target_rev["revision_number"]),
                "source_revision_number": int(source_rev["revision_number"]),
                "imported_count": imported_count,
                "scale_x": round(scale_x, 4),
                "scale_y": round(scale_y, 4),
                "replace_existing": replace_existing,
            },
            _conn=conn,
        )

    return imported_count


# --- Section Pitch Dimensional Standards ---


def get_section_pitch_standards(layout_id: str) -> dict[str, dict[str, Any]]:
    """Return all section pitch standards configured for a layout keyed by section_id."""
    store = _store_module()
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM layout_section_pitch_standards
            WHERE layout_id = ?
            """,
            (layout_id,),
        ).fetchall()
        return {
            str(row["section_id"]): {
                "id": str(row["id"]),
                "section_id": str(row["section_id"]),
                "pitch_width": float(row["pitch_width"]),
                "pitch_height": float(row["pitch_height"]),
                "unit": str(row["unit"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        }


def set_section_pitch_standard(
    project_id: str,
    layout_id: str,
    section_id: str,
    pitch_width: float,
    pitch_height: float,
    unit: str,
    editor_name: str,
) -> dict[str, Any]:
    """Upsert standard workstation pitch length & width for a section in this layout."""
    store = _store_module()
    editor = _require_editor(editor_name)
    cleaned_unit = unit.lower().strip()
    if cleaned_unit not in LAYOUT_UNITS:
        raise ValueError(f"Invalid unit '{unit}'.")
    if pitch_width <= 0 or pitch_height <= 0:
        raise ValueError("Pitch width and height must both be greater than zero.")

    timestamp = store.now_iso()
    with store.connection() as conn:
        layout = conn.execute(
            "SELECT id FROM layout_plans WHERE id=? AND project_id=?", (layout_id, project_id)
        ).fetchone()
        if not layout:
            raise ValueError("That layout does not exist in this project.")

        existing = conn.execute(
            "SELECT id FROM layout_section_pitch_standards WHERE layout_id=? AND section_id=?",
            (layout_id, section_id),
        ).fetchone()

        if existing:
            standard_id = str(existing["id"])
            conn.execute(
                """
                UPDATE layout_section_pitch_standards
                SET pitch_width=?, pitch_height=?, unit=?, updated_at=?
                WHERE id=?
                """,
                (pitch_width, pitch_height, cleaned_unit, timestamp, standard_id),
            )
        else:
            standard_id = str(uuid4())
            conn.execute(
                """
                INSERT INTO layout_section_pitch_standards
                (id, layout_id, section_id, pitch_width, pitch_height, unit, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    standard_id,
                    layout_id,
                    section_id,
                    pitch_width,
                    pitch_height,
                    cleaned_unit,
                    timestamp,
                    timestamp,
                ),
            )

        store.record_audit_event(
            project_id,
            "Layouts",
            "Set section pitch dimensions",
            1,
            editor,
            {
                "layout_id": layout_id,
                "section_id": section_id,
                "pitch_width": pitch_width,
                "pitch_height": pitch_height,
                "unit": cleaned_unit,
            },
            _conn=conn,
        )

        return {
            "id": standard_id,
            "layout_id": layout_id,
            "section_id": section_id,
            "pitch_width": pitch_width,
            "pitch_height": pitch_height,
            "unit": cleaned_unit,
            "updated_at": timestamp,
        }


# --- Cross-Scenario Yamazumi Pitch Queries ---


def list_project_yamazumi_pitches(project_id: str) -> list[dict[str, Any]]:
    """List unique workstation pitches across all planning scenarios with scenario and area metadata."""
    store = _store_module()
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id AS pitch_id,
                p.pitch_number,
                p.pitch_name,
                p.pitch_type,
                p.status AS pitch_status,
                p.sequence AS pitch_sequence,
                p.feeds_into_pitch_id,
                a.id AS area_id,
                a.name AS area_name,
                a.section_id,
                s.id AS scenario_id,
                s.name AS scenario_name,
                s.revision_label AS scenario_revision_label
            FROM yamazumi_pitches p
            JOIN yamazumi_areas a ON a.id = p.area_id
            JOIN planning_scenarios s ON s.id = a.scenario_id
            WHERE s.project_id = ?
            ORDER BY a.name, p.sequence, p.pitch_number
            """,
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pitch_layout_footprints(project_id: str, scenario_id: str) -> list[dict[str, Any]]:
    """Return placed layout shapes linked to pitches in this scenario, providing real-world coordinates for the Pin Map."""
    store = _store_module()
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT
                s.id AS shape_id,
                s.pitch_id,
                p.pitch_number,
                p.pitch_name,
                p.status AS pitch_status,
                s.x,
                s.y,
                s.width,
                s.height,
                s.rotation,
                s.color,
                s.style_json,
                r.id AS revision_id,
                r.revision_number,
                r.image_path,
                r.unit,
                r.unit AS layout_unit,
                r.scale_width_in,
                r.scale_height_in,
                r.image_width_px,
                r.image_height_px,
                (CAST(r.image_width_px AS REAL) / r.scale_width_in) AS scale_px_per_in,
                (CAST(r.image_width_px AS REAL) / r.scale_width_in) AS scale_px_per_in_x,
                (CAST(r.image_height_px AS REAL) / r.scale_height_in) AS scale_px_per_in_y,
                l.id AS layout_id,
                l.name AS layout_name
            FROM layout_shapes s
            JOIN layout_revisions r ON r.id = s.revision_id
            JOIN layout_plans l ON l.id = r.layout_id
            JOIN yamazumi_pitches p ON p.id = s.pitch_id
            JOIN yamazumi_areas a ON a.id = p.area_id
            WHERE l.project_id = ? AND a.scenario_id = ?
            ORDER BY s.x, s.y
            """,
            (project_id, scenario_id),
        ).fetchall()
        return [dict(r) for r in rows]


__domain_exports__ = [
    "LAYOUT_UNITS",
    "UNIT_TO_INCHES",
    "to_canonical_inches",
    "from_canonical_inches",
    "format_dimension",
    "init_layout_schema",
    "list_layouts",
    "get_layout",
    "create_layout",
    "update_layout",
    "layout_deletion_impact",
    "delete_layout",
    "list_layout_revisions",
    "get_layout_revision",
    "get_latest_layout_revision",
    "SUPPORTED_LAYOUT_EXTENSIONS",
    "get_pdf_page_count",
    "render_pdf_page_to_image",
    "render_dxf_to_image",
    "apply_image_orientation",
    "apply_image_crop",
    "auto_detect_whitespace_crop",
    "annotate_preview_with_dimensions",
    "load_and_orient_layout_preview",
    "create_layout_revision",
    "update_layout_revision_scale",
    "delete_layout_revision",
    "list_layout_shapes",
    "save_layout_shapes",
    "import_shapes_from_revision",
    "get_section_pitch_standards",
    "set_section_pitch_standard",
    "list_project_yamazumi_pitches",
    "get_pitch_layout_footprints",
]
