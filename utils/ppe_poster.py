"""PPE Poster Generator (11x17 Landscape) HTML renderer and asset helpers."""

from __future__ import annotations

import base64
import html
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import streamlit as st

import hashlib
import streamlit.components.v1 as components

_PPE_POSTER_HOT_RELOAD_REV = 9

from utils.safety_store import (
    normalize_ppe_name,
    EHS_LOGO_PATH,
    PPE_CATALOG,
    PPE_ICONS_DIR,
    STANDARD_BASELINE_PPE,
    get_ppe_catalog_item,
    resolve_pitch_ppe_rollup,
)


@lru_cache(maxsize=64)
def _file_to_data_uri(path_str: str) -> str:
    """Read an image file and return a base64 data URI, cached in memory."""
    if not path_str:
        return ""
    p = Path(path_str)
    if not p.is_file():
        return ""
    try:
        raw = p.read_bytes()
    except OSError:
        return ""
    ext = p.suffix.lower().lstrip(".")
    mime = "image/png" if ext == "png" else f"image/{ext or 'png'}"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def get_ppe_icon_data_uri(ppe_name: str) -> str:
    """Return a base64 data URI for a catalog PPE item's icon."""
    item = get_ppe_catalog_item(ppe_name)
    if not item:
        return ""
    img_path = item.get("image_path") or ""
    return _file_to_data_uri(str(img_path))


def get_jsa_icon_data_uri(ppe_name: str) -> str:
    """Return a base64 data URI for a catalog PPE item's JSA icon (falling back to standard PPE icon)."""
    item = get_ppe_catalog_item(ppe_name)
    if not item:
        return ""
    jsa_path = str(item.get("jsa_image_path") or "").strip()
    if jsa_path and Path(jsa_path).is_file():
        return _file_to_data_uri(jsa_path)
    img_path = str(item.get("image_path") or "").strip()
    return _file_to_data_uri(img_path)


def _resolve_media_data_uri(raw_path: str) -> str:
    """Resolve an uploaded PAAG visual aid path or URL into an embeddable image src."""
    cleaned = str(raw_path or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith(("http://", "https://", "data:")):
        return cleaned
    p = Path(cleaned)
    if not p.is_file():
        from utils.db_core import ROOT, resolve_upload_path
        cand = Path(ROOT) / cleaned
        if cand.is_file():
            p = cand
        else:
            try:
                resolved = resolve_upload_path(cleaned)
                if resolved and Path(resolved).is_file():
                    p = Path(resolved)
            except Exception:
                return ""
    return _file_to_data_uri(str(p)) if p.is_file() else ""


def get_ehs_logo_data_uri() -> str:
    """Return a base64 data URI for the EHS&S logo."""
    return _file_to_data_uri(str(EHS_LOGO_PATH))



PPTX_JS_HELPERS = r"""
const _CRC32_TABLE = (() => {
  const tbl = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) {
      c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    }
    tbl[i] = c >>> 0;
  }
  return tbl;
})();

function _crc32Bytes(u8) {
  let crc = 0xFFFFFFFF;
  for (let i = 0; i < u8.length; i++) {
    crc = _CRC32_TABLE[(crc ^ u8[i]) & 0xFF] ^ (crc >>> 8);
  }
  return (crc ^ 0xFFFFFFFF) >>> 0;
}

function _buildZipBlob(entries, mimeType) {
  const enc = new TextEncoder();
  const prepared = entries.map(e => {
    const nameBytes = enc.encode(e.path);
    const dataBytes = (e.data instanceof Uint8Array) ? e.data : enc.encode(String(e.data || ""));
    const crc = _crc32Bytes(dataBytes);
    return { nameBytes, dataBytes, crc };
  });

  let localSize = 0;
  let centralSize = 0;
  prepared.forEach(p => {
    localSize += 30 + p.nameBytes.length + p.dataBytes.length;
    centralSize += 46 + p.nameBytes.length;
  });

  const totalSize = localSize + centralSize + 22;
  const out = new Uint8Array(totalSize);
  const view = new DataView(out.buffer);

  let offset = 0;
  const offsets = [];

  prepared.forEach(p => {
    offsets.push(offset);
    view.setUint32(offset, 0x04034b50, true);
    view.setUint16(offset + 4, 20, true);
    view.setUint16(offset + 6, 0x0800, true);
    view.setUint16(offset + 8, 0, true);
    view.setUint16(offset + 10, 0, true);
    view.setUint16(offset + 12, 0x21, true);
    view.setUint32(offset + 14, p.crc, true);
    view.setUint32(offset + 18, p.dataBytes.length, true);
    view.setUint32(offset + 22, p.dataBytes.length, true);
    view.setUint16(offset + 26, p.nameBytes.length, true);
    view.setUint16(offset + 28, 0, true);
    out.set(p.nameBytes, offset + 30);
    out.set(p.dataBytes, offset + 30 + p.nameBytes.length);
    offset += 30 + p.nameBytes.length + p.dataBytes.length;
  });

  const centralStart = offset;
  prepared.forEach((p, idx) => {
    view.setUint32(offset, 0x02014b50, true);
    view.setUint16(offset + 4, 20, true);
    view.setUint16(offset + 6, 20, true);
    view.setUint16(offset + 8, 0x0800, true);
    view.setUint16(offset + 10, 0, true);
    view.setUint16(offset + 12, 0, true);
    view.setUint16(offset + 14, 0x21, true);
    view.setUint32(offset + 16, p.crc, true);
    view.setUint32(offset + 20, p.dataBytes.length, true);
    view.setUint32(offset + 24, p.dataBytes.length, true);
    view.setUint16(offset + 28, p.nameBytes.length, true);
    view.setUint16(offset + 30, 0, true);
    view.setUint16(offset + 32, 0, true);
    view.setUint16(offset + 34, 0, true);
    view.setUint16(offset + 36, 0, true);
    view.setUint32(offset + 38, 0, true);
    view.setUint32(offset + 42, offsets[idx], true);
    out.set(p.nameBytes, offset + 46);
    offset += 46 + p.nameBytes.length;
  });

  const centralLen = offset - centralStart;
  view.setUint32(offset, 0x06054b50, true);
  view.setUint16(offset + 4, 0, true);
  view.setUint16(offset + 6, 0, true);
  view.setUint16(offset + 8, prepared.length, true);
  view.setUint16(offset + 10, prepared.length, true);
  view.setUint32(offset + 12, centralLen, true);
  view.setUint32(offset + 16, centralStart, true);
  view.setUint16(offset + 20, 0, true);

  return new Blob([out], { type: mimeType || "application/vnd.openxmlformats-officedocument.presentationml.presentation" });
}

function _xmlEsc(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function _dataUriToMediaInfo(uri) {
  if (!uri || typeof uri !== "string" || !uri.startsWith("data:image/")) return null;
  const commaIdx = uri.indexOf(",");
  if (commaIdx < 0) return null;
  const header = uri.slice(0, commaIdx);
  const b64 = uri.slice(commaIdx + 1);
  let ext = "png";
  let mime = "image/png";
  if (header.includes("image/jpeg") || header.includes("image/jpg")) {
    ext = "jpeg";
    mime = "image/jpeg";
  }
  try {
    const binStr = atob(b64);
    const bytes = new Uint8Array(binStr.length);
    for (let i = 0; i < binStr.length; i++) {
      bytes[i] = binStr.charCodeAt(i);
    }
    return { ext, mime, bytes };
  } catch (e) {
    return null;
  }
}

function _buildEditablePptxBlob(spec) {
  const slideW = Math.round(spec.slideW || 7772400);
  const slideH = Math.round(spec.slideH || 10058400);
  const shapes = spec.shapes || [];
  const images = spec.images || [];
  const tables = spec.tables || [];

  let nextId = 2;
  const shapeXmlList = [];
  const slideRels = [
    `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>`
  ];
  const mediaFiles = [];

  shapes.forEach((sh, idx) => {
    const id = nextId++;
    const x = Math.round(sh.x || 0);
    const y = Math.round(sh.y || 0);
    const w = Math.max(1000, Math.round(sh.w || 100000));
    const h = Math.max(1000, Math.round(sh.h || 100000));
    const fillXml = sh.fill
      ? `<a:solidFill><a:srgbClr val="${sh.fill.replace('#','')}"/></a:solidFill>`
      : `<a:noFill/>`;
    let lnXml = `<a:ln><a:noFill/></a:ln>`;
    if (sh.lineColor) {
      const lw = Math.round((sh.lineWidthPt || 1) * 12700);
      const dashXml = sh.lineDash ? `<a:prstDash val="${sh.lineDash}"/>` : "";
      lnXml = `<a:ln w="${lw}"><a:solidFill><a:srgbClr val="${sh.lineColor.replace('#','')}"/></a:solidFill>${dashXml}</a:ln>`;
    }
    const valign = sh.valign || "ctr";
    const align = sh.align || "l";
    const lIns = Math.round(sh.lIns != null ? sh.lIns : 68580);
    const rIns = Math.round(sh.rIns != null ? sh.rIns : 68580);
    const tIns = Math.round(sh.tIns != null ? sh.tIns : 36576);
    const bIns = Math.round(sh.bIns != null ? sh.bIns : 36576);
    const fontSz = Math.round((sh.fontSizePt || 12) * 100);
    const boldAttr = sh.bold ? ` b="1"` : "";
    const italicAttr = sh.italic ? ` i="1"` : "";
    const colorHex = (sh.color || "000000").replace("#", "");
    const rawLines = String(sh.text != null ? sh.text : "").split(/\r?\n/);
    const parasXml = rawLines.map(line =>
      `<a:p><a:pPr algn="${align}"/><a:r><a:rPr lang="en-US" sz="${fontSz}"${boldAttr}${italicAttr} dirty="0"><a:solidFill><a:srgbClr val="${colorHex}"/></a:solidFill><a:latin typeface="Arial"/></a:rPr><a:t>${_xmlEsc(line)}</a:t></a:r></a:p>`
    ).join("");

    shapeXmlList.push(
      `<p:sp>` +
        `<p:nvSpPr>` +
          `<p:cNvPr id="${id}" name="${_xmlEsc(sh.name || ('Shape ' + idx))}"/>` +
          `<p:cNvSpPr txBox="1"/>` +
          `<p:nvPr/>` +
        `</p:nvSpPr>` +
        `<p:spPr>` +
          `<a:xfrm><a:off x="${x}" y="${y}"/><a:ext cx="${w}" cy="${h}"/></a:xfrm>` +
          `<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>` +
          fillXml +
          lnXml +
        `</p:spPr>` +
        `<p:txBody>` +
          `<a:bodyPr wrap="square" lIns="${lIns}" tIns="${tIns}" rIns="${rIns}" bIns="${bIns}" anchor="${valign}"/>` +
          `<a:lstStyle/>` +
          parasXml +
        `</p:txBody>` +
      `</p:sp>`
    );
  });

  images.forEach((im, idx) => {
    const media = _dataUriToMediaInfo(im.dataUri);
    if (!media) return;
    const id = nextId++;
    const imgNum = mediaFiles.length + 1;
    const rId = `rIdImg${imgNum}`;
    const fileName = `image${imgNum}.${media.ext}`;
    mediaFiles.push({ path: `ppt/media/${fileName}`, data: media.bytes });
    slideRels.push(
      `<Relationship Id="${rId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/${fileName}"/>`
    );
    const x = Math.round(im.x || 0);
    const y = Math.round(im.y || 0);
    const w = Math.max(1000, Math.round(im.w || 400000));
    const h = Math.max(1000, Math.round(im.h || 400000));
    shapeXmlList.push(
      `<p:pic>` +
        `<p:nvPicPr>` +
          `<p:cNvPr id="${id}" name="${_xmlEsc(im.name || ('Picture ' + idx))}"/>` +
          `<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>` +
          `<p:nvPr/>` +
        `</p:nvPicPr>` +
        `<p:blipFill>` +
          `<a:blip r:embed="${rId}"/>` +
          `<a:stretch><a:fillRect/></a:stretch>` +
        `</p:blipFill>` +
        `<p:spPr>` +
          `<a:xfrm><a:off x="${x}" y="${y}"/><a:ext cx="${w}" cy="${h}"/></a:xfrm>` +
          `<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>` +
        `</p:spPr>` +
      `</p:pic>`
    );
  });

  tables.forEach((tbl, idx) => {
    const id = nextId++;
    const x = Math.round(tbl.x || 0);
    const y = Math.round(tbl.y || 0);
    const w = Math.max(10000, Math.round(tbl.w || 5000000));
    const h = Math.max(10000, Math.round(tbl.h || 2000000));
    const gridColsXml = (tbl.colWidths || []).map(cw => `<a:gridCol w="${Math.round(cw)}"/>`).join("");
    const rowsXml = (tbl.rows || []).map(row => {
      const rh = Math.max(180000, Math.round(row.height || 300000));
      const cellsXml = (row.cells || []).map(cell => {
        const fontSz = Math.round((cell.fontSizePt || (row.isHeader ? 10 : 9.5)) * 100);
        const boldAttr = (cell.bold || row.isHeader) ? ` b="1"` : "";
        const colorHex = (cell.color || "000000").replace("#", "");
        const fillHex = (cell.fill || row.fill || "FFFFFF").replace("#", "");
        const align = cell.align || "l";
        const borderW = row.isHeader ? 15875 : 12700;
        const borderXml =
          `<a:lnL w="${borderW}" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:lnL>` +
          `<a:lnR w="${borderW}" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:lnR>` +
          `<a:lnT w="${borderW}" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:lnT>` +
          `<a:lnB w="${borderW}" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:lnB>`;
        const lines = String(cell.text != null ? cell.text : "").split(/\r?\n/);
        const cellParas = lines.map(ln =>
          `<a:p><a:pPr algn="${align}"/><a:r><a:rPr lang="en-US" sz="${fontSz}"${boldAttr} dirty="0"><a:solidFill><a:srgbClr val="${colorHex}"/></a:solidFill><a:latin typeface="Arial"/></a:rPr><a:t>${_xmlEsc(ln)}</a:t></a:r></a:p>`
        ).join("");
        return (
          `<a:tc>` +
            `<a:txBody><a:bodyPr/><a:lstStyle/>${cellParas}</a:txBody>` +
            `<a:tcPr marL="68580" marR="68580" marT="36576" marB="36576" anchor="t">` +
              borderXml +
              `<a:solidFill><a:srgbClr val="${fillHex}"/></a:solidFill>` +
            `</a:tcPr>` +
          `</a:tc>`
        );
      }).join("");
      return `<a:tr h="${rh}">${cellsXml}</a:tr>`;
    }).join("");

    shapeXmlList.push(
      `<p:graphicFrame>` +
        `<p:nvGraphicFramePr>` +
          `<p:cNvPr id="${id}" name="${_xmlEsc(tbl.name || ('Table ' + idx))}"/>` +
          `<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>` +
          `<p:nvPr/>` +
        `</p:nvGraphicFramePr>` +
        `<p:xfrm><a:off x="${x}" y="${y}"/><a:ext cx="${w}" cy="${h}"/></p:xfrm>` +
        `<a:graphic>` +
          `<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">` +
            `<a:tbl>` +
              `<a:tblPr firstRow="1" bandRow="0"/>` +
              `<a:tblGrid>${gridColsXml}</a:tblGrid>` +
              rowsXml +
            `</a:tbl>` +
          `</a:graphicData>` +
        `</a:graphic>` +
      `</p:graphicFrame>`
    );
  });

  const contentTypesXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
      `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>` +
      `<Default Extension="xml" ContentType="application/xml"/>` +
      `<Default Extension="png" ContentType="image/png"/>` +
      `<Default Extension="jpeg" ContentType="image/jpeg"/>` +
      `<Default Extension="jpg" ContentType="image/jpeg"/>` +
      `<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>` +
      `<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>` +
      `<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>` +
      `<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>` +
      `<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>` +
      `<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>` +
      `<Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"/>` +
      `<Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/>` +
    `</Types>`;

  const rootRelsXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
      `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>` +
    `</Relationships>`;

  const presentationXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">` +
      `<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>` +
      `<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>` +
      `<p:sldSz cx="${slideW}" cy="${slideH}" type="custom"/>` +
      `<p:notesSz cx="6858000" cy="9144000"/>` +
      `<p:defaultTextStyle><a:defPPr/><a:lvl1pPr algn="l"><a:defRPr sz="1200"/></a:lvl1pPr></p:defaultTextStyle>` +
    `</p:presentation>`;

  const presentationRelsXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
      `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>` +
      `<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>` +
      `<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/presProps" Target="presProps.xml"/>` +
      `<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/viewProps" Target="viewProps.xml"/>` +
      `<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>` +
      `<Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/tableStyles" Target="tableStyles.xml"/>` +
    `</Relationships>`;

  const presPropsXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<p:presProps xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>`;

  const viewPropsXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<p:viewProps xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">` +
      `<p:normalViewPr><p:restoredLeft sz="15620"/><p:restoredTop sz="94660"/></p:normalViewPr>` +
    `</p:viewProps>`;

  const tableStylesXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>`;

  const themeXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="PAAG Theme">` +
      `<a:themeElements>` +
        `<a:clrScheme name="PAAG">` +
          `<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>` +
          `<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>` +
          `<a:dk2><a:srgbClr val="1F2D3A"/></a:dk2>` +
          `<a:lt2><a:srgbClr val="F5F7FA"/></a:lt2>` +
          `<a:accent1><a:srgbClr val="008A5E"/></a:accent1>` +
          `<a:accent2><a:srgbClr val="2563EB"/></a:accent2>` +
          `<a:accent3><a:srgbClr val="6F42C1"/></a:accent3>` +
          `<a:accent4><a:srgbClr val="D97706"/></a:accent4>` +
          `<a:accent5><a:srgbClr val="0284C7"/></a:accent5>` +
          `<a:accent6><a:srgbClr val="16A34A"/></a:accent6>` +
          `<a:hlink><a:srgbClr val="2563EB"/></a:hlink>` +
          `<a:folHlink><a:srgbClr val="6F42C1"/></a:folHlink>` +
        `</a:clrScheme>` +
        `<a:fontScheme name="PAAG">` +
          `<a:majorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>` +
          `<a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>` +
        `</a:fontScheme>` +
        `<a:fmtScheme name="PAAG">` +
          `<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>` +
          `<a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="25400"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="38100"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>` +
          `<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>` +
          `<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>` +
        `</a:fmtScheme>` +
      `</a:themeElements>` +
      `<a:objectDefaults/>` +
      `<a:extraClrSchemeLst/>` +
    `</a:theme>`;

  const slideMasterXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">` +
      `<p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>` +
      `<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>` +
      `<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>` +
    `</p:sldMaster>`;

  const slideMasterRelsXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
      `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>` +
      `<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>` +
    `</Relationships>`;

  const slideLayoutXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">` +
      `<p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>` +
      `<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>` +
    `</p:sldLayout>`;

  const slideLayoutRelsXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
      `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>` +
    `</Relationships>`;

  const slide1Xml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">` +
      `<p:cSld>` +
        `<p:spTree>` +
          `<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>` +
          `<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>` +
          shapeXmlList.join("") +
        `</p:spTree>` +
      `</p:cSld>` +
      `<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>` +
    `</p:sld>`;

  const slide1RelsXml =
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
      slideRels.join("") +
    `</Relationships>`;

  const files = [
    { path: "[Content_Types].xml", data: contentTypesXml },
    { path: "_rels/.rels", data: rootRelsXml },
    { path: "ppt/presentation.xml", data: presentationXml },
    { path: "ppt/_rels/presentation.xml.rels", data: presentationRelsXml },
    { path: "ppt/presProps.xml", data: presPropsXml },
    { path: "ppt/viewProps.xml", data: viewPropsXml },
    { path: "ppt/tableStyles.xml", data: tableStylesXml },
    { path: "ppt/theme/theme1.xml", data: themeXml },
    { path: "ppt/slideMasters/slideMaster1.xml", data: slideMasterXml },
    { path: "ppt/slideMasters/_rels/slideMaster1.xml.rels", data: slideMasterRelsXml },
    { path: "ppt/slideLayouts/slideLayout1.xml", data: slideLayoutXml },
    { path: "ppt/slideLayouts/_rels/slideLayout1.xml.rels", data: slideLayoutRelsXml },
    { path: "ppt/slides/slide1.xml", data: slide1Xml },
    { path: "ppt/slides/_rels/slide1.xml.rels", data: slide1RelsXml },
    ...mediaFiles
  ];

  return _buildZipBlob(files, "application/vnd.openxmlformats-officedocument.presentationml.presentation");
}
function exportJsaPptx(fileBase) {
  const plantCode = (document.getElementById("jsaPlantCode").textContent || "").trim();
  const jobTitle = (document.getElementById("jsaJobTitle").textContent || "").trim();
  const notice = (document.getElementById("jsaImportantNotice").textContent || "").trim();
  const logoImg = document.querySelector(".jsa-logo-box img");
  const logoSrc = logoImg ? logoImg.src : "";
  const effective = resolveEffectivePPEList();
  const rows = collectCurrentStepRows();

  const shapes = [
    { name: "Outer Border", x: 137160, y: 137160, w: 7498080, h: 9784080, text: "", fill: "00965E", lineColor: "000000", lineWidthPt: 2 },
    { name: "Inner Sheet", x: 342900, y: 342900, w: 7086600, h: 9372600, text: "", fill: "FFFFFF", lineColor: "000000", lineWidthPt: 1.5 },
    { name: "Plant Code", x: 457200, y: 434340, w: 1280160, h: 685800, text: plantCode, fontSizePt: 22, bold: true, color: "000000", align: "l", valign: "ctr" },
    { name: "Main Heading", x: 1783080, y: 411480, w: 4206240, h: 342900, text: "JOB SAFETY ANALYSIS", fontSizePt: 20, bold: true, color: "000000", align: "ctr", valign: "ctr" },
    { name: "Job Title", x: 2057400, y: 765810, w: 3657600, h: 297180, text: jobTitle, fill: "E5E7EB", lineColor: "222222", lineWidthPt: 1.25, fontSizePt: 13, bold: true, color: "000000", align: "ctr", valign: "ctr" },
    { name: "Operation Label", x: 2057400, y: 1066800, w: 3657600, h: 205740, text: "Operation", fontSizePt: 11.5, bold: true, color: "000000", align: "ctr", valign: "ctr" },
    { name: "Important Header", x: 457200, y: 1303020, w: 6858000, h: 251460, text: "IMPORTANT", fill: "10C486", lineColor: "000000", lineWidthPt: 1.25, fontSizePt: 12, bold: true, color: "000000", align: "ctr", valign: "ctr" },
    { name: "Important Notice", x: 457200, y: 1554480, w: 6858000, h: 480060, text: notice, fill: "FFFFFF", lineColor: "000000", lineWidthPt: 1.25, fontSizePt: 10, bold: true, color: "000000", align: "l", valign: "ctr" }
  ];

  const images = [];
  if (logoSrc && logoSrc.startsWith("data:image/")) {
    images.push({ name: "EHS Logo", x: 6126480, y: 457200, w: 1143000, h: 640080, dataUri: logoSrc });
  }

  const vzX = 457200, vzY = 2103120, vzW = 6858000, vzH = 1325880;
  if (effective.length === 0) {
    shapes.push({
      name: "PPE Zone Placeholder",
      x: vzX, y: vzY, w: vzW, h: vzH,
      text: "Add PPE Icons",
      fill: "FFFFFF", lineColor: "CBD5E1", lineDash: "dash", lineWidthPt: 1,
      fontSizePt: 16, bold: false, color: "64748B", align: "ctr", valign: "ctr"
    });
  } else {
    shapes.push({
      name: "PPE Zone Box",
      x: vzX, y: vzY, w: vzW, h: vzH,
      text: "", fill: "FFFFFF", lineColor: "CBD5E1", lineDash: "dash", lineWidthPt: 1
    });
    const cols = Math.min(6, Math.max(1, effective.length));
    const rowsCnt = Math.ceil(effective.length / cols);
    const cellW = Math.floor((vzW - 182880) / cols);
    const cellH = Math.floor((vzH - 137160) / rowsCnt);
    effective.forEach((item, idx) => {
      const r = Math.floor(idx / cols);
      const c = idx % cols;
      const cx = vzX + 91440 + c * cellW;
      const cy = vzY + 68580 + r * cellH;
      const src = (typeof useJsaIcons !== "undefined" && useJsaIcons && item.jsa_image) ? item.jsa_image : item.card_image;
      if (src && src.startsWith("data:image/")) {
        const imgW = Math.min(cellW - 91440, 1051560);
        const imgH = Math.min(cellH - 45720, 1051560);
        images.push({
          name: item.name,
          x: cx + Math.floor((cellW - imgW) / 2),
          y: cy + Math.floor((cellH - imgH) / 2),
          w: imgW,
          h: imgH,
          dataUri: src
        });
      } else {
        shapes.push({
          name: item.name,
          x: cx + 22860, y: cy + 22860, w: cellW - 45720, h: cellH - 45720,
          text: item.name, fill: "F8FAFC", lineColor: "CBD5E1", lineWidthPt: 1,
          fontSizePt: 9, bold: true, color: "0F172A", align: "ctr", valign: "ctr"
        });
      }
    });
  }

  const tableRows = [
    {
      height: 300000,
      isHeader: true,
      fill: "FFFFFF",
      cells: [
        { text: "JOB STEPS", bold: true, fontSizePt: 10 },
        { text: "POTENTIAL ERRORS / HAZARDS", bold: true, fontSizePt: 10 },
        { text: "ACTION", bold: true, fontSizePt: 10 }
      ]
    }
  ];
  const availTableH = 5250000;
  const bodyRowH = Math.max(240000, Math.min(420000, Math.floor(availTableH / Math.max(1, rows.length))));
  rows.forEach(r => {
    const rowFill = r.is_auto_ppe_row ? "F8FAFC" : "FFFFFF";
    tableRows.push({
      height: bodyRowH,
      isHeader: false,
      fill: rowFill,
      cells: [
        { text: r.job_step || "", fontSizePt: 9.5, fill: rowFill },
        { text: r.potential_hazards || "", fontSizePt: 9.5, fill: rowFill },
        { text: r.proposed_actions || "", fontSizePt: 9.5, fill: rowFill }
      ]
    });
  });

  const tables = [
    {
      name: "JSA Job Steps Table",
      x: 457200,
      y: 3497580,
      w: 6858000,
      h: 300000 + bodyRowH * rows.length,
      colWidths: [1920240, 2263140, 2674620],
      rows: tableRows
    }
  ];

  shapes.push({
    name: "Validation Sticker Box",
    x: 4846320,
    y: 8961120,
    w: 2468880,
    h: 685800,
    text: "PLACE ANNUAL REVIEW STICKER HERE\nJSA Template - FRM-GEA-SAF-085 Rev 0 2/28/2024",
    fill: "FFFFFF",
    lineColor: "64748B",
    lineDash: "dash",
    lineWidthPt: 1.25,
    fontSizePt: 8,
    bold: true,
    color: "64748B",
    align: "ctr",
    valign: "ctr"
  });

  const blob = _buildEditablePptxBlob({
    slideW: 7772400,
    slideH: 10058400,
    shapes,
    images,
    tables
  });
  triggerBlobDownload(blob, `${fileBase}.pptx`);
}

function exportPpePptx(fileBase) {
  const jobVal = (document.getElementById("posterJob").textContent || "").trim();
  const wsVal = (document.getElementById("posterWorkstation").textContent || "").trim();
  const secVal = (document.getElementById("posterSection").textContent || "").trim();
  const logoEl = document.querySelector(".header-logo");
  const logoSrc = logoEl ? logoEl.src : "";
  const isStd = posterPage && posterPage.classList.contains("mode-standard");
  const selectedItems = ppeData.filter(item => selectedPPE.has(item.name));

  const shapes = [
    { name: "Outer Border", x: 182880, y: 182880, w: 15179040, h: 9692640, text: "", fill: "6F42C1", lineColor: "0F3B5F", lineWidthPt: 2 },
    { name: "Inner Sheet", x: 411480, y: 411480, w: 14721840, h: 9235440, text: "", fill: "FFFFFF", lineColor: "0F3B5F", lineWidthPt: 1.5 },
    { name: "Poster Header", x: 594360, y: 548640, w: 14356080, h: 960120, text: "MINIMUM PPE REQUIREMENTS", fill: "E9EDF2", lineColor: "0F3B5F", lineWidthPt: 1.25, fontSizePt: 24, bold: true, color: "1F2D3A", align: "ctr", valign: "ctr" },
    { name: "Validation Sticker Slot", x: 731520, y: 640080, w: 2377440, h: 777240, text: "VALIDATION\nPlace annual review sticker here", fill: "FFFFFF", lineColor: "0F3B5F", lineDash: "dash", lineWidthPt: 1.5, fontSizePt: 9.5, bold: true, color: "0F3B5F", align: "l", valign: "ctr" },
    { name: "Job Chip", x: 594360, y: 1627632, w: 4663440, h: 411480, text: "Job: " + jobVal, fill: "F5F7FA", lineColor: "0F3B5F", lineWidthPt: 1.25, fontSizePt: 12, bold: true, color: "1F2D3A", align: "l", valign: "ctr" },
    { name: "Workstation Chip", x: 5440680, y: 1627632, w: 4663440, h: 411480, text: "Workstation: " + wsVal, fill: "F5F7FA", lineColor: "0F3B5F", lineWidthPt: 1.25, fontSizePt: 12, bold: true, color: "1F2D3A", align: "l", valign: "ctr" },
    { name: "Section Chip", x: 10287000, y: 1627632, w: 4663440, h: 411480, text: "Section: " + secVal, fill: "F5F7FA", lineColor: "0F3B5F", lineWidthPt: 1.25, fontSizePt: 12, bold: true, color: "1F2D3A", align: "l", valign: "ctr" },
    { name: "Left Panel", x: 594360, y: 2176272, w: 6949440, h: 7269480, text: "", fill: "F7F9FB", lineColor: "C9D3DF", lineWidthPt: 1.25 },
    { name: "Left Panel Title", x: 731520, y: 2249424, w: 6675120, h: 297180, text: "Required PPE (Visual)", fontSizePt: 12, bold: true, color: "0F3B5F", align: "l", valign: "ctr" },
    { name: "Left Panel Grid Box", x: 731520, y: 2587752, w: 6675120, h: 6720840, text: "", fill: "FFFFFF", lineColor: "C9D3DF", lineWidthPt: 1 },
    { name: "Right Panel", x: 7726680, y: 2176272, w: 7223760, h: 7269480, text: "", fill: "F7F9FB", lineColor: "C9D3DF", lineWidthPt: 1.25 },
    { name: "Right Panel Title", x: 7863840, y: 2249424, w: 6949440, h: 297180, text: "Hazards & Mitigations", fontSizePt: 12, bold: true, color: "0F3B5F", align: "l", valign: "ctr" }
  ];

  const images = [];
  if (logoSrc && logoSrc.startsWith("data:image/")) {
    images.push({ name: "EHS Logo", x: 13167360, y: 640080, w: 1645920, h: 777240, dataUri: logoSrc });
  }

  const gx = 822960, gy = 2679192, gw = 6492240, gh = 6537960;
  if (selectedItems.length > 0) {
    const cols = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(selectedItems.length))));
    const rowsCnt = Math.ceil(selectedItems.length / cols);
    const tileW = Math.floor(gw / cols);
    const tileH = Math.floor(gh / rowsCnt);
    selectedItems.forEach((item, idx) => {
      const r = Math.floor(idx / cols);
      const c = idx % cols;
      const tx = gx + c * tileW + 36576;
      const ty = gy + r * tileH + 36576;
      const tw = tileW - 73152;
      const th = tileH - 73152;
      shapes.push({
        name: "Tile " + item.name,
        x: tx, y: ty, w: tw, h: th,
        text: "", fill: "FFFFFF", lineColor: "E4E7EC", lineWidthPt: 1
      });
      const capH = Math.min(365760, Math.floor(th * 0.28));
      const imgBoxH = th - capH - 73152;
      if (item.image && item.image.startsWith("data:image/")) {
        const iconSide = Math.min(tw - 109728, imgBoxH);
        images.push({
          name: item.name,
          x: tx + Math.floor((tw - iconSide) / 2),
          y: ty + 36576 + Math.floor((imgBoxH - iconSide) / 2),
          w: iconSide,
          h: iconSide,
          dataUri: item.image
        });
      }
      shapes.push({
        name: "Caption " + item.name,
        x: tx + 27432,
        y: ty + th - capH - 18288,
        w: tw - 54864,
        h: capH,
        text: item.name,
        fontSizePt: 9.5,
        bold: true,
        color: "1E293B",
        align: "ctr",
        valign: "ctr"
      });
    });
  }

  const ppeTableRows = [
    {
      height: 320000,
      isHeader: true,
      fill: "EEF2F7",
      cells: [
        { text: "PPE Item", bold: true, fontSizePt: 10, fill: "EEF2F7", color: "1F2D3A" },
        { text: "Hazard", bold: true, fontSizePt: 10, fill: "EEF2F7", color: "1F2D3A" },
        { text: "Mitigation", bold: true, fontSizePt: 10, fill: "EEF2F7", color: "1F2D3A" }
      ]
    }
  ];
  const availPpeTableH = 6200000;
  const ppeRowH = Math.max(260000, Math.min(480000, Math.floor(availPpeTableH / Math.max(1, selectedItems.length))));
  selectedItems.forEach(item => {
    ppeTableRows.push({
      height: ppeRowH,
      isHeader: false,
      fill: "FFFFFF",
      cells: [
        { text: item.name || "", bold: true, fontSizePt: 9.5 },
        { text: item.hazard || "", fontSizePt: 9.5 },
        { text: item.mitigation || "", fontSizePt: 9.5 }
      ]
    });
  });

  const tables = [
    {
      name: "PPE Hazards and Mitigations Table",
      x: 7863840,
      y: 2587752,
      w: 6949440,
      h: 320000 + ppeRowH * selectedItems.length,
      colWidths: [1806854, 2571293, 2571293],
      rows: ppeTableRows
    }
  ];

  const blob = _buildEditablePptxBlob({
    slideW: 15544800,
    slideH: 10058400,
    shapes,
    images,
    tables
  });
  const dlUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = dlUrl;
  a.download = `${fileBase}.pptx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(dlUrl), 1000);
}
"""

def build_ppe_poster_html(
    *,
    pitch_id: str = "",
    job_name: str = "",
    workstation: str = "",
    section_name: str = "",
    selected_ppe_names: list[str] | None = None,
    effective_ppe_items: list[Any] | None = None,
    work_elements: list[dict[str, Any]] | None = None,
    pitch_label: str = "",
    overridden_items: list[dict[str, Any]] | None = None,
    overrides: list[dict[str, Any]] | None = None,
    allow_interactive_selector: bool = True,
    interactive_controls: bool | None = None,
    default_job: str = "",
    default_workstation: str = "",
    default_section: str = "",
) -> str:
    """Render the self-contained 11x17 landscape PPE Poster HTML component."""
    if interactive_controls is not None:
        allow_interactive_selector = bool(interactive_controls)

    raw_ppe_input: list[str] = []
    if selected_ppe_names is not None:
        raw_ppe_input = [str(x) for x in selected_ppe_names if str(x or "").strip()]
    elif effective_ppe_items is not None:
        for entry in effective_ppe_items:
            if isinstance(entry, dict):
                nm = str(entry.get("canonical_name") or entry.get("name") or "").strip()
                if nm:
                    raw_ppe_input.append(nm)
            elif str(entry or "").strip():
                raw_ppe_input.append(str(entry).strip())

    rollup = resolve_pitch_ppe_rollup(raw_ppe_input)
    effective_names = rollup.get("effective_canonical_names") or rollup["effective_names"]
    initial_mode_class = "mode-special"
    initial_badge_class = "standard" if rollup.get("is_standard_mode") else "special"
    initial_badge_text = (
        "Standard Baseline Border (Green)"
        if rollup.get("is_standard_mode")
        else "Special / Elevated PPE Border (Purple)"
    )

    catalog_js_items: list[dict[str, Any]] = []
    seen_catalog_names: set[str] = set()
    for item in PPE_CATALOG:
        name = item["name"]
        seen_catalog_names.add(name)
        catalog_js_items.append(
            {
                "name": name,
                "image": _file_to_data_uri(item["image_path"]),
                "hazard": item["hazard"],
                "mitigation": item["mitigation"],
            }
        )
    # Include any custom non-catalog PPE items assigned to the pitch so they also render on the table/poster
    for eff_item in rollup["effective_items"]:
        if eff_item["name"] not in seen_catalog_names:
            catalog_js_items.append(
                {
                    "name": eff_item["name"],
                    "image": "",
                    "hazard": eff_item.get("hazard") or "Task-specific workplace hazard.",
                    "mitigation": eff_item.get("mitigation")
                    or f"Correctly wear approved {eff_item['name'].upper()}.",
                }
            )

    ppe_pitch_tasks_js: list[dict[str, Any]] = []
    seen_ppe_task_we_ids: set[str] = set()
    for t_row in work_elements or []:
        if not isinstance(t_row, dict):
            continue
        we_id_str = str(t_row.get("work_element_id") or "").strip()
        if not we_id_str or we_id_str in seen_ppe_task_we_ids:
            continue
        seen_ppe_task_we_ids.add(we_id_str)
        raw_t_ppe = t_row.get("ppe") or []
        norm_t_ppe: list[str] = []
        if isinstance(raw_t_ppe, (list, tuple, set)):
            for p_val in raw_t_ppe:
                c_name = normalize_ppe_name(str(p_val or ""))
                if c_name and c_name not in norm_t_ppe:
                    norm_t_ppe.append(c_name)
        t_label = (
            str(t_row.get("operation") or "").strip()
            or str(t_row.get("job_step") or "").strip()
            or f"Task {len(ppe_pitch_tasks_js) + 1}"
        )
        ppe_pitch_tasks_js.append(
            {
                "work_element_id": we_id_str,
                "step_number": len(ppe_pitch_tasks_js) + 1,
                "label": t_label,
                "job_step": str(t_row.get("job_step") or t_label).strip(),
                "ppe": norm_t_ppe,
            }
        )
    if ppe_pitch_tasks_js and effective_names and not any(t["ppe"] for t in ppe_pitch_tasks_js):
        for t in ppe_pitch_tasks_js:
            t["ppe"] = list(effective_names)

    logo_uri = get_ehs_logo_data_uri()
    catalog_json = json.dumps(catalog_js_items, ensure_ascii=False)
    selected_json = json.dumps(effective_names, ensure_ascii=False)
    baseline_json = json.dumps(list(STANDARD_BASELINE_PPE), ensure_ascii=False)
    ppe_pitch_id_json = json.dumps(str(pitch_id or ""), ensure_ascii=False)
    ppe_pitch_tasks_json = json.dumps(ppe_pitch_tasks_js, ensure_ascii=False)

    safe_job = html.escape(str(job_name or default_job or "").strip())
    safe_ws = html.escape(str(workstation or default_workstation or "").strip())
    safe_sec = html.escape(str(section_name or default_section or "").strip())
    safe_pitch_label = html.escape(str(pitch_label or workstation or default_workstation or "Pitch").strip())

    override_banner_html = ""
    override_source = overridden_items if overridden_items is not None else (overrides or rollup.get("overrides") or [])
    if override_source:
        badges = []
        for ov in override_source:
            if not isinstance(ov, dict):
                continue
            if "overridden_by" in ov and "item" in ov:
                badges.append(
                    f"<strong>{html.escape(str(ov['overridden_by']))}</strong> overrides "
                    f"<em>{html.escape(str(ov['item']))}</em> ({html.escape(str(ov.get('category') or ''))})"
                )
            elif "winner" in ov and "overridden_items" in ov:
                ov_items_str = ", ".join(str(x) for x in (ov.get("overridden_items") or []))
                badges.append(
                    f"<strong>{html.escape(str(ov['winner']))}</strong> overrides "
                    f"<em>{html.escape(ov_items_str)}</em> ({html.escape(str(ov.get('category_label') or ''))})"
                )
            elif "summary" in ov:
                badges.append(html.escape(str(ov["summary"])))
        if badges:
            override_banner_html = (
                '<div class="override-info-banner no-print">'
                "<span>⚡ Automatic Pitch Hierarchy Override applied: "
                + " &bull; ".join(badges)
                + "</span></div>"
            )

    selector_display_style = "" if allow_interactive_selector else "display:none;"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Minimum PPE Requirements Poster - {safe_pitch_label}</title>
<style>
  :root {{
    --page-w: 17in;
    --page-h: 11in;
    --page-pad: 0.25in;
    --border-pad: 0.28in;
    --poster-inner-pad: 0.20in;
    --col-gap: 0.20in;
    --left-col-w: 58%;
    --right-col-w: 42%;
    --brand: #3b4b59;
    --accent: #0f3b5f;
    --ink: #111;
    --muted: #555;
    --card: #f9fafb;
    --grid: #dcdfe4;
  }}

  @page {{
    size: 17in 11in;
    margin: 0.25in;
  }}

  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}

  html, body {{
    margin: 0;
    padding: 6px 10px;
    min-height: 100%;
    height: auto;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    color: var(--ink);
    font-family: Segoe UI, Roboto, Arial, sans-serif;
    background: #eef2f6;
  }}

  .toolbar-wrap {{
    flex: 0 0 auto;
    width: 100%;
    max-width: 16.5in;
    margin: 2px auto 6px auto;
    background: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 10px;
    padding: 10px 14px;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
  }}

  .toolbar-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 10px;
  }}

  .toolbar-actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }}

  .btn {{
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 600;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }}
  .btn:hover {{
    opacity: 0.92;
  }}
  .btn-secondary {{
    background: #475569;
  }}
  .btn-outline {{
    background: #f8fafc;
    color: #0f3b5f;
    border: 1px solid #cbd5e1;
  }}

  .mode-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
  }}
  .mode-badge.standard {{
    background: #dcfce7;
    color: #166534;
    border: 1px solid #86efac;
  }}
  .mode-badge.special {{
    background: #f3e8ff;
    color: #6b21a8;
    border: 1px solid #d8b4fe;
  }}

  .override-info-banner {{
    max-width: 16.5in;
    margin: 6px auto;
    padding: 8px 14px;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    color: #1e3a8a;
    font-size: 13px;
  }}

  .interactive-drawer {{
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid #e2e8f0;
    display: none;
  }}
  .interactive-drawer.open {{
    display: block;
  }}

  .meta-inputs-row {{
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 10px;
  }}
  .meta-inputs-row label {{
    display: flex;
    flex-direction: column;
    font-size: 12px;
    font-weight: 600;
    color: #334155;
    flex: 1 1 200px;
  }}
  .meta-inputs-row input {{
    margin-top: 4px;
    padding: 6px 8px;
    font-size: 13px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
  }}

  .ppe-selector-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: 8px;
    margin-top: 8px;
    max-height: 220px;
    overflow-y: auto;
    padding: 4px;
  }}

  .ppe-item-btn {{
    border: 2px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px;
    text-align: center;
    cursor: pointer;
    background: #fff;
    transition: transform 0.08s ease, box-shadow 0.08s ease, border-color 0.08s ease;
  }}
  .ppe-item-btn:hover {{
    transform: translateY(-1px);
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
  }}
  .ppe-item-btn.selected {{
    border-color: #2563eb;
    background: #eff6ff;
  }}
  .ppe-item-btn img {{
    max-width: 52px;
    max-height: 52px;
    display: block;
    margin: 0 auto 4px;
    object-fit: contain;
  }}
  .ppe-item-btn span {{
    font-size: 11px;
    line-height: 1.2;
    display: block;
    color: #1e293b;
    font-weight: 600;
  }}

  .poster-viewport.zoomed-scroll {{
    scrollbar-width: auto;
    scrollbar-color: #64748b #e2e8f0;
  }}
  .poster-viewport.zoomed-scroll::-webkit-scrollbar {{
    width: 12px;
    height: 12px;
  }}
  .poster-viewport.zoomed-scroll::-webkit-scrollbar-track {{
    background: #e2e8f0;
    border-radius: 6px;
  }}
  .poster-viewport.zoomed-scroll::-webkit-scrollbar-thumb {{
    background: #64748b;
    border-radius: 6px;
    border: 2px solid #e2e8f0;
  }}
  .poster-viewport.zoomed-scroll::-webkit-scrollbar-thumb:hover {{
    background: #475569;
  }}

  .poster-viewport {{
    flex: 0 0 auto;
    min-height: 0;
    width: 100%;
    overflow: hidden;
    padding: 4px 0 12px 0;
  }}

  #posterPage {{
    width: calc(var(--page-w) - 2*var(--page-pad));
    height: calc(var(--page-h) - 2*var(--page-pad));
    margin: 0 auto;
    padding: var(--border-pad);
    border-radius: 10px;
    position: relative;
    background:
      repeating-linear-gradient(
        135deg,
        #b998ff 0 16px,
        #ffffff 16px 32px
      );
    box-shadow: 0 4px 16px rgba(15, 23, 42, 0.14);
  }}

  #posterPage.mode-standard {{
    background:
      repeating-linear-gradient(
        135deg,
        #19a974 0 16px,
        #ffffff 16px 32px
      );
  }}

  #posterPage.mode-special {{
    background:
      repeating-linear-gradient(
        135deg,
        #6f42c1 0 16px,
        #ffffff 16px 32px
      );
  }}

  #poster {{
    width: 100%;
    height: 100%;
    background: #fff;
    border-radius: 6px;
    border: 2px solid var(--brand);
    padding: var(--poster-inner-pad);
    display: grid;
    grid-template-rows: auto auto 1fr;
    row-gap: 0.14in;
    overflow: hidden;
  }}

  .poster-header {{
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #e9edf2;
    border: 1.5px solid var(--brand);
    border-radius: 6px;
    padding: 0.10in 0.16in;
    min-height: 1.1in;
  }}
  .poster-header h2 {{
    margin: 0;
    font-size: 28pt;
    letter-spacing: 0.5px;
    color: #1f2d3a;
    font-weight: 800;
    text-align: center;
  }}
  .header-logo {{
    position: absolute;
    right: 0.16in;
    top: 50%;
    transform: translateY(-50%);
    max-height: 0.9in;
    max-width: 2.2in;
    width: auto;
    height: auto;
    object-fit: contain;
  }}

  .validation-box {{
    position: absolute;
    left: 0.16in;
    top: 50%;
    transform: translateY(-50%);
    width: 2.6in;
    height: 0.9in;
    border: 2px dashed var(--brand);
    border-radius: 6px;
    background: #fff;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 0.06in 0.1in;
  }}
  .validation-title {{
    font-size: 10pt;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: var(--brand);
    text-transform: uppercase;
  }}
  .validation-sub {{
    font-size: 8.5pt;
    color: var(--muted);
    italic: true;
  }}

  .meta-bar-inline {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 0.12in;
  }}
  .meta-chip {{
    border: 1.5px solid var(--brand);
    border-radius: 6px;
    padding: 0.08in 0.12in;
    background: #f5f7fa;
    font-size: 12pt;
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-height: 0.45in;
  }}
  .meta-chip strong {{
    color: #1f2d3a;
    white-space: nowrap;
  }}
  .meta-chip span {{
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}

  .poster-body {{
    display: grid;
    grid-template-columns: var(--left-col-w) var(--right-col-w);
    column-gap: var(--col-gap);
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }}

  .icons-panel {{
    border: 1.5px solid var(--grid);
    border-radius: 6px;
    padding: 0.14in;
    background: var(--card);
    display: grid;
    grid-template-rows: auto 1fr;
    min-height: 0;
    overflow: hidden;
  }}
  .panel-title {{
    font-size: 12pt;
    font-weight: 700;
    color: var(--brand);
    margin: 0 0 0.08in 0;
  }}

  #posterIcons {{
    --cols: 3;
    --tile-h: 160px;
    --img-h: 110px;
    --cap-fs: 10.5pt;
    display: grid;
    grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
    grid-auto-rows: var(--tile-h);
    gap: 0.12in;
    align-content: start;
    justify-items: stretch;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    background: #fff;
    border: 1px solid var(--grid);
    border-radius: 6px;
    padding: 0.12in;
  }}

  .icon-tile {{
    border: 1px solid #e4e7ec;
    border-radius: 8px;
    background: #fff;
    padding: 0.08in;
    display: grid;
    grid-template-rows: 1fr auto;
    align-items: center;
    justify-items: center;
    overflow: hidden;
  }}
  .icon-tile img {{
    max-width: 100%;
    max-height: var(--img-h);
    width: auto;
    height: auto;
    object-fit: contain;
    display: block;
  }}
  .icon-tile .caption {{
    margin-top: 0.05in;
    text-align: center;
    font-size: var(--cap-fs);
    line-height: 1.15;
    color: #222;
    word-break: break-word;
    max-height: 2.4em;
    overflow: hidden;
  }}

  .table-panel {{
    border: 1.5px solid var(--grid);
    border-radius: 6px;
    padding: 0.14in;
    background: var(--card);
    display: grid;
    grid-template-rows: auto 1fr;
    min-height: 0;
  }}
  .table-wrap {{
    background: #fff;
    border: 1px solid var(--grid);
    border-radius: 6px;
    padding: 0.08in;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    display: grid;
    grid-template-rows: 1fr;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    font-size: 10.5pt;
  }}
  thead th {{
    background: #eef2f7;
    color: #1f2d3a;
    border: 1px solid var(--grid);
    padding: 6px 8px;
    font-weight: 700;
    text-align: left;
  }}
  tbody td {{
    border: 1px solid var(--grid);
    padding: 6px 8px;
    vertical-align: top;
    word-wrap: break-word;
  }}
  col.col-item {{ width: 26%; }}
  col.col-haz  {{ width: 37%; }}
  col.col-mit  {{ width: 37%; }}

  .compact-1 table {{ font-size: 9.5pt; }}
  .compact-1 tbody td, .compact-1 thead th {{ padding: 5px 6px; }}
  .compact-2 table {{ font-size: 8.5pt; }}
  .compact-2 tbody td, .compact-2 thead th {{ padding: 4px 5px; }}
  .compact-3 table {{ font-size: 7.8pt; }}
  .compact-3 tbody td, .compact-3 thead th {{ padding: 3px 4px; }}

  @media print {{
    html, body {{
      background: #fff;
      height: auto !important;
      overflow: visible !important;
      display: block !important;
      padding: 0 !important;
    }}
    .no-print {{
      display: none !important;
    }}
    .poster-viewport.zoomed-scroll {{
    scrollbar-width: auto;
    scrollbar-color: #64748b #e2e8f0;
  }}
  .poster-viewport.zoomed-scroll::-webkit-scrollbar {{
    width: 12px;
    height: 12px;
  }}
  .poster-viewport.zoomed-scroll::-webkit-scrollbar-track {{
    background: #e2e8f0;
    border-radius: 6px;
  }}
  .poster-viewport.zoomed-scroll::-webkit-scrollbar-thumb {{
    background: #64748b;
    border-radius: 6px;
    border: 2px solid #e2e8f0;
  }}
  .poster-viewport.zoomed-scroll::-webkit-scrollbar-thumb:hover {{
    background: #475569;
  }}

  .poster-viewport {{
      padding: 0;
      overflow: visible !important;
      height: auto !important;
    }}
    #ppeScaleStage {{
      width: auto !important;
      height: auto !important;
    }}
    #posterPage {{
      transform: none !important;
      margin: 0 auto !important;
      box-shadow: none;
      page-break-inside: avoid;
    }}
  }}
