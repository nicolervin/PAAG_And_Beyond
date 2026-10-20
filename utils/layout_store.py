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

SUPPORTED_LAYOUT_CAD_EXTENSIONS: tuple[str, ...] = (".dwg", ".dxf")
MAX_LAYOUT_CAD_FILE_SIZE_BYTES: int = 100 * 1024 * 1024  # 100 MB
MAX_LAYOUT_CAD_FILE_SIZE_MB: int = 100

LAYOUT_UNITS: tuple[str, ...] = ("feet", "inches", "meters", "yards", "miles")
IMPERIAL_LAYOUT_UNITS: tuple[str, ...] = ("feet", "inches", "yards")

UNIT_TO_INCHES: dict[str, float] = {
    "inches": 1.0,
    "in": 1.0,
    "feet": 12.0,
    "ft": 12.0,
    "meters": 39.37007874,
    "meter": 39.37007874,
    "m": 39.37007874,
    "yards": 36.0,
    "yd": 36.0,
    "miles": 63360.0,
    "mi": 63360.0,
}

DEFAULT_ENGINEERING_LAYERS: tuple[tuple[str, str, int, str], ...] = (
    ("Facility & CAD Grid", "facility", 10, "#64748B"),
    ("Conveyors & Pitches", "pitches", 20, "#2563EB"),
    ("Workers & HMI Screens", "operators_screens", 30, "#0D9488"),
    ("Material Flow & Racks", "material_flow", 40, "#D97706"),
    ("Information Flow & Signals", "information_flow", 50, "#7C3AED"),
    ("Equipment, Safety & Callouts", "equipment", 60, "#E11D48"),
)


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
    """Initialize database tables for 2D plant floor plan layouts, layers, and shapes."""
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
            cad_file_path TEXT NOT NULL DEFAULT '',
            cad_file_name TEXT NOT NULL DEFAULT '',
            cad_file_size_bytes INTEGER NOT NULL DEFAULT 0,
            cad_web_url TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL DEFAULT '',
            UNIQUE(layout_id, revision_number)
        );
        CREATE TABLE IF NOT EXISTS layout_layers (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES layout_revisions(id) ON DELETE CASCADE,
            scenario_id TEXT DEFAULT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            layer_type TEXT NOT NULL DEFAULT 'custom',
            visible INTEGER NOT NULL DEFAULT 1,
            locked INTEGER NOT NULL DEFAULT 0,
            opacity REAL NOT NULL DEFAULT 1.0,
            z_index INTEGER NOT NULL DEFAULT 0,
            color TEXT NOT NULL DEFAULT '#2563EB',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS layout_shapes (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES layout_revisions(id) ON DELETE CASCADE,
            layer_id TEXT DEFAULT NULL REFERENCES layout_layers(id) ON DELETE SET NULL,
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
            z_index INTEGER NOT NULL DEFAULT 0,
            group_id TEXT NOT NULL DEFAULT '',
            locked INTEGER NOT NULL DEFAULT 0,
            source_shape_id TEXT DEFAULT NULL REFERENCES layout_shapes(id) ON DELETE SET NULL,
            target_shape_id TEXT DEFAULT NULL REFERENCES layout_shapes(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_layout_plans_project
            ON layout_plans(project_id, name);
        CREATE INDEX IF NOT EXISTS idx_layout_revisions_layout
            ON layout_revisions(layout_id, revision_number);
        CREATE INDEX IF NOT EXISTS idx_layout_layers_revision
            ON layout_layers(revision_id, z_index);
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
        CREATE TABLE IF NOT EXISTS layout_custom_stencils (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Saved Shapes',
            stencil_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_layout_custom_stencils_project
            ON layout_custom_stencils(project_id, name);
        """
    )
    # Safe repeatable in-place schema upgrades for layout_revisions
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(layout_revisions)").fetchall()}
    if "cad_file_path" not in existing_cols:
        conn.execute("ALTER TABLE layout_revisions ADD COLUMN cad_file_path TEXT NOT NULL DEFAULT ''")
    if "cad_file_name" not in existing_cols:
        conn.execute("ALTER TABLE layout_revisions ADD COLUMN cad_file_name TEXT NOT NULL DEFAULT ''")
    if "cad_file_size_bytes" not in existing_cols:
        conn.execute("ALTER TABLE layout_revisions ADD COLUMN cad_file_size_bytes INTEGER NOT NULL DEFAULT 0")
    if "cad_web_url" not in existing_cols:
        conn.execute("ALTER TABLE layout_revisions ADD COLUMN cad_web_url TEXT NOT NULL DEFAULT ''")

    # Safe repeatable in-place schema upgrades for layout_shapes
    shape_cols = {row[1] for row in conn.execute("PRAGMA table_info(layout_shapes)").fetchall()}
    if "layer_id" not in shape_cols:
        conn.execute(
            "ALTER TABLE layout_shapes ADD COLUMN layer_id TEXT DEFAULT NULL REFERENCES layout_layers(id) ON DELETE SET NULL"
        )
    if "z_index" not in shape_cols:
        conn.execute("ALTER TABLE layout_shapes ADD COLUMN z_index INTEGER NOT NULL DEFAULT 0")
    if "group_id" not in shape_cols:
        conn.execute("ALTER TABLE layout_shapes ADD COLUMN group_id TEXT NOT NULL DEFAULT ''")
    if "locked" not in shape_cols:
        conn.execute("ALTER TABLE layout_shapes ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    if "source_shape_id" not in shape_cols:
        conn.execute(
            "ALTER TABLE layout_shapes ADD COLUMN source_shape_id TEXT DEFAULT NULL REFERENCES layout_shapes(id) ON DELETE SET NULL"
        )
    if "target_shape_id" not in shape_cols:
        conn.execute(
            "ALTER TABLE layout_shapes ADD COLUMN target_shape_id TEXT DEFAULT NULL REFERENCES layout_shapes(id) ON DELETE SET NULL"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_layout_shapes_layer ON layout_shapes(revision_id, layer_id, z_index)"
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
            "SELECT id, image_path, cad_file_path FROM layout_revisions WHERE layout_id=?", (layout_id,)
        ).fetchall()
        rev_ids = [str(r["id"]) for r in revisions]
        image_paths = [str(r["image_path"]) for r in revisions if _text(r["image_path"])]
        cad_paths = [str(r["cad_file_path"]) for r in revisions if _text(r["cad_file_path"])]
        all_file_paths = image_paths + cad_paths
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
            "image_paths": all_file_paths,
            "cad_count": len(cad_paths),
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
    cad_file: Any | None = None,
    cad_web_url: str = "",
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

    cad_path_str = ""
    cad_name_str = ""
    cad_size_int = 0
    clean_cad_url = _text(cad_web_url)

    if cad_file:
        cad_raw_name = str(getattr(cad_file, "name", "drawing.dwg")).strip()
        cad_suffix = Path(cad_raw_name).suffix.lower()
        if cad_suffix not in SUPPORTED_LAYOUT_CAD_EXTENSIONS:
            allowed = ", ".join(ext.upper().lstrip(".") for ext in SUPPORTED_LAYOUT_CAD_EXTENSIONS)
            raise ValueError(f"Unsupported AutoCAD drawing format '{cad_suffix}'. Allowed formats: {allowed}.")
        cad_bytes = (
            cad_file.getvalue() if hasattr(cad_file, "getvalue") else cad_file.read()
        )
        if hasattr(cad_file, "seek"):
            cad_file.seek(0)
        if not cad_bytes:
            raise ValueError("The provided AutoCAD drawing file is empty.")
        if len(cad_bytes) > MAX_LAYOUT_CAD_FILE_SIZE_BYTES:
            size_mb = len(cad_bytes) / (1024 * 1024)
            raise ValueError(
                f"AutoCAD drawing is {size_mb:.1f} MB. Maximum upload size is {MAX_LAYOUT_CAD_FILE_SIZE_MB} MB. "
                f"For larger facility drawings, use the CAD Web Link option."
            )
        cad_target = store.UPLOAD_DIR / f"layout_cad_{layout_id}_{uuid4()}{cad_suffix}"
        cad_target.write_bytes(cad_bytes)
        cad_path_str = str(cad_target)
        cad_name_str = cad_raw_name
        cad_size_int = len(cad_bytes)
    elif not isinstance(image_file, Image.Image):
        raw_fname = str(getattr(image_file, "name", "")).strip()
        if Path(raw_fname).suffix.lower() == ".dxf" and content:
            cad_target = store.UPLOAD_DIR / f"layout_cad_{layout_id}_{uuid4()}.dxf"
            cad_target.write_bytes(content)
            cad_path_str = str(cad_target)
            cad_name_str = raw_fname
            cad_size_int = len(content)

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
                 notes, cad_file_path, cad_file_name, cad_file_size_bytes, cad_web_url,
                 created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    cad_path_str,
                    cad_name_str,
                    cad_size_int,
                    clean_cad_url,
                    timestamp,
                    editor,
                ),
            )

            # Copy forward shapes and layers from previous revision if requested
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

                target_layers = ensure_default_layers_for_revision(new_revision_id, _conn=conn)
                target_layer_by_type = {str(l["layer_type"]): str(l["id"]) for l in target_layers}
                target_layer_by_name = {str(l["name"]).lower(): str(l["id"]) for l in target_layers}
                default_target_lid = target_layer_by_type.get("pitches") or (str(target_layers[0]["id"]) if target_layers else None)

                source_layers = ensure_default_layers_for_revision(copy_from_revision_id, _conn=conn)
                source_layer_map: dict[str, str] = {}
                for sl in source_layers:
                    sl_id = str(sl["id"])
                    sl_name = str(sl["name"]).lower()
                    sl_type = str(sl["layer_type"])
                    if sl_name in target_layer_by_name:
                        source_layer_map[sl_id] = target_layer_by_name[sl_name]
                    elif sl_type in target_layer_by_type:
                        source_layer_map[sl_id] = target_layer_by_type[sl_type]
                    else:
                        new_lid = str(uuid4())
                        conn.execute(
                            """
                            INSERT INTO layout_layers
                            (id, revision_id, scenario_id, name, layer_type, visible, locked, opacity, z_index, color, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                new_lid,
                                new_revision_id,
                                sl.get("scenario_id"),
                                str(sl["name"]),
                                sl_type,
                                int(sl.get("visible", 1)),
                                int(sl.get("locked", 0)),
                                float(sl.get("opacity", 1.0)),
                                int(sl.get("z_index", 50)),
                                str(sl.get("color", "#2563EB")),
                                timestamp,
                                timestamp,
                            ),
                        )
                        source_layer_map[sl_id] = new_lid

                shapes_to_copy = source_shapes
                if shapes_to_copy is None:
                    shapes_to_copy = conn.execute(
                        "SELECT * FROM layout_shapes WHERE revision_id=?", (copy_from_revision_id,)
                    ).fetchall()

                old_to_new_shape_id: dict[str, str] = {}
                prepared_shapes: list[tuple[str, dict[str, Any]]] = []
                for old_shape in shapes_to_copy:
                    old_s = dict(old_shape)
                    old_id = str(old_s.get("id") or uuid4())
                    new_id = str(uuid4())
                    old_to_new_shape_id[old_id] = new_id
                    prepared_shapes.append((new_id, old_s))

                copied_connector_links: list[tuple[str | None, str | None, str]] = []
                for idx, (new_id, old_s) in enumerate(prepared_shapes):
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
                            for kx in ("x1", "x2"):
                                if kx in sdict and sdict[kx] is not None:
                                    sdict[kx] = round(float(sdict[kx]) * scale_x, 2)
                            for ky in ("y1", "y2"):
                                if ky in sdict and sdict[ky] is not None:
                                    sdict[ky] = round(float(sdict[ky]) * scale_y, 2)
                            new_style_json = json.dumps(sdict, sort_keys=True)
                        except Exception:
                            new_style_json = old_s.get("style_json")
                    elif isinstance(new_style_json, dict):
                        new_style_json = json.dumps(new_style_json, sort_keys=True)

                    old_lid = _text(old_s.get("layer_id"))
                    mapped_lid = source_layer_map.get(old_lid, default_target_lid)
                    old_src_id = _text(old_s.get("source_shape_id"))
                    old_tgt_id = _text(old_s.get("target_shape_id"))
                    mapped_src_id = old_to_new_shape_id.get(old_src_id) if old_src_id else None
                    mapped_tgt_id = old_to_new_shape_id.get(old_tgt_id) if old_tgt_id else None
                    if mapped_src_id or mapped_tgt_id:
                        copied_connector_links.append((mapped_src_id, mapped_tgt_id, new_id))

                    conn.execute(
                        """
                        INSERT INTO layout_shapes
                        (id, revision_id, layer_id, shape_type, label, x, y, width, height,
                         rotation, color, style_json, pitch_id, equipment_id,
                         z_index, group_id, locked, source_shape_id, target_shape_id,
                         created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id,
                            new_revision_id,
                            mapped_lid,
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
                            int(old_s.get("z_index") if old_s.get("z_index") is not None else idx),
                            _text(old_s.get("group_id")),
                            int(old_s.get("locked") or 0),
                            None,
                            None,
                            timestamp,
                            timestamp,
                        ),
                    )
                    copied_shapes_count += 1

                if copied_connector_links:
                    conn.executemany(
                        "UPDATE layout_shapes SET source_shape_id=?, target_shape_id=? WHERE id=?",
                        copied_connector_links,
                    )

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
                    "has_cad_file": bool(cad_path_str),
                    "cad_file_name": cad_name_str,
                    "has_cad_url": bool(clean_cad_url),
                },
                _conn=conn,
            )
    except Exception:
        _remove_owned_upload(target_path)
        if cad_path_str:
            _remove_owned_upload(cad_path_str)
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
        "cad_file_path": cad_path_str,
        "cad_file_name": cad_name_str,
        "cad_file_size_bytes": cad_size_int,
        "cad_web_url": clean_cad_url,
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
        cad_file_path = str(rev["cad_file_path"] or "") if "cad_file_path" in rev.keys() else ""
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
    if cad_file_path:
        _remove_owned_upload(cad_file_path)


def attach_layout_revision_cad(
    project_id: str,
    revision_id: str,
    cad_file: Any | None = None,
    cad_web_url: str = "",
    editor_name: str = "",
) -> dict[str, Any]:
    """Attach or update a native AutoCAD file or CAD web link on an existing revision."""
    store = _store_module()
    editor = _require_editor(editor_name)
    clean_url = _text(cad_web_url)

    if not cad_file and not clean_url:
        raise ValueError("Provide either an AutoCAD drawing file (.dwg, .dxf) or a CAD Web Link.")

    with store.connection() as conn:
        rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id = ? AND p.project_id = ?
            """,
            (revision_id, project_id),
        ).fetchone()
        if not rev:
            raise ValueError("Revision not found in active project.")

        old_cad_path = str(rev["cad_file_path"] or "") if "cad_file_path" in rev.keys() else ""
        cad_path_str = old_cad_path
        cad_name_str = str(rev["cad_file_name"] or "") if "cad_file_name" in rev.keys() else ""
        cad_size_int = int(rev["cad_file_size_bytes"] or 0) if "cad_file_size_bytes" in rev.keys() else 0

        if cad_file:
            raw_name = str(getattr(cad_file, "name", "drawing.dwg")).strip()
            suffix = Path(raw_name).suffix.lower()
            if suffix not in SUPPORTED_LAYOUT_CAD_EXTENSIONS:
                allowed = ", ".join(ext.upper().lstrip(".") for ext in SUPPORTED_LAYOUT_CAD_EXTENSIONS)
                raise ValueError(f"Unsupported AutoCAD format '{suffix}'. Allowed: {allowed}.")
            content = cad_file.getvalue() if hasattr(cad_file, "getvalue") else cad_file.read()
            if hasattr(cad_file, "seek"):
                cad_file.seek(0)
            if not content:
                raise ValueError("The provided AutoCAD file is empty.")
            if len(content) > MAX_LAYOUT_CAD_FILE_SIZE_BYTES:
                size_mb = len(content) / (1024 * 1024)
                raise ValueError(
                    f"AutoCAD drawing is {size_mb:.1f} MB. Maximum upload size is {MAX_LAYOUT_CAD_FILE_SIZE_MB} MB. "
                    f"For larger facility drawings, use the CAD Web Link option."
                )
            store.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            target = store.UPLOAD_DIR / f"layout_cad_{rev['layout_id']}_{uuid4()}{suffix}"
            target.write_bytes(content)
            cad_path_str = str(target)
            cad_name_str = raw_name
            cad_size_int = len(content)

        conn.execute(
            """
            UPDATE layout_revisions
            SET cad_file_path = ?, cad_file_name = ?, cad_file_size_bytes = ?, cad_web_url = ?
            WHERE id = ?
            """,
            (cad_path_str, cad_name_str, cad_size_int, clean_url, revision_id),
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Update AutoCAD source",
            1,
            editor,
            {
                "layout_id": str(rev["layout_id"]),
                "revision_number": int(rev["revision_number"]),
                "cad_file_name": cad_name_str,
                "has_cad_file": bool(cad_path_str),
                "has_cad_url": bool(clean_url),
            },
            _conn=conn,
        )

    if cad_file and old_cad_path and old_cad_path != cad_path_str:
        _remove_owned_upload(old_cad_path)

    return get_layout_revision(revision_id) or {}


def remove_layout_revision_cad(
    project_id: str,
    revision_id: str,
    editor_name: str = "",
) -> dict[str, Any]:
    """Remove attached native AutoCAD file and CAD web link from a revision."""
    store = _store_module()
    editor = _require_editor(editor_name)

    with store.connection() as conn:
        rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id = ? AND p.project_id = ?
            """,
            (revision_id, project_id),
        ).fetchone()
        if not rev:
            raise ValueError("Revision not found in active project.")

        old_cad_path = str(rev["cad_file_path"] or "") if "cad_file_path" in rev.keys() else ""
        conn.execute(
            """
            UPDATE layout_revisions
            SET cad_file_path = '', cad_file_name = '', cad_file_size_bytes = 0, cad_web_url = ''
            WHERE id = ?
            """,
            (revision_id,),
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Remove AutoCAD source",
            1,
            editor,
            {
                "layout_id": str(rev["layout_id"]),
                "revision_number": int(rev["revision_number"]),
            },
            _conn=conn,
        )

    if old_cad_path:
        _remove_owned_upload(old_cad_path)

    return get_layout_revision(revision_id) or {}


# --- Layer Operations & Scale Calibration ---


def _infer_default_layer_type_for_shape(shape: dict[str, Any]) -> str:
    """Choose the best default engineering layer type for a shape when layer_id is unset."""
    if shape.get("pitch_id"):
        return "pitches"
    if shape.get("equipment_id"):
        return "equipment"
    stype = _text(shape.get("shape_type")).lower()
    if stype in ("operator", "worker", "screen", "hmi", "scanner", "computer_kiosk"):
        return "operators_screens"
    if stype in ("rack", "supermarket", "pallet", "agv", "mat_flow"):
        return "material_flow"
    if stype in ("connector", "arrow", "info_flow"):
        return "information_flow"
    if stype in ("conveyor", "conveyor_curve", "pitch_box", "workstation", "turntable", "area_header"):
        return "pitches"
    return "pitches"


def ensure_default_layers_for_revision(
    revision_id: str, _conn: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """Idempotently seed default engineering layers for a layout revision and backfill unassigned shapes."""
    store = _store_module()

    def _run(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT * FROM layout_layers
            WHERE revision_id = ?
            ORDER BY z_index ASC, created_at ASC
            """,
            (revision_id,),
        ).fetchall()
        timestamp = store.now_iso()
        if not rows:
            for name, ltype, z_idx, color in DEFAULT_ENGINEERING_LAYERS:
                conn.execute(
                    """
                    INSERT INTO layout_layers
                    (id, revision_id, scenario_id, name, layer_type, visible, locked, opacity, z_index, color, created_at, updated_at)
                    VALUES (?, ?, NULL, ?, ?, 1, 0, 1.0, ?, ?, ?, ?)
                    """,
                    (str(uuid4()), revision_id, name, ltype, z_idx, color, timestamp, timestamp),
                )
            rows = conn.execute(
                """
                SELECT * FROM layout_layers
                WHERE revision_id = ?
                ORDER BY z_index ASC, created_at ASC
                """,
                (revision_id,),
            ).fetchall()

        layers = [dict(r) for r in rows]
        layer_by_type = {str(l["layer_type"]): str(l["id"]) for l in layers}
        fallback_layer_id = layer_by_type.get("pitches") or (str(layers[0]["id"]) if layers else None)

        if fallback_layer_id:
            unassigned = conn.execute(
                "SELECT id, shape_type, pitch_id, equipment_id FROM layout_shapes WHERE revision_id = ? AND (layer_id IS NULL OR layer_id = '')",
                (revision_id,),
            ).fetchall()
            if unassigned:
                updates = []
                for srow in unassigned:
                    sdict = dict(srow)
                    inferred_type = _infer_default_layer_type_for_shape(sdict)
                    target_lid = layer_by_type.get(inferred_type, fallback_layer_id)
                    updates.append((target_lid, str(sdict["id"])))
                conn.executemany(
                    "UPDATE layout_shapes SET layer_id = ? WHERE id = ?",
                    updates,
                )
        return layers

    if _conn is not None:
        return _run(_conn)
    with store.connection() as conn:
        return _run(conn)


def list_layout_layers(
    revision_id: str, scenario_id: str | None = None
) -> list[dict[str, Any]]:
    """Return all layers for a layout revision (ensuring default layers exist), ordered by z_index."""
    store = _store_module()
    with store.connection() as conn:
        ensure_default_layers_for_revision(revision_id, _conn=conn)
        if scenario_id:
            rows = conn.execute(
                """
                SELECT l.*,
                       (SELECT COUNT(*) FROM layout_shapes s WHERE s.layer_id = l.id) AS shape_count
                FROM layout_layers l
                WHERE l.revision_id = ? AND (l.scenario_id IS NULL OR l.scenario_id = ?)
                ORDER BY l.z_index ASC, l.created_at ASC
                """,
                (revision_id, scenario_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT l.*,
                       (SELECT COUNT(*) FROM layout_shapes s WHERE s.layer_id = l.id) AS shape_count
                FROM layout_layers l
                WHERE l.revision_id = ?
                ORDER BY l.z_index ASC, l.created_at ASC
                """,
                (revision_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def create_layout_layer(
    project_id: str,
    revision_id: str,
    name: str,
    layer_type: str = "custom",
    color: str = "#2563EB",
    scenario_id: str | None = None,
    editor_name: str = "",
) -> dict[str, Any]:
    """Create a new layer on a layout revision."""
    store = _store_module()
    editor = _require_editor(editor_name)
    cleaned_name = _text(name)
    if not cleaned_name:
        raise ValueError("Layer name cannot be blank.")
    cleaned_color = _text(color) or "#2563EB"
    cleaned_type = _text(layer_type) or "custom"
    timestamp = store.now_iso()
    layer_id = str(uuid4())

    with store.connection() as conn:
        rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id = ? AND p.project_id = ?
            """,
            (revision_id, project_id),
        ).fetchone()
        if not rev:
            raise ValueError("Revision not found in active project.")

        ensure_default_layers_for_revision(revision_id, _conn=conn)
        max_z = conn.execute(
            "SELECT COALESCE(MAX(z_index), 0) AS max_z FROM layout_layers WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()
        next_z = int(max_z["max_z"] if max_z else 0) + 10

        conn.execute(
            """
            INSERT INTO layout_layers
            (id, revision_id, scenario_id, name, layer_type, visible, locked, opacity, z_index, color, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, 0, 1.0, ?, ?, ?, ?)
            """,
            (
                layer_id,
                revision_id,
                _text(scenario_id) or None,
                cleaned_name,
                cleaned_type,
                next_z,
                cleaned_color,
                timestamp,
                timestamp,
            ),
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Create layout layer",
            1,
            editor,
            {
                "layout_id": str(rev["layout_id"]),
                "revision_number": int(rev["revision_number"]),
                "layer_name": cleaned_name,
                "layer_type": cleaned_type,
                "scenario_id": _text(scenario_id) or None,
            },
            _conn=conn,
        )
        return {
            "id": layer_id,
            "revision_id": revision_id,
            "scenario_id": _text(scenario_id) or None,
            "name": cleaned_name,
            "layer_type": cleaned_type,
            "visible": 1,
            "locked": 0,
            "opacity": 1.0,
            "z_index": next_z,
            "color": cleaned_color,
            "shape_count": 0,
            "created_at": timestamp,
            "updated_at": timestamp,
        }


def update_layout_layer(
    project_id: str,
    layer_id: str,
    *,
    name: str | None = None,
    visible: bool | int | None = None,
    locked: bool | int | None = None,
    opacity: float | None = None,
    z_index: int | None = None,
    color: str | None = None,
    editor_name: str = "",
) -> dict[str, Any]:
    """Update a layout layer's visibility, lock status, opacity, z_index, name, or color."""
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()

    with store.connection() as conn:
        row = conn.execute(
            """
            SELECT l.*, r.layout_id, r.revision_number
            FROM layout_layers l
            JOIN layout_revisions r ON r.id = l.revision_id
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE l.id = ? AND p.project_id = ?
            """,
            (layer_id, project_id),
        ).fetchone()
        if not row:
            raise ValueError("Layer not found in active project.")

        new_name = _text(name) if name is not None else str(row["name"])
        if not new_name:
            raise ValueError("Layer name cannot be blank.")
        new_vis = (1 if bool(visible) else 0) if visible is not None else int(row["visible"])
        new_lock = (1 if bool(locked) else 0) if locked is not None else int(row["locked"])
        new_op = max(0.05, min(1.0, float(opacity))) if opacity is not None else float(row["opacity"])
        new_z = int(z_index) if z_index is not None else int(row["z_index"])
        new_col = _text(color) or str(row["color"]) if color is not None else str(row["color"])

        conn.execute(
            """
            UPDATE layout_layers
            SET name = ?, visible = ?, locked = ?, opacity = ?, z_index = ?, color = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_name, new_vis, new_lock, new_op, new_z, new_col, timestamp, layer_id),
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Update layout layer",
            1,
            editor,
            {
                "layout_id": str(row["layout_id"]),
                "revision_number": int(row["revision_number"]),
                "layer_name": new_name,
                "visible": bool(new_vis),
                "locked": bool(new_lock),
                "opacity": round(new_op, 2),
                "z_index": new_z,
            },
            _conn=conn,
        )
        updated = conn.execute("SELECT * FROM layout_layers WHERE id = ?", (layer_id,)).fetchone()
        return dict(updated) if updated else {}


def delete_layout_layer(
    project_id: str,
    layer_id: str,
    editor_name: str = "",
    move_shapes_to_layer_id: str | None = None,
    delete_layer_shapes: bool = False,
) -> None:
    """Delete a layout layer, either reassigning its shapes to another layer or deleting them."""
    store = _store_module()
    editor = _require_editor(editor_name)

    with store.connection() as conn:
        row = conn.execute(
            """
            SELECT l.*, r.layout_id, r.revision_number
            FROM layout_layers l
            JOIN layout_revisions r ON r.id = l.revision_id
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE l.id = ? AND p.project_id = ?
            """,
            (layer_id, project_id),
        ).fetchone()
        if not row:
            raise ValueError("Layer not found in active project.")

        revision_id = str(row["revision_id"])
        remaining_layers = conn.execute(
            "SELECT id FROM layout_layers WHERE revision_id = ? AND id != ? ORDER BY z_index ASC",
            (revision_id, layer_id),
        ).fetchall()
        if not remaining_layers:
            raise ValueError("Cannot delete the last remaining layer on a layout revision.")

        if delete_layer_shapes:
            conn.execute("DELETE FROM layout_shapes WHERE layer_id = ?", (layer_id,))
        else:
            target_lid = _text(move_shapes_to_layer_id) or str(remaining_layers[0]["id"])
            conn.execute(
                "UPDATE layout_shapes SET layer_id = ? WHERE layer_id = ?",
                (target_lid, layer_id),
            )

        conn.execute("DELETE FROM layout_layers WHERE id = ?", (layer_id,))
        store.record_audit_event(
            project_id,
            "Layouts",
            "Delete layout layer",
            1,
            editor,
            {
                "layout_id": str(row["layout_id"]),
                "revision_number": int(row["revision_number"]),
                "layer_name": str(row["name"]),
                "deleted_shapes": bool(delete_layer_shapes),
            },
            _conn=conn,
        )


def reorder_layout_layers(
    project_id: str,
    revision_id: str,
    ordered_layer_ids: list[str],
    editor_name: str = "",
) -> list[dict[str, Any]]:
    """Update z_index values for layers on a revision according to ordered_layer_ids."""
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()
    with store.connection() as conn:
        rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id = ? AND p.project_id = ?
            """,
            (revision_id, project_id),
        ).fetchone()
        if not rev:
            raise ValueError("Revision not found in active project.")
        for idx, lid in enumerate(ordered_layer_ids):
            conn.execute(
                "UPDATE layout_layers SET z_index = ?, updated_at = ? WHERE id = ? AND revision_id = ?",
                ((idx + 1) * 10, timestamp, str(lid), revision_id),
            )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Reorder layout layers",
            len(ordered_layer_ids),
            editor,
            {
                "layout_id": str(rev["layout_id"]),
                "revision_number": int(rev["revision_number"]),
            },
            _conn=conn,
        )
    return list_layout_layers(revision_id)


def calibrate_revision_scale_by_reference(
    project_id: str,
    revision_id: str,
    px_distance: float | None = None,
    real_distance: float | None = None,
    unit: str = "feet",
    editor_name: str = "",
    *,
    pixel_distance: float | None = None,
    physical_distance: float | None = None,
) -> dict[str, Any]:
    """Calibrate the physical scale of a layout revision from a 2-point pixel measurement on the canvas."""
    store = _store_module()
    editor = _require_editor(editor_name)
    effective_px = float(px_distance if px_distance is not None else (pixel_distance or 0.0))
    effective_real = float(real_distance if real_distance is not None else (physical_distance or 0.0))
    cleaned_unit = unit.lower().strip()
    if cleaned_unit not in LAYOUT_UNITS:
        raise ValueError(f"Invalid unit '{unit}'. Choose from: {', '.join(LAYOUT_UNITS)}.")
    if effective_px <= 0.5:
        raise ValueError("Reference pixel distance is too small. Click two distinct points on the canvas.")
    if effective_real <= 0:
        raise ValueError("Real-world reference distance must be greater than zero.")

    with store.connection() as conn:
        rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id = ? AND p.project_id = ?
            """,
            (revision_id, project_id),
        ).fetchone()
        if not rev:
            raise ValueError("Layout revision not found.")

        img_w_px = float(rev["image_width_px"] or 1600)
        img_h_px = float(rev["image_height_px"] or 1000)
        units_per_px = float(effective_real) / float(effective_px)
        w_val = round(img_w_px * units_per_px, 2)
        h_val = round(img_h_px * units_per_px, 2)
        scale_width_in = to_canonical_inches(w_val, cleaned_unit)
        scale_height_in = to_canonical_inches(h_val, cleaned_unit)

        conn.execute(
            """
            UPDATE layout_revisions
            SET width_value = ?, height_value = ?, unit = ?,
                scale_width_in = ?, scale_height_in = ?
            WHERE id = ?
            """,
            (w_val, h_val, cleaned_unit, scale_width_in, scale_height_in, revision_id),
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Calibrate layout scale (2-point reference)",
            1,
            editor,
            {
                "layout_id": str(rev["layout_id"]),
                "revision_number": int(rev["revision_number"]),
                "reference_px": round(effective_px, 2),
                "reference_distance": f"{effective_real} {cleaned_unit}",
                "new_dimensions": f"{w_val} {cleaned_unit} × {h_val} {cleaned_unit}",
            },
            _conn=conn,
        )
        return {
            "revision_id": revision_id,
            "width_value": w_val,
            "height_value": h_val,
            "unit": cleaned_unit,
            "scale_width_in": scale_width_in,
            "scale_height_in": scale_height_in,
        }


def create_blank_scaled_revision(
    project_id: str,
    layout_id: str,
    width_value: float,
    height_value: float,
    unit: str = "feet",
    notes: str = "",
    copy_from_revision_id: str | None = None,
    editor_name: str = "",
    canvas_width_px: int | None = None,
    canvas_height_px: int | None = None,
) -> dict[str, Any]:
    """Create a clean, blank scaled canvas revision (without requiring an image file upload first)."""
    store = _store_module()
    editor = _require_editor(editor_name)
    cleaned_unit = unit.lower().strip()
    if cleaned_unit not in LAYOUT_UNITS:
        raise ValueError(f"Invalid unit '{unit}'. Choose from: {', '.join(LAYOUT_UNITS)}.")
    w_val = float(width_value)
    h_val = float(height_value)
    if w_val <= 0 or h_val <= 0:
        raise ValueError("Width and Height must be greater than zero.")

    if canvas_width_px and canvas_height_px and canvas_width_px > 0 and canvas_height_px > 0:
        base_w_px = int(canvas_width_px)
        base_h_px = int(canvas_height_px)
    else:
        aspect = max(0.25, min(4.0, w_val / h_val))
        base_h_px = 1800
        base_w_px = int(round(base_h_px * aspect))
        base_w_px = max(1200, min(4800, base_w_px))

    img = Image.new("RGB", (base_w_px, base_h_px), (248, 250, 252))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "blank_scaled_canvas.png"

    return create_layout_revision(
        project_id=project_id,
        layout_id=layout_id,
        image_file=buf,
        width_value=w_val,
        height_value=h_val,
        unit=cleaned_unit,
        notes=notes or "Blank scaled engineering canvas",
        editor_name=editor,
        copy_from_revision_id=copy_from_revision_id,
    )


# --- Shape Operations ---


def list_layout_shapes(revision_id: str) -> list[dict[str, Any]]:
    """Return all drawn shapes and workstation/equipment footprints for a revision with layer metadata."""
    store = _store_module()
    with store.connection() as conn:
        ensure_default_layers_for_revision(revision_id, _conn=conn)
        rows = conn.execute(
            """
            SELECT s.*,
                   ll.name AS layer_name,
                   ll.layer_type AS layer_type,
                   COALESCE(ll.visible, 1) AS layer_visible,
                   COALESCE(ll.locked, 0) AS layer_locked,
                   COALESCE(ll.opacity, 1.0) AS layer_opacity,
                   COALESCE(ll.z_index, 0) AS layer_z_index,
                   yp.pitch_number,
                   yp.pitch_name,
                   yp.status AS pitch_status,
                   ea.name AS equipment_name
            FROM layout_shapes s
            LEFT JOIN layout_layers ll ON ll.id = s.layer_id
            LEFT JOIN yamazumi_pitches yp ON yp.id = s.pitch_id
            LEFT JOIN equipment_assets ea ON ea.id = s.equipment_id
            WHERE s.revision_id = ?
            ORDER BY COALESCE(ll.z_index, 0) ASC, COALESCE(s.z_index, 0) ASC, s.created_at ASC
            """,
            (revision_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def save_layout_shapes(
    project_id: str,
    revision_id: str,
    shapes: list[dict[str, Any]],
    editor_name: str,
    layers: list[dict[str, Any]] | None = None,
    scale_calibration: dict[str, Any] | None = None,
) -> None:
    """Atomically save the list of shapes (and optional layer/scale updates) for a layout revision using high-speed batch SQL."""
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

        existing_layers = ensure_default_layers_for_revision(revision_id, _conn=conn)
        valid_layer_ids = {str(l["id"]) for l in existing_layers}
        layer_by_type = {str(l["layer_type"]): str(l["id"]) for l in existing_layers}
        default_layer_id = layer_by_type.get("pitches") or (str(existing_layers[0]["id"]) if existing_layers else None)

        # Apply optional layer state updates from the canvas Layer Manager
        if layers:
            for litem in layers:
                lid = _text(litem.get("id"))
                if not lid:
                    continue
                lname = _text(litem.get("name")) or "Layer"
                ltype = _text(litem.get("layer_type")) or "custom"
                lvis = 1 if bool(litem.get("visible", True)) else 0
                llock = 1 if bool(litem.get("locked", False)) else 0
                lop = max(0.05, min(1.0, float(litem.get("opacity", 1.0))))
                lz = int(litem.get("z_index", 10))
                lcol = _text(litem.get("color")) or "#2563EB"
                lscen = _text(litem.get("scenario_id")) or None
                if lid in valid_layer_ids:
                    conn.execute(
                        """
                        UPDATE layout_layers
                        SET name=?, layer_type=?, visible=?, locked=?, opacity=?, z_index=?, color=?, updated_at=?
                        WHERE id=? AND revision_id=?
                        """,
                        (lname, ltype, lvis, llock, lop, lz, lcol, timestamp, lid, revision_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO layout_layers
                        (id, revision_id, scenario_id, name, layer_type, visible, locked, opacity, z_index, color, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (lid, revision_id, lscen, lname, ltype, lvis, llock, lop, lz, lcol, timestamp, timestamp),
                    )
                    valid_layer_ids.add(lid)

        # Apply optional 2-point scale calibration from the canvas
        if scale_calibration:
            try:
                cal_w = float(scale_calibration.get("width_value") or 0.0)
                cal_h = float(scale_calibration.get("height_value") or 0.0)
                cal_unit = _text(scale_calibration.get("unit") or rev["unit"] or "feet").lower()
                if cal_w > 0 and cal_h > 0 and cal_unit in LAYOUT_UNITS:
                    sw_in = to_canonical_inches(cal_w, cal_unit)
                    sh_in = to_canonical_inches(cal_h, cal_unit)
                    conn.execute(
                        """
                        UPDATE layout_revisions
                        SET width_value=?, height_value=?, unit=?, scale_width_in=?, scale_height_in=?
                        WHERE id=?
                        """,
                        (cal_w, cal_h, cal_unit, sw_in, sh_in, revision_id),
                    )
            except Exception:
                pass

        valid_pitch_ids = {
            str(r["id"])
            for r in conn.execute("SELECT id FROM yamazumi_pitches").fetchall()
        }
        valid_equip_ids = {
            str(r["id"])
            for r in conn.execute(
                "SELECT id FROM equipment_assets WHERE project_id=?", (project_id,)
            ).fetchall()
        }

        normalized_shapes: list[dict[str, Any]] = []
        all_shape_ids: set[str] = set()
        for shape in shapes:
            s_copy = dict(shape)
            sid = _text(s_copy.get("id")) or str(uuid4())
            while sid in all_shape_ids:
                sid = str(uuid4())
            s_copy["id"] = sid
            all_shape_ids.add(sid)
            normalized_shapes.append(s_copy)

        def _canonical_style_str(val: Any) -> str:
            if isinstance(val, dict):
                return json.dumps(val, sort_keys=True)
            txt = _text(val or "{}")
            try:
                parsed = json.loads(txt)
                return json.dumps(parsed, sort_keys=True) if isinstance(parsed, dict) else txt
            except (ValueError, TypeError):
                return txt

        batch_rows = []
        connector_links: list[tuple[str | None, str | None, str]] = []
        incoming_comparison: list[tuple[Any, ...]] = []
        for idx, shape in enumerate(normalized_shapes):
            shape_id = str(shape["id"])
            raw_layer_id = _text(shape.get("layer_id"))
            if not raw_layer_id or raw_layer_id not in valid_layer_ids:
                inferred_type = _infer_default_layer_type_for_shape(shape)
                raw_layer_id = layer_by_type.get(inferred_type, default_layer_id)
            raw_style = shape.get("style_json") if shape.get("style_json") is not None else shape.get("style")
            style_str = _canonical_style_str(raw_style)
            raw_pitch_id = _text(shape.get("pitch_id")) or None
            if raw_pitch_id and raw_pitch_id not in valid_pitch_ids:
                raw_pitch_id = None
            raw_equip_id = _text(shape.get("equipment_id")) or None
            if raw_equip_id and raw_equip_id not in valid_equip_ids:
                raw_equip_id = None
            raw_src_id = _text(shape.get("source_shape_id")) or None
            if raw_src_id and raw_src_id not in all_shape_ids:
                raw_src_id = None
            raw_tgt_id = _text(shape.get("target_shape_id")) or None
            if raw_tgt_id and raw_tgt_id not in all_shape_ids:
                raw_tgt_id = None
            if raw_src_id or raw_tgt_id:
                connector_links.append((raw_src_id, raw_tgt_id, shape_id))
            s_type = _text(shape.get("shape_type") or "rectangle")
            s_label = _text(shape.get("label"))
            s_x = round(float(shape.get("x") or 0.0), 3)
            s_y = round(float(shape.get("y") or 0.0), 3)
            s_w = round(float(shape.get("width") or 0.0), 3)
            s_h = round(float(shape.get("height") or 0.0), 3)
            s_rot = round(float(shape.get("rotation") or 0.0), 3)
            s_col = _text(shape.get("color") or "#1976d2")
            s_z = int(shape.get("z_index") if shape.get("z_index") is not None else idx)
            s_grp = _text(shape.get("group_id"))
            s_lck = 1 if bool(shape.get("locked", False)) else 0
            incoming_comparison.append(
                (
                    shape_id,
                    raw_layer_id,
                    s_type,
                    s_label,
                    s_x,
                    s_y,
                    s_w,
                    s_h,
                    s_rot,
                    s_col,
                    style_str,
                    raw_pitch_id,
                    raw_equip_id,
                    s_z,
                    s_grp,
                    s_lck,
                    raw_src_id,
                    raw_tgt_id,
                )
            )
            batch_rows.append(
                (
                    shape_id,
                    revision_id,
                    raw_layer_id,
                    s_type,
                    s_label,
                    float(shape.get("x") or 0.0),
                    float(shape.get("y") or 0.0),
                    float(shape.get("width") or 0.0),
                    float(shape.get("height") or 0.0),
                    float(shape.get("rotation") or 0.0),
                    s_col,
                    style_str,
                    raw_pitch_id,
                    raw_equip_id,
                    s_z,
                    s_grp,
                    s_lck,
                    None,
                    None,
                    timestamp,
                    timestamp,
                )
            )

        existing_shape_rows = conn.execute(
            """
            SELECT id, layer_id, shape_type, label, x, y, width, height, rotation,
                   color, style_json, pitch_id, equipment_id, z_index, group_id,
                   locked, source_shape_id, target_shape_id
            FROM layout_shapes
            WHERE revision_id = ?
            ORDER BY COALESCE(z_index, 0) ASC, created_at ASC
            """,
            (revision_id,),
        ).fetchall()
        existing_comparison: list[tuple[Any, ...]] = []
        for er in existing_shape_rows:
            existing_comparison.append(
                (
                    str(er["id"]),
                    _text(er["layer_id"]) or None,
                    _text(er["shape_type"] or "rectangle"),
                    _text(er["label"]),
                    round(float(er["x"] or 0.0), 3),
                    round(float(er["y"] or 0.0), 3),
                    round(float(er["width"] or 0.0), 3),
                    round(float(er["height"] or 0.0), 3),
                    round(float(er["rotation"] or 0.0), 3),
                    _text(er["color"] or "#1976d2"),
                    _canonical_style_str(er["style_json"]),
                    _text(er["pitch_id"]) or None,
                    _text(er["equipment_id"]) or None,
                    int(er["z_index"] or 0),
                    _text(er["group_id"]),
                    1 if bool(er["locked"]) else 0,
                    _text(er["source_shape_id"]) or None,
                    _text(er["target_shape_id"]) or None,
                )
            )

        if (
            sorted(existing_comparison, key=lambda t: t[0])
            == sorted(incoming_comparison, key=lambda t: t[0])
            and not scale_calibration
        ):
            return

        conn.execute("DELETE FROM layout_shapes WHERE revision_id=?", (revision_id,))
        if batch_rows:
            conn.executemany(
                """
                INSERT INTO layout_shapes
                (id, revision_id, layer_id, shape_type, label, x, y, width, height,
                 rotation, color, style_json, pitch_id, equipment_id,
                 z_index, group_id, locked, source_shape_id, target_shape_id,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch_rows,
            )
            if connector_links:
                conn.executemany(
                    "UPDATE layout_shapes SET source_shape_id=?, target_shape_id=? WHERE id=?",
                    connector_links,
                )

        store.record_audit_event(
            project_id,
            "Layouts",
            "Save layout annotations",
            len(batch_rows),
            editor,
            {
                "layout_id": str(rev["layout_id"]),
                "revision_number": int(rev["revision_number"]),
                "shape_count": len(batch_rows),
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
    """Import and auto-scale shapes from a source revision into a target revision."""
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

        target_layers = ensure_default_layers_for_revision(target_revision_id, _conn=conn)
        target_layer_by_type = {str(l["layer_type"]): str(l["id"]) for l in target_layers}
        target_layer_by_name = {str(l["name"]).lower(): str(l["id"]) for l in target_layers}
        default_target_lid = target_layer_by_type.get("pitches") or (str(target_layers[0]["id"]) if target_layers else None)

        source_layers = ensure_default_layers_for_revision(source_revision_id, _conn=conn)
        source_layer_map: dict[str, str] = {}
        for sl in source_layers:
            sl_id = str(sl["id"])
            sl_name = str(sl["name"]).lower()
            sl_type = str(sl["layer_type"])
            if sl_name in target_layer_by_name:
                source_layer_map[sl_id] = target_layer_by_name[sl_name]
            elif sl_type in target_layer_by_type:
                source_layer_map[sl_id] = target_layer_by_type[sl_type]
            else:
                new_lid = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO layout_layers
                    (id, revision_id, scenario_id, name, layer_type, visible, locked, opacity, z_index, color, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_lid,
                        target_revision_id,
                        sl.get("scenario_id"),
                        str(sl["name"]),
                        sl_type,
                        int(sl.get("visible", 1)),
                        int(sl.get("locked", 0)),
                        float(sl.get("opacity", 1.0)),
                        int(sl.get("z_index", 50)),
                        str(sl.get("color", "#2563EB")),
                        timestamp,
                        timestamp,
                    ),
                )
                source_layer_map[sl_id] = new_lid

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

        old_to_new_shape_id: dict[str, str] = {}
        prepared_shapes: list[dict[str, Any]] = []
        for s in shapes_to_copy:
            old_s = dict(s)
            old_id = str(old_s.get("id") or uuid4())
            new_id = str(uuid4())
            old_to_new_shape_id[old_id] = new_id
            prepared_shapes.append((new_id, old_s))

        imported_count = 0
        imported_connector_links: list[tuple[str | None, str | None, str]] = []
        for idx, (new_id, old_s) in enumerate(prepared_shapes):
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
                    for kx in ("x1", "x2"):
                        if kx in sdict and sdict[kx] is not None:
                            sdict[kx] = round(float(sdict[kx]) * scale_x, 2)
                    for ky in ("y1", "y2"):
                        if ky in sdict and sdict[ky] is not None:
                            sdict[ky] = round(float(sdict[ky]) * scale_y, 2)
                    new_style_json = json.dumps(sdict, sort_keys=True)
                except Exception:
                    new_style_json = old_s.get("style_json")
            elif isinstance(new_style_json, dict):
                new_style_json = json.dumps(new_style_json, sort_keys=True)

            old_lid = _text(old_s.get("layer_id"))
            mapped_lid = source_layer_map.get(old_lid, default_target_lid)
            old_src_id = _text(old_s.get("source_shape_id"))
            old_tgt_id = _text(old_s.get("target_shape_id"))
            mapped_src_id = old_to_new_shape_id.get(old_src_id) if old_src_id else None
            mapped_tgt_id = old_to_new_shape_id.get(old_tgt_id) if old_tgt_id else None
            if mapped_src_id or mapped_tgt_id:
                imported_connector_links.append((mapped_src_id, mapped_tgt_id, new_id))

            conn.execute(
                """
                INSERT INTO layout_shapes
                (id, revision_id, layer_id, shape_type, label, x, y, width, height,
                 rotation, color, style_json, pitch_id, equipment_id,
                 z_index, group_id, locked, source_shape_id, target_shape_id,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id,
                    target_revision_id,
                    mapped_lid,
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
                    int(old_s.get("z_index") if old_s.get("z_index") is not None else idx),
                    _text(old_s.get("group_id")),
                    int(old_s.get("locked") or 0),
                    None,
                    None,
                    timestamp,
                    timestamp,
                ),
            )
            imported_count += 1

        if imported_connector_links:
            conn.executemany(
                "UPDATE layout_shapes SET source_shape_id=?, target_shape_id=? WHERE id=?",
                imported_connector_links,
            )

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


# --- Cross-Scenario Yamazumi Pitch Queries & Live Pin Map Metrics ---


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


def get_scenario_pitch_metrics_for_pin_map(
    project_id: str, scenario_id: str
) -> dict[str, dict[str, Any]]:
    """Compute live PAAG & Yamazumi metrics per pitch_id for the active scenario to power Lucidchart-style data overlays."""
    store = _store_module()
    with store.connection() as conn:
        scen_row = conn.execute(
            "SELECT takt_time_s FROM planning_scenarios WHERE id = ? AND project_id = ?",
            (scenario_id, project_id),
        ).fetchone()
        default_takt = float(scen_row["takt_time_s"] or 60.0) if scen_row else 60.0

        pitch_rows = conn.execute(
            """
            SELECT
                p.id AS pitch_id,
                p.pitch_number,
                p.pitch_name,
                p.pitch_type,
                p.status AS pitch_status,
                p.feeds_into_pitch_id,
                a.id AS area_id,
                a.name AS area_name,
                a.section_id,
                COALESCE(a.takt_override_s, ?) AS target_takt_sec
            FROM yamazumi_pitches p
            JOIN yamazumi_areas a ON a.id = p.area_id
            WHERE a.project_id = ? AND a.scenario_id = ?
            ORDER BY a.name, p.sequence, p.pitch_number
            """,
            (default_takt, project_id, scenario_id),
        ).fetchall()

        elem_rows = conn.execute(
            """
            SELECT
                ye.pitch_id,
                COUNT(DISTINCT ye.id) AS step_count,
                COALESCE(SUM(COALESCE(we.cycle_time_s, ye.time_s, 0.0)), 0.0) AS cycle_time_sec,
                COUNT(DISTINCT CASE
                    WHEN COALESCE(we.resource_detail, '') != '' THEN we.resource_detail
                    WHEN COALESCE(ye.work_region, '') NOT IN ('', 'None') THEN ye.work_region
                    ELSE 'Op-1'
                END) AS operator_count
            FROM yamazumi_elements ye
            JOIN yamazumi_areas a ON a.id = ye.area_id
            LEFT JOIN work_elements we ON we.id = ye.process_element_id
            WHERE a.project_id = ? AND a.scenario_id = ? AND ye.pitch_id IS NOT NULL
            GROUP BY ye.pitch_id
            """,
            (project_id, scenario_id),
        ).fetchall()
        elem_by_pitch = {str(r["pitch_id"]): dict(r) for r in elem_rows}

        step_rows = conn.execute(
            """
            SELECT
                ye.pitch_id,
                COALESCE(we.sequence, ye.sequence, 10) AS seq,
                COALESCE(NULLIF(we.operation, ''), ye.description, 'Work Step') AS operation,
                COALESCE(we.description, ye.description, '') AS description,
                ROUND(COALESCE(we.cycle_time_s, ye.time_s, 0.0), 1) AS cycle_time_s,
                COALESCE(NULLIF(we.resource_detail, ''), NULLIF(ye.work_region, 'None'), 'Operator') AS resource_label,
                COALESCE(we.part_number, '') AS part_number,
                COALESCE(we.tool, '') AS tool
            FROM yamazumi_elements ye
            JOIN yamazumi_areas a ON a.id = ye.area_id
            LEFT JOIN work_elements we ON we.id = ye.process_element_id
            WHERE a.project_id = ? AND a.scenario_id = ? AND ye.pitch_id IS NOT NULL
            ORDER BY ye.pitch_id, COALESCE(we.sequence, ye.sequence, 10), ye.id
            """,
            (project_id, scenario_id),
        ).fetchall()
        steps_by_pitch: dict[str, list[dict[str, Any]]] = {}
        for srow in step_rows:
            spid = str(srow["pitch_id"])
            lst = steps_by_pitch.setdefault(spid, [])
            if len(lst) < 15:
                lst.append(
                    {
                        "seq": int(srow["seq"] or 0),
                        "operation": str(srow["operation"] or ""),
                        "description": str(srow["description"] or ""),
                        "cycle_time_s": float(srow["cycle_time_s"] or 0.0),
                        "resource_label": str(srow["resource_label"] or ""),
                        "part_number": str(srow["part_number"] or ""),
                        "tool": str(srow["tool"] or ""),
                    }
                )

        metrics: dict[str, dict[str, Any]] = {}
        for prow in pitch_rows:
            pid = str(prow["pitch_id"])
            edata = elem_by_pitch.get(pid, {})
            takt = float(prow["target_takt_sec"] or default_takt or 60.0)
            ct = float(edata.get("cycle_time_sec") or 0.0)
            step_cnt = int(edata.get("step_count") or 0)
            op_cnt = int(edata.get("operator_count") or (1 if step_cnt > 0 else 0))
            util_pct = round((ct / takt) * 100.0, 1) if takt > 0 else 0.0
            metrics[pid] = {
                "pitch_id": pid,
                "pitch_number": str(prow["pitch_number"] or ""),
                "pitch_name": str(prow["pitch_name"] or ""),
                "pitch_type": str(prow["pitch_type"] or "Pitch"),
                "pitch_status": str(prow["pitch_status"] or "Active"),
                "feeds_into_pitch_id": str(prow["feeds_into_pitch_id"] or ""),
                "area_id": str(prow["area_id"] or ""),
                "area_name": str(prow["area_name"] or ""),
                "section_id": str(prow["section_id"] or ""),
                "target_takt_sec": round(takt, 1),
                "cycle_time_sec": round(ct, 1),
                "utilization_pct": util_pct,
                "step_count": step_cnt,
                "operator_count": op_cnt,
                "steps": steps_by_pitch.get(pid, []),
            }
        return metrics


def get_pitch_layout_footprints(project_id: str, scenario_id: str) -> list[dict[str, Any]]:
    """Return placed layout shapes linked to pitches in this scenario, providing real-world coordinates for the Pin Map."""
    store = _store_module()
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT
                s.id AS shape_id,
                p.id AS pitch_id,
                s.layer_id,
                s.shape_type,
                s.label,
                s.z_index,
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
                r.notes AS revision_notes,
                r.image_path,
                r.cad_file_path,
                r.cad_file_name,
                r.cad_file_size_bytes,
                r.cad_web_url,
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
            LEFT JOIN layout_layers ly ON ly.id = s.layer_id
            JOIN yamazumi_pitches p_src ON p_src.id = s.pitch_id
            JOIN yamazumi_areas a_src ON a_src.id = p_src.area_id
            JOIN yamazumi_pitches p ON (
                p.id = p_src.id
                OR (a_src.scenario_id != ? AND LOWER(p.pitch_number) = LOWER(p_src.pitch_number))
            )
            JOIN yamazumi_areas a ON a.id = p.area_id AND a.scenario_id = ?
                AND (
                    p.id = p_src.id
                    OR (a.section_id IS NOT NULL AND a.section_id != '' AND a.section_id = a_src.section_id)
                    OR LOWER(a.name) = LOWER(a_src.name)
                )
            WHERE l.project_id = ?
              AND r.revision_number = (
                  SELECT MAX(r2.revision_number)
                  FROM layout_revisions r2
                  WHERE r2.layout_id = l.id
              )
              AND COALESCE(ly.visible, 1) = 1
            ORDER BY COALESCE(ly.z_index, 0), COALESCE(s.z_index, 0), s.x, s.y
            """,
            (scenario_id, scenario_id, project_id),
        ).fetchall()
        return [dict(r) for r in rows]



def ensure_default_pin_map_page(
    project_id: str,
    editor_name: str = "Workspace",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ensure at least one layout ('Page 1') and one scaled blank revision (200 x 100 ft) exist for the project."""
    effective_editor = _text(editor_name) or "Workspace"
    layouts = list_layouts(project_id)
    if not layouts:
        created_layout = create_layout(
            project_id=project_id,
            name="Page 1",
            description="Pin Map & Scaled Line Layout",
            editor_name=effective_editor,
        )
    else:
        created_layout = layouts[0]

    revs = list_layout_revisions(str(created_layout["id"]))
    if not revs:
        created_rev = create_blank_scaled_revision(
            project_id=project_id,
            layout_id=str(created_layout["id"]),
            width_value=200.0,
            height_value=100.0,
            unit="feet",
            notes="Blank scaled grid canvas",
            editor_name=effective_editor,
        )
        rev = get_layout_revision(str(created_rev["id"])) or created_rev
    else:
        rev = get_layout_revision(str(revs[0]["id"])) or revs[0]

    layout = get_layout(project_id, str(created_layout["id"])) or created_layout
    return layout, rev


def update_revision_background_from_data_url(
    project_id: str,
    revision_id: str,
    data_url: str,
    editor_name: str = "Workspace",
) -> dict[str, Any]:
    """Replace or clear (if data_url=='') the background floorplan image on an existing revision."""
    import base64

    store = _store_module()
    editor = _require_editor(_text(editor_name) or "Workspace")
    with store.connection() as conn:
        rev = conn.execute(
            """
            SELECT r.*, p.name AS layout_name
            FROM layout_revisions r
            JOIN layout_plans p ON p.id = r.layout_id
            WHERE r.id = ? AND p.project_id = ?
            """,
            (revision_id, project_id),
        ).fetchone()
        if not rev:
            raise ValueError("Layout revision not found.")

        old_img_path = str(rev["image_path"] or "")
        old_w_px = float(rev["image_width_px"] or 0.0)
        old_h_px = float(rev["image_height_px"] or 0.0)
        w_val = float(rev["width_value"] or 200.0)
        h_val = float(rev["height_value"] or 100.0)
        unit_str = _text(rev["unit"] or "feet").lower()
        if unit_str not in LAYOUT_UNITS:
            unit_str = "feet"
        layout_id = str(rev["layout_id"])

        store.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        clean_data = _text(data_url)
        if not clean_data:
            aspect = max(0.25, min(4.0, w_val / max(0.01, h_val)))
            img_h_px = 1800
            img_w_px = max(1200, min(4800, int(round(img_h_px * aspect))))
            img = Image.new("RGB", (img_w_px, img_h_px), (248, 250, 252))
            target_path = store.UPLOAD_DIR / f"blank_scaled_canvas_{layout_id}_{uuid4()}.png"
            img.save(target_path, "PNG")
            new_h_val = h_val
            new_scale_h_in = to_canonical_inches(new_h_val, unit_str)
            action_label = "Clear background image (blank scaled grid)"
            new_notes = "Blank scaled grid canvas"
        else:
            if "," in clean_data:
                _, b64_part = clean_data.split(",", 1)
            else:
                b64_part = clean_data
            try:
                raw_bytes = base64.b64decode(b64_part)
                with Image.open(BytesIO(raw_bytes)) as loaded_img:
                    loaded_img = ImageOps.exif_transpose(loaded_img).convert("RGB")
                    img_w_px, img_h_px = loaded_img.size
                    if img_w_px <= 0 or img_h_px <= 0:
                        raise ValueError("Uploaded image has invalid dimensions.")
                    target_path = store.UPLOAD_DIR / f"layout_{layout_id}_{uuid4()}.png"
                    loaded_img.save(target_path, "PNG")
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError("Invalid or unsupported floorplan image file.") from exc
            new_h_val = round(max(1.0, w_val * (img_h_px / max(1, img_w_px))), 2)
            new_scale_h_in = to_canonical_inches(new_h_val, unit_str)
            action_label = "Update floorplan background image"
            new_notes = "Uploaded floorplan background"

        if old_w_px > 0 and old_h_px > 0 and (img_w_px != int(old_w_px) or img_h_px != int(old_h_px)):
            sx = float(img_w_px) / old_w_px
            sy = float(img_h_px) / old_h_px
            conn.execute(
                """
                UPDATE layout_shapes
                SET x = ROUND(x * ?, 2),
                    y = ROUND(y * ?, 2),
                    width = MAX(4.0, ROUND(width * ?, 2)),
                    height = MAX(4.0, ROUND(height * ?, 2))
                WHERE revision_id = ?
                """,
                (sx, sy, sx, sy, revision_id),
            )
            conn_rows = conn.execute(
                "SELECT id, style_json FROM layout_shapes WHERE revision_id = ? AND shape_type = 'connector'",
                (revision_id,),
            ).fetchall()
            for crow in conn_rows:
                try:
                    st_dict = json.loads(str(crow["style_json"] or "{}"))
                    if isinstance(st_dict, dict) and any(k in st_dict for k in ("x1", "y1", "x2", "y2")):
                        for kx in ("x1", "x2"):
                            if kx in st_dict and st_dict[kx] is not None:
                                st_dict[kx] = round(float(st_dict[kx]) * sx, 2)
                        for ky in ("y1", "y2"):
                            if ky in st_dict and st_dict[ky] is not None:
                                st_dict[ky] = round(float(st_dict[ky]) * sy, 2)
                        conn.execute(
                            "UPDATE layout_shapes SET style_json = ? WHERE id = ?",
                            (json.dumps(st_dict, sort_keys=True), str(crow["id"])),
                        )
                except Exception:
                    pass

        conn.execute(
            """
            UPDATE layout_revisions
            SET image_path = ?, image_width_px = ?, image_height_px = ?,
                height_value = ?, scale_height_in = ?, notes = ?
            WHERE id = ?
            """,
            (
                str(target_path),
                img_w_px,
                img_h_px,
                new_h_val,
                new_scale_h_in,
                new_notes,
                revision_id,
            ),
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            action_label,
            1,
            editor,
            {
                "layout_id": layout_id,
                "revision_number": int(rev["revision_number"]),
                "resolution": f"{img_w_px}x{img_h_px}",
            },
            _conn=conn,
        )

    if old_img_path and old_img_path != str(target_path):
        _remove_owned_upload(old_img_path)

    return get_layout_revision(revision_id) or {}


# --- Saved Custom Shapes / Stencils Operations ---


def list_layout_custom_stencils(project_id: str) -> list[dict[str, Any]]:
    """Return all user-saved custom shapes/stencils for a project."""
    store = _store_module()
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, name, category, stencil_json, created_at, updated_at
            FROM layout_custom_stencils
            WHERE project_id = ?
            ORDER BY name COLLATE NOCASE ASC, created_at ASC
            """,
            (project_id,),
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw_json = item.get("stencil_json") or "{}"
        try:
            parsed = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            if not isinstance(parsed, dict):
                parsed = {}
        except Exception:
            parsed = {}
        item["stencil_data"] = parsed
        results.append(item)
    return results


def save_layout_custom_stencil(
    project_id: str,
    name: str,
    stencil_data: dict[str, Any] | str,
    editor_name: str,
    *,
    category: str = "Saved Shapes",
    stencil_id: str | None = None,
) -> dict[str, Any]:
    """Create or update a saved custom composite shape/stencil for a project."""
    store = _store_module()
    editor = _require_editor(editor_name)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Custom shape name is required.")
    clean_cat = (category or "Saved Shapes").strip() or "Saved Shapes"
    if isinstance(stencil_data, str):
        try:
            parsed_obj = json.loads(stencil_data)
        except Exception as exc:
            raise ValueError("Invalid custom shape definition JSON.") from exc
    elif isinstance(stencil_data, dict):
        parsed_obj = stencil_data
    else:
        raise ValueError("Invalid custom shape definition.")

    serialized = json.dumps(parsed_obj, ensure_ascii=False)
    now = store.now_iso()
    target_id = (stencil_id or "").strip() or str(uuid4())

    with store.connection() as conn:
        existing = conn.execute(
            "SELECT id FROM layout_custom_stencils WHERE id = ? AND project_id = ?",
            (target_id, project_id),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE layout_custom_stencils
                SET name = ?, category = ?, stencil_json = ?, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (clean_name, clean_cat, serialized, now, target_id, project_id),
            )
            action_label = "Update custom Pin Map shape"
        else:
            conn.execute(
                """
                INSERT INTO layout_custom_stencils (
                    id, project_id, name, category, stencil_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (target_id, project_id, clean_name, clean_cat, serialized, now, now),
            )
            action_label = "Save custom Pin Map shape"

        store.record_audit_event(
            project_id,
            "Layouts",
            action_label,
            1,
            editor,
            {"stencil_id": target_id, "name": clean_name, "category": clean_cat},
            _conn=conn,
        )

    return {
        "id": target_id,
        "project_id": project_id,
        "name": clean_name,
        "category": clean_cat,
        "stencil_json": serialized,
        "stencil_data": parsed_obj,
        "updated_at": now,
    }


def delete_layout_custom_stencil(
    project_id: str,
    stencil_id: str,
    editor_name: str,
) -> bool:
    """Delete a saved custom shape/stencil from a project."""
    store = _store_module()
    editor = _require_editor(editor_name)
    clean_id = (stencil_id or "").strip()
    if not clean_id:
        return False
    with store.connection() as conn:
        row = conn.execute(
            "SELECT id, name FROM layout_custom_stencils WHERE id = ? AND project_id = ?",
            (clean_id, project_id),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "DELETE FROM layout_custom_stencils WHERE id = ? AND project_id = ?",
            (clean_id, project_id),
        )
        store.record_audit_event(
            project_id,
            "Layouts",
            "Delete custom Pin Map shape",
            1,
            editor,
            {"stencil_id": clean_id, "name": str(row["name"])},
            _conn=conn,
        )
    return True


__domain_exports__ = [
    "LAYOUT_UNITS",
    "UNIT_TO_INCHES",
    "DEFAULT_ENGINEERING_LAYERS",
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
    "SUPPORTED_LAYOUT_CAD_EXTENSIONS",
    "MAX_LAYOUT_CAD_FILE_SIZE_BYTES",
    "MAX_LAYOUT_CAD_FILE_SIZE_MB",
    "get_pdf_page_count",
    "render_pdf_page_to_image",
    "render_dxf_to_image",
    "apply_image_orientation",
    "apply_image_crop",
    "auto_detect_whitespace_crop",
    "annotate_preview_with_dimensions",
    "load_and_orient_layout_preview",
    "create_layout_revision",
    "create_blank_scaled_revision",
    "ensure_default_pin_map_page",
    "update_revision_background_from_data_url",
    "update_layout_revision_scale",
    "calibrate_revision_scale_by_reference",
    "delete_layout_revision",
    "attach_layout_revision_cad",
    "remove_layout_revision_cad",
    "ensure_default_layers_for_revision",
    "list_layout_layers",
    "create_layout_layer",
    "update_layout_layer",
    "delete_layout_layer",
    "reorder_layout_layers",
    "list_layout_shapes",
    "save_layout_shapes",
    "import_shapes_from_revision",
    "get_section_pitch_standards",
    "set_section_pitch_standard",
    "list_project_yamazumi_pitches",
    "get_scenario_pitch_metrics_for_pin_map",
    "get_pitch_layout_footprints",
    "list_layout_custom_stencils",
    "save_layout_custom_stencil",
    "delete_layout_custom_stencil",
]

