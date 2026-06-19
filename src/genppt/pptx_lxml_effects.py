"""OOXML effect injection for python-pptx generated shapes.

python-pptx can draw shapes but cannot set advanced effects like shadows,
glow, or gradient fills. This module post-processes the PPTX file with
lxml to inject these effects directly into the OOXML.

Supported effects:
- outerShdw: outer shadow for card/panel depth
- gradFill: gradient fills for accent bars and decorative shapes
- glow: soft glow on emphasis elements

It opens the PPTX as a zip archive, modifies slide XML, then re-saves it.
"""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# ── XML namespaces ──────────────────────────────────────────────────────────
NSMAP = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def _ns(tag: str) -> str:
    """Resolve namespace prefix: 'a:solidFill' -> '{...}solidFill'."""
    prefix, local = tag.split(":", 1)
    return f"{{{NSMAP[prefix]}}}{local}"


def _sub_element(parent: ET.Element, tag: str, **attribs) -> ET.Element:
    el = ET.SubElement(parent, _ns(tag))
    for k, v in attribs.items():
        el.set(k, str(v))
    return el


# ═══════════════════════════════════════════════════════════════════════════════
# Effect builders
# ═══════════════════════════════════════════════════════════════════════════════

def _make_outer_shadow(
    blur_rad: int = 40000,
    dist: int = 25000,
    direction: int = 5400000,
    alpha: int = 20000,
    color: str = "000000",
) -> ET.Element:
    """Create <a:outerShdw> element.

    blur_rad: blur radius in EMUs (40000 = 4pt)
    dist: offset distance in EMUs (25000 = 2.5pt)
    dir: shadow direction in 60000ths of a degree (5400000 = 90deg = below)
    alpha: opacity in 1/1000th percent (20000 = 20%)
    """
    el = ET.Element(_ns("a:outerShdw"))
    el.set("blurRad", str(blur_rad))
    el.set("dist", str(dist))
    el.set("dir", str(direction))
    el.set("algn", "ctr")
    el.set("rotWithShape", "0")
    # Shadow color
    srgb = _sub_element(el, "a:srgbClr", val=color)
    _sub_element(srgb, "a:alpha", val=str(alpha))
    return el


def _make_gradient_fill(colors: list[tuple[str, int]], angle: int = 900000) -> ET.Element:
    """Create <a:gradFill> with linear gradient.

    colors: list of (hex_color, position_percent) e.g. [("2563EB", 0), ("4F46E5", 100)]
    angle: gradient angle in 60000ths of a degree (900000 = 90deg = left-to-right)
    """
    el = ET.Element(_ns("a:gradFill"))
    el.set("rotWithShape", "1")
    gs_lst = _sub_element(el, "a:gsLst")
    for hex_color, pos in colors:
        gs = _sub_element(gs_lst, "a:gs", pos=str(pos * 1000))
        srgb = _sub_element(gs, "a:srgbClr", val=hex_color.lstrip("#"))
    lin = _sub_element(el, "a:lin", ang=str(angle), scaled="1")
    return el


def _make_glow(radius: int = 60000, alpha: int = 40000, color: str = "2563EB") -> ET.Element:
    """Create <a:glow> effect for soft glow around a shape.

    radius: glow radius in EMUs (60000 = 6pt)
    alpha: opacity in 1/1000th percent (40000 = 40%)
    """
    el = ET.Element(_ns("a:glow"))
    el.set("rad", str(radius))
    srgb = _sub_element(el, "a:srgbClr", val=color.lstrip("#"))
    _sub_element(srgb, "a:alpha", val=str(alpha))
    return el


def _make_solid_fill(color: str) -> ET.Element:
    """Create <a:solidFill> element."""
    el = ET.Element(_ns("a:solidFill"))
    _sub_element(el, "a:srgbClr", val=color.lstrip("#"))
    return el


# ═══════════════════════════════════════════════════════════════════════════════
# Shape effect application
# ═══════════════════════════════════════════════════════════════════════════════

def _get_or_create_effect_list(sp_pr: ET.Element) -> ET.Element:
    """Get or create <a:effectLst> inside a shape properties element."""
    el = sp_pr.find(_ns("a:effectLst"))
    if el is None:
        el = ET.Element(_ns("a:effectLst"))
        sp_pr.insert(0, el)
    return el


def _get_or_create_sp_pr(shape_elem: ET.Element) -> ET.Element | None:
    """Find the <a:spPr> or <p:spPr> element for a shape."""
    # For <p:sp> (shape)
    for tag in [_ns("p:spPr"), _ns("a:spPr")]:
        el = shape_elem.find(tag)
        if el is not None:
            return el
    # For <p:pic> (picture)
    for tag in [_ns("p:nvPicPr"), _ns("p:blipFill")]:
        parent = shape_elem.find(tag)
        if parent is not None:
            sp_pr = parent.find(_ns("a:spPr"))
            if sp_pr is not None:
                return sp_pr
    return None


def apply_shadow_to_shape(shape_elem: ET.Element, blur: int = 35000, dist: int = 20000, alpha: int = 18000) -> bool:
    """Apply outer shadow to a single shape XML element."""
    sp_pr = _get_or_create_sp_pr(shape_elem)
    if sp_pr is None:
        return False
    effect_lst = _get_or_create_effect_list(sp_pr)
    shadow = _make_outer_shadow(blur_rad=blur, dist=dist, alpha=alpha)
    effect_lst.append(shadow)
    return True