</style>
</head>
<body>

<div class="toolbar-wrap no-print">
  <div class="toolbar-header">
    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
      <strong style="font-size:15px; color:#0f3b5f;">11&quot;&times;17&quot; Landscape PPE Poster — {safe_pitch_label}</strong>
    </div>
    <div class="toolbar-actions">
      <div style="display:inline-flex; align-items:center; gap:3px; background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:2px 4px;">
        <button type="button" class="btn btn-outline" style="padding:4px 8px; border:none; background:transparent;" onclick="stepPpeZoom(-0.1)" title="Zoom Out">&#x2796;</button>
        <button type="button" class="btn btn-outline" id="ppeZoomLabelBtn" style="padding:4px 8px; border:none; background:transparent; min-width:80px; font-variant-numeric:tabular-nums;" onclick="resetPpeZoomFit()" title="Reset zoom to fit window">Fit</button>
        <button type="button" class="btn btn-outline" style="padding:4px 8px; border:none; background:transparent;" onclick="stepPpeZoom(0.1)" title="Zoom In">&#x2795;</button>
      </div>
      <button type="button" class="btn" id="btnSaveRefreshPpe" style="background:#2563eb;" onclick="saveAndRefreshPpePoster()" title="Save PPE task assignments to the database and refresh">&#x1F4BE; Save &amp; Refresh</button>
      <button type="button" class="btn btn-outline" id="btnUndoPpe" style="display:none;" onclick="resetToPitchPPE()" title="Discard unsaved PPE changes">&#x21B6; Undo</button>
      <button type="button" class="btn" style="background:#008a5e;" onclick="printPoster()">&#x1F5A8;&#xFE0F; Print PPE Poster</button>
      <button type="button" class="btn btn-outline" onclick="openPpeSaveAsModal()">&#x1F4BE; Save As</button>
      <button type="button" class="btn btn-outline" style="{selector_display_style}" onclick="toggleInteractiveDrawer()">
        &#x1F6E1;&#xFE0F; Add PPE to Task
      </button>
    </div>
  </div>

  <div id="interactiveDrawer" class="interactive-drawer">
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; gap:8px; flex-wrap:wrap;">
      <div>
        <strong style="font-size:12.5px; color:#0f172a;">&#x1F6E1;&#xFE0F; Select PPE Icons for Poster:</strong>
        <span style="font-size:11.5px; color:#475569; margin-left:6px;">Click any PPE icon to confirm which PAAG task(s) on this pitch require it (so PPE moves with the task if rebalanced).</span>
      </div>
      <button type="button" class="btn btn-outline" style="padding:4px 10px; font-size:11.5px;" onclick="toggleInteractiveDrawer()">Close &#x2715;</button>
    </div>
    <div class="ppe-selector-grid" id="ppeSelector"></div>
  </div>
</div>

<div id="ppeTaskConfirmModal" class="no-print" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,0.45); z-index:9999; align-items:flex-start; justify-content:center; padding:64px 16px 16px 16px;" onclick="if(event.target===this) closePpeTaskConfirmModal()">
  <div style="background:#fff; border-radius:12px; border:1px solid #cbd5e1; box-shadow:0 20px 25px -5px rgba(0,0,0,0.18); width:95%; max-width:560px; padding:16px 18px;" role="dialog" aria-modal="true" aria-labelledby="ppeTaskConfirmTitle">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
      <h3 id="ppeTaskConfirmTitle" style="display:flex;align-items:center;gap:8px;margin:0;font-size:15px;color:#0f172a;">&#x1F6E1;&#xFE0F; Confirm Tasks for PPE on JSA Poster</h3>
      <button type="button" onclick="closePpeTaskConfirmModal()" style="background:transparent; border:none; font-size:18px; cursor:pointer; color:#64748b;" title="Close">&#x2715;</button>
    </div>
    <div id="ppeTaskConfirmHero" style="display:flex;align-items:center;gap:12px;padding:10px 12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;margin-bottom:10px;"></div>
    <div id="ppeTaskBundleWrap" style="margin-bottom:10px;">
      <div style="font-size:11.5px;font-weight:700;color:#475569;margin-bottom:5px;">&#x2795; Optional: Also assign additional PPE to the same selected task(s):</div>
      <div id="ppeTaskBundlePills" style="display:flex;flex-wrap:wrap;gap:5px;max-height:84px;overflow-y:auto;padding:2px;"></div>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:6px;">
      <div>
        <div style="font-size:12.5px;font-weight:700;color:#0f172a;">Which PAAG task(s) on this pitch require this PPE?</div>
        <div style="font-size:11px;color:#64748b;">PPE is linked to the checked task(s) so it moves with them if a task changes pitch.</div>
      </div>
      <div style="display:flex;gap:6px;align-items:center;">
        <button type="button" class="btn btn-outline" style="padding:3px 8px;font-size:11px;" onclick="setAllPpeConfirmTasks(true)">Select All</button>
        <button type="button" class="btn btn-outline" style="padding:3px 8px;font-size:11px;" onclick="setAllPpeConfirmTasks(false)">Clear All</button>
      </div>
    </div>
    <div id="ppeTaskConfirmList" style="max-height:230px;overflow-y:auto;border:1px solid #cbd5e1;border-radius:8px;padding:6px;background:#ffffff;margin-bottom:8px;display:flex;flex-direction:column;gap:5px;"></div>
    <div id="ppeTaskConfirmError" style="display:none;font-size:11.5px;font-weight:700;color:#dc2626;margin-bottom:8px;">Please select at least one task, or click "Remove from Pitch" to unassign this PPE.</div>
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-top:6px;">
      <div>
        <button type="button" class="btn btn-outline" id="btnRemovePpeFromPitch" style="display:none;color:#dc2626;border-color:#fca5a5;background:#fef2f2;padding:6px 10px;font-size:12px;" onclick="removeConfirmedPpeFromPitch()">&#x1F5D1;&#xFE0F; Remove from Pitch</button>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;">
        <button type="button" class="btn btn-outline" onclick="closePpeTaskConfirmModal()">Cancel</button>
        <button type="button" class="btn" style="background:#008a5e;" onclick="applyPpeTaskConfirmation()" title="Add to the Poster and keep editing">&#x2713; Confirm &amp; Add to Poster</button>
      </div>
    </div>
  </div>
</div>

<div id="ppeSaveAsModal" class="no-print" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,0.45); z-index:9999; align-items:center; justify-content:center; padding:16px;" onclick="if(event.target===this) closePpeSaveAsModal()">
  <div style="background:#fff; border-radius:12px; border:1px solid #cbd5e1; box-shadow:0 20px 25px -5px rgba(0,0,0,0.18); width:100%; max-width:460px; padding:18px 20px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h3 style="margin:0; font-size:16px; color:#0f172a;">&#x1F4BE; Save 11&times;17 PPE Poster As</h3>
      <button type="button" onclick="closePpeSaveAsModal()" style="background:transparent; border:none; font-size:18px; cursor:pointer; color:#64748b;">&#x2715;</button>
    </div>
    <div style="margin-bottom:14px;">
      <label for="ppeSaveAsFileName" style="display:block; font-size:12px; font-weight:700; color:#334155; margin-bottom:4px;">File name</label>
      <input type="text" id="ppeSaveAsFileName" value="" placeholder="PPE_Poster" style="width:100%; padding:8px 10px; font-size:13px; border:1px solid #cbd5e1; border-radius:6px;" />
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:14px;">
      <button type="button" class="btn btn-outline" style="flex-direction:column; align-items:flex-start; padding:10px 12px; text-align:left;" onclick="exportPpeAs('pptx')">
        <strong style="font-size:13px; color:#0f172a;">&#x1F4CA; PowerPoint (.pptx)</strong>
        <span style="font-size:11px; color:#64748b; font-weight:400;">Editable PowerPoint slide</span>
      </button>
      <button type="button" class="btn btn-outline" style="flex-direction:column; align-items:flex-start; padding:10px 12px; text-align:left;" onclick="exportPpeAs('pdf')">
        <strong style="font-size:13px; color:#0f172a;">&#x1F4C4; PDF Document (.pdf)</strong>
        <span style="font-size:11px; color:#64748b; font-weight:400;">Print / Save as PDF</span>
      </button>
      <button type="button" class="btn btn-outline" style="flex-direction:column; align-items:flex-start; padding:10px 12px; text-align:left;" onclick="exportPpeAs('doc')">
        <strong style="font-size:13px; color:#0f172a;">&#x1F4DD; Word Document (.doc)</strong>
        <span style="font-size:11px; color:#64748b; font-weight:400;">Editable Word document</span>
      </button>
      <button type="button" class="btn btn-outline" style="flex-direction:column; align-items:flex-start; padding:10px 12px; text-align:left;" onclick="exportPpeAs('html')">
        <strong style="font-size:13px; color:#0f172a;">&#x1F310; Web Document (.html)</strong>
        <span style="font-size:11px; color:#64748b; font-weight:400;">Standalone HTML file</span>
      </button>
    </div>
    <div style="display:flex; justify-content:flex-end;">
      <button type="button" class="btn btn-outline" onclick="closePpeSaveAsModal()">Cancel</button>
    </div>
  </div>
</div>
{override_banner_html}

<div class="poster-viewport" id="ppeViewport">
  <div id="ppeScaleStage" style="margin:0 auto; position:relative;">
    <div id="posterPage" class="{initial_mode_class}">
    <div id="poster">
      <div class="poster-header">
        <div class="validation-box" aria-label="Validation Sticker Slot">
          <div class="validation-title">VALIDATION</div>
          <div class="validation-sub">Place annual review sticker here</div>
        </div>
        <h2>MINIMUM PPE REQUIREMENTS</h2>
        <img class="header-logo" src="{logo_uri}" alt="EHS&amp;S Logo" />
      </div>

      <div class="meta-bar-inline">
        <div class="meta-chip"><strong>Job:</strong> <span id="posterJob">{safe_job}</span></div>
        <div class="meta-chip"><strong>Workstation:</strong> <span id="posterWorkstation">{safe_ws}</span></div>
        <div class="meta-chip"><strong>Section:</strong> <span id="posterSection">{safe_sec}</span></div>
      </div>

      <div class="poster-body">
        <div class="icons-panel">
          <div class="panel-title">Required PPE (Visual)</div>
          <div id="posterIcons"></div>
        </div>

        <div class="table-panel">
          <div class="panel-title">Hazards &amp; Mitigations</div>
          <div class="table-wrap" id="tableWrap">
            <table id="posterTable" aria-label="PPE Hazards and Mitigations">
              <colgroup>
                <col class="col-item" />
                <col class="col-haz" />
                <col class="col-mit" />
              </colgroup>
              <thead>
                <tr>
                  <th>PPE Item</th>
                  <th>Hazard</th>
                  <th>Mitigation</th>
                </tr>
              </thead>
              <tbody></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
  </div>
</div>

<script>
const currentPitchId = {ppe_pitch_id_json};
const ppeData = {catalog_json};
const initialPitchPPE = {selected_json};
const initialPitchTasks = {ppe_pitch_tasks_json};
let pitchTasks = JSON.parse(JSON.stringify(initialPitchTasks || []));
let taskPpeByWeId = {{}};
const unassignedPitchPPE = new Set();
const selectedPPE = new Set(initialPitchPPE);

const CUT_GLOVE_RANKS = {{
  "Cut Level 1 Gloves": 1,
  "Cut Level 2 Gloves": 2,
  "Cut Level 3 Gloves": 3,
  "Cut Level 4 Gloves": 4,
  "Cut Level 5 Gloves": 5,
  "Cut Level 6 Gloves": 6
}};
const FOOTWEAR_RANKS = {{
  "Sturdy Closed Toe and Heel Shoes": 1,
  "Safety Toe Shoes": 2
}};
const EYE_RANKS = {{
  "Safety Glasses": 1,
  "Foam Lined Safety Glasses": 2
}};
const HEAD_RANKS = {{
  "Bump Cap": 1,
  "Hard Hat": 2
}};

function initTaskPpeFromBaseline() {{
  taskPpeByWeId = {{}};
  unassignedPitchPPE.clear();
  pitchTasks.forEach(t => {{
    const wid = String(t.work_element_id || "");
    if (wid) {{
      taskPpeByWeId[wid] = new Set(Array.isArray(t.ppe) ? t.ppe : []);
    }}
  }});
  if (pitchTasks.length === 0) {{
    initialPitchPPE.forEach(n => unassignedPitchPPE.add(n));
  }}
}}
initTaskPpeFromBaseline();

function recomputeSelectedPPEFromTasks() {{
  if (pitchTasks.length === 0) return;
  const rawNames = new Set();
  Object.values(taskPpeByWeId).forEach(setObj => {{
    if (setObj && typeof setObj.forEach === "function") {{
      setObj.forEach(n => rawNames.add(n));
    }}
  }});
  unassignedPitchPPE.forEach(n => rawNames.add(n));
  let maxCut = 0, maxFoot = 0, maxEye = 0, maxHead = 0;
  rawNames.forEach(name => {{
    if (CUT_GLOVE_RANKS[name]) maxCut = Math.max(maxCut, CUT_GLOVE_RANKS[name]);
    if (FOOTWEAR_RANKS[name]) maxFoot = Math.max(maxFoot, FOOTWEAR_RANKS[name]);
    if (EYE_RANKS[name]) maxEye = Math.max(maxEye, EYE_RANKS[name]);
    if (HEAD_RANKS[name]) maxHead = Math.max(maxHead, HEAD_RANKS[name]);
  }});
  selectedPPE.clear();
  rawNames.forEach(name => {{
    if (CUT_GLOVE_RANKS[name] && CUT_GLOVE_RANKS[name] < maxCut) return;
    if (FOOTWEAR_RANKS[name] && FOOTWEAR_RANKS[name] < maxFoot) return;
    if (EYE_RANKS[name] && EYE_RANKS[name] < maxEye) return;
    if (HEAD_RANKS[name] && HEAD_RANKS[name] < maxHead) return;
    selectedPPE.add(name);
  }});
}}

function getSerializableTaskPpeMap() {{
  const out = {{}};
  Object.keys(taskPpeByWeId).forEach(wid => {{
    out[wid] = Array.from(taskPpeByWeId[wid] || []);
  }});
  return out;
}}

function getTasksUsingPpe(ppeName) {{
  const matched = [];
  pitchTasks.forEach(t => {{
    const wid = String(t.work_element_id || "");
    const setObj = taskPpeByWeId[wid];
    if (setObj && setObj.has(ppeName)) {{
      matched.push(wid);
    }}
  }});
  return matched;
}}

try {{
  if (currentPitchId) {{
    const cachedTaskMapJson = sessionStorage.getItem("paag_pitch_ppe_tasks_" + currentPitchId);
    if (cachedTaskMapJson && pitchTasks.length > 0) {{
      const parsedMap = JSON.parse(cachedTaskMapJson);
      if (parsedMap && typeof parsedMap === "object") {{
        Object.keys(parsedMap).forEach(wid => {{
          if (Array.isArray(parsedMap[wid]) && taskPpeByWeId[wid]) {{
            taskPpeByWeId[wid] = new Set(parsedMap[wid]);
          }}
        }});
        recomputeSelectedPPEFromTasks();
      }}
    }} else {{
      const cachedPpeJson = sessionStorage.getItem("paag_pitch_ppe_" + currentPitchId);
      if (cachedPpeJson) {{
        const cachedArr = JSON.parse(cachedPpeJson);
        if (Array.isArray(cachedArr)) {{
          selectedPPE.clear();
          cachedArr.forEach(n => selectedPPE.add(n));
        }}
      }}
    }}
  }}
}} catch (e) {{}}
recomputeSelectedPPEFromTasks();

let baselinePpeSnapshot = "";
function getPpeSnapshotJson() {{
  const sortedTaskMap = {{}};
  Object.keys(taskPpeByWeId).sort().forEach(wid => {{
    sortedTaskMap[wid] = Array.from(taskPpeByWeId[wid] || []).slice().sort();
  }});
  return JSON.stringify({{
    ppe: Array.from(selectedPPE).slice().sort(),
    taskPpe: sortedTaskMap
  }});
}}

function checkPpeDirtyState() {{
  if (!baselinePpeSnapshot) return;
  const dirty = getPpeSnapshotJson() !== baselinePpeSnapshot;
  const saveBtn = document.getElementById("btnSaveRefreshPpe");
  const undoBtn = document.getElementById("btnUndoPpe");
  if (saveBtn) {{
    saveBtn.style.background = dirty ? "#ea580c" : "#2563eb";
  }}
  if (undoBtn) {{
    undoBtn.style.display = dirty ? "inline-flex" : "none";
  }}
}}

const selectorContainer = document.getElementById("ppeSelector");
const posterIcons = document.getElementById("posterIcons");
const posterTableBody = document.querySelector("#posterTable tbody");
const tableWrap = document.getElementById("tableWrap");
const posterPage = document.getElementById("posterPage");
const modeBadge = document.getElementById("modeBadge");

let pendingConfirmPrimaryPpe = "";
let pendingConfirmBundledPpe = new Set();
let pendingConfirmTaskIds = new Set();

function openPpeTaskConfirmModal(ppeName) {{
  const item = ppeData.find(it => it.name === ppeName);
  if (!item) return;
  if (!pitchTasks || pitchTasks.length === 0) {{
    if (selectedPPE.has(ppeName)) selectedPPE.delete(ppeName);
    else selectedPPE.add(ppeName);
    renderSelectorTiles();
    updatePoster();
    syncFromPpePoster();
    checkPpeDirtyState();
    return;
  }}
  pendingConfirmPrimaryPpe = ppeName;
  pendingConfirmBundledPpe = new Set([ppeName]);
  const existingTaskIds = getTasksUsingPpe(ppeName);
  const wasAssigned = existingTaskIds.length > 0 || selectedPPE.has(ppeName);
  if (existingTaskIds.length > 0) {{
    pendingConfirmTaskIds = new Set(existingTaskIds);
  }} else {{
    pendingConfirmTaskIds = new Set(pitchTasks.map(t => String(t.work_element_id)));
  }}
  const removeBtn = document.getElementById("btnRemovePpeFromPitch");
  if (removeBtn) removeBtn.style.display = wasAssigned ? "inline-flex" : "none";
  const errEl = document.getElementById("ppeTaskConfirmError");
  if (errEl) errEl.style.display = "none";
  renderPpeTaskConfirmModalContents();
  const modal = document.getElementById("ppeTaskConfirmModal");
  if (modal) modal.style.display = "flex";
}}

function closePpeTaskConfirmModal() {{
  const modal = document.getElementById("ppeTaskConfirmModal");
  if (modal) modal.style.display = "none";
  pendingConfirmPrimaryPpe = "";
  pendingConfirmBundledPpe.clear();
}}

function renderPpeTaskConfirmModalContents() {{
  const item = ppeData.find(it => it.name === pendingConfirmPrimaryPpe);
  if (!item) return;
  const hero = document.getElementById("ppeTaskConfirmHero");
  const bundledList = Array.from(pendingConfirmBundledPpe);
  const extraCount = bundledList.length - 1;
  const titleSuffix = extraCount > 0 ? " + " + extraCount + " more PPE item(s)" : "";
  if (hero) {{
    hero.innerHTML =
      (item.image ? `<img src="${{item.image}}" alt="${{item.name}}" style="width:52px;height:52px;object-fit:contain;background:#fff;border:1px solid #cbd5e1;border-radius:6px;padding:2px;flex-shrink:0;" />` : "") +
      `<div style="min-width:0;">` +
      `<div style="font-size:14px;font-weight:800;color:#0f172a;">${{item.name}}${{titleSuffix}}</div>` +
      `<div style="font-size:11.5px;color:#475569;margin-top:2px;">Confirm which PAAG task(s) on this pitch require this PPE.</div>` +
      `</div>`;
  }}
  const pillsWrap = document.getElementById("ppeTaskBundlePills");
  if (pillsWrap) {{
    pillsWrap.innerHTML = "";
    ppeData.forEach(catItem => {{
      if (catItem.name === pendingConfirmPrimaryPpe) return;
      const isPicked = pendingConfirmBundledPpe.has(catItem.name);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.style.cssText =
        "display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:999px;font-size:11px;cursor:pointer;" +
        (isPicked
          ? "border:1.5px solid #0284c7;background:#e0f2fe;color:#0369a1;font-weight:700;"
          : "border:1px solid #cbd5e1;background:#f8fafc;color:#334155;font-weight:500;");
      btn.textContent = (isPicked ? "\u2713 " : "+ ") + catItem.name;
      btn.onclick = () => {{
        if (pendingConfirmBundledPpe.has(catItem.name)) pendingConfirmBundledPpe.delete(catItem.name);
        else pendingConfirmBundledPpe.add(catItem.name);
        renderPpeTaskConfirmModalContents();
      }};
      pillsWrap.appendChild(btn);
    }});
  }}
  const listEl = document.getElementById("ppeTaskConfirmList");
  if (!listEl) return;
  listEl.innerHTML = "";
  pitchTasks.forEach((task, idx) => {{
    const wid = String(task.work_element_id || "");
    const isChecked = pendingConfirmTaskIds.has(wid);
    const currentTaskPpe = Array.from(taskPpeByWeId[wid] || []);
    const row = document.createElement("div");
    row.style.cssText =
      "display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 10px;border-radius:6px;cursor:pointer;" +
      (isChecked ? "border:1.5px solid #008a5e;background:#ecfdf5;" : "border:1px solid #e2e8f0;background:#f8fafc;");
    const left = document.createElement("label");
    left.style.cssText = "display:flex;align-items:flex-start;gap:8px;cursor:pointer;flex:1;min-width:0;";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = isChecked;
    cb.style.cssText = "margin-top:2px;width:15px;height:15px;cursor:pointer;accent-color:#008a5e;";
    cb.onchange = () => {{
      if (cb.checked) pendingConfirmTaskIds.add(wid);
      else pendingConfirmTaskIds.delete(wid);
      const errEl = document.getElementById("ppeTaskConfirmError");
      if (errEl && pendingConfirmTaskIds.size > 0) errEl.style.display = "none";
      renderPpeTaskConfirmModalContents();
    }};
    const textCol = document.createElement("div");
    textCol.style.cssText = "min-width:0;flex:1;";
    const stepTitle = document.createElement("div");
    stepTitle.style.cssText = "font-size:12.5px;font-weight:700;color:#0f172a;line-height:1.3;";
    stepTitle.textContent = "Step " + (task.step_number || (idx + 1)) + ": " + (task.label || task.job_step || "Task");
    textCol.appendChild(stepTitle);
    if (currentTaskPpe.length > 0) {{
      const ppeSub = document.createElement("div");
      ppeSub.style.cssText = "font-size:10.5px;color:#475569;margin-top:2px;";
      ppeSub.textContent = "Current PPE: " + currentTaskPpe.join(", ");
      textCol.appendChild(ppeSub);
    }}
    left.appendChild(cb);
    left.appendChild(textCol);
    const onlyBtn = document.createElement("button");
    onlyBtn.type = "button";
    onlyBtn.style.cssText =
      "padding:2px 7px;font-size:10.5px;font-weight:600;border-radius:4px;border:1px solid #cbd5e1;background:#ffffff;color:#0369a1;cursor:pointer;flex-shrink:0;";
    onlyBtn.textContent = "Only this task";
    onlyBtn.onclick = (e) => {{
      e.stopPropagation();
      pendingConfirmTaskIds = new Set([wid]);
      const errEl = document.getElementById("ppeTaskConfirmError");
      if (errEl) errEl.style.display = "none";
      renderPpeTaskConfirmModalContents();
    }};
    row.appendChild(left);
    row.appendChild(onlyBtn);
    listEl.appendChild(row);
  }});
}}

function setAllPpeConfirmTasks(selectAll) {{
  if (selectAll) {{
    pendingConfirmTaskIds = new Set(pitchTasks.map(t => String(t.work_element_id)));
    const errEl = document.getElementById("ppeTaskConfirmError");
    if (errEl) errEl.style.display = "none";
  }} else {{
    pendingConfirmTaskIds.clear();
  }}
  renderPpeTaskConfirmModalContents();
}}

function syncFromPpePoster() {{
  const effectiveNames = Array.from(selectedPPE);
  try {{
    if (currentPitchId) {{
      sessionStorage.setItem("paag_pitch_ppe_" + currentPitchId, JSON.stringify(effectiveNames));
      sessionStorage.setItem("paag_pitch_ppe_tasks_" + currentPitchId, JSON.stringify(getSerializableTaskPpeMap()));
    }}
  }} catch (e) {{}}
  try {{
    if (window.parent && window.parent !== window) {{
      window.parent.postMessage({{
        type: "PAAG_JSA_PPE_SYNC",
        pitchId: currentPitchId,
        effectivePPE: effectiveNames
      }}, "*");
      if (window.parent.frames) {{
        for (let i = 0; i < window.parent.frames.length; i++) {{
          try {{
            window.parent.frames[i].postMessage({{
              type: "PAAG_JSA_PPE_SYNC",
              pitchId: currentPitchId,
              effectivePPE: effectiveNames
            }}, "*");
          }} catch (fe) {{}}
        }}
      }}
    }}
  }} catch (e) {{}}
}}

function applyPpeTaskConfirmation() {{
  if (pendingConfirmTaskIds.size === 0) {{
    const errEl = document.getElementById("ppeTaskConfirmError");
    if (errEl) errEl.style.display = "block";
    return;
  }}
  const ppeNamesToApply = Array.from(pendingConfirmBundledPpe);
  pitchTasks.forEach(t => {{
    const wid = String(t.work_element_id || "");
    if (!wid) return;
    if (!taskPpeByWeId[wid]) taskPpeByWeId[wid] = new Set();
    if (pendingConfirmTaskIds.has(wid)) {{
      ppeNamesToApply.forEach(pName => taskPpeByWeId[wid].add(pName));
    }} else if (ppeNamesToApply.length === 1 && ppeNamesToApply[0] === pendingConfirmPrimaryPpe) {{
      taskPpeByWeId[wid].delete(pendingConfirmPrimaryPpe);
    }}
  }});
  ppeNamesToApply.forEach(pName => unassignedPitchPPE.delete(pName));
  recomputeSelectedPPEFromTasks();
  closePpeTaskConfirmModal();
  renderSelectorTiles();
  updatePoster();
  syncFromPpePoster();
  checkPpeDirtyState();
}}

function removeConfirmedPpeFromPitch() {{
  if (!pendingConfirmPrimaryPpe) return;
  Object.keys(taskPpeByWeId).forEach(wid => {{
    if (taskPpeByWeId[wid]) taskPpeByWeId[wid].delete(pendingConfirmPrimaryPpe);
  }});
  unassignedPitchPPE.delete(pendingConfirmPrimaryPpe);
  recomputeSelectedPPEFromTasks();
  closePpeTaskConfirmModal();
  renderSelectorTiles();
  updatePoster();
  syncFromPpePoster();
  checkPpeDirtyState();
}}

function saveAndRefreshPpePoster() {{
  const payload = {{
    pitchId: currentPitchId,
    ppeOnly: true,
    effectivePPE: Array.from(selectedPPE),
    ppeByWorkElement: getSerializableTaskPpeMap(),
    savedAt: new Date().toISOString()
  }};
  baselinePpeSnapshot = getPpeSnapshotJson();
  checkPpeDirtyState();
  try {{
    if (window.parent && window.parent !== window) {{
      window.parent.postMessage({{
        type: "PAAG_JSA_SAVE_REQUEST",
        payload: payload
      }}, "*");
      if (window.parent.frames) {{
        for (let i = 0; i < window.parent.frames.length; i++) {{
          try {{
            window.parent.frames[i].postMessage({{
              type: "PAAG_JSA_SAVE_REQUEST",
              payload: payload
            }}, "*");
          }} catch (fe) {{}}
        }}
      }}
    }}
  }} catch (e) {{}}
}}

function renderSelectorTiles() {{
  if (!selectorContainer) return;
  selectorContainer.innerHTML = "";
  const totalTasks = pitchTasks.length;
  ppeData.forEach(item => {{
    const div = document.createElement("div");
    const isSel = selectedPPE.has(item.name);
    div.className = "ppe-item-btn" + (isSel ? " selected" : "");
    div.dataset.name = item.name;
    let taskBadgeHtml = "";
    if (totalTasks > 0 && isSel) {{
      const usedCount = getTasksUsingPpe(item.name).length;
      const badgeTxt = usedCount === totalTasks
        ? "All " + totalTasks + " task" + (totalTasks === 1 ? "" : "s")
        : usedCount + "/" + totalTasks + " tasks";
      taskBadgeHtml = `<div style="font-size:9.5px;background:#dcfce7;color:#166534;border:1px solid #86efac;border-radius:999px;padding:1px 6px;font-weight:700;margin-top:3px;">&#x1F4CB; ${{badgeTxt}}</div>`;
    }}
    const imgHtml = item.image ? `<img src="${{item.image}}" alt="${{item.name}}">` : "";
    div.innerHTML = `${{imgHtml}}<span>${{item.name}}</span>${{taskBadgeHtml}}`;
    div.onclick = () => {{
      openPpeTaskConfirmModal(item.name);
    }};
    selectorContainer.appendChild(div);
  }});
}}

let ppeZoomMode = "fit";
let ppeZoomScale = 1.0;
let isApplyingPpeZoom = false;

function applyPpeZoom() {{
  if (isApplyingPpeZoom) return;
  const stage = document.getElementById("ppeScaleStage");
  const viewport = document.getElementById("ppeViewport");
  const labelBtn = document.getElementById("ppeZoomLabelBtn");
  if (!posterPage || !stage || !viewport) return;

  isApplyingPpeZoom = true;
  try {{
    const naturalW = posterPage.offsetWidth || 1584;
    const naturalH = posterPage.offsetHeight || 1008;

    const containerW = document.documentElement.clientWidth || window.innerWidth || viewport.clientWidth || 900;
    const availW = Math.max(260, containerW - 24);
    const _fitScaleInit = Math.max(0.22, Math.min(1.0, availW / naturalW));
    const fitW = Math.ceil(naturalW * _fitScaleInit);
    const fitH = Math.ceil(naturalH * _fitScaleInit);
    const fitScale = Math.max(0.22, Math.min(1.0, availW / naturalW));

    if (ppeZoomMode === "fit") {{
      ppeZoomScale = fitScale;
    }}

    posterPage.style.transformOrigin = "top left";
    posterPage.style.transform = `scale(${{ppeZoomScale}})`;
    posterPage.style.margin = "0";

    const scaledW = Math.ceil(naturalW * ppeZoomScale);
    const scaledH = Math.ceil(naturalH * ppeZoomScale);
    stage.style.width = scaledW + "px";
    stage.style.height = scaledH + "px";

    const isZoomedIn = ppeZoomScale > (fitScale + 0.005);
    const targetPosterH = isZoomedIn ? fitH : scaledH;
    const targetViewportW = isZoomedIn ? Math.min(availW, fitW + 18) : availW;
    stage.style.margin = isZoomedIn ? "0" : "0 auto";
    viewport.classList.toggle("zoomed-scroll", isZoomedIn);
    viewport.style.overflowX = isZoomedIn ? "scroll" : "hidden";
    viewport.style.overflowY = isZoomedIn ? "scroll" : "hidden";
    viewport.style.width = isZoomedIn ? targetViewportW + "px" : "100%";
    viewport.style.maxWidth = isZoomedIn ? targetViewportW + "px" : "none";
    viewport.style.margin = isZoomedIn ? "0 auto" : "0";
    viewport.style.height = (targetPosterH + (isZoomedIn ? 20 : 16)) + "px";
    viewport.style.maxHeight = isZoomedIn ? (targetPosterH + 20) + "px" : "none";
    if (false) {{
      const isZoomedOver100 = ppeZoomScale > 1.001;
    const targetPosterH = isZoomedOver100 ? naturalH : scaledH;
    viewport.style.overflow = isZoomedOver100 ? "auto" : "hidden";
    viewport.style.height = (targetPosterH + 16) + "px";
    viewport.style.maxHeight = isZoomedOver100 ? (naturalH + 16) + "px" : "none";
    }}

    const viewportTop = viewport.offsetTop || 64;
    const desiredIframeH = Math.ceil(viewportTop + targetPosterH + 24);
    try {{
      if (window.frameElement) {{
        const curH = window.frameElement.offsetHeight || parseInt(window.frameElement.style.height || "0", 10) || 0;
        if (Math.abs(curH - desiredIframeH) > 2) {{
          window.frameElement.style.height = desiredIframeH + "px";
          window.frameElement.height = String(desiredIframeH);
        }}
      }}
    }} catch (fe) {{}}

    const pct = Math.round(ppeZoomScale * 100);
    if (labelBtn) {{
      labelBtn.textContent = ppeZoomMode === "fit" ? `Fit (${{pct}}%)` : `${{pct}}% (Fit)`;
    }}
  }} finally {{
    isApplyingPpeZoom = false;
  }}
}}

function stepPpeZoom(delta) {{
  ppeZoomMode = "manual";
  let nextScale = Math.round((ppeZoomScale + delta) * 20) / 20;
  if (delta > 0 && nextScale <= ppeZoomScale + 0.005) nextScale = ppeZoomScale + 0.05;
  if (delta < 0 && nextScale >= ppeZoomScale - 0.005) nextScale = ppeZoomScale - 0.05;
  ppeZoomScale = Math.max(0.20, Math.min(2.5, nextScale));
  applyPpeZoom();
}}

function resetPpeZoomFit() {{
  ppeZoomMode = "fit";
  applyPpeZoom();
}}

function toggleInteractiveDrawer() {{
  const drawer = document.getElementById("interactiveDrawer");
  if (drawer) {{
    drawer.classList.toggle("open");
    applyPpeZoom();
  }}
}}

function resetToPitchPPE() {{
  initTaskPpeFromBaseline();
  selectedPPE.clear();
  initialPitchPPE.forEach(n => selectedPPE.add(n));
  recomputeSelectedPPEFromTasks();
  try {{
    if (currentPitchId) {{
      sessionStorage.removeItem("paag_pitch_ppe_" + currentPitchId);
      sessionStorage.removeItem("paag_pitch_ppe_tasks_" + currentPitchId);
    }}
  }} catch (e) {{}}
  syncFromPpePoster();
  renderSelectorTiles();
  updatePoster();
  checkPpeDirtyState();
}}