def apply_gradient_to_shape(shape_elem: ET.Element, colors: list[tuple[str, int]], angle: int = 900000) -> bool:
    """Apply gradient fill to a shape, replacing any existing solid fill."""
    sp_pr = _get_or_create_sp_pr(shape_elem)
    if sp_pr is None:
        return False
    # Remove existing fill
    for fill_tag in [_ns("a:solidFill"), _ns("a:gradFill"), _ns("a:noFill")]:
        existing = sp_pr.find(fill_tag)
        if existing is not None:
            sp_pr.remove(existing)
    grad = _make_gradient_fill(colors, angle)
    sp_pr.append(grad)
    return True


def apply_glow_to_shape(shape_elem: ET.Element, radius: int = 55000, alpha: int = 35000, color: str = "2563EB") -> bool:
    """Apply glow effect to a shape."""
    sp_pr = _get_or_create_sp_pr(shape_elem)
    if sp_pr is None:
        return False
    effect_lst = _get_or_create_effect_list(sp_pr)
    glow = _make_glow(radius=radius, alpha=alpha, color=color)
    effect_lst.append(glow)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Slide-level post-processing
# ═══════════════════════════════════════════════════════════════════════════════

SHADOW_SHAPE_NAMES = {"card_bg", "panel", "insight-panel", "card-panel",
                      "proof-panel", "metric-bg", "cell-bg", "risk_bg",
                      "evidence_bg", "phase-bg", "section-bg"}
GRADIENT_SHAPE_NAMES = {"accent", "geo-accent", "accent-bar", "chrome-rail",
                        "chrome-band", "sep", "diagonal-accent", "cell-bar",
                        "card-bar", "phase-bar", "metric-bar", "lane-bar",
                        "step-bar", "section-bar", "risk-bar", "row_bar"}
GLOW_SHAPE_NAMES = {"dot", "step-num", "card-num", "chrome-dot"}


def _name_matches(shape_name: str, targets: set[str]) -> bool:
    """Check if shape name contains any of the target patterns."""
    name_lower = shape_name.lower()
    for target in targets:
        if target.replace("_", "-") in name_lower or target in name_lower:
            return True
    return False


def postprocess_slide_effects(slide_xml: bytes, accent_color: str = "2563EB") -> bytes:
    """Apply shadows, gradients, and glow to a slide's XML.

    Scans all shapes in the slide and applies effects based on shape naming
    conventions from the layout engine (block_XX_role_idx format).
    """
    try:
        root = ET.fromstring(slide_xml)
    except ET.ParseError:
        return slide_xml

    shape_count = 0
    shadow_count = 0
    gradient_count = 0
    glow_count = 0

    # Find all shapes
    for sp in root.iter(_ns("p:sp")):
        # Get shape name from cNvPr
        nv_sp_pr = sp.find(_ns("p:nvSpPr"))
        if nv_sp_pr is None:
            continue
        c_nv_pr = nv_sp_pr.find(_ns("p:cNvPr"))
        if c_nv_pr is None:
            continue
        shape_name = c_nv_pr.get("name", "")
        if not shape_name:
            continue
        shape_count += 1

        # Apply shadow to card/panel shapes
        if _name_matches(shape_name, SHADOW_SHAPE_NAMES):
            if apply_shadow_to_shape(sp):
                shadow_count += 1

        # Apply gradient to accent bars
        if _name_matches(shape_name, GRADIENT_SHAPE_NAMES):
            colors = [(accent_color, 0), (_darken(accent_color), 100)]
            if apply_gradient_to_shape(sp, colors):
                gradient_count += 1

        # Apply glow to dots/numbers
        if _name_matches(shape_name, GLOW_SHAPE_NAMES):
            if apply_glow_to_shape(sp, color=accent_color):
                glow_count += 1

    result = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    print(f"  [effects] {shape_count} shapes: {shadow_count} shadows, "
          f"{gradient_count} gradients, {glow_count} glows")
    return result


def apply_effects_to_pptx(pptx_path: str | Path, accent_color: str = "2563EB") -> dict[str, Any]:
    """Post-process a PPTX file: inject effects into all slides.

    Returns a report dict with per-slide effect counts.
    """
    pptx_path = Path(pptx_path).resolve()
    if not pptx_path.exists():
        return {"status": "error", "reason": f"File not found: {pptx_path}"}

    tmp_path = pptx_path.with_suffix(".tmp.pptx")
    report: dict[str, Any] = {"status": "ok", "slides": {}, "accent_color": accent_color}

    with zipfile.ZipFile(pptx_path, "r") as zin:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item)
                if item.filename.startswith("ppt/slides/slide") and item.filename.endswith(".xml"):
                    new_data = postprocess_slide_effects(data, accent_color)
                    slide_num = item.filename.replace("ppt/slides/slide", "").replace(".xml", "")
                    report["slides"][slide_num] = "processed"
                else:
                    new_data = data
                zout.writestr(item, new_data)

    # Replace original atomically
    import os as _os
    _os.replace(tmp_path, pptx_path)

    return report


def _darken(hex_color: str, factor: float = 0.6) -> str:
    """Darken a hex color by a factor."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r2 = int(r * factor)
    g2 = int(g * factor)
    b2 = int(b * factor)
    return f"{r2:02X}{g2:02X}{b2:02X}"