function updatePoster() {{
  const selectedItems = ppeData.filter(item => selectedPPE.has(item.name));

  posterIcons.innerHTML = "";
  selectedItems.forEach(item => {{
    const tile = document.createElement("div");
    tile.className = "icon-tile";
    tile.style.cursor = "pointer";
    tile.title = item.name + " - click to view or update which pitch tasks require this PPE";
    tile.onclick = () => openPpeTaskConfirmModal(item.name);
    const imgHtml = item.image ? `<img src="${{item.image}}" alt="${{item.name}}" />` : `<div style="font-weight:700;font-size:14pt;text-align:center;">${{item.name}}</div>`;
    tile.innerHTML = `
      ${{imgHtml}}
      <div class="caption">${{item.name}}</div>
    `;
    posterIcons.appendChild(tile);
  }});

  posterTableBody.innerHTML = "";
  selectedItems.forEach(item => {{
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${{item.name}}</strong></td>
      <td>${{item.hazard}}</td>
      <td>${{item.mitigation}}</td>
    `;
    posterTableBody.appendChild(tr);
  }});

  fitAll();
}}

function fitAll() {{
  fitTableDensity();
  fitIconsNoCutoff();
  applyPpeZoom();
}}

function fitTableDensity() {{
  tableWrap.classList.remove("compact-1", "compact-2", "compact-3");
  const count = selectedPPE.size;
  if (count > 8 && count <= 12) {{
    tableWrap.classList.add("compact-1");
  }} else if (count > 12 && count <= 16) {{
    tableWrap.classList.add("compact-2");
  }} else if (count > 16) {{
    tableWrap.classList.add("compact-3");
  }}
  let step = 0;
  while (tableWrap.scrollHeight > tableWrap.clientHeight && step < 3) {{
    step++;
    tableWrap.classList.add(`compact-${{step}}`);
  }}
}}

function fitIconsNoCutoff() {{
  const count = selectedPPE.size;
  const W = posterIcons.clientWidth;
  const H = posterIcons.clientHeight;

  if (count === 0 || W === 0 || H === 0) {{
    posterIcons.style.setProperty("--cols", 3);
    posterIcons.style.setProperty("--tile-h", "160px");
    posterIcons.style.setProperty("--img-h", "110px");
    posterIcons.style.setProperty("--cap-fs", "10.5pt");
    return;
  }}

  const cs = getComputedStyle(posterIcons);
  const gap = parseFloat(cs.gap) || 10;
  const padV = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);

  const maxCols = Math.min(6, count);
  let best = null;

  for (let cols = 1; cols <= maxCols; cols++) {{
    const rows = Math.ceil(count / cols);
    const totalGapsH = gap * (rows - 1);
    const availH = H - padV - totalGapsH;
    if (availH <= 0) continue;

    const tileH = Math.floor(availH / rows);
    if (tileH < 60) continue;

    const capFS = Math.max(8, Math.min(11, Math.floor(tileH * 0.09)));
    const reserveForCaption = Math.ceil(capFS * 2.4) + 12;
    const imgH = Math.max(36, tileH - reserveForCaption);

    const score = imgH * 1000 - cols;
    if (!best || score > best.score) {{
      best = {{ cols, tileH, imgH, capFS, score }};
    }}
  }}

  if (!best) {{
    const cols = Math.min(6, Math.max(1, count));
    const rows = Math.ceil(count / cols);
    const totalGapsH = gap * (rows - 1);
    const availH = Math.max(60, H - padV - totalGapsH);
    const tileH = Math.max(60, Math.floor(availH / rows));
    const capFS = 8;
    const imgH = Math.max(32, tileH - 28);
    best = {{ cols, tileH, imgH, capFS }};
  }}

  posterIcons.style.setProperty("--cols", best.cols);
  posterIcons.style.setProperty("--tile-h", `${{best.tileH}}px`);
  posterIcons.style.setProperty("--img-h", `${{best.imgH}}px`);
  posterIcons.style.setProperty("--cap-fs", `${{best.capFS}}pt`);
}}

{PPTX_JS_HELPERS}

function getDefaultPpeFileBase() {{
  const ws = (document.getElementById("posterWorkstation").textContent || "").trim();
  const job = (document.getElementById("posterJob").textContent || "").trim();
  const raw = ws || job || "Pitch";
  const slug = raw.replace(/[^a-zA-Z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
  return `PPE_Poster_${{slug || "Pitch"}}`;
}}

function openPpeSaveAsModal() {{
  const modal = document.getElementById("ppeSaveAsModal");
  const input = document.getElementById("ppeSaveAsFileName");
  if (input && !input.value.trim()) input.value = getDefaultPpeFileBase();
  if (modal) modal.style.display = "flex";
}}

function closePpeSaveAsModal() {{
  const modal = document.getElementById("ppeSaveAsModal");
  if (modal) modal.style.display = "none";
}}

function exportPpeAs(format) {{
  const input = document.getElementById("ppeSaveAsFileName");
  const raw = (input && input.value.trim()) ? input.value.trim() : getDefaultPpeFileBase();
  const fileBase = raw.replace(/\\.(pptx|pdf|png|jpg|jpeg|doc|docx|html)$/i, "");
  closePpeSaveAsModal();
  if (format === "pptx") {{
    exportPpePptx(fileBase);
    return;
  }}
  if (format === "pdf") {{
    openPrintableWindow();
    return;
  }}
  if (format === "html") {{
    const htmlContent = "<!DOCTYPE html>\\n" + document.documentElement.outerHTML;
    const blob = new Blob([htmlContent], {{ type: "text/html;charset=utf-8" }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${{fileBase}}.html`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return;
  }}
  if (format === "doc") {{
    const jobVal = (document.getElementById("posterJob").textContent || "").trim();
    const wsVal = (document.getElementById("posterWorkstation").textContent || "").trim();
    const secVal = (document.getElementById("posterSection").textContent || "").trim();
    const selectedItems = ppeData.filter(item => selectedPPE.has(item.name));
    const rowsHtml = selectedItems.map(it => `<tr><td style="border:1pt solid #000;padding:4pt;"><b>${{_xmlEsc(it.name)}}</b></td><td style="border:1pt solid #000;padding:4pt;">${{_xmlEsc(it.hazard)}}</td><td style="border:1pt solid #000;padding:4pt;">${{_xmlEsc(it.mitigation)}}</td></tr>`).join("");
    const wordHtml = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40"><head><meta charset="utf-8"><title>${{_xmlEsc(fileBase)}}</title></head><body style="font-family:Arial,sans-serif;"><h2>MINIMUM PPE REQUIREMENTS</h2><p><b>Job:</b> ${{_xmlEsc(jobVal)}} &nbsp;|&nbsp; <b>Workstation:</b> ${{_xmlEsc(wsVal)}} &nbsp;|&nbsp; <b>Section:</b> ${{_xmlEsc(secVal)}}</p><table style="width:100%;border-collapse:collapse;border:1.5pt solid #000;"><thead><tr><th style="border:1pt solid #000;padding:5pt;background:#eef2f7;text-align:left;">PPE Item</th><th style="border:1pt solid #000;padding:5pt;background:#eef2f7;text-align:left;">Hazard</th><th style="border:1pt solid #000;padding:5pt;background:#eef2f7;text-align:left;">Mitigation</th></tr></thead><tbody>${{rowsHtml}}</tbody></table></body></html>`;
    const blob = new Blob(["\\ufeff", wordHtml], {{ type: "application/msword;charset=utf-8" }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${{fileBase}}.doc`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return;
  }}
}}

function printPoster() {{
  fitAll();
  try {{
    if (window.parent && window.parent !== window) {{
      const reqPayload = {{
        posterType: "ppe",
        pitchId: currentPitchId,
        requestedAt: new Date().toISOString()
      }};
      window.parent.postMessage({{ type: "PAAG_JSA_PRINT_REQUEST", payload: reqPayload }}, "*");
      if (window.parent.frames) {{
        for (let i = 0; i < window.parent.frames.length; i++) {{
          try {{
            window.parent.frames[i].postMessage({{ type: "PAAG_JSA_PRINT_REQUEST", payload: reqPayload }}, "*");
          }} catch (fe) {{}}
        }}
      }}
      return;
    }}
  }} catch (e) {{}}
  window.print();
}}
function _legacyPrintPosterNoop() {{
  fitAll();
  window.print();
}}

function openPrintableWindow() {{
  fitAll();
  const w = window.open("", "_blank");
  if (!w) {{
    window.print();
    return;
  }}
  w.document.open();
  w.document.write(document.documentElement.outerHTML);
  w.document.close();
  setTimeout(() => {{
    w.focus();
    w.print();
  }}, 350);
}}

function savePosterJSON() {{
  const data = {{
    jobName: document.getElementById("jobName").value,
    workstation: document.getElementById("workstation").value,
    section: document.getElementById("section").value,
    selectedPPE: Array.from(selectedPPE)
  }};
  const blob = new Blob([JSON.stringify(data, null, 2)], {{ type: "application/json" }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${{data.jobName || "ppe_poster"}}_${{data.workstation || "pitch"}}.json`;
  a.click();
  URL.revokeObjectURL(url);
}}

function importPosterJSON(event) {{
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(e) {{
    try {{
      const data = JSON.parse(e.target.result);
      document.getElementById("jobName").value = data.jobName || "";
      document.getElementById("workstation").value = data.workstation || "";
      document.getElementById("section").value = data.section || "";
      selectedPPE.clear();
      (data.selectedPPE || []).forEach(name => {{
        const normalized = (name === "Chemiclal Resistant Galoshes") ? "Chemical Resistant Galoshes" : name;
        selectedPPE.add(normalized);
      }});
      renderSelectorTiles();
      updatePoster();
    }} catch (err) {{
      alert("Invalid JSON file.");
    }}
  }};
  reader.readAsText(file);
}}

window.addEventListener("message", (event) => {{
  const data = event && event.data;
  if (!data || data.type !== "PAAG_JSA_PPE_SYNC") return;
  if (data.pitchId && currentPitchId && data.pitchId !== currentPitchId) return;
  if (Array.isArray(data.effectivePPE)) {{
    selectedPPE.clear();
    data.effectivePPE.forEach(n => selectedPPE.add(n));
    renderSelectorTiles();
    updatePoster();
  }}
}});
window.addEventListener("resize", fitAll);
window.addEventListener("beforeprint", fitAll);
renderSelectorTiles();
updatePoster();
baselinePpeSnapshot = getPpeSnapshotJson();
checkPpeDirtyState();
</script>
</body>
</html>
"""


def build_jsa_poster_html(
    *,
    pitch_id: str = "",
    section_name: str = "",
    job_title: str = "",
    plant_code: str = "AP1",
    important_notice: str = "",
    effective_ppe_items: list[Any] | None = None,
    jsa_rows: list[dict[str, Any]] | None = None,
    work_elements: list[dict[str, Any]] | None = None,
    pitch_photos: list[dict[str, Any]] | None = None,
    include_pitch_photos: bool = False,
    overrides: list[dict[str, Any]] | None = None,
    min_table_rows: int = 10,
) -> str:
    """Render the portrait Job Safety Analysis (JSA) Poster (FRM-GEA-SAF-085 Rev 0) HTML component."""
    raw_ppe_input: list[str] = []
    if effective_ppe_items:
        for entry in effective_ppe_items:
            if isinstance(entry, dict):
                nm = str(entry.get("canonical_name") or entry.get("name") or "").strip()
                if nm:
                    raw_ppe_input.append(nm)
            elif str(entry or "").strip():
                raw_ppe_input.append(str(entry).strip())

    rollup = resolve_pitch_ppe_rollup(raw_ppe_input)
    effective_names = rollup.get("effective_canonical_names") or rollup["effective_names"]
    override_list = overrides if overrides is not None else rollup.get("overrides", [])

    catalog_js_items: list[dict[str, Any]] = []
    seen_catalog_names: set[str] = set()
    for item in PPE_CATALOG:
        name = str(item["name"])
        seen_catalog_names.add(name)
        catalog_js_items.append(
            {
                "name": name,
                "jsa_image": get_jsa_icon_data_uri(name),
                "card_image": get_ppe_icon_data_uri(name),
                "hazard": str(item.get("hazard") or ""),
                "mitigation": str(item.get("mitigation") or ""),
            }
        )
    for eff_item in rollup["effective_items"]:
        if eff_item["name"] not in seen_catalog_names:
            catalog_js_items.append(
                {
                    "name": eff_item["name"],
                    "jsa_image": "",
                    "card_image": "",
                    "hazard": str(eff_item.get("hazard") or "Task-specific workplace hazard."),
                    "mitigation": str(
                        eff_item.get("mitigation")
                        or f"Correctly wear approved {eff_item['name'].upper()}."
                    ),
                }
            )

    embedded_photos: list[dict[str, str]] = []
    for photo in pitch_photos or []:
        uri = _resolve_media_data_uri(str(photo.get("file_path") or ""))
        if uri:
            embedded_photos.append(
                {
                    "caption": str(photo.get("caption") or "Workstation Photo"),
                    "src": uri,
                }
            )

    default_sec_str = str(section_name or "").strip()
    rows_data: list[dict[str, Any]] = []
    for r in jsa_rows or []:
        j_step = str(r.get("job_step") or "")
        p_haz = str(r.get("potential_hazards") or "")
        p_act = str(r.get("proposed_actions") or "")
        is_auto = bool(r.get("is_auto_ppe_row"))
        has_content = bool(j_step.strip() or p_haz.strip() or p_act.strip() or is_auto)
        rows_data.append(
            {
                "work_element_id": str(r.get("work_element_id") or ""),
                "section_name": str(r.get("section_name") or (default_sec_str if has_content else "")),
                "job_step": j_step,
                "potential_hazards": p_haz,
                "proposed_actions": p_act,
                "is_auto_ppe_row": is_auto,
            }
        )
    if not rows_data:
        rows_data.append(
            {
                "section_name": default_sec_str,
                "job_step": "Put on PPE",
                "potential_hazards": "",
                "proposed_actions": "",
                "is_auto_ppe_row": True,
            }
        )

    while len(rows_data) < max(1, int(min_table_rows)):
        rows_data.append(
            {
                "section_name": "",
                "job_step": "",
                "potential_hazards": "",
                "proposed_actions": "",
                "is_auto_ppe_row": False,
            }
        )

    override_pills_html = ""
    if override_list:
        pills: list[str] = []
        for ov in override_list:
            summary_txt = str(ov.get("summary") or "").strip()
            if summary_txt:
                pills.append(f'<span class="override-pill">⚡ {html.escape(summary_txt)}</span>')
        if pills:
            override_pills_html = (
                '<div class="override-banner no-print">'
                '<strong>Hierarchy Overrides Active:</strong> '
                + " ".join(pills)
                + "</div>"
            )

    ehs_logo_uri = get_ehs_logo_data_uri()
    escaped_job_title = html.escape(job_title or "Enter Job Title")
    escaped_plant_code = html.escape(plant_code or "AP1")
    default_notice = (
        "The JSA should be reviewed by all employees operating this workstation. "
        "This JSA should be reviewed & updated when changes to equipment / processes occur."
    )
    escaped_notice = html.escape(important_notice or default_notice)

    raw_task_source = work_elements if work_elements is not None else [
        r for r in (jsa_rows or [])
        if isinstance(r, dict) and str(r.get("work_element_id") or "").strip() and not bool(r.get("is_auto_ppe_row"))
    ]
    pitch_tasks_js: list[dict[str, Any]] = []
    seen_task_we_ids: set[str] = set()
    for idx_t, t_row in enumerate(raw_task_source or []):
        if not isinstance(t_row, dict):
            continue
        we_id_str = str(t_row.get("work_element_id") or "").strip()
        if not we_id_str or we_id_str in seen_task_we_ids:
            continue
        seen_task_we_ids.add(we_id_str)
        raw_t_ppe = t_row.get("ppe") or []
        norm_t_ppe: list[str] = []
        if isinstance(raw_t_ppe, (list, tuple, set)):
            for p_val in raw_t_ppe:
                c_name = normalize_ppe_name(str(p_val or ""))
                if c_name and c_name not in norm_t_ppe:
                    norm_t_ppe.append(c_name)
        t_label = (
            str(t_row.get("operation") or "").strip()
            or str(t_row.get("job_step") or "").strip()
            or f"Task {len(pitch_tasks_js) + 1}"
        )
        pitch_tasks_js.append(
            {
                "work_element_id": we_id_str,
                "step_number": len(pitch_tasks_js) + 1,
                "label": t_label,
                "job_step": str(t_row.get("job_step") or t_label).strip(),
                "ppe": norm_t_ppe,
            }
        )
    if pitch_tasks_js and effective_names and not any(t["ppe"] for t in pitch_tasks_js):
        for t in pitch_tasks_js:
            t["ppe"] = list(effective_names)

    catalog_json = json.dumps(catalog_js_items)
    selected_json = json.dumps(effective_names)
    pitch_tasks_json = json.dumps(pitch_tasks_js)
    photos_json = json.dumps(embedded_photos)
    rows_json = json.dumps(rows_data)
    pitch_id_json = json.dumps(str(pitch_id or ""))
    section_name_json = json.dumps(default_sec_str)
    initial_show_photos_js = "false"
    try:
        _jsa_style_pref = str(st.session_state.get("pref_jsa_ppe_display_mode", "cards") or "cards")
        _jsa_zoom_pref = str(st.session_state.get("pref_canvas_zoom_default", "fit") or "fit")
    except Exception:
        _jsa_style_pref = "cards"
        _jsa_zoom_pref = "fit"
    initial_use_jsa_icons_js = "true" if _jsa_style_pref == "icons" else "false"
    initial_icon_style_btn_label = "Style: JSA Icons" if _jsa_style_pref == "icons" else "Style: Photo Cards"
    jsa_default_zoom_mode = "manual" if _jsa_zoom_pref == "100%" else "fit"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Job Safety Analysis (JSA) - {escaped_job_title}</title>
<style>
  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }}
  html, body {{
    font-family: Arial, Helvetica, sans-serif;
    margin: 0;
    padding: 8px 12px;
    min-height: 100%;
    height: auto;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    background: #eef2f6;
    color: #111;
  }}
  .toolbar {{
    flex: 0 0 auto;
    width: 100%;
    max-width: 900px;
    margin: 0 auto 8px auto;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 14px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .toolbar-group {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }}
  .btn {{
    padding: 7px 12px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #f8fafc;
    color: #1e293b;
    transition: all 0.15s ease;
  }}
  .btn:hover {{
    background: #e2e8f0;
  }}
  .btn-primary {{
    background: #008a5e;
    color: #ffffff;
    border-color: #00724d;
  }}
  .btn-primary:hover {{
    background: #006e4a;
  }}
  .override-banner {{
    max-width: 900px;
    margin: 0 auto 10px auto;
    background: #f5f3ff;
    border: 1px solid #c4b5fd;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    color: #4c1d95;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }}
  .override-pill {{
    background: #ede9fe;
    border: 1px solid #a78bfa;
    border-radius: 999px;
    padding: 2px 8px;
    font-weight: 600;
  }}
  .selector-drawer {{
    max-width: 900px;
    margin: 0 auto 12px auto;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 12px;
    display: none;
  }}
  .selector-drawer.open {{
    display: block;
  }}
  .selector-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(125px, 1fr));
    gap: 6px;
    max-height: 220px;
    overflow-y: auto;
    margin-top: 8px;
  }}
  .sel-tile {{
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px;
    text-align: center;
    cursor: pointer;
    background: #fff;
    font-size: 11px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }}
  .sel-tile.active {{
    border: 2px solid #008a5e;
    background: #ecfdf5;
    font-weight: 700;
  }}
  .sel-tile img {{
    height: 38px;
    object-fit: contain;
  }}

  /* JSA Sheet (Portrait 8.5 x 11 / 11 x 17 scalable) */
  .jsa-outer-frame {{
    width: 850px;
    min-height: 1100px;
    margin: 0 auto;
    padding: 28px;
    background: repeating-linear-gradient(
      135deg,
      #00b377 0px,
      #00b377 34px,
      #000000 34px,
      #000000 68px
    );
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
  }}
  .jsa-outer-frame.border-purple {{
    background: repeating-linear-gradient(
      135deg,
      #7851a9 0px,
      #7851a9 34px,
      #000000 34px,
      #000000 68px
    );
  }}
  .jsa-inner-sheet {{
    background: #ffffff;
    border: 2px solid #000000;
    min-height: 1044px;
    padding: 14px 18px 16px 18px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}
  .jsa-top-section {{
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .jsa-header-row {{
    display: grid;
    grid-template-columns: 120px 1fr 110px;
    align-items: center;
    gap: 10px;
  }}
  .jsa-plant-code {{
    font-size: 36px;
    font-weight: 900;
    letter-spacing: 0.5px;
    color: #000;
    text-align: left;
    padding-left: 6px;
    outline: none;
  }}
  .jsa-title-block {{
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }}
  .jsa-main-heading {{
    font-size: 26px;
    font-weight: 900;
    letter-spacing: 0.6px;
    margin: 0;
    color: #000;
  }}
  .jsa-job-title-box {{
    border: 1.5px solid #222;
    background: #e5e7eb;
    padding: 4px 14px;
    font-size: 16px;
    font-weight: 700;
    min-width: 360px;
    max-width: 95%;
    text-align: center;
    color: #000;
    outline: none;
  }}
  .jsa-operation-sub {{
    font-size: 16px;
    font-weight: 800;
    color: #000;
    margin-top: 1px;
  }}
  .jsa-logo-box {{
    display: flex;
    justify-content: flex-end;
    align-items: center;
  }}
  .jsa-logo-box img {{
    max-height: 68px;
    max-width: 105px;
    object-fit: contain;
  }}

  /* IMPORTANT Banner */
  .jsa-important-box {{
    border: 1.8px solid #000;
    margin-top: 2px;
  }}
  .jsa-important-header {{
    background: #10c486;
    border-bottom: 1.5px solid #000;
    text-align: center;
    font-weight: 900;
    font-size: 16px;
    padding: 3px 8px;
    letter-spacing: 0.5px;
    color: #000;
  }}
  .jsa-important-body {{
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 700;
    line-height: 1.35;
    color: #000;
    outline: none;
  }}

  /* Middle Visual Area: Add Photos / PPE Icons */
  .jsa-visual-zone {{
    min-height: 215px;
    max-height: 275px;
    margin: 8px 0;
    padding: 8px 10px;
    border: 1px dashed #cbd5e1;
    border-radius: 6px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 12px;
    overflow: hidden;
  }}
  .jsa-visual-empty {{
    font-size: 28px;
    color: #64748b;
    text-align: center;
    font-weight: 500;
  }}
  .jsa-ppe-tile {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: var(--icon-w, 108px);
    padding: 3px;
    text-align: center;
  }}
  .jsa-ppe-tile img {{
    height: var(--icon-h, 88px);
    max-width: 100%;
    object-fit: contain;
  }}
  .jsa-ppe-tile .jsa-ppe-cap {{
    font-size: 9.5px;
    font-weight: 700;
    color: #111;
    margin-top: 2px;
    line-height: 1.15;
  }}
  .jsa-photo-card {{
    display: flex;
    flex-direction: column;
    align-items: center;
    border: 1px solid #94a3b8;
    border-radius: 4px;
    padding: 4px;
    background: #fff;
    max-width: 190px;
  }}
  .jsa-photo-card img {{
    height: var(--photo-h, 120px);
    max-width: 180px;
    object-fit: contain;
  }}
  .jsa-photo-card span {{
    font-size: 9.5px;
    font-weight: 700;
    color: #1e293b;
    margin-top: 3px;
    text-align: center;
    max-width: 175px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}

  /* Job Steps Table */
  .jsa-steps-table {{
    width: 100%;
    border-collapse: collapse;
    border: 2.5px solid #000;
    table-layout: fixed;
    margin-top: 2px;
  }}
  .jsa-steps-table th {{
    border: 1.5px solid #000;
    padding: 6px 8px;
    font-size: 12px;
    font-weight: 900;
    text-align: left;
    text-transform: uppercase;
    background: #ffffff;
    color: #000;
  }}
  .jsa-steps-table td {{
    border: 1.2px solid #000;
    padding: 6px 8px;
    font-size: 11.5px;
    vertical-align: top;
    line-height: 1.3;
    height: 38px;
    color: #000;
    word-wrap: break-word;
    outline: none;
  }}
  .jsa-steps-table tr.auto-ppe-row td {{
    background: #f8fafc;
  }}
  .jsa-steps-table tr.selected-step-row td {{
    background: #eff6ff !important;
  }}
  .jsa-step-cell,
  .jsa-hazard-cell {{
    position: relative;
  }}
  .jsa-action-cell {{
    position: relative;
    padding-right: 26px !important;
  }}
  .jsa-cell-text {{
    outline: none;
    min-height: 22px;
    width: 100%;
  }}
  .jsa-between-hover-zone {{
    position: absolute;
    left: 0;
    right: 0;
    bottom: -8px;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 30;
  }}
  .jsa-between-add-btn {{
    width: 19px;
    height: 19px;
    border-radius: 999px;
    border: 1.5px solid #2563eb;
    background: #ffffff;
    color: #2563eb;
    font-size: 12px;
    font-weight: 800;
    line-height: 1;
    padding: 0;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 1px 4px rgba(37, 99, 235, 0.28);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.12s ease, background 0.12s ease, color 0.12s ease, transform 0.12s ease;
  }}
  .jsa-between-hover-zone:hover .jsa-between-add-btn {{
    opacity: 1;
    pointer-events: auto;
  }}
  .jsa-between-add-btn:hover {{
    background: #2563eb;
    color: #ffffff;
    transform: scale(1.12);
  }}
  .jsa-row-del-btn {{
    position: absolute;
    top: 5px;
    right: 5px;
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #fca5a5;
    background: #fef2f2;
    color: #dc2626;
    font-size: 10px;
    font-weight: 700;
    line-height: 1;
    padding: 0;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.12s ease, background 0.12s ease;
    z-index: 20;
  }}
  .jsa-row-del-btn:hover {{
    opacity: 1 !important;
    background: #fee2e2;
    border-color: #ef4444;
  }}
  #jsaStepsBody tr:hover .jsa-row-del-btn {{
    opacity: 0.85;
    pointer-events: auto;
  }}
  .jsa-table-bottom-add {{
    display: flex;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
    gap: 10px;
    padding: 5px 0 6px 0;
    min-height: 28px;
  }}
  .btn-save-refresh {{
    background: #2563eb;
    color: #ffffff;
    border-color: #1d4ed8;
  }}
  .btn-save-refresh:hover {{
    background: #1d4ed8;
  }}
  .btn-save-refresh.dirty-highlight {{
    background: #ea580c;
    border-color: #c2410c;
    box-shadow: 0 0 0 2px rgba(249, 115, 22, 0.28);
  }}
  .btn-save-refresh.dirty-highlight:hover {{
    background: #c2410c;
  }}
  .jsa-unsaved-banner {{
    display: none;
    max-width: 900px;
    margin: 0 auto 10px auto;
    padding: 8px 14px;
    border-radius: 7px;
    border: 1.5px solid #f97316;
    background: #fff7ed;
    color: #c2410c;
    font-size: 12.5px;
    font-weight: 700;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }}
  .jsa-unsaved-banner.visible {{
    display: flex;
  }}
  .jsa-bottom-unsaved-note {{
    display: none;
    color: #d97706;
    font-size: 12px;
    font-weight: 700;
    align-items: center;
    gap: 8px;
  }}
  .jsa-bottom-unsaved-note.visible {{
    display: inline-flex;
  }}
  .jsa-bottom-add-row-btn {{
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 12px;
    border-radius: 999px;
    border: 1.5px dashed #3b82f6;
    background: #f8fafc;
    color: #1d4ed8;
    font-size: 11.5px;
    font-weight: 700;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.14s ease, background 0.14s ease, border-color 0.14s ease, box-shadow 0.14s ease;
  }}
  .jsa-table-bottom-add:hover .jsa-bottom-add-row-btn,
  .jsa-bottom-add-row-btn:focus-visible {{
    opacity: 1;
  }}
  .jsa-bottom-add-row-btn:hover {{
    opacity: 1;
    background: #eff6ff;
    border-style: solid;
    border-color: #2563eb;
    box-shadow: 0 1px 4px rgba(37, 99, 235, 0.18);
  }}
  .jsa-bottom-add-row-btn .plus-badge {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 999px;
    background: #2563eb;
    color: #ffffff;
    font-size: 12px;
    font-weight: 800;
    line-height: 1;
  }}
  .col-step {{ width: 28%; }}
  .col-hazard {{ width: 33%; }}
  .col-action {{ width: 39%; }}

  /* Bottom Footer & Annual Review Sticker Box */
  .jsa-viewport.zoomed-scroll {{
    scrollbar-width: auto;
    scrollbar-color: #64748b #e2e8f0;
  }}
  .jsa-viewport.zoomed-scroll::-webkit-scrollbar {{
    width: 12px;
    height: 12px;
  }}
  .jsa-viewport.zoomed-scroll::-webkit-scrollbar-track {{
    background: #e2e8f0;
    border-radius: 6px;
  }}
  .jsa-viewport.zoomed-scroll::-webkit-scrollbar-thumb {{
    background: #64748b;
    border-radius: 6px;
    border: 2px solid #e2e8f0;
  }}
  .jsa-viewport.zoomed-scroll::-webkit-scrollbar-thumb:hover {{
    background: #475569;
  }}

  .jsa-footer-row {{
    display: flex;
    justify-content: flex-end;
    margin-top: 12px;
  }}
  .jsa-sticker-box {{
    width: 265px;
    border: 1.5px dashed #64748b;
    text-align: center;
  }}
  .jsa-sticker-area {{
    padding: 8px 10px 6px 10px;
    font-family: "Times New Roman", Times, serif;
    font-size: 13px;
    font-weight: 700;
    color: #cbd5e1;
    line-height: 1.25;
    letter-spacing: 0.4px;
    text-transform: uppercase;
  }}
  .jsa-template-rev {{
    border-top: 1px solid #94a3b8;
    padding: 3px 6px;
    font-size: 9px;
    color: #64748b;
    font-family: Arial, sans-serif;
  }}

  /* Save As Modal */
  .save-as-backdrop {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.52);
    z-index: 9999;
    align-items: flex-start;
    justify-content: center;
    padding: 64px 16px 16px 16px;
  }}
  .save-as-backdrop.open {{
    display: flex;
  }}
  .save-as-modal {{
    background: #ffffff;
    border-radius: 12px;
    border: 1px solid #cbd5e1;
    width: 100%;
    max-width: 480px;
    padding: 18px 20px;
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.25);
  }}
  .save-as-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }}
  .save-as-header h3 {{
    margin: 0;
    font-size: 16px;
    color: #0f172a;
  }}
  .save-as-close {{
    background: transparent;
    border: none;
    font-size: 18px;
    color: #64748b;
    cursor: pointer;
    padding: 2px 6px;
    border-radius: 6px;
  }}
  .save-as-close:hover {{
    background: #f1f5f9;
    color: #0f172a;
  }}
  .save-as-field {{
    margin-bottom: 14px;
  }}
  .save-as-field label {{
    display: block;
    font-size: 12px;
    font-weight: 700;
    color: #334155;
    margin-bottom: 5px;
  }}
  .save-as-field input {{
    width: 100%;
    padding: 8px 10px;
    font-size: 13px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    color: #0f172a;
  }}
  .save-as-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-bottom: 14px;
  }}
  .save-as-option {{
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 3px;
    padding: 10px 12px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #f8fafc;
    cursor: pointer;
    text-align: left;
    transition: all 0.14s ease;
  }}
  .save-as-option:hover {{
    background: #eff6ff;
    border-color: #2563eb;
    box-shadow: 0 2px 6px rgba(37, 99, 235, 0.12);
  }}
  .save-as-option strong {{
    font-size: 13px;
    color: #0f172a;
  }}
  .save-as-option span {{
    font-size: 11px;
    color: #64748b;
  }}

  @page {{
    size: portrait;
    margin: 0.25in;
  }}
  @media print {{
    html, body {{
      background: #ffffff;
      padding: 0 !important;
      margin: 0 !important;
      height: auto !important;
      overflow: visible !important;
      display: block !important;
    }}
    .no-print {{
      display: none !important;
    }}
    .jsa-viewport {{
      overflow: visible !important;
      height: auto !important;
    }}
    #jsaScaleStage {{
      width: auto !important;
      height: auto !important;
    }}
    .jsa-outer-frame {{
      transform: none !important;
      box-shadow: none;
      width: 100%;
      margin: 0 !important;
    }}
    .jsa-visual-zone {{
      border-color: transparent;
    }}
    .jsa-steps-table tr.selected-step-row td {{
      background: transparent !important;
    }}
    .jsa-steps-table tr.auto-ppe-row.selected-step-row td {{
      background: #f8fafc !important;
    }}
    .jsa-action-cell {{
      padding-right: 8px !important;
    }}
  }}
</style>
</head>
<body>

<div class="toolbar no-print">
  <div class="toolbar-group">
    <div style="display:inline-flex; align-items:center; gap:2px; background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:1px 4px;">
      <button type="button" class="btn" style="padding:4px 8px; border:none; background:transparent;" onclick="stepJsaZoom(-0.1)" title="Zoom Out">&#x2796;</button>
      <button type="button" class="btn" id="jsaZoomLabelBtn" style="padding:4px 8px; border:none; background:transparent; min-width:78px; font-variant-numeric:tabular-nums;" onclick="resetJsaZoomFit()" title="Reset zoom to fit window">Fit</button>
      <button type="button" class="btn" style="padding:4px 8px; border:none; background:transparent;" onclick="stepJsaZoom(0.1)" title="Zoom In">&#x2795;</button>
    </div>
    <button class="btn btn-save-refresh" id="btnSaveRefreshJsa" onclick="saveAndRefreshJsa()" title="Save JSA edits to the database and refresh">💾 Save &amp; Refresh</button>
    <button class="btn" id="btnUndoJsa" onclick="undoJsaChanges()" style="display:none;" title="Discard unsaved JSA edits">↶ Undo</button>
    <button class="btn btn-primary" onclick="requestJsaPrint()" title="Open Print &amp; Export Settings for 1 pitch, a Fishbone section, or all pitches">🖨️ Print JSA Poster</button>
    <button class="btn" onclick="openSaveAsModal()">💾 Save As</button>
    <button class="btn" onclick="toggleSelectorDrawer()">🛡️ Add PPE to Task</button>
    <button class="btn" id="btnIconStyle" onclick="toggleIconStyle()">🎨 {initial_icon_style_btn_label}</button>
    <button class="btn" onclick="addBlankStepRow()">➕ Add Blank Row</button>
    <button class="btn" onclick="deleteStepRow()" title="Delete the selected row (or the last row if none is selected)">🗑️ Delete Row</button>
  </div>
</div>

<div class="jsa-unsaved-banner no-print" id="jsaUnsavedBanner">
  <span>⚠️ Unsaved changes on this JSA Poster — click <strong>Save &amp; Refresh</strong> to save your updates before leaving.</span>
  <div style="display:flex; gap:6px; align-items:center;">
    <button type="button" class="btn" style="padding:4px 10px; font-size:11.5px;" onclick="undoJsaChanges()">↶ Discard</button>
    <button type="button" class="btn btn-save-refresh dirty-highlight" style="padding:4px 10px; font-size:11.5px;" onclick="saveAndRefreshJsa()">💾 Save &amp; Refresh</button>
  </div>
</div>

<div class="save-as-backdrop no-print" id="unsavedNavModal" onclick="if(event.target===this) closeUnsavedNavModal()">
  <div class="save-as-modal" role="dialog" aria-modal="true" aria-labelledby="unsavedNavModalTitle">
    <div class="save-as-header">
      <h3 id="unsavedNavModalTitle" style="color:#c2410c;">⚠️ Unsaved JSA Poster Changes</h3>
      <button type="button" class="save-as-close" onclick="closeUnsavedNavModal()" title="Close">✕</button>
    </div>
    <p style="margin:0 0 14px 0; font-size:13px; line-height:1.45; color:#d97706; font-weight:700;">
      You have unsaved edits on this JSA Poster. If you navigate away now without saving, your changes will be lost.
    </p>
    <div style="display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap;">
      <button type="button" class="btn" onclick="closeUnsavedNavModal()">Stay on JSA Poster</button>
      <button type="button" class="btn" style="color:#dc2626; border-color:#fca5a5; background:#fef2f2;" onclick="discardAndContinueNav()">Discard Changes &amp; Leave</button>
      <button type="button" class="btn btn-save-refresh dirty-highlight" onclick="saveAndRefreshJsa()">💾 Save &amp; Refresh</button>
    </div>
  </div>
</div>

<div class="save-as-backdrop no-print" id="saveAsModal" onclick="if(event.target===this) closeSaveAsModal()">
  <div class="save-as-modal" role="dialog" aria-modal="true" aria-labelledby="saveAsModalTitle">
    <div class="save-as-header">
      <h3 id="saveAsModalTitle">💾 Save JSA Poster As</h3>
      <button type="button" class="save-as-close" onclick="closeSaveAsModal()" title="Close">✕</button>
    </div>
    <div class="save-as-field">
      <label for="saveAsFileName">File name</label>
      <input type="text" id="saveAsFileName" value="" placeholder="JSA_Poster" />
    </div>
    <div class="save-as-grid">
      <button type="button" class="save-as-option" onclick="exportJsaAs('pdf')">
        <strong>📄 PDF Document (.pdf)</strong>
        <span>Print / Save as PDF</span>
      </button>
      <button type="button" class="save-as-option" onclick="exportJsaAs('png')">
        <strong>🖼️ PNG Image (.png)</strong>
        <span>High-res lossless image</span>
      </button>
      <button type="button" class="save-as-option" onclick="exportJsaAs('jpg')">
        <strong>📷 JPEG Image (.jpg)</strong>
        <span>Compact photo image</span>
      </button>
      <button type="button" class="save-as-option" onclick="exportJsaAs('doc')">
        <strong>📝 Word Document (.doc)</strong>
        <span>Editable Microsoft Word file</span>
      </button>
      <button type="button" class="save-as-option" onclick="exportJsaAs('pptx')">
        <strong>&#x1F4CA; PowerPoint Slide (.pptx)</strong>
        <span>Editable PowerPoint slide</span>
      </button>
      <button type="button" class="save-as-option" onclick="exportJsaAs('html')">
        <strong>🌐 Web Document (.html)</strong>
        <span>Standalone interactive HTML file</span>
      </button>
    </div>
    <div style="display:flex; justify-content:flex-end;">
      <button type="button" class="btn" onclick="closeSaveAsModal()">Cancel</button>
    </div>
  </div>
</div>

{override_pills_html}

<div class="selector-drawer no-print" id="selectorDrawer">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
    <div>
      <strong style="font-size:12.5px;">&#x1F6E1;&#xFE0F; Select PPE Icons for JSA Poster:</strong>
      <span style="font-size:11.5px;color:#475569;margin-left:6px;">Click any PPE icon to confirm which PAAG task(s) on this pitch require it (so PPE moves with the task if rebalanced).</span>
    </div>
    <button class="btn" onclick="toggleSelectorDrawer()">Close &#x2715;</button>
  </div>
  <div class="selector-grid" id="selectorGrid"></div>
</div>

<div class="save-as-backdrop no-print" id="ppeTaskConfirmModal" onclick="if(event.target===this) closePpeTaskConfirmModal()">
  <div class="save-as-modal" style="max-width:560px; width:95%;" role="dialog" aria-modal="true" aria-labelledby="ppeTaskConfirmTitle">
    <div class="save-as-header">
      <h3 id="ppeTaskConfirmTitle" style="display:flex;align-items:center;gap:8px;margin:0;font-size:15px;color:#0f172a;">&#x1F6E1;&#xFE0F; Confirm Tasks for PPE on JSA Poster</h3>
      <button type="button" class="save-as-close" onclick="closePpeTaskConfirmModal()" title="Close">&#x2715;</button>
    </div>
    <div id="ppeTaskConfirmHero" style="display:flex;align-items:center;gap:12px;padding:10px 12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;margin-bottom:10px;"></div>
    <div id="ppeTaskBundleWrap" style="margin-bottom:10px;">
      <div style="font-size:11.5px;font-weight:700;color:#475569;margin-bottom:5px;">&#x2795; Optional: Also assign additional PPE to the same selected task(s):</div>
      <div id="ppeTaskBundlePills" style="display:flex;flex-wrap:wrap;gap:5px;max-height:84px;overflow-y:auto;padding:2px;"></div>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:6px;">
      <div>
        <div style="font-size:12.5px;font-weight:700;color:#0f172a;">Which PAAG task(s) on this pitch require this PPE?</div>
        <div style="font-size:11px;color:#64748b;">PPE is linked to the checked task(s) so it moves with them if a task changes pitch.</div>
      </div>
      <div style="display:flex;gap:6px;align-items:center;">
        <button type="button" class="btn" style="padding:3px 8px;font-size:11px;" onclick="setAllPpeConfirmTasks(true)">Select All</button>
        <button type="button" class="btn" style="padding:3px 8px;font-size:11px;" onclick="setAllPpeConfirmTasks(false)">Clear All</button>
      </div>
    </div>
    <div id="ppeTaskConfirmList" style="max-height:230px;overflow-y:auto;border:1px solid #cbd5e1;border-radius:8px;padding:6px;background:#ffffff;margin-bottom:8px;display:flex;flex-direction:column;gap:5px;"></div>
    <div id="ppeTaskConfirmError" style="display:none;font-size:11.5px;font-weight:700;color:#dc2626;margin-bottom:8px;">Please select at least one task, or click "Remove from Pitch" to unassign this PPE.</div>
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-top:6px;">
      <div>
        <button type="button" class="btn" id="btnRemovePpeFromPitch" style="display:none;color:#dc2626;border-color:#fca5a5;background:#fef2f2;padding:6px 10px;font-size:12px;" onclick="removeConfirmedPpeFromPitch()">&#x1F5D1;&#xFE0F; Remove from Pitch</button>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;">
        <button type="button" class="btn" onclick="closePpeTaskConfirmModal()">Cancel</button>
        <button type="button" class="btn btn-primary" onclick="applyPpeTaskConfirmation(false)" title="Add to the JSA Poster and keep editing">&#x2713; Confirm &amp; Add to Poster</button>
      </div>
    </div>
  </div>
</div>

<div class="jsa-viewport" id="jsaViewport" style="flex:0 0 auto; min-height:0; width:100%; overflow:hidden; padding:2px 0 10px 0;">
  <div id="jsaScaleStage" style="margin:0 auto; position:relative;">
    <div class="jsa-outer-frame" id="jsaOuterFrame">
  <div class="jsa-inner-sheet">
    <div class="jsa-top-section">
      <div class="jsa-header-row">
        <div class="jsa-plant-code" id="jsaPlantCode" contenteditable="true" title="Click to edit Plant/Building code">{escaped_plant_code}</div>
        <div class="jsa-title-block">
          <h1 class="jsa-main-heading">JOB SAFETY ANALYSIS</h1>
          <div class="jsa-job-title-box" id="jsaJobTitle" contenteditable="true" title="Click to edit Job Title">{escaped_job_title}</div>
          <div class="jsa-operation-sub">Operation</div>
        </div>
        <div class="jsa-logo-box">
          <img src="{ehs_logo_uri}" alt="EHS&S Logo" />
        </div>
      </div>

      <div class="jsa-important-box">
        <div class="jsa-important-header">IMPORTANT</div>
        <div class="jsa-important-body" id="jsaImportantNotice" contenteditable="true" title="Click to edit Important Notice">{escaped_notice}</div>
      </div>

      <div class="jsa-visual-zone" id="jsaVisualZone"></div>

      <table class="jsa-steps-table" id="jsaStepsTable">
        <thead>
          <tr>
            <th class="col-step">JOB STEPS</th>
            <th class="col-hazard">POTENTIAL ERRORS / HAZARDS</th>
            <th class="col-action">ACTION</th>
          </tr>
        </thead>
        <tbody id="jsaStepsBody"></tbody>
      </table>
      <div class="jsa-table-bottom-add no-print">
        <button type="button" class="jsa-bottom-add-row-btn" onclick="addBlankStepRow()" title="Add a new row to the bottom of the JSA table">
          <span class="plus-badge">+</span> Add Row
        </button>
        <span class="jsa-bottom-unsaved-note" id="jsaBottomUnsavedNote">
          ⚠️ Unsaved changes
          <button type="button" class="btn btn-save-refresh dirty-highlight" style="padding:3px 10px; font-size:11px;" onclick="saveAndRefreshJsa()">💾 Save &amp; Refresh</button>
        </span>
      </div>
    </div>

    <div class="jsa-footer-row">
      <div class="jsa-sticker-box">
        <div class="jsa-sticker-area">
          PLACE ANNUAL<br/>REVIEW<br/>STICKER HERE
        </div>
        <div class="jsa-template-rev">
          JSA Template - FRM-GEA-SAF-085 Rev 0 2/28/2024
        </div>
      </div>
    </div>
  </div>
  </div>
  </div>
</div>

<script>
const currentPitchId = {pitch_id_json};
const defaultSectionName = {section_name_json};
const ppeCatalog = {catalog_json};
const initialSelectedPPEList = {selected_json};
const initialPitchTasks = {pitch_tasks_json};
let pitchTasks = JSON.parse(JSON.stringify(initialPitchTasks || []));
let taskPpeByWeId = {{}};
const unassignedPitchPPE = new Set();
function initTaskPpeFromBaseline() {{
  taskPpeByWeId = {{}};
  unassignedPitchPPE.clear();
  pitchTasks.forEach(t => {{
    const wid = String(t.work_element_id || "");
    if (wid) {{
      taskPpeByWeId[wid] = new Set(Array.isArray(t.ppe) ? t.ppe : []);
    }}
  }});
  if (pitchTasks.length === 0) {{
    initialSelectedPPEList.forEach(n => unassignedPitchPPE.add(n));
  }}
}}
initTaskPpeFromBaseline();
const selectedPPE = new Set(initialSelectedPPEList);
function recomputeSelectedPPEFromTasks() {{
  if (pitchTasks.length === 0) {{
    return;
  }}
  selectedPPE.clear();
  Object.values(taskPpeByWeId).forEach(setObj => {{
    if (setObj && typeof setObj.forEach === "function") {{
      setObj.forEach(n => selectedPPE.add(n));
    }}
  }});
  unassignedPitchPPE.forEach(n => selectedPPE.add(n));
}}
function getSerializableTaskPpeMap() {{
  const out = {{}};
  Object.keys(taskPpeByWeId).forEach(wid => {{
    out[wid] = Array.from(taskPpeByWeId[wid] || []);
  }});
  return out;
}}
function getTasksUsingPpe(ppeName) {{
  const matched = [];
  pitchTasks.forEach(t => {{
    const wid = String(t.work_element_id || "");
    const setObj = taskPpeByWeId[wid];
    if (setObj && setObj.has(ppeName)) {{
      matched.push(wid);
    }}
  }});
  return matched;
}}
try {{
  if (currentPitchId) {{
    const cachedTaskMapJson = sessionStorage.getItem("paag_pitch_ppe_tasks_" + currentPitchId);
    if (cachedTaskMapJson && pitchTasks.length > 0) {{
      const parsedMap = JSON.parse(cachedTaskMapJson);
      if (parsedMap && typeof parsedMap === "object") {{
        Object.keys(parsedMap).forEach(wid => {{
          if (Array.isArray(parsedMap[wid]) && taskPpeByWeId[wid]) {{
            taskPpeByWeId[wid] = new Set(parsedMap[wid]);
          }}
        }});
        recomputeSelectedPPEFromTasks();
      }}
    }} else {{
      const cachedPpeJson = sessionStorage.getItem("paag_pitch_ppe_" + currentPitchId);
      if (cachedPpeJson && pitchTasks.length === 0) {{
        const cachedArr = JSON.parse(cachedPpeJson);
        if (Array.isArray(cachedArr)) {{
          selectedPPE.clear();
          cachedArr.forEach(n => selectedPPE.add(n));
        }}
      }}
    }}
  }}
}} catch (e) {{}}
recomputeSelectedPPEFromTasks();
const pitchPhotos = {photos_json};
const initialRows = {rows_json};
const initialPlantCodeText = document.getElementById("jsaPlantCode").textContent.trim();
const initialJobTitleText = document.getElementById("jsaJobTitle").textContent.trim();
const initialNoticeText = document.getElementById("jsaImportantNotice").textContent.trim();
let useJsaIcons = {initial_use_jsa_icons_js};
let showPitchPhotos = {initial_show_photos_js};
let baselineSnapshotJson = "";
let isJsaDirty = false;
let pendingParentNavTarget = null;

const CUT_GLOVE_RANKS = {{
  "Cut Level 1 Gloves": 1,
  "Cut Level 2 Gloves": 2,
  "Cut Level 3 Gloves": 3,
  "Cut Level 4 Gloves": 4,
  "Cut Level 5 Gloves": 5,
  "Cut Level 6 Gloves": 6
}};
const FOOTWEAR_RANKS = {{
  "Sturdy Closed Toe and Heel Shoes": 1,
  "Safety Toe Shoes": 2
}};
const EYE_RANKS = {{
  "Safety Glasses": 1,
  "Foam Lined Safety Glasses": 2
}};
const HEAD_RANKS = {{
  "Bump Cap": 1,
  "Hard Hat": 2
}};

function resolveEffectivePPEList() {{
  let maxCut = 0, maxFoot = 0, maxEye = 0, maxHead = 0;
  selectedPPE.forEach(name => {{
    if (CUT_GLOVE_RANKS[name]) maxCut = Math.max(maxCut, CUT_GLOVE_RANKS[name]);
    if (FOOTWEAR_RANKS[name]) maxFoot = Math.max(maxFoot, FOOTWEAR_RANKS[name]);
    if (EYE_RANKS[name]) maxEye = Math.max(maxEye, EYE_RANKS[name]);
    if (HEAD_RANKS[name]) maxHead = Math.max(maxHead, HEAD_RANKS[name]);
  }});
  return ppeCatalog.filter(item => {{
    if (!selectedPPE.has(item.name)) return false;
    if (CUT_GLOVE_RANKS[item.name] && CUT_GLOVE_RANKS[item.name] < maxCut) return false;
    if (FOOTWEAR_RANKS[item.name] && FOOTWEAR_RANKS[item.name] < maxFoot) return false;
    if (EYE_RANKS[item.name] && EYE_RANKS[item.name] < maxEye) return false;
    if (HEAD_RANKS[item.name] && HEAD_RANKS[item.name] < maxHead) return false;
    return true;
  }});
}}

let pendingConfirmPrimaryPpe = "";
let pendingConfirmBundledPpe = new Set();
let pendingConfirmTaskIds = new Set();

function openPpeTaskConfirmModal(ppeName) {{
  const item = ppeCatalog.find(it => it.name === ppeName);
  if (!item) return;
  if (!pitchTasks || pitchTasks.length === 0) {{
    if (selectedPPE.has(ppeName)) selectedPPE.delete(ppeName);
    else selectedPPE.add(ppeName);
    renderSelectorDrawer();
    renderVisualZone();
    updateAutoPpeRow();
    syncPpeToPoster();
    checkJsaDirtyState();
    return;
  }}

  pendingConfirmPrimaryPpe = ppeName;
  pendingConfirmBundledPpe = new Set([ppeName]);
  const existingTaskIds = getTasksUsingPpe(ppeName);
  const wasAssigned = existingTaskIds.length > 0 || selectedPPE.has(ppeName);

  if (existingTaskIds.length > 0) {{
    pendingConfirmTaskIds = new Set(existingTaskIds);
  }} else if (activeStepRow && activeStepRow.dataset && activeStepRow.dataset.workElementId) {{
    pendingConfirmTaskIds = new Set([String(activeStepRow.dataset.workElementId)]);
  }} else {{
    pendingConfirmTaskIds = new Set(pitchTasks.map(t => String(t.work_element_id)));
  }}

  const removeBtn = document.getElementById("btnRemovePpeFromPitch");
  if (removeBtn) {{
    removeBtn.style.display = wasAssigned ? "inline-flex" : "none";
  }}
  const errEl = document.getElementById("ppeTaskConfirmError");
  if (errEl) errEl.style.display = "none";

  renderPpeTaskConfirmModalContents();
  const modal = document.getElementById("ppeTaskConfirmModal");
  if (modal) modal.classList.add("open");
}}

function closePpeTaskConfirmModal() {{
  const modal = document.getElementById("ppeTaskConfirmModal");
  if (modal) modal.classList.remove("open");
  pendingConfirmPrimaryPpe = "";
  pendingConfirmBundledPpe.clear();
}}

function renderPpeTaskConfirmModalContents() {{
  const item = ppeCatalog.find(it => it.name === pendingConfirmPrimaryPpe);
  if (!item) return;
  const hero = document.getElementById("ppeTaskConfirmHero");
  const imgSrc = (useJsaIcons && item.jsa_image) ? item.jsa_image : item.card_image;
  const bundledList = Array.from(pendingConfirmBundledPpe);
  const extraCount = bundledList.length - 1;
  const titleSuffix = extraCount > 0 ? " + " + extraCount + " more PPE item(s)" : "";
  if (hero) {{
    hero.innerHTML =
      (imgSrc ? `<img src="${{imgSrc}}" alt="${{item.name}}" style="width:52px;height:52px;object-fit:contain;background:#fff;border:1px solid #cbd5e1;border-radius:6px;padding:2px;flex-shrink:0;" />` : "") +
      `<div style="min-width:0;">` +
      `<div style="font-size:14px;font-weight:800;color:#0f172a;">${{item.name}}${{titleSuffix}}</div>` +
      `<div style="font-size:11.5px;color:#475569;margin-top:2px;">Confirm which PAAG task(s) on this pitch require this PPE.</div>` +
      `</div>`;
  }}

  const pillsWrap = document.getElementById("ppeTaskBundlePills");
  if (pillsWrap) {{
    pillsWrap.innerHTML = "";
    ppeCatalog.forEach(catItem => {{
      if (catItem.name === pendingConfirmPrimaryPpe) return;
      const isPicked = pendingConfirmBundledPpe.has(catItem.name);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.style.cssText =
        "display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:999px;font-size:11px;cursor:pointer;" +
        (isPicked
          ? "border:1.5px solid #0284c7;background:#e0f2fe;color:#0369a1;font-weight:700;"
          : "border:1px solid #cbd5e1;background:#f8fafc;color:#334155;font-weight:500;");
      btn.textContent = (isPicked ? "\u2713 " : "+ ") + catItem.name;
      btn.onclick = () => {{
        if (pendingConfirmBundledPpe.has(catItem.name)) {{
          pendingConfirmBundledPpe.delete(catItem.name);
        }} else {{
          pendingConfirmBundledPpe.add(catItem.name);
        }}
        renderPpeTaskConfirmModalContents();
      }};
      pillsWrap.appendChild(btn);
    }});
  }}

  const listEl = document.getElementById("ppeTaskConfirmList");
  if (!listEl) return;
  listEl.innerHTML = "";
  pitchTasks.forEach((task, idx) => {{
    const wid = String(task.work_element_id || "");
    const isChecked = pendingConfirmTaskIds.has(wid);
    const currentTaskPpe = Array.from(taskPpeByWeId[wid] || []);
    const row = document.createElement("div");
    row.style.cssText =
      "display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 10px;border-radius:6px;cursor:pointer;" +
      (isChecked
        ? "border:1.5px solid #008a5e;background:#ecfdf5;"
        : "border:1px solid #e2e8f0;background:#f8fafc;");

    const left = document.createElement("label");
    left.style.cssText = "display:flex;align-items:flex-start;gap:8px;cursor:pointer;flex:1;min-width:0;";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = isChecked;
    cb.style.cssText = "margin-top:2px;width:15px;height:15px;cursor:pointer;accent-color:#008a5e;";
    cb.onchange = () => {{
      if (cb.checked) pendingConfirmTaskIds.add(wid);
      else pendingConfirmTaskIds.delete(wid);
      const errEl = document.getElementById("ppeTaskConfirmError");
      if (errEl && pendingConfirmTaskIds.size > 0) errEl.style.display = "none";
      renderPpeTaskConfirmModalContents();
    }};

    const textCol = document.createElement("div");
    textCol.style.cssText = "min-width:0;flex:1;";
    const stepTitle = document.createElement("div");
    stepTitle.style.cssText = "font-size:12.5px;font-weight:700;color:#0f172a;line-height:1.3;";
    stepTitle.textContent = "Step " + (task.step_number || (idx + 1)) + ": " + (task.label || task.job_step || "Task");
    textCol.appendChild(stepTitle);

    if (currentTaskPpe.length > 0) {{
      const ppeSub = document.createElement("div");
      ppeSub.style.cssText = "font-size:10.5px;color:#475569;margin-top:2px;";
      ppeSub.textContent = "Current PPE: " + currentTaskPpe.join(", ");
      textCol.appendChild(ppeSub);
    }}

    left.appendChild(cb);
    left.appendChild(textCol);

    const onlyBtn = document.createElement("button");
    onlyBtn.type = "button";
    onlyBtn.style.cssText =
      "padding:2px 7px;font-size:10.5px;font-weight:600;border-radius:4px;border:1px solid #cbd5e1;background:#ffffff;color:#0369a1;cursor:pointer;flex-shrink:0;";
    onlyBtn.textContent = "Only this task";
    onlyBtn.title = "Assign only to this single task";
    onlyBtn.onclick = (e) => {{
      e.stopPropagation();
      pendingConfirmTaskIds = new Set([wid]);
      const errEl = document.getElementById("ppeTaskConfirmError");
      if (errEl) errEl.style.display = "none";
      renderPpeTaskConfirmModalContents();
    }};

    row.appendChild(left);
    row.appendChild(onlyBtn);
    listEl.appendChild(row);
  }});
}}

function setAllPpeConfirmTasks(selectAll) {{
  if (selectAll) {{
    pendingConfirmTaskIds = new Set(pitchTasks.map(t => String(t.work_element_id)));
    const errEl = document.getElementById("ppeTaskConfirmError");
    if (errEl) errEl.style.display = "none";
  }} else {{
    pendingConfirmTaskIds.clear();
  }}
  renderPpeTaskConfirmModalContents();
}}

function syncTaskHazardAndActionRowsForAssignedPpe(targetWeIds) {{
  // EHS fills in Potential Errors / Hazards and Action manually; do not auto-populate
}}

function applyPpeTaskConfirmation(saveImmediately) {{
  if (pendingConfirmTaskIds.size === 0) {{
    const errEl = document.getElementById("ppeTaskConfirmError");
    if (errEl) errEl.style.display = "block";
    return;
  }}
  const ppeNamesToApply = Array.from(pendingConfirmBundledPpe);
  pitchTasks.forEach(t => {{
    const wid = String(t.work_element_id || "");
    if (!wid) return;
    if (!taskPpeByWeId[wid]) taskPpeByWeId[wid] = new Set();
    if (pendingConfirmTaskIds.has(wid)) {{
      ppeNamesToApply.forEach(pName => taskPpeByWeId[wid].add(pName));
    }} else if (ppeNamesToApply.length === 1 && ppeNamesToApply[0] === pendingConfirmPrimaryPpe) {{
      taskPpeByWeId[wid].delete(pendingConfirmPrimaryPpe);
    }}
  }});
  ppeNamesToApply.forEach(pName => unassignedPitchPPE.delete(pName));
  recomputeSelectedPPEFromTasks();
  syncTaskHazardAndActionRowsForAssignedPpe(pendingConfirmTaskIds);
  closePpeTaskConfirmModal();
  renderSelectorDrawer();
  renderVisualZone();
  updateAutoPpeRow();
  syncPpeToPoster();
  checkJsaDirtyState();
  if (saveImmediately) {{
    saveAndRefreshJsa();
  }}
}}

function removeConfirmedPpeFromPitch() {{
  if (!pendingConfirmPrimaryPpe) return;
  Object.keys(taskPpeByWeId).forEach(wid => {{
    if (taskPpeByWeId[wid]) {{
      taskPpeByWeId[wid].delete(pendingConfirmPrimaryPpe);
    }}
  }});
  unassignedPitchPPE.delete(pendingConfirmPrimaryPpe);
  recomputeSelectedPPEFromTasks();
  closePpeTaskConfirmModal();
  renderSelectorDrawer();
  renderVisualZone();
  updateAutoPpeRow();
  syncPpeToPoster();
  checkJsaDirtyState();
}}

function renderSelectorDrawer() {{
  const grid = document.getElementById("selectorGrid");
  grid.innerHTML = "";
  const totalTasks = pitchTasks.length;
  ppeCatalog.forEach(item => {{
    const div = document.createElement("div");
    const isSelected = selectedPPE.has(item.name);
    div.className = "sel-tile" + (isSelected ? " active" : "");
    div.title = totalTasks > 0
      ? "Click to confirm which PAAG task(s) on this pitch require " + item.name
      : "Click to toggle " + item.name + " on this pitch";
    const imgSrc = (useJsaIcons && item.jsa_image) ? item.jsa_image : item.card_image;
    let taskBadgeHtml = "";
    if (totalTasks > 0 && isSelected) {{
      const usedCount = getTasksUsingPpe(item.name).length;
      const badgeTxt = usedCount === totalTasks
        ? "All " + totalTasks + " task" + (totalTasks === 1 ? "" : "s")
        : usedCount + "/" + totalTasks + " tasks";
      taskBadgeHtml = `<span style="font-size:9.5px;background:#dcfce7;color:#166534;border:1px solid #86efac;border-radius:999px;padding:1px 6px;font-weight:700;">&#x1F4CB; ${{badgeTxt}}</span>`;
    }}
    div.innerHTML =
      (imgSrc ? `<img src="${{imgSrc}}" alt="${{item.name}}"/>` : "") +
      `<span>${{item.name}}</span>` +
      taskBadgeHtml;
    div.onclick = () => {{
      openPpeTaskConfirmModal(item.name);
    }};
    grid.appendChild(div);
  }});
}}

function renderVisualZone() {{
  const zone = document.getElementById("jsaVisualZone");
  const effective = resolveEffectivePPEList();
  const badgeEl = document.getElementById("ppeCountBadge");
  if (badgeEl) badgeEl.textContent = effective.length;
  zone.innerHTML = "";

  const activePhotos = showPitchPhotos ? pitchPhotos : [];
  const totalItems = effective.length + activePhotos.length;

  if (totalItems === 0) {{
    zone.innerHTML = '<div class="jsa-visual-empty" style="cursor:pointer;" title="Click to choose PPE icons and confirm tasks" onclick="toggleSelectorDrawer()">Add PPE Icons</div>';
    return;
  }}

  // Dynamically scale icon height based on how many icons + photos are shown
  let iconH = 105;
  let iconW = 115;
  if (totalItems > 8) {{ iconH = 74; iconW = 88; }}
  else if (totalItems > 5) {{ iconH = 88; iconW = 100; }}
  zone.style.setProperty("--icon-h", iconH + "px");
  zone.style.setProperty("--icon-w", iconW + "px");
  zone.style.setProperty("--photo-h", Math.min(135, iconH + 22) + "px");

  effective.forEach(item => {{
    const tile = document.createElement("div");
    tile.className = "jsa-ppe-tile";
    tile.style.cursor = "pointer";
    tile.title = item.name + " - click to view or update which pitch tasks require this PPE";
    tile.onclick = () => openPpeTaskConfirmModal(item.name);
    const src = (useJsaIcons && item.jsa_image) ? item.jsa_image : item.card_image;
    if (src) {{
      const img = document.createElement("img");
      img.src = src;
      img.alt = item.name;
      tile.appendChild(img);
    }} else {{
      const cap = document.createElement("div");
      cap.className = "jsa-ppe-cap";
      cap.textContent = item.name;
      tile.appendChild(cap);
    }}
    zone.appendChild(tile);
  }});

  activePhotos.forEach(photo => {{
    const card = document.createElement("div");
    card.className = "jsa-photo-card";
    const img = document.createElement("img");
    img.src = photo.src;
    img.alt = photo.caption;
    const span = document.createElement("span");
    span.textContent = photo.caption;
    card.appendChild(img);
    card.appendChild(span);
    zone.appendChild(card);
  }});
}}

let activeStepRow = null;

function selectStepRow(tr) {{
  document.querySelectorAll("#jsaStepsBody tr.selected-step-row").forEach(r => {{
    r.classList.remove("selected-step-row");
  }});
  activeStepRow = tr;
  if (tr) tr.classList.add("selected-step-row");
}}

function removeStepRow(tr) {{
  if (!tr) return;
  if (activeStepRow === tr) activeStepRow = null;
  tr.remove();
  checkJsaDirtyState();
}}

function insertStepRowAfter(referenceTr) {{
  const tbody = document.getElementById("jsaStepsBody");
  const newTr = createStepRowElement({{ job_step: "", potential_hazards: "", proposed_actions: "" }});
  if (referenceTr && referenceTr.parentNode === tbody) {{
    referenceTr.insertAdjacentElement("afterend", newTr);
  }} else {{
    tbody.appendChild(newTr);
  }}
  selectStepRow(newTr);
  const firstEditable = newTr.querySelector(".jsa-cell-text");
  if (firstEditable) firstEditable.focus();
  checkJsaDirtyState();
}}

function bindRowButtons(tr) {{
  tr.addEventListener("click", () => selectStepRow(tr));
  tr.addEventListener("focusin", () => selectStepRow(tr));
  tr.querySelectorAll(".jsa-between-add-btn, .jsa-row-add-btn").forEach((btn) => {{
    btn.onclick = (e) => {{
      e.stopPropagation();
      insertStepRowAfter(tr);
    }};
  }});
  const delBtn = tr.querySelector(".jsa-row-del-btn");
  if (delBtn) {{
    delBtn.onclick = (e) => {{
      e.stopPropagation();
      removeStepRow(tr);
    }};
  }}
}}

function createStepRowElement(row) {{
  const tr = document.createElement("tr");
  if (row && row.is_auto_ppe_row) tr.className = "auto-ppe-row";
  tr.dataset.workElementId = (row && row.work_element_id) ? String(row.work_element_id) : "";

  const tdStep = document.createElement("td");
  tdStep.className = "jsa-step-cell";
  const divStep = document.createElement("div");
  divStep.className = "jsa-cell-text";
  divStep.contentEditable = "true";
  divStep.textContent = (row && row.job_step) || "";
  tdStep.appendChild(divStep);

  const betweenZoneStep = document.createElement("div");
  betweenZoneStep.className = "jsa-between-hover-zone no-print";
  const betweenBtnLeft = document.createElement("button");
  betweenBtnLeft.type = "button";
  betweenBtnLeft.className = "jsa-between-add-btn no-print";
  betweenBtnLeft.title = "Insert a row below this line";
  betweenBtnLeft.textContent = "+";
  betweenZoneStep.appendChild(betweenBtnLeft);
  tdStep.appendChild(betweenZoneStep);

  const tdHaz = document.createElement("td");
  tdHaz.className = "jsa-hazard-cell";
  const divHaz = document.createElement("div");
  divHaz.className = "jsa-cell-text";
  divHaz.contentEditable = "true";
  divHaz.textContent = (row && row.potential_hazards) || "";
  tdHaz.appendChild(divHaz);

  const betweenZoneHaz = document.createElement("div");
  betweenZoneHaz.className = "jsa-between-hover-zone no-print";
  const betweenBtnCenter = document.createElement("button");
  betweenBtnCenter.type = "button";
  betweenBtnCenter.className = "jsa-between-add-btn no-print";
  betweenBtnCenter.title = "Insert a row below this line";
  betweenBtnCenter.textContent = "+";
  betweenZoneHaz.appendChild(betweenBtnCenter);
  tdHaz.appendChild(betweenZoneHaz);

  const tdAct = document.createElement("td");
  tdAct.className = "jsa-action-cell";
  const divAct = document.createElement("div");
  divAct.className = "jsa-cell-text";
  divAct.contentEditable = "true";
  divAct.textContent = (row && row.proposed_actions) || "";
  if (row && row.is_auto_ppe_row) divAct.id = "autoPpeActionCell";
  tdAct.appendChild(divAct);

  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.className = "jsa-row-del-btn no-print";
  delBtn.title = "Delete this row";
  delBtn.textContent = "✕";
  tdAct.appendChild(delBtn);

  tr.appendChild(tdStep);
  tr.appendChild(tdHaz);
  tr.appendChild(tdAct);
  bindRowButtons(tr);
  return tr;
}}

function renderStepsTable() {{
  const tbody = document.getElementById("jsaStepsBody");
  if (tbody.children.length > 0) {{
    tbody.querySelectorAll("tr").forEach((tr) => {{
      tr.classList.remove("selected-step-row");
      bindRowButtons(tr);
    }});
    return;
  }}
  tbody.innerHTML = "";
  activeStepRow = null;
  initialRows.forEach((row) => {{
    tbody.appendChild(createStepRowElement(row));
  }});
}}

function syncPpeToPoster() {{
  const effectiveNames = resolveEffectivePPEList().map(i => i.name);
  try {{
    if (currentPitchId) {{
      sessionStorage.setItem("paag_pitch_ppe_" + currentPitchId, JSON.stringify(effectiveNames));
      sessionStorage.setItem("paag_pitch_ppe_tasks_" + currentPitchId, JSON.stringify(getSerializableTaskPpeMap()));
    }}
  }} catch (e) {{}}
  try {{
    if (window.parent && window.parent !== window) {{
      window.parent.postMessage({{
        type: "PAAG_JSA_PPE_SYNC",
        pitchId: currentPitchId,
        effectivePPE: effectiveNames
      }}, "*");
      if (window.parent.frames) {{
        for (let i = 0; i < window.parent.frames.length; i++) {{
          try {{
            window.parent.frames[i].postMessage({{
              type: "PAAG_JSA_PPE_SYNC",
              pitchId: currentPitchId,
              effectivePPE: effectiveNames
            }}, "*");
          }} catch (fe) {{}}
        }}
      }}
    }}
  }} catch (e) {{}}
}}

function updateAutoPpeRow() {{
  // EHS fills in Potential Errors / Hazards and Action manually; do not auto-populate
}}

function addBlankStepRow() {{
  const tbody = document.getElementById("jsaStepsBody");
  const tr = createStepRowElement({{ job_step: "", potential_hazards: "", proposed_actions: "" }});
  tbody.appendChild(tr);
  selectStepRow(tr);
  const firstEditable = tr.querySelector(".jsa-cell-text");
  if (firstEditable) firstEditable.focus();
  checkJsaDirtyState();
}}

function deleteStepRow() {{
  const tbody = document.getElementById("jsaStepsBody");
  if (activeStepRow && tbody.contains(activeStepRow)) {{
    removeStepRow(activeStepRow);
    return;
  }}
  if (tbody.lastElementChild) {{
    removeStepRow(tbody.lastElementChild);
  }}
}}

function toggleSelectorDrawer() {{
  document.getElementById("selectorDrawer").classList.toggle("open");
  if (typeof applyJsaZoom === "function") applyJsaZoom();
}}

function toggleIconStyle() {{
  useJsaIcons = !useJsaIcons;
  document.getElementById("btnIconStyle").textContent = useJsaIcons
    ? "🎨 Style: JSA Icons"
    : "🎨 Style: Photo Cards";
  renderSelectorDrawer();
  renderVisualZone();
}}

function togglePhotos() {{
  showPitchPhotos = !showPitchPhotos;
  renderVisualZone();
}}

function toggleBorderTheme() {{
  document.getElementById("jsaOuterFrame").classList.toggle("border-purple");
}}

function getDefaultFileBase() {{
  const rawTitle = (document.getElementById("jsaJobTitle").textContent || "").trim();
  const slug = rawTitle.replace(/[^a-zA-Z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
  return `JSA_${{slug || "Poster"}}`;
}}

function openSaveAsModal() {{
  const modal = document.getElementById("saveAsModal");
  const input = document.getElementById("saveAsFileName");
  if (input && !input.value.trim()) {{
    input.value = getDefaultFileBase();
  }}
  if (modal) modal.classList.add("open");
}}

function closeSaveAsModal() {{
  const modal = document.getElementById("saveAsModal");
  if (modal) modal.classList.remove("open");
}}

function getCleanFileBase() {{
  const input = document.getElementById("saveAsFileName");
  const raw = (input && input.value.trim()) ? input.value.trim() : getDefaultFileBase();
  return raw.replace(/\\.(pptx|pdf|png|jpg|jpeg|doc|docx|html)$/i, "");
}}

function triggerBlobDownload(blob, filename) {{
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}}

function requestJsaPrint() {{
  try {{
    if (window.parent && window.parent !== window) {{
      const reqPayload = {{
        posterType: "jsa",
        pitchId: currentPitchId,
        useJsaIcons: Boolean(useJsaIcons),
        requestedAt: new Date().toISOString()
      }};
      window.parent.postMessage({{ type: "PAAG_JSA_PRINT_REQUEST", payload: reqPayload }}, "*");
      if (window.parent.frames) {{
        for (let i = 0; i < window.parent.frames.length; i++) {{
          try {{
            window.parent.frames[i].postMessage({{ type: "PAAG_JSA_PRINT_REQUEST", payload: reqPayload }}, "*");
          }} catch (fe) {{}}
        }}
      }}
      return;
    }}
  }} catch (e) {{}}
  window.print();
}}

function openPrintableJSA() {{
  const modal = document.getElementById("saveAsModal");
  if (modal) modal.classList.remove("open");
  const w = window.open("", "_blank");
  if (!w) {{
    window.print();
    return;
  }}
  w.document.open();
  w.document.write("<!DOCTYPE html>\\n" + document.documentElement.outerHTML);
  w.document.close();
  setTimeout(() => {{
    w.focus();
    w.print();
  }}, 350);
}}

function collectCurrentStepRows() {{
  const stepRows = [];
  document.querySelectorAll("#jsaStepsBody tr").forEach(tr => {{
    const cells = tr.querySelectorAll("td");
    if (cells.length === 3) {{
      const stepEl = cells[0].querySelector(".jsa-cell-text") || cells[0];
      const hazEl = cells[1].querySelector(".jsa-cell-text") || cells[1];
      const actEl = cells[2].querySelector(".jsa-cell-text") || cells[2];
      stepRows.push({{
        work_element_id: tr.dataset.workElementId || "",
        job_step: stepEl.textContent.trim(),
        potential_hazards: hazEl.textContent.trim(),
        proposed_actions: actEl.textContent.trim(),
        is_auto_ppe_row: tr.classList.contains("auto-ppe-row")
      }});
    }}
  }});
  return stepRows;
}}

function getCurrentJsaSnapshotJson() {{
  const sortedTaskMap = {{}};
  Object.keys(taskPpeByWeId).sort().forEach(wid => {{
    sortedTaskMap[wid] = Array.from(taskPpeByWeId[wid] || []).slice().sort();
  }});
  return JSON.stringify({{
    plantCode: (document.getElementById("jsaPlantCode").textContent || "").trim(),
    jobTitle: (document.getElementById("jsaJobTitle").textContent || "").trim(),
    importantNotice: (document.getElementById("jsaImportantNotice").textContent || "").trim(),
    ppe: Array.from(selectedPPE).slice().sort(),
    taskPpe: sortedTaskMap,
    steps: collectCurrentStepRows()
  }});
}}

function updateUnsavedUi(dirty) {{
  isJsaDirty = Boolean(dirty);
  const banner = document.getElementById("jsaUnsavedBanner");
  const bottomNote = document.getElementById("jsaBottomUnsavedNote");
  const saveBtn = document.getElementById("btnSaveRefreshJsa");
  const undoBtn = document.getElementById("btnUndoJsa");
  if (banner) banner.classList.toggle("visible", isJsaDirty);
  if (bottomNote) bottomNote.classList.toggle("visible", isJsaDirty);
  if (saveBtn) saveBtn.classList.toggle("dirty-highlight", isJsaDirty);
  if (undoBtn) undoBtn.style.display = isJsaDirty ? "inline-block" : "none";
  if (typeof applyJsaZoom === "function") applyJsaZoom();
}}

function checkJsaDirtyState() {{
  if (!baselineSnapshotJson) return;
  const currentJson = getCurrentJsaSnapshotJson();
  updateUnsavedUi(currentJson !== baselineSnapshotJson);
}}

function undoJsaChanges() {{
  document.getElementById("jsaPlantCode").textContent = initialPlantCodeText;
  document.getElementById("jsaJobTitle").textContent = initialJobTitleText;
  document.getElementById("jsaImportantNotice").textContent = initialNoticeText;
  initTaskPpeFromBaseline();
  selectedPPE.clear();
  initialSelectedPPEList.forEach(n => selectedPPE.add(n));
  recomputeSelectedPPEFromTasks();
  try {{
    if (currentPitchId) {{
      sessionStorage.removeItem("paag_pitch_ppe_" + currentPitchId);
      sessionStorage.removeItem("paag_pitch_ppe_tasks_" + currentPitchId);
    }}
  }} catch (e) {{}}
  syncPpeToPoster();
  renderSelectorDrawer();
  renderVisualZone();
  const tbody = document.getElementById("jsaStepsBody");
  tbody.innerHTML = "";
  activeStepRow = null;
  initialRows.forEach((row) => {{
    tbody.appendChild(createStepRowElement(row));
  }});
  baselineSnapshotJson = getCurrentJsaSnapshotJson();
  updateUnsavedUi(false);
  closeUnsavedNavModal();
}}

function saveAndRefreshJsa() {{
  const payload = {{
    pitchId: currentPitchId,
    plantCode: (document.getElementById("jsaPlantCode").textContent || "").trim(),
    jobTitle: (document.getElementById("jsaJobTitle").textContent || "").trim(),
    importantNotice: (document.getElementById("jsaImportantNotice").textContent || "").trim(),
    effectivePPE: resolveEffectivePPEList().map(i => i.name),
    ppeByWorkElement: getSerializableTaskPpeMap(),
    steps: collectCurrentStepRows()
  }};
  try {{
    if (currentPitchId) {{
      sessionStorage.removeItem("paag_pitch_ppe_" + currentPitchId);
      sessionStorage.removeItem("paag_pitch_ppe_tasks_" + currentPitchId);
    }}
  }} catch (e) {{}}
  syncPpeToPoster();
  baselineSnapshotJson = getCurrentJsaSnapshotJson();
  updateUnsavedUi(false);
  closeUnsavedNavModal();
  try {{
    if (window.parent && window.parent !== window) {{
      window.parent.postMessage({{ type: "PAAG_JSA_SAVE", payload }}, "*");
    }}
  }} catch (err) {{
    console.error("Failed to send JSA save message:", err);
  }}
}}

function openUnsavedNavModal(targetEl) {{
  pendingParentNavTarget = targetEl || null;
  const modal = document.getElementById("unsavedNavModal");
  if (modal) modal.classList.add("open");
  try {{
    if (window.frameElement) {{
      window.frameElement.scrollIntoView({{ behavior: "smooth", block: "start" }});
    }}
  }} catch (e) {{}}
}}

function closeUnsavedNavModal() {{
  const modal = document.getElementById("unsavedNavModal");
  if (modal) modal.classList.remove("open");
  pendingParentNavTarget = null;
}}

function discardAndContinueNav() {{
  const target = pendingParentNavTarget;
  updateUnsavedUi(false);
  closeUnsavedNavModal();
  if (target && typeof target.click === "function") {{
    setTimeout(() => {{
      try {{ target.click(); }} catch (e) {{}}
    }}, 30);
  }}
}}

function exportJsaWordDoc(fileBase) {{
  const plantCode = document.getElementById("jsaPlantCode").textContent.trim();
  const jobTitle = document.getElementById("jsaJobTitle").textContent.trim();
  const notice = document.getElementById("jsaImportantNotice").textContent.trim();
  const logoImg = document.querySelector(".jsa-logo-box img");
  const logoSrc = logoImg ? logoImg.src : "";
  const effective = resolveEffectivePPEList();
  const rows = collectCurrentStepRows();

  const esc = (s) => String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

  const ppeCellsHtml = effective.map(item => {{
    const src = (useJsaIcons && item.jsa_image) ? item.jsa_image : item.card_image;
    if (src) {{
      return `<td style="border:none;padding:6px;text-align:center;"><img src="${{src}}" width="85" height="85" style="width:85px;height:85px;object-fit:contain;" /><div style="font-size:8.5pt;font-weight:bold;">${{esc(item.name)}}</div></td>`;
    }}
    return `<td style="border:none;padding:6px;text-align:center;font-weight:bold;font-size:9pt;">${{esc(item.name)}}</td>`;
  }}).join("");

  const rowsHtml = rows.map(r => `
    <tr>
      <td style="border:1pt solid #000;padding:5pt 6pt;font-size:10pt;vertical-align:top;">${{esc(r.job_step)}}</td>
      <td style="border:1pt solid #000;padding:5pt 6pt;font-size:10pt;vertical-align:top;">${{esc(r.potential_hazards)}}</td>
      <td style="border:1pt solid #000;padding:5pt 6pt;font-size:10pt;vertical-align:top;">${{esc(r.proposed_actions)}}</td>
    </tr>
  `).join("");

  const wordHtml = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
  <head><meta charset="utf-8"><title>${{esc(jobTitle)}}</title>
  <style>
    @page {{ size: 8.5in 11in; margin: 0.4in; }}
    body {{ font-family: Arial, sans-serif; color: #000; }}
    table {{ border-collapse: collapse; width: 100%; }}
  </style>
  </head>
  <body>
    <table style="border:2pt solid #000;margin-bottom:8pt;">
      <tr>
        <td style="border:1.5pt solid #000;width:24%;text-align:center;font-size:28pt;font-weight:bold;padding:8pt;">${{esc(plantCode)}}</td>
        <td style="border:1.5pt solid #000;width:52%;text-align:center;padding:6pt;">
          <div style="font-size:16pt;font-weight:bold;">JOB SAFETY ANALYSIS</div>
          <div style="border:1.5pt solid #000;padding:4pt;margin-top:4pt;font-size:11pt;font-weight:bold;">${{esc(jobTitle)}}</div>
          <div style="font-size:9pt;font-weight:bold;margin-top:2pt;">Operation</div>
        </td>
        <td style="border:1.5pt solid #000;width:24%;text-align:center;padding:6pt;">
          ${{logoSrc ? `<img src="${{logoSrc}}" width="120" style="max-width:120px;" />` : "EHS&amp;S"}}
        </td>
      </tr>
    </table>
    <table style="border:1.5pt solid #000;margin-bottom:8pt;">
      <tr><td style="background:#f1f5f9;border-bottom:1.5pt solid #000;text-align:center;font-weight:bold;font-size:11pt;padding:3pt;">IMPORTANT</td></tr>
      <tr><td style="text-align:center;font-weight:bold;font-size:10pt;padding:6pt;">${{esc(notice)}}</td></tr>
    </table>
    ${{ppeCellsHtml ? `<table style="margin-bottom:8pt;"><tr>${{ppeCellsHtml}}</tr></table>` : ""}}
    <table style="border:2pt solid #000;">
      <thead>
        <tr>
          <th style="border:1.5pt solid #000;padding:5pt;text-align:left;width:28%;font-size:10pt;">JOB STEPS</th>
          <th style="border:1.5pt solid #000;padding:5pt;text-align:left;width:33%;font-size:10pt;">POTENTIAL ERRORS / HAZARDS</th>
          <th style="border:1.5pt solid #000;padding:5pt;text-align:left;width:39%;font-size:10pt;">ACTION</th>
        </tr>
      </thead>
      <tbody>${{rowsHtml}}</tbody>
    </table>
    <div style="text-align:right;margin-top:10pt;font-size:8pt;color:#475569;">JSA Template - FRM-GEA-SAF-085 Rev 0 2/28/2024</div>
  </body></html>`;

  const blob = new Blob(["\\ufeff", wordHtml], {{ type: "application/msword;charset=utf-8" }});
  triggerBlobDownload(blob, `${{fileBase}}.doc`);
}}

function wrapCanvasText(ctx, text, maxWidth) {{
  const rawLines = String(text || "").split(/\\r?\\n/);
  const lines = [];
  rawLines.forEach(raw => {{
    const words = raw.split(/\\s+/).filter(Boolean);
    if (words.length === 0) {{
      lines.push("");
      return;
    }}
    let current = words[0];
    for (let i = 1; i < words.length; i++) {{
      const test = current + " " + words[i];
      if (ctx.measureText(test).width <= maxWidth) {{
        current = test;
      }} else {{
        lines.push(current);
        current = words[i];
      }}
    }}
    lines.push(current);
  }});
  return lines.length ? lines : [""];
}}

function loadImageElement(src) {{
  return new Promise((resolve) => {{
    if (!src) {{ resolve(null); return; }}
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  }});
}}

async function renderJsaPosterToCanvas() {{
  const scale = 2;
  const W = 850;
  const pad = 26;
  const innerW = W - pad * 2;
  const contentPad = 14;
  const contentW = innerW - contentPad * 2;

  const plantCode = document.getElementById("jsaPlantCode").textContent.trim();
  const jobTitle = document.getElementById("jsaJobTitle").textContent.trim();
  const notice = document.getElementById("jsaImportantNotice").textContent.trim();
  const effective = resolveEffectivePPEList();
  const rows = collectCurrentStepRows();

  const logoEl = document.querySelector(".jsa-logo-box img");
  const logoImg = await loadImageElement(logoEl ? logoEl.src : "");
  const ppeImgs = await Promise.all(effective.map(item => {{
    const src = (useJsaIcons && item.jsa_image) ? item.jsa_image : item.card_image;
    return loadImageElement(src);
  }}));

  const measureCanvas = document.createElement("canvas");
  const mctx = measureCanvas.getContext("2d");

  const colStepW = Math.floor(contentW * 0.28);
  const colHazW = Math.floor(contentW * 0.33);
  const colActW = contentW - colStepW - colHazW;

  mctx.font = "12px Arial";
  const measuredRows = rows.map(r => {{
    const sLines = wrapCanvasText(mctx, r.job_step, colStepW - 16);
    const hLines = wrapCanvasText(mctx, r.potential_hazards, colHazW - 16);
    const aLines = wrapCanvasText(mctx, r.proposed_actions, colActW - 16);
    const maxL = Math.max(sLines.length, hLines.length, aLines.length, 1);
    const rowH = Math.max(38, maxL * 16 + 14);
    return {{ ...r, sLines, hLines, aLines, rowH }};
  }});

  const headerH = 104;
  const impH = 68;
  const visualH = effective.length > 0 ? 156 : 70;
  const tableHeaderH = 30;
  const tableRowsH = measuredRows.reduce((acc, r) => acc + r.rowH, 0);
  const footerH = 92;
  const innerH = Math.max(1030, contentPad * 2 + headerH + 8 + impH + 8 + visualH + 8 + tableHeaderH + tableRowsH + 14 + footerH);
  const H = innerH + pad * 2;

  const canvas = document.createElement("canvas");
  canvas.width = W * scale;
  canvas.height = H * scale;
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);

  // Striped outer border (#00965e and #111111)
  ctx.fillStyle = "#00965e";
  ctx.fillRect(0, 0, W, H);
  ctx.save();
  ctx.fillStyle = "#111111";
  const stripeW = 24;
  for (let offset = -H; offset < W + H; offset += stripeW * 2) {{
    ctx.beginPath();
    ctx.moveTo(offset, 0);
    ctx.lineTo(offset + stripeW, 0);
    ctx.lineTo(offset + stripeW - H, H);
    ctx.lineTo(offset - H, H);
    ctx.closePath();
    ctx.fill();
  }}
  ctx.restore();

  // Inner white sheet
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(pad, pad, innerW, innerH);
  ctx.strokeStyle = "#000000";
  ctx.lineWidth = 2;
  ctx.strokeRect(pad, pad, innerW, innerH);

  let y = pad + contentPad;
  const x = pad + contentPad;

  // Top Header Row
  const plantW = Math.floor(contentW * 0.24);
  const logoW = Math.floor(contentW * 0.24);
  const titleW = contentW - plantW - logoW - 16;

  // Plant Code Box
  ctx.lineWidth = 2.2;
  ctx.strokeRect(x, y, plantW, headerH);
  ctx.fillStyle = "#000000";
  ctx.font = "bold 46px Arial";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(plantCode, x + plantW / 2, y + headerH / 2);

  // Title Block
  const titleX = x + plantW + 8;
  ctx.font = "900 22px Arial";
  ctx.fillText("JOB SAFETY ANALYSIS", titleX + titleW / 2, y + 18);
  ctx.lineWidth = 2;
  ctx.strokeRect(titleX, y + 32, titleW, 46);
  ctx.font = "bold 14px Arial";
  const titleLines = wrapCanvasText(ctx, jobTitle, titleW - 14).slice(0, 2);
  titleLines.forEach((line, idx) => {{
    const ty = titleLines.length === 1 ? (y + 55) : (y + 47 + idx * 16);
    ctx.fillText(line, titleX + titleW / 2, ty);
  }});
  ctx.font = "bold 12px Arial";
  ctx.fillText("Operation", titleX + titleW / 2, y + 90);

  // Logo Box
  const logoX = titleX + titleW + 8;
  ctx.strokeRect(logoX, y, logoW, headerH);
  if (logoImg) {{
    const ratio = Math.min((logoW - 16) / logoImg.width, (headerH - 16) / logoImg.height);
    const dw = logoImg.width * ratio;
    const dh = logoImg.height * ratio;
    ctx.drawImage(logoImg, logoX + (logoW - dw) / 2, y + (headerH - dh) / 2, dw, dh);
  }}

  y += headerH + 8;

  // IMPORTANT Box
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, contentW, impH);
  ctx.beginPath();
  ctx.moveTo(x, y + 24);
  ctx.lineTo(x + contentW, y + 24);
  ctx.stroke();
  ctx.font = "900 14px Arial";
  ctx.fillText("IMPORTANT", x + contentW / 2, y + 13);
  ctx.font = "bold 12.5px Arial";
  const noticeLines = wrapCanvasText(ctx, notice, contentW - 24).slice(0, 2);
  noticeLines.forEach((line, idx) => {{
    ctx.fillText(line, x + contentW / 2, y + 38 + idx * 16);
  }});

  y += impH + 8;

  // Visual PPE Zone
  if (effective.length > 0) {{
    const count = effective.length;
    const itemW = Math.min(125, Math.floor((contentW - 16) / count));
    const totalRowW = itemW * count;
    let ix = x + (contentW - totalRowW) / 2;
    effective.forEach((item, idx) => {{
      const img = ppeImgs[idx];
      if (img) {{
        const maxH = 115;
        const maxW = itemW - 8;
        const r = Math.min(maxW / img.width, maxH / img.height);
        const dw = img.width * r;
        const dh = img.height * r;
        ctx.drawImage(img, ix + (itemW - dw) / 2, y + (visualH - dh) / 2, dw, dh);
      }} else {{
        ctx.font = "bold 11px Arial";
        ctx.fillText(item.name, ix + itemW / 2, y + visualH / 2);
      }}
      ix += itemW;
    }});
  }}
  y += visualH + 8;

  // Job Steps Table
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, contentW, tableHeaderH + tableRowsH);

  // Header row
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(x, y, contentW, tableHeaderH);
  ctx.strokeRect(x, y, colStepW, tableHeaderH);
  ctx.strokeRect(x + colStepW, y, colHazW, tableHeaderH);
  ctx.strokeRect(x + colStepW + colHazW, y, colActW, tableHeaderH);
  ctx.fillStyle = "#000000";
  ctx.font = "900 12px Arial";
  ctx.fillText("JOB STEPS", x + 8, y + 8);
  ctx.fillText("POTENTIAL ERRORS / HAZARDS", x + colStepW + 8, y + 8);
  ctx.fillText("ACTION", x + colStepW + colHazW + 8, y + 8);
  y += tableHeaderH;

  // Body rows
  ctx.lineWidth = 1.2;
  measuredRows.forEach(r => {{
    if (r.is_auto_ppe_row) {{
      ctx.fillStyle = "#f8fafc";
      ctx.fillRect(x, y, contentW, r.rowH);
    }}
    ctx.strokeRect(x, y, colStepW, r.rowH);
    ctx.strokeRect(x + colStepW, y, colHazW, r.rowH);
    ctx.strokeRect(x + colStepW + colHazW, y, colActW, r.rowH);
    ctx.fillStyle = "#000000";
    ctx.font = "11.5px Arial";
    r.sLines.forEach((l, i) => ctx.fillText(l, x + 8, y + 7 + i * 15));
    r.hLines.forEach((l, i) => ctx.fillText(l, x + colStepW + 8, y + 7 + i * 15));
    r.aLines.forEach((l, i) => ctx.fillText(l, x + colStepW + colHazW + 8, y + 7 + i * 15));
    y += r.rowH;
  }});

  // Sticker Box Footer
  const stickerW = 265;
  const stickerH = 74;
  const sx = pad + innerW - contentPad - stickerW;
  const sy = pad + innerH - contentPad - stickerH;
  ctx.save();
  ctx.setLineDash([5, 4]);
  ctx.strokeStyle = "#64748b";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(sx, sy, stickerW, stickerH);
  ctx.restore();
  ctx.fillStyle = "#cbd5e1";
  ctx.font = "bold 12px 'Times New Roman', serif";
  ctx.textAlign = "center";
  ctx.fillText("PLACE ANNUAL", sx + stickerW / 2, sy + 10);
  ctx.fillText("REVIEW", sx + stickerW / 2, sy + 24);
  ctx.fillText("STICKER HERE", sx + stickerW / 2, sy + 38);
  ctx.beginPath();
  ctx.strokeStyle = "#94a3b8";
  ctx.lineWidth = 1;
  ctx.moveTo(sx, sy + 54);
  ctx.lineTo(sx + stickerW, sy + 54);
  ctx.stroke();
  ctx.fillStyle = "#64748b";
  ctx.font = "9px Arial";
  ctx.fillText("JSA Template - FRM-GEA-SAF-085 Rev 0 2/28/2024", sx + stickerW / 2, sy + 59);

  return canvas;
}}

{PPTX_JS_HELPERS}

async function exportJsaAs(format) {{
  const fileBase = getCleanFileBase();
  closeSaveAsModal();

  if (format === "pptx") {{
    exportJsaPptx(fileBase);
    return;
  }}
  if (format === "pdf") {{
    openPrintableJSA();
    return;
  }}
  if (format === "html") {{
    const htmlContent = "<!DOCTYPE html>\\n" + document.documentElement.outerHTML;
    const blob = new Blob([htmlContent], {{ type: "text/html;charset=utf-8" }});
    triggerBlobDownload(blob, `${{fileBase}}.html`);
    return;
  }}
  if (format === "doc") {{
    exportJsaWordDoc(fileBase);
    return;
  }}
  if (format === "png" || format === "jpg") {{
    const canvas = await renderJsaPosterToCanvas();
    const mime = format === "png" ? "image/png" : "image/jpeg";
    const ext = format === "png" ? "png" : "jpg";
    canvas.toBlob((blob) => {{
      if (blob) triggerBlobDownload(blob, `${{fileBase}}.${{ext}}`);
    }}, mime, 0.95);
  }}
}}

let jsaZoomMode = "{jsa_default_zoom_mode}";
let jsaZoomScale = 1.0;
let isApplyingJsaZoom = false;

function applyJsaZoom() {{
  if (isApplyingJsaZoom) return;
  const frame = document.getElementById("jsaOuterFrame");
  const stage = document.getElementById("jsaScaleStage");
  const viewport = document.getElementById("jsaViewport");
  const labelBtn = document.getElementById("jsaZoomLabelBtn");
  if (!frame || !stage || !viewport) return;

  isApplyingJsaZoom = true;
  try {{
    const naturalW = frame.offsetWidth || 850;
    const naturalH = frame.offsetHeight || 1100;

    const containerW = document.documentElement.clientWidth || window.innerWidth || viewport.clientWidth || 900;
    const availW = Math.max(260, containerW - 24);
    const _fitScaleInit = Math.max(0.22, Math.min(1.0, availW / naturalW));
    const fitW = Math.ceil(naturalW * _fitScaleInit);
    const fitH = Math.ceil(naturalH * _fitScaleInit);
    const fitScale = _fitScaleInit;

    if (jsaZoomMode === "fit") {{
      jsaZoomScale = fitScale;
    }}

    frame.style.transformOrigin = "top left";
    frame.style.transform = `scale(${{jsaZoomScale}})`;
    frame.style.margin = "0";

    const scaledW = Math.ceil(naturalW * jsaZoomScale);
    const scaledH = Math.ceil(naturalH * jsaZoomScale);
    stage.style.width = scaledW + "px";
    stage.style.height = scaledH + "px";

    const isZoomedIn = jsaZoomScale > (fitScale + 0.005);
    const targetPosterH = isZoomedIn ? fitH : scaledH;
    const targetViewportW = isZoomedIn ? Math.min(availW, fitW + 18) : availW;
    stage.style.margin = isZoomedIn ? "0" : "0 auto";
    viewport.classList.toggle("zoomed-scroll", isZoomedIn);
    viewport.style.overflowX = isZoomedIn ? "scroll" : "hidden";
    viewport.style.overflowY = isZoomedIn ? "scroll" : "hidden";
    viewport.style.width = isZoomedIn ? targetViewportW + "px" : "100%";
    viewport.style.maxWidth = isZoomedIn ? targetViewportW + "px" : "none";
    viewport.style.margin = isZoomedIn ? "0 auto" : "0";
    viewport.style.height = (targetPosterH + (isZoomedIn ? 20 : 16)) + "px";
    viewport.style.maxHeight = isZoomedIn ? (targetPosterH + 20) + "px" : "none";
    if (false) {{
      const isZoomedOver100 = jsaZoomScale > 1.001;
    const targetPosterH = isZoomedOver100 ? naturalH : scaledH;
    viewport.style.overflow = isZoomedOver100 ? "auto" : "hidden";
    viewport.style.height = (targetPosterH + 16) + "px";
    viewport.style.maxHeight = isZoomedOver100 ? (naturalH + 16) + "px" : "none";
    }}

    const viewportTop = viewport.offsetTop || 60;
    const desiredIframeH = Math.ceil(viewportTop + targetPosterH + 24);
    try {{
      if (window.frameElement) {{
        const curH = window.frameElement.offsetHeight || parseInt(window.frameElement.style.height || "0", 10) || 0;
        if (Math.abs(curH - desiredIframeH) > 2) {{
          window.frameElement.style.height = desiredIframeH + "px";
          window.frameElement.height = String(desiredIframeH);
        }}
      }}
    }} catch (fe) {{}}

    const pct = Math.round(jsaZoomScale * 100);
    if (labelBtn) {{
      labelBtn.textContent = jsaZoomMode === "fit" ? `Fit (${{pct}}%)` : `${{pct}}% (Fit)`;
    }}
  }} finally {{
    isApplyingJsaZoom = false;
  }}
}}

function stepJsaZoom(delta) {{
  jsaZoomMode = "manual";
  let nextScale = Math.round((jsaZoomScale + delta) * 20) / 20;
  if (delta > 0 && nextScale <= jsaZoomScale + 0.005) nextScale = jsaZoomScale + 0.05;
  if (delta < 0 && nextScale >= jsaZoomScale - 0.005) nextScale = jsaZoomScale - 0.05;
  jsaZoomScale = Math.max(0.25, Math.min(2.5, nextScale));
  applyJsaZoom();
}}

function resetJsaZoomFit() {{
  jsaZoomMode = "fit";
  applyJsaZoom();
}}

window.addEventListener("resize", applyJsaZoom);
if (typeof ResizeObserver !== "undefined") {{
  const jsaRo = new ResizeObserver(() => applyJsaZoom());
  const jsaFrameEl = document.getElementById("jsaOuterFrame");
  if (jsaFrameEl) jsaRo.observe(jsaFrameEl);
}}

renderSelectorDrawer();
renderVisualZone();
renderStepsTable();
applyJsaZoom();
setTimeout(applyJsaZoom, 120);
baselineSnapshotJson = getCurrentJsaSnapshotJson();

["jsaPlantCode", "jsaJobTitle", "jsaImportantNotice", "jsaStepsBody"].forEach(id => {{
  const el = document.getElementById(id);
  if (el) {{
    el.addEventListener("input", checkJsaDirtyState);
    el.addEventListener("keyup", checkJsaDirtyState);
    el.addEventListener("blur", checkJsaDirtyState, true);
  }}
}});

window.addEventListener("beforeunload", (e) => {{
  if (isJsaDirty) {{
    e.preventDefault();
    e.returnValue = "";
  }}
}});

try {{
  if (window.parent && window.parent !== window && window.parent.document) {{
    const parentDoc = window.parent.document;
    const handleParentClick = (e) => {{
      if (!isJsaDirty) return;
      const target = e.target && e.target.closest
        ? e.target.closest("button, a, [role='tab'], [data-baseweb='select'], [data-testid='stSidebarNav'] a")
        : null;
      if (!target) return;
      e.preventDefault();
      e.stopPropagation();
      openUnsavedNavModal(target);
    }};
    parentDoc.addEventListener("click", handleParentClick, true);
    window.addEventListener("unload", () => {{
      try {{ parentDoc.removeEventListener("click", handleParentClick, true); }} catch (err) {{}}
    }});
  }}
}} catch (err) {{}}
</script>
</body>
</html>
"""


_JSA_SAVE_BRIDGE_COMPONENT = st.components.v2.component(
    "paag_jsa_poster_save_bridge_v2",
    html='<div style="display:none;"></div>',
    css="",
    js="""
export default function(component) {
  const { setTriggerValue } = component;
  const handler = (event) => {
    const data = event && event.data;
    if (!data || !data.payload) return;
    if (data.type === "PAAG_JSA_PRINT_REQUEST") {
      setTriggerValue("print_request", data.payload);
      return;
    }
    if (data.type !== "PAAG_JSA_SAVE" && data.type !== "PAAG_JSA_SAVE_REQUEST") return;
    setTriggerValue("save_payload", data.payload);
  };
  window.addEventListener("message", handler);
  return () => {
    window.removeEventListener("message", handler);
  };
}
""",
)


def jsa_poster_save_bridge(*, key: str):
    """Mount a zero-height bridge component that receives Save & Refresh payloads from the JSA Poster."""
    try:
        return _JSA_SAVE_BRIDGE_COMPONENT(
            key=key,
            on_save_payload_change=lambda: None,
            on_print_request_change=lambda: None,
            height="content",
        )
    except Exception:
        return None



def _extract_effective_ppe_names(raw_items: list[Any] | None) -> list[str]:
    names: list[str] = []
    for entry in raw_items or []:
        if isinstance(entry, dict):
            nm = str(entry.get("canonical_name") or entry.get("name") or "").strip()
        else:
            nm = str(entry or "").strip()
        if nm:
            names.append(nm)
    rollup = resolve_pitch_ppe_rollup(names)
    return list(rollup.get("effective_canonical_names") or rollup.get("effective_names") or [])


def build_jsa_poster_print_card_html(
    jsa_summary: dict[str, Any],
    *,
    use_jsa_icons: bool = False,
    min_table_rows: int = 10,
) -> str:
    """Render a static, self-contained portrait JSA Poster card for multi-pitch print/PDF/HTML decks."""
    effective_names = _extract_effective_ppe_names(jsa_summary.get("effective_ppe"))
    baseline_set = {normalize_ppe_name(x) for x in STANDARD_BASELINE_PPE}
    has_special_ppe = any(normalize_ppe_name(n) not in baseline_set for n in effective_names)
    border_class = "border-purple" if has_special_ppe else ""

    plant_code = html.escape(str(jsa_summary.get("plant_code") or "AP1").strip() or "AP1")
    job_title = html.escape(
        str(
            jsa_summary.get("job_title")
            or jsa_summary.get("pitch_display_label")
            or jsa_summary.get("pitch_number")
            or "Job Safety Analysis"
        ).strip()
    )
    default_notice = (
        "The JSA should be reviewed by all employees operating this workstation. "
        "This JSA should be reviewed & updated when changes to equipment / processes occur."
    )
    important_notice = html.escape(
        str(jsa_summary.get("important_notice") or default_notice).strip() or default_notice
    )
    ehs_logo_uri = get_ehs_logo_data_uri()

    # Build PPE tiles
    ppe_count = len(effective_names)
    if ppe_count <= 4:
        icon_w, icon_h = 132, 108
    elif ppe_count <= 6:
        icon_w, icon_h = 112, 92
    elif ppe_count <= 8:
        icon_w, icon_h = 94, 76
    else:
        icon_w, icon_h = 80, 64

    ppe_tiles_html_parts: list[str] = []
    for ppe_name in effective_names:
        img_uri = (
            get_jsa_icon_data_uri(ppe_name)
            if use_jsa_icons
            else (get_ppe_icon_data_uri(ppe_name) or get_jsa_icon_data_uri(ppe_name))
        )
        safe_p_name = html.escape(ppe_name)
        if img_uri:
            ppe_tiles_html_parts.append(
                f'<div class="jsa-deck-ppe-tile" style="width:{icon_w}px;">'
                f'<img src="{img_uri}" alt="{safe_p_name}" style="height:{icon_h}px;" />'
                f'<div class="jsa-deck-ppe-cap">{safe_p_name}</div>'
                f"</div>"
            )
        else:
            ppe_tiles_html_parts.append(
                f'<div class="jsa-deck-ppe-tile" style="width:{icon_w}px;">'
                f'<div class="jsa-deck-ppe-fallback">{safe_p_name}</div>'
                f"</div>"
            )
    visual_zone_inner = (
        "".join(ppe_tiles_html_parts)
        if ppe_tiles_html_parts
        else '<div class="jsa-deck-visual-empty">No PPE Assigned</div>'
    )

    # Build JSA step rows
    raw_rows = list(jsa_summary.get("jsa_rows") or [])
    rows_to_render: list[dict[str, Any]] = []
    for r in raw_rows:
        if not isinstance(r, dict):
            continue
        rows_to_render.append(
            {
                "job_step": str(r.get("job_step") or ""),
                "potential_hazards": str(r.get("potential_hazards") or ""),
                "proposed_actions": str(r.get("proposed_actions") or ""),
                "is_auto_ppe_row": bool(r.get("is_auto_ppe_row")),
            }
        )
    if not rows_to_render:
        rows_to_render.append(
            {
                "job_step": "Put on PPE",
                "potential_hazards": "",
                "proposed_actions": "",
                "is_auto_ppe_row": True,
            }
        )
    while len(rows_to_render) < max(1, int(min_table_rows)):
        rows_to_render.append(
            {
                "job_step": "",
                "potential_hazards": "",
                "proposed_actions": "",
                "is_auto_ppe_row": False,
            }
        )

    tbody_parts: list[str] = []
    for r in rows_to_render:
        tr_cls = ' class="auto-ppe-row"' if r["is_auto_ppe_row"] else ""
        s_txt = html.escape(r["job_step"]).replace("\n", "<br/>")
        h_txt = html.escape(r["potential_hazards"]).replace("\n", "<br/>")
        a_txt = html.escape(r["proposed_actions"]).replace("\n", "<br/>")
        tbody_parts.append(
            f"<tr{tr_cls}>"
            f"<td>{s_txt}</td>"
            f"<td>{h_txt}</td>"
            f"<td>{a_txt}</td>"
            f"</tr>"
        )

    logo_img_html = f'<img src="{ehs_logo_uri}" alt="EHS&amp;S Logo" />' if ehs_logo_uri else "<strong>EHS&amp;S</strong>"

    return f"""
<div class="safety-print-card jsa-print-card" data-poster-kind="jsa">
  <div class="jsa-deck-outer-frame {border_class}">
    <div class="jsa-deck-inner-sheet">
      <div class="jsa-deck-top-section">
        <div class="jsa-deck-header-row">
          <div class="jsa-deck-plant-code">{plant_code}</div>
          <div class="jsa-deck-title-block">
            <div class="jsa-deck-main-heading">JOB SAFETY ANALYSIS</div>
            <div class="jsa-deck-job-title-box">{job_title}</div>
            <div class="jsa-deck-operation-sub">Operation</div>
          </div>
          <div class="jsa-deck-logo-box">{logo_img_html}</div>
        </div>

        <div class="jsa-deck-important-box">
          <div class="jsa-deck-important-header">IMPORTANT</div>
          <div class="jsa-deck-important-body">{important_notice}</div>
        </div>

        <div class="jsa-deck-visual-zone">{visual_zone_inner}</div>

        <table class="jsa-deck-steps-table">
          <thead>
            <tr>
              <th style="width:28%;">JOB STEPS</th>
              <th style="width:33%;">POTENTIAL ERRORS / HAZARDS</th>
              <th style="width:39%;">ACTION</th>
            </tr>
          </thead>
          <tbody>
            {"".join(tbody_parts)}
          </tbody>
        </table>
      </div>

      <div class="jsa-deck-footer-row">
        <div class="jsa-deck-sticker-box">
          <div class="jsa-deck-sticker-area">
            PLACE ANNUAL<br/>REVIEW<br/>STICKER HERE
          </div>
          <div class="jsa-deck-template-rev">
            JSA Template - FRM-GEA-SAF-085 Rev 0 2/28/2024
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
"""


def build_ppe_poster_print_card_html(ppe_summary: dict[str, Any]) -> str:
    """Render a static, self-contained 11x17 Landscape PPE Poster card for multi-pitch print/PDF/HTML decks."""
    effective_names = _extract_effective_ppe_names(ppe_summary.get("effective_ppe"))
    effective_set = set(effective_names)

    safe_job = html.escape(
        str(
            ppe_summary.get("job_name")
            or ppe_summary.get("default_job")
            or ppe_summary.get("pitch_name")
            or ppe_summary.get("pitch_number")
            or ""
        ).strip()
    )
    safe_ws = html.escape(
        str(
            ppe_summary.get("workstation")
            or ppe_summary.get("default_workstation")
            or ppe_summary.get("pitch_number")
            or ""
        ).strip()
    )
    safe_sec = html.escape(
        str(
            ppe_summary.get("section")
            or ppe_summary.get("default_section")
            or ppe_summary.get("section_name")
            or ""
        ).strip()
    )
    logo_uri = get_ehs_logo_data_uri()

    # Collect ordered catalog + custom PPE items with hazards & mitigations
    selected_items: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for cat_item in PPE_CATALOG:
        c_name = str(cat_item["name"])
        if c_name in effective_set:
            seen_names.add(c_name)
            selected_items.append(
                {
                    "name": c_name,
                    "image": get_ppe_icon_data_uri(c_name),
                    "hazard": str(cat_item.get("hazard") or ""),
                    "mitigation": str(cat_item.get("mitigation") or ""),
                }
            )
    for custom_name in effective_names:
        if custom_name not in seen_names:
            seen_names.add(custom_name)
            selected_items.append(
                {
                    "name": custom_name,
                    "image": get_ppe_icon_data_uri(custom_name),
                    "hazard": "Task-specific workplace hazard.",
                    "mitigation": f"Correctly wear approved {custom_name.upper()}.",
                }
            )

    count = len(selected_items)
    if count <= 3:
        cols, tile_h, img_h, cap_fs = max(1, count or 3), 260, 195, "11pt"
    elif count <= 6:
        cols, tile_h, img_h, cap_fs = 3, 225, 165, "10.5pt"
    elif count <= 9:
        cols, tile_h, img_h, cap_fs = 3, 155, 110, "9.5pt"
    elif count <= 12:
        cols, tile_h, img_h, cap_fs = 4, 150, 105, "9pt"
    else:
        cols, tile_h, img_h, cap_fs = 5, 125, 85, "8.5pt"

    if count > 16:
        compact_cls = "compact-3"
    elif count > 12:
        compact_cls = "compact-2"
    elif count > 8:
        compact_cls = "compact-1"
    else:
        compact_cls = ""

    icon_tiles_html: list[str] = []
    table_rows_html: list[str] = []
    for item in selected_items:
        s_name = html.escape(item["name"])
        s_haz = html.escape(item["hazard"])
        s_mit = html.escape(item["mitigation"])
        img_tag = (
            f'<img src="{item["image"]}" alt="{s_name}" style="max-height:{img_h}px;" />'
            if item["image"]
            else f'<div style="font-weight:700;font-size:13pt;text-align:center;">{s_name}</div>'
        )
        icon_tiles_html.append(
            f'<div class="ppe-deck-icon-tile">'
            f"{img_tag}"
            f'<div class="ppe-deck-caption" style="font-size:{cap_fs};">{s_name}</div>'
            f"</div>"
        )
        table_rows_html.append(
            f"<tr>"
            f"<td><strong>{s_name}</strong></td>"
            f"<td>{s_haz}</td>"
            f"<td>{s_mit}</td>"
            f"</tr>"
        )

    return f"""
<div class="safety-print-card ppe-print-card" data-poster-kind="ppe">
  <div class="ppe-deck-page mode-special">
    <div class="ppe-deck-poster">
      <div class="ppe-deck-header">
        <div class="ppe-deck-validation-box">
          <div class="ppe-deck-validation-title">VALIDATION</div>
          <div class="ppe-deck-validation-sub">Place annual review sticker here</div>
        </div>
        <h2>MINIMUM PPE REQUIREMENTS</h2>
        <img class="ppe-deck-header-logo" src="{logo_uri}" alt="EHS&amp;S Logo" />
      </div>

      <div class="ppe-deck-meta-bar">
        <div class="ppe-deck-meta-chip"><strong>Job:</strong> <span>{safe_job}</span></div>
        <div class="ppe-deck-meta-chip"><strong>Workstation:</strong> <span>{safe_ws}</span></div>
        <div class="ppe-deck-meta-chip"><strong>Section:</strong> <span>{safe_sec}</span></div>
      </div>

      <div class="ppe-deck-body">
        <div class="ppe-deck-icons-panel">
          <div class="ppe-deck-panel-title">Required PPE (Visual)</div>
          <div class="ppe-deck-icons-grid" style="--cols:{cols}; --tile-h:{tile_h}px;">
            {"".join(icon_tiles_html)}
          </div>
        </div>

        <div class="ppe-deck-table-panel">
          <div class="ppe-deck-panel-title">Hazards &amp; Mitigations</div>
          <div class="ppe-deck-table-wrap {compact_cls}">
            <table class="ppe-deck-table">
              <colgroup>
                <col style="width:26%;" />
                <col style="width:37%;" />
                <col style="width:37%;" />
              </colgroup>
              <thead>
                <tr>
                  <th>PPE Item</th>
                  <th>Hazard</th>
                  <th>Mitigation</th>
                </tr>
              </thead>
              <tbody>
                {"".join(table_rows_html)}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
"""


def render_printable_safety_poster_deck(
    slides_html: list[str],
    *,
    poster_mode: str = "jsa",
    paper_size: str = "letter",
    title: str = "JSA & PPE Posters",
) -> str:
    """Wrap 1 or more static JSA and/or 11x17 PPE Poster cards into a standalone printable/PDF/HTML deck."""
    is_tabloid = str(paper_size).lower() == "tabloid"
    mode_norm = str(poster_mode).lower()

    if mode_norm == "ppe":
        # 11x17 Landscape by default (or 11x8.5 Landscape if Letter selected)
        page_css_size = "17in 11in" if is_tabloid else "11in 8.5in"
        ppe_print_scale = "1" if is_tabloid else "0.64"
        jsa_print_scale = "1"
        format_badge = "11 × 17 in (Tabloid Landscape)" if is_tabloid else "8.5 × 11 in (Letter Landscape)"
    elif mode_norm == "jsa":
        # Portrait JSA
        page_css_size = "11in 17in" if is_tabloid else "8.5in 11in"
        ppe_print_scale = "0.64"
        jsa_print_scale = "1.22" if is_tabloid else "0.92"
        format_badge = "11 × 17 in (Tabloid Portrait)" if is_tabloid else "8.5 × 11 in (Letter Portrait)"
    else:
        # Both JSA + PPE
        page_css_size = "17in 11in" if is_tabloid else "8.5in 11in"
        ppe_print_scale = "1" if is_tabloid else "0.48"
        jsa_print_scale = "0.92"
        format_badge = "11 × 17 in (Tabloid)" if is_tabloid else "8.5 × 11 in (Letter)"

    total_slides = len(slides_html)
    safe_title = html.escape(title)
    slides_joined = "\n".join(
        f'<div class="safety-print-slide-wrapper">{s}</div>' for s in slides_html
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{safe_title}</title>
<style>
  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }}
  @page {{
    size: {page_css_size};
    margin: 0.2in;
  }}
  html, body {{
    margin: 0;
    padding: 0;
    background: #e2e8f0;
    font-family: Segoe UI, Roboto, Arial, sans-serif;
    color: #0f172a;
  }}
  .print-banner {{
    position: sticky;
    top: 0;
    z-index: 9999;
    background: #0f172a;
    color: #f8fafc;
    padding: 12px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  }}
  .print-banner-btn {{
    background: #0284c7;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 0.92rem;
    font-weight: 700;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }}
  .print-banner-btn:hover {{
    background: #0369a1;
  }}
  .print-banner-btn.green {{
    background: #008a5e;
  }}
  .print-banner-btn.green:hover {{
    background: #006e4a;
  }}
  .print-banner-btn.secondary {{
    background: #334155;
    font-weight: 600;
  }}
  .print-banner-btn.secondary:hover {{
    background: #475569;
  }}
  .pdf-tip-banner {{
    display: none;
    background: #eff6ff;
    border-bottom: 2px solid #3b82f6;
    color: #1e3a8a;
    padding: 9px 24px;
    font-size: 0.9rem;
    font-weight: 600;
    text-align: center;
  }}
  .pdf-tip-banner.visible {{
    display: block;
  }}
  .safety-deck-container {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 28px;
    padding: 24px 16px 48px 16px;
  }}
  .safety-print-slide-wrapper {{
    display: flex;
    justify-content: center;
    align-items: flex-start;
    width: 100%;
  }}

  /* --- JSA Card Styles --- */
  .jsa-deck-outer-frame {{
    width: 850px;
    min-height: 1080px;
    padding: 26px;
    background: repeating-linear-gradient(
      135deg,
      #00b377 0px,
      #00b377 34px,
      #000000 34px,
      #000000 68px
    );
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
  }}
  .jsa-deck-outer-frame.border-purple {{
    background: repeating-linear-gradient(
      135deg,
      #7851a9 0px,
      #7851a9 34px,
      #000000 34px,
      #000000 68px
    );
  }}
  .jsa-deck-inner-sheet {{
    background: #ffffff;
    border: 2px solid #000000;
    min-height: 1028px;
    padding: 14px 18px 16px 18px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}
  .jsa-deck-top-section {{
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .jsa-deck-header-row {{
    display: grid;
    grid-template-columns: 120px 1fr 110px;
    align-items: center;
    gap: 10px;
  }}
  .jsa-deck-plant-code {{
    font-size: 36px;
    font-weight: 900;
    color: #000;
    padding-left: 6px;
  }}
  .jsa-deck-title-block {{
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }}
  .jsa-deck-main-heading {{
    font-size: 25px;
    font-weight: 900;
    letter-spacing: 0.6px;
    color: #000;
  }}
  .jsa-deck-job-title-box {{
    border: 1.5px solid #222;
    background: #e5e7eb;
    padding: 4px 14px;
    font-size: 15.5px;
    font-weight: 700;
    min-width: 340px;
    max-width: 96%;
    text-align: center;
    color: #000;
  }}
  .jsa-deck-operation-sub {{
    font-size: 15px;
    font-weight: 800;
    color: #000;
  }}
  .jsa-deck-logo-box {{
    display: flex;
    justify-content: flex-end;
    align-items: center;
  }}
  .jsa-deck-logo-box img {{
    max-height: 66px;
    max-width: 105px;
    object-fit: contain;
  }}
  .jsa-deck-important-box {{
    border: 1.8px solid #000;
  }}
  .jsa-deck-important-header {{
    background: #10c486;
    border-bottom: 1.5px solid #000;
    text-align: center;
    font-weight: 900;
    font-size: 15px;
    padding: 3px 8px;
    color: #000;
  }}
  .jsa-deck-important-body {{
    padding: 6px 12px;
    font-size: 12.5px;
    font-weight: 700;
    line-height: 1.35;
    color: #000;
  }}
  .jsa-deck-visual-zone {{
    min-height: 195px;
    margin: 4px 0;
    padding: 8px 10px;
    border: 1px dashed #cbd5e1;
    border-radius: 6px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }}
  .jsa-deck-visual-empty {{
    font-size: 22px;
    color: #64748b;
    font-weight: 600;
  }}
  .jsa-deck-ppe-tile {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3px;
    text-align: center;
  }}
  .jsa-deck-ppe-tile img {{
    max-width: 100%;
    object-fit: contain;
  }}
  .jsa-deck-ppe-cap {{
    font-size: 9.5px;
    font-weight: 700;
    color: #111;
    margin-top: 2px;
    line-height: 1.15;
  }}
  .jsa-deck-ppe-fallback {{
    border: 1px solid #94a3b8;
    border-radius: 6px;
    padding: 8px;
    font-size: 11px;
    font-weight: 700;
  }}
  .jsa-deck-steps-table {{
    width: 100%;
    border-collapse: collapse;
    border: 2.5px solid #000;
    table-layout: fixed;
  }}
  .jsa-deck-steps-table th {{
    border: 1.5px solid #000;
    padding: 6px 8px;
    font-size: 11.5px;
    font-weight: 900;
    text-align: left;
    background: #ffffff;
    color: #000;
  }}
  .jsa-deck-steps-table td {{
    border: 1.2px solid #000;
    padding: 5px 8px;
    font-size: 11px;
    vertical-align: top;
    line-height: 1.28;
    height: 34px;
    color: #000;
    word-wrap: break-word;
  }}
  .jsa-deck-steps-table tr.auto-ppe-row td {{
    background: #f8fafc;
  }}
  .jsa-deck-footer-row {{
    display: flex;
    justify-content: flex-end;
    margin-top: 10px;
  }}
  .jsa-deck-sticker-box {{
    width: 260px;
    border: 1.5px dashed #64748b;
    text-align: center;
  }}
  .jsa-deck-sticker-area {{
    padding: 7px 10px 5px 10px;
    font-family: "Times New Roman", Times, serif;
    font-size: 12.5px;
    font-weight: 700;
    color: #94a3b8;
    line-height: 1.22;
  }}
  .jsa-deck-template-rev {{
    border-top: 1px solid #94a3b8;
    padding: 3px 6px;
    font-size: 9px;
    color: #64748b;
  }}

  /* --- 11x17 PPE Poster Card Styles --- */
  .ppe-deck-page {{
    width: 1584px;
    height: 1008px;
    padding: 26px;
    border-radius: 10px;
    background: repeating-linear-gradient(
      135deg,
      #6f42c1 0 16px,
      #ffffff 16px 32px
    );
    box-shadow: 0 6px 20px rgba(15, 23, 42, 0.16);
  }}
  .ppe-deck-poster {{
    width: 100%;
    height: 100%;
    background: #ffffff;
    border-radius: 6px;
    border: 2px solid #3b4b59;
    padding: 18px;
    display: grid;
    grid-template-rows: auto auto 1fr;
    row-gap: 13px;
    overflow: hidden;
  }}
  .ppe-deck-header {{
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #e9edf2;
    border: 1.5px solid #3b4b59;
    border-radius: 6px;
    padding: 10px 16px;
    min-height: 104px;
  }}
  .ppe-deck-header h2 {{
    margin: 0;
    font-size: 28pt;
    letter-spacing: 0.5px;
    color: #1f2d3a;
    font-weight: 800;
    text-align: center;
  }}
  .ppe-deck-header-logo {{
    position: absolute;
    right: 16px;
    top: 50%;
    transform: translateY(-50%);
    max-height: 84px;
    max-width: 210px;
    object-fit: contain;
  }}
  .ppe-deck-validation-box {{
    position: absolute;
    left: 16px;
    top: 50%;
    transform: translateY(-50%);
    width: 245px;
    height: 84px;
    border: 2px dashed #3b4b59;
    border-radius: 6px;
    background: #fff;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 6px 10px;
  }}
  .ppe-deck-validation-title {{
    font-size: 10pt;
    font-weight: 800;
    color: #3b4b59;
  }}
  .ppe-deck-validation-sub {{
    font-size: 8.5pt;
    color: #555;
  }}
  .ppe-deck-meta-bar {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 12px;
  }}
  .ppe-deck-meta-chip {{
    border: 1.5px solid #3b4b59;
    border-radius: 6px;
    padding: 7px 12px;
    background: #f5f7fa;
    font-size: 12pt;
    display: flex;
    align-items: baseline;
    gap: 6px;
  }}
  .ppe-deck-meta-chip span {{
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .ppe-deck-body {{
    display: grid;
    grid-template-columns: 58% 42%;
    column-gap: 18px;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }}
  .ppe-deck-icons-panel,
  .ppe-deck-table-panel {{
    border: 1.5px solid #dcdfe4;
    border-radius: 6px;
    padding: 13px;
    background: #f9fafb;
    display: grid;
    grid-template-rows: auto 1fr;
    min-height: 0;
    overflow: hidden;
  }}
  .ppe-deck-panel-title {{
    font-size: 12pt;
    font-weight: 700;
    color: #3b4b59;
    margin: 0 0 8px 0;
  }}
  .ppe-deck-icons-grid {{
    display: grid;
    grid-template-columns: repeat(var(--cols, 3), minmax(0, 1fr));
    grid-auto-rows: var(--tile-h, 160px);
    gap: 11px;
    align-content: start;
    height: 100%;
    background: #fff;
    border: 1px solid #dcdfe4;
    border-radius: 6px;
    padding: 11px;
    overflow: hidden;
  }}
  .ppe-deck-icon-tile {{
    border: 1px solid #e4e7ec;
    border-radius: 8px;
    background: #fff;
    padding: 7px;
    display: grid;
    grid-template-rows: 1fr auto;
    align-items: center;
    justify-items: center;
    overflow: hidden;
  }}
  .ppe-deck-icon-tile img {{
    max-width: 100%;
    object-fit: contain;
    display: block;
  }}
  .ppe-deck-caption {{
    margin-top: 4px;
    text-align: center;
    line-height: 1.15;
    color: #222;
    font-weight: 600;
  }}
  .ppe-deck-table-wrap {{
    background: #fff;
    border: 1px solid #dcdfe4;
    border-radius: 6px;
    padding: 7px;
    height: 100%;
    overflow: hidden;
  }}
  .ppe-deck-table {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    font-size: 10.5pt;
  }}
  .ppe-deck-table thead th {{
    background: #eef2f7;
    color: #1f2d3a;
    border: 1px solid #dcdfe4;
    padding: 6px 8px;
    font-weight: 700;
    text-align: left;
  }}
  .ppe-deck-table tbody td {{
    border: 1px solid #dcdfe4;
    padding: 6px 8px;
    vertical-align: top;
    word-wrap: break-word;
  }}
  .ppe-deck-table-wrap.compact-1 .ppe-deck-table {{ font-size: 9.2pt; }}
  .ppe-deck-table-wrap.compact-1 .ppe-deck-table td,
  .ppe-deck-table-wrap.compact-1 .ppe-deck-table th {{ padding: 4px 6px; }}
  .ppe-deck-table-wrap.compact-2 .ppe-deck-table {{ font-size: 8.2pt; }}
  .ppe-deck-table-wrap.compact-2 .ppe-deck-table td,
  .ppe-deck-table-wrap.compact-2 .ppe-deck-table th {{ padding: 3px 5px; }}
  .ppe-deck-table-wrap.compact-3 .ppe-deck-table {{ font-size: 7.4pt; }}
  .ppe-deck-table-wrap.compact-3 .ppe-deck-table td,
  .ppe-deck-table-wrap.compact-3 .ppe-deck-table th {{ padding: 2px 4px; }}

  @media print {{
    html, body {{
      background: #ffffff !important;
    }}
    .no-print {{
      display: none !important;
    }}
    .safety-deck-container {{
      padding: 0 !important;
      gap: 0 !important;
      display: block !important;
    }}
    .safety-print-slide-wrapper {{
      page-break-after: always;
      break-after: page;
      page-break-inside: avoid;
      break-inside: avoid;
      display: flex !important;
      justify-content: center !important;
      align-items: flex-start !important;
      margin: 0 auto !important;
      padding: 0 !important;
    }}
    .safety-print-slide-wrapper:last-child {{
      page-break-after: auto;
      break-after: auto;
    }}
    .jsa-deck-outer-frame {{
      box-shadow: none !important;
      zoom: {jsa_print_scale};
    }}
    .ppe-deck-page {{
      box-shadow: none !important;
      zoom: {ppe_print_scale};
    }}
  }}
</style>
</head>
<body>
  <div class="print-banner no-print">
    <div>
      <strong style="font-size:1.05rem;">🖨️ {safe_title} — Ready to Print ({total_slides} Poster{"s" if total_slides != 1 else ""})</strong>
      <div style="font-size:0.82rem; color:#94a3b8; margin-top:2px;">
        Target Page Format: <strong>{html.escape(format_badge)}</strong> &bull; Enable <strong>Background graphics</strong> in your browser print dialog.
      </div>
    </div>
    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
      <button type="button" class="print-banner-btn green" onclick="triggerPhysicalPrint()">
        🖨️ Print Physical Paper Copies
      </button>
      <button type="button" class="print-banner-btn" onclick="triggerSaveAsPdf()">
        📄 Save as PDF
      </button>
      <button type="button" class="print-banner-btn secondary" onclick="downloadStandaloneDeckHtml()">
        🌐 Download HTML
      </button>
      <button type="button" class="print-banner-btn secondary" onclick="window.close()">
        ✕ Close
      </button>
    </div>
  </div>
  <div id="pdfTipBanner" class="pdf-tip-banner no-print">
    💡 <strong>Save as PDF Tip:</strong> In the print window that opens, set <strong>Destination</strong> (Printer) to <strong>"Save as PDF"</strong> (or <strong>"Microsoft Print to PDF"</strong>) and check <strong>Background graphics</strong>.
  </div>
  <div class="safety-deck-container">
    {slides_joined}
  </div>
  <script>
    function triggerPhysicalPrint() {{
      const tip = document.getElementById("pdfTipBanner");
      if (tip) tip.classList.remove("visible");
      window.print();
    }}
    function triggerSaveAsPdf() {{
      const tip = document.getElementById("pdfTipBanner");
      if (tip) tip.classList.add("visible");
      setTimeout(function() {{ window.print(); }}, 120);
    }}
    function downloadStandaloneDeckHtml() {{
      const htmlContent = "<!DOCTYPE html>\\n" + document.documentElement.outerHTML;
      const blob = new Blob([htmlContent], {{ type: "text/html;charset=utf-8" }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = {json.dumps(title.replace(" ", "_") + ".html")};
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function() {{ URL.revokeObjectURL(url); }}, 1000);
    }}
    if (window.location.hash === "#autoprint") {{
      window.addEventListener("load", function() {{
        setTimeout(function() {{ window.print(); }}, 350);
      }});
    }} else if (window.location.hash === "#autopdf") {{
      window.addEventListener("load", function() {{
        const tip = document.getElementById("pdfTipBanner");
        if (tip) tip.classList.add("visible");
        setTimeout(function() {{ window.print(); }}, 350);
      }});
    }}
  </script>
</body>
</html>
"""


def render_safety_poster_print_dialog_body(
    *,
    project_id: str,
    scenario_id: str,
    selected_pitch_id: str,
    poster_summaries: list[dict[str, Any]] | None = None,
    jsa_summaries: list[dict[str, Any]] | None = None,
    default_poster_type: str = "jsa",
    active_section_filter: str = "",
    key_prefix: str = "safety_print",
    on_close_callback: Any | None = None,
    close_button_label: str = "✕ Close Print Window",
) -> None:
    """Render the PAAG-style Print & Export Settings UI for JSA and 11x17 PPE Posters."""
    from utils.safety_store import pitch_jsa_poster_summary, pitch_ppe_poster_summary

    all_ppe_list = (
        poster_summaries
        if poster_summaries is not None
        else pitch_ppe_poster_summary(project_id, scenario_id)
    )
    all_jsa_list = (
        jsa_summaries
        if jsa_summaries is not None
        else pitch_jsa_poster_summary(project_id, scenario_id)
    )

    ppe_by_pid: dict[str, dict[str, Any]] = {
        str(p.get("pitch_id") or ""): p for p in (all_ppe_list or []) if p.get("pitch_id")
    }
    jsa_by_pid: dict[str, dict[str, Any]] = {
        str(j.get("pitch_id") or ""): j for j in (all_jsa_list or []) if j.get("pitch_id")
    }

    ordered_pids: list[str] = [
        str(p.get("pitch_id") or "")
        for p in (all_ppe_list or all_jsa_list or [])
        if p.get("pitch_id")
    ]
    if not ordered_pids and selected_pitch_id:
        ordered_pids = [selected_pitch_id]

    pitch_label_map: dict[str, str] = {}
    sec_pitch_map: dict[str, list[str]] = {}
    ordered_sec_names: list[str] = []

    for pid in ordered_pids:
        p_info = ppe_by_pid.get(pid) or jsa_by_pid.get(pid) or {}
        p_num = str(p_info.get("pitch_number") or "Pitch").strip()
        p_name = str(p_info.get("pitch_name") or p_info.get("job_name") or "").strip()
        sec_name = str(p_info.get("section_name") or p_info.get("section") or "Unassigned").strip() or "Unassigned"
        pitch_label_map[pid] = f"{p_num} — {p_name}" if p_name else p_num
        if sec_name not in sec_pitch_map:
            sec_pitch_map[sec_name] = []
            ordered_sec_names.append(sec_name)
        sec_pitch_map[sec_name].append(pid)

    curr_pid = selected_pitch_id if selected_pitch_id in ordered_pids else (ordered_pids[0] if ordered_pids else "")
    curr_p_info = ppe_by_pid.get(curr_pid) or jsa_by_pid.get(curr_pid) or {}
    curr_pitch_label = pitch_label_map.get(curr_pid, "Current Pitch")
    curr_sec_name = (
        str(curr_p_info.get("section_name") or curr_p_info.get("section") or "").strip()
        or "Unassigned"
    )
    target_sec_name = (
        active_section_filter
        if (active_section_filter and active_section_filter in sec_pitch_map)
        else curr_sec_name
    )
    target_sec_count = len(sec_pitch_map.get(target_sec_name, []))

    top_c1, top_c2 = st.columns([4.5, 1.3], vertical_alignment="center")
    with top_c1:
        st.markdown("### Export & Print JSA & PPE Posters")
        st.caption(
            "Choose to print 1 pitch poster, all posters from a Fishbone section, or all pitches in the project — "
            "as physical paper copies, Save as PDF, or standalone HTML."
        )
    with top_c2:
        if on_close_callback is not None:
            if st.button(
                close_button_label,
                key=f"{key_prefix}_top_close_{scenario_id}_{curr_pid}",
                width="stretch",
            ):
                on_close_callback()
                st.rerun()

    POSTER_TYPE_JSA = "📋 JSA Poster (FRM-GEA-SAF-085)"
    POSTER_TYPE_PPE = "🛡️ 11×17 Minimum PPE Poster"
    POSTER_TYPE_BOTH = "📑 Both Posters (JSA + 11×17 PPE)"
    poster_type_options = [POSTER_TYPE_JSA, POSTER_TYPE_PPE, POSTER_TYPE_BOTH]

    poster_type_state_key = f"{key_prefix}_poster_type_{scenario_id}"
    req_default = str(default_poster_type or "jsa").lower()
    if st.session_state.get(poster_type_state_key) not in poster_type_options:
        if req_default == "ppe":
            st.session_state[poster_type_state_key] = POSTER_TYPE_PPE
        elif req_default == "both":
            st.session_state[poster_type_state_key] = POSTER_TYPE_BOTH
        else:
            st.session_state[poster_type_state_key] = POSTER_TYPE_JSA

    chosen_poster_type = st.segmented_control(
        "Poster Type to Print / Export",
        options=poster_type_options,
        key=poster_type_state_key,
    ) or POSTER_TYPE_JSA

    if chosen_poster_type == POSTER_TYPE_PPE:
        poster_mode = "ppe"
    elif chosen_poster_type == POSTER_TYPE_BOTH:
        poster_mode = "both"
    else:
        poster_mode = "jsa"

    col_scope, col_fmt = st.columns([1.5, 1.2])

    with col_scope:
        scope_choices = [
            f"Current pitch only (1 pitch — {curr_pitch_label})",
        ]
        if target_sec_name and target_sec_count > 0:
            scope_choices.append(
                f"Current Fishbone section: {target_sec_name} ({target_sec_count} pitch{'es' if target_sec_count != 1 else ''})"
            )
        if len(ordered_sec_names) > 0:
            scope_choices.append("Select specific Fishbone section(s)...")
        scope_choices.append(
            f"All pitches in project / scenario ({len(ordered_pids)} pitch{'es' if len(ordered_pids) != 1 else ''})"
        )
        scope_choices.append("Select specific pitches...")

        chosen_scope = st.radio(
            "Print Selection (Scope)",
            scope_choices,
            index=0,
            key=f"{key_prefix}_scope_{scenario_id}",
            help="Choose to print 1 slide (current pitch), all slides in a Fishbone section, or all slides in the project.",
        )

        selected_sec_names: list[str] = []
        if "specific Fishbone section" in chosen_scope:
            def_secs = [target_sec_name] if target_sec_name in ordered_sec_names else ordered_sec_names[:1]
            selected_sec_names = st.multiselect(
                "Choose Fishbone Section(s) to Print",
                options=ordered_sec_names,
                default=def_secs,
                format_func=lambda s: f"{s} ({len(sec_pitch_map.get(s, []))} pitch{'es' if len(sec_pitch_map.get(s, [])) != 1 else ''})",
                key=f"{key_prefix}_sec_multi_{scenario_id}",
            )

        selected_custom_pids: list[str] = []
        if "specific pitches" in chosen_scope:
            selected_custom_pids = st.multiselect(
                "Choose Pitches to Include",
                options=ordered_pids,
                default=[curr_pid] if curr_pid else ordered_pids[:1],
                format_func=lambda pid: pitch_label_map.get(pid, pid),
                key=f"{key_prefix}_pitch_multi_{scenario_id}",
            )

    with col_fmt:
        if poster_mode == "ppe":
            fmt_options = [
                "11 × 17 in (Tabloid Landscape — Standard PPE Poster)",
                "8.5 × 11 in (Letter Landscape — Scaled to Fit)",
            ]
            default_fmt_idx = 0
        elif poster_mode == "jsa":
            fmt_options = [
                "8.5 × 11 in (Letter Portrait — Standard JSA)",
                "11 × 17 in (Tabloid Portrait — Large Format JSA)",
            ]
            default_fmt_idx = 0
        else:
            fmt_options = [
                "8.5 × 11 in (Letter)",
                "11 × 17 in (Tabloid — 11×17)",
            ]
            default_fmt_idx = 1

        format_choice = st.radio(
            "Paper Size / Page Format",
            fmt_options,
            index=default_fmt_idx,
            key=f"{key_prefix}_fmt_{poster_mode}_{scenario_id}",
            help="Select standard 8.5×11 Letter or 11×17 Tabloid paper size for physical printing and Save as PDF.",
        )
        paper_size = "tabloid" if "11 × 17" in format_choice else "letter"

        use_jsa_icons = False
        if poster_mode in {"jsa", "both"}:
            style_choice = st.radio(
                "JSA PPE Visual Style",
                ["Photo Cards (with description)", "JSA Square Icons"],
                index=0,
                key=f"{key_prefix}_jsa_style_{scenario_id}",
            )
            use_jsa_icons = "Square Icons" in style_choice

    # Resolve target pitch IDs in walk order
    if "Current pitch only" in chosen_scope:
        target_pids = [curr_pid] if curr_pid else ordered_pids[:1]
    elif "Current Fishbone section" in chosen_scope:
        target_pids = list(sec_pitch_map.get(target_sec_name, [curr_pid]))
    elif "specific Fishbone section" in chosen_scope:
        target_pids = []
        for s_name in selected_sec_names:
            for pid in sec_pitch_map.get(s_name, []):
                if pid not in target_pids:
                    target_pids.append(pid)
        if not target_pids and curr_pid:
            target_pids = [curr_pid]
    elif "All pitches" in chosen_scope:
        target_pids = list(ordered_pids)
    else:
        target_pids = list(selected_custom_pids) if selected_custom_pids else ([curr_pid] if curr_pid else ordered_pids[:1])

    slides_html: list[str] = []
    for pid in target_pids:
        if poster_mode in {"jsa", "both"}:
            j_sum = jsa_by_pid.get(pid)
            if j_sum:
                slides_html.append(
                    build_jsa_poster_print_card_html(
                        j_sum,
                        use_jsa_icons=use_jsa_icons,
                    )
                )
        if poster_mode in {"ppe", "both"}:
            p_sum = ppe_by_pid.get(pid)
            if p_sum:
                slides_html.append(build_ppe_poster_print_card_html(p_sum))

    if not slides_html:
        st.warning("No posters were selected for printing.")
        return

    total_posters = len(slides_html)
    total_pitches_sel = len(target_pids)
    mode_title_map = {
        "jsa": "JSA_Posters",
        "ppe": "PPE_11x17_Posters",
        "both": "JSA_and_PPE_Posters",
    }
    deck_title = f"{mode_title_map.get(poster_mode, 'Safety_Posters')}_{total_pitches_sel}_Pitches"
    full_deck_html = render_printable_safety_poster_deck(
        slides_html,
        poster_mode=poster_mode,
        paper_size=paper_size,
        title=f"Safety Posters ({total_posters} Slide{'s' if total_posters != 1 else ''})",
    )

    st.info(
        f"Ready to output **{total_posters} poster slide{'s' if total_posters != 1 else ''}** "
        f"across **{total_pitches_sel} pitch{'es' if total_pitches_sel != 1 else ''}** "
        f"on **{format_choice}**."
    )

    scope_sig = f"{poster_mode}_{chosen_scope}_{paper_size}_{use_jsa_icons}_{target_pids}"
    scope_slug = hashlib.md5(scope_sig.encode("utf-8")).hexdigest()[:8]

    act_c1, act_c2 = st.columns([2.2, 1.0], vertical_alignment="center")
    with act_c1:
        escaped_deck_html = (
            json.dumps(full_deck_html)
            .replace("</script>", "<\\/script>")
            .replace("</Script>", "<\\/Script>")
        )
        action_buttons_html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{
    margin: 0;
    padding: 2px 0;
    background: transparent;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .btn-act {{
    text-decoration: none;
    font-size: 0.9rem;
    font-weight: 700;
    padding: 8px 15px;
    border-radius: 6px;
    border: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12);
  }}
  .btn-print-paper {{
    background: #008a5e;
    color: #ffffff !important;
  }}
  .btn-print-paper:hover {{
    background: #006e4a;
  }}
  .btn-save-pdf {{
    background: #0284c7;
    color: #ffffff !important;
  }}
  .btn-save-pdf:hover {{
    background: #0369a1;
  }}
  .btn-open-tab {{
    background: #f1f5f9;
    color: #0f172a !important;
    border: 1px solid #cbd5e1;
    font-weight: 600;
  }}
  .btn-open-tab:hover {{
    background: #e2e8f0;
  }}
</style>
</head>
<body>
  <button id="btnPrintPaper" class="btn-act btn-print-paper" title="Open print dialog to print physical paper copies">
    <span>🖨️</span> Print Physical Paper Copies
  </button>
  <button id="btnSavePdf" class="btn-act btn-save-pdf" title="Open print preview ready to Save as PDF">
    <span>📄</span> Save as PDF
  </button>
  <button id="btnOpenTab" class="btn-act btn-open-tab" title="Open compiled multi-poster deck in a new browser tab">
    <span>↗️</span> Open in New Tab
  </button>
  <script>
    const deckContent = {escaped_deck_html};
    function openDeckWindow(mode) {{
      let htmlToOpen = deckContent;
      if (mode === "print") {{
        htmlToOpen = deckContent.replace(
          "</body>",
          '<script>window.addEventListener("load", function(){{ setTimeout(function(){{ window.print(); }}, 380); }});<\\/script></body>'
        );
      }} else if (mode === "pdf") {{
        htmlToOpen = deckContent.replace(
          "</body>",
          '<script>window.addEventListener("load", function(){{ var t=document.getElementById("pdfTipBanner"); if(t) t.classList.add("visible"); setTimeout(function(){{ window.print(); }}, 380); }});<\\/script></body>'
        );
      }}
      const blob = new Blob([htmlToOpen], {{ type: "text/html;charset=utf-8" }});
      const blobUrl = URL.createObjectURL(blob);
      const win = window.open(blobUrl, "_blank");
      if (win) win.focus();
    }}
    document.getElementById("btnPrintPaper").onclick = function(e) {{
      e.preventDefault();
      openDeckWindow("print");
    }};
    document.getElementById("btnSavePdf").onclick = function(e) {{
      e.preventDefault();
      openDeckWindow("pdf");
    }};
    document.getElementById("btnOpenTab").onclick = function(e) {{
      e.preventDefault();
      openDeckWindow("view");
    }};
  </script>
</body>
</html>"""
        components.html(action_buttons_html, height=46)

    with act_c2:
        safe_html_fn = f"{deck_title}_{paper_size}.html".replace(" ", "_")
        st.download_button(
            f"Download HTML ({total_posters} Poster{'s' if total_posters != 1 else ''})",
            data=full_deck_html,
            file_name=safe_html_fn,
            mime="text/html",
            icon=":material/download:",
            type="secondary",
            width="stretch",
            key=f"{key_prefix}_dl_html_{scenario_id}_{scope_slug}",
        )

    st.divider()
    st.caption(
        f"Preview (Poster 1 of {total_posters} — use **Open in New Tab**, **Print Physical Paper Copies**, or **Save as PDF** above to view/print all {total_posters} poster{'s' if total_posters != 1 else ''}):"
    )
    preview_deck_html = render_printable_safety_poster_deck(
        slides_html[:1],
        poster_mode=poster_mode,
        paper_size=paper_size,
        title="Poster 1 Preview",
    )
    components.html(preview_deck_html, height=720, scrolling=True)

    if on_close_callback is not None:
        if st.button(
            close_button_label,
            key=f"{key_prefix}_bottom_close_{scenario_id}_{curr_pid}",
        ):
            on_close_callback()
            st.rerun()
