from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def profile_pptx_template(pptx_path: Path) -> dict[str, Any]:
    """Extract a compact master/layout/placeholder profile from a PPTX file."""
    pptx_path = pptx_path.resolve()
    if not pptx_path.exists():
        raise FileNotFoundError(pptx_path)

    with zipfile.ZipFile(pptx_path) as archive:
        names = archive.namelist()
        layout_paths = sorted(name for name in names if name.startswith("ppt/slideLayouts/slideLayout") and name.endswith(".xml"))
        master_paths = sorted(name for name in names if name.startswith("ppt/slideMasters/slideMaster") and name.endswith(".xml"))
        theme_paths = sorted(name for name in names if name.startswith("ppt/theme/theme") and name.endswith(".xml"))
        layouts = [_profile_layout(archive, path) for path in layout_paths]

    placeholder_counts: dict[str, int] = {}
    for layout in layouts:
        for placeholder in layout["placeholders"]:
            key = placeholder["type"]
            placeholder_counts[key] = placeholder_counts.get(key, 0) + 1

    return {
        "template_path": str(pptx_path),
        "master_count": len(master_paths),
        "layout_count": len(layouts),
        "theme_count": len(theme_paths),
        "placeholder_counts": placeholder_counts,
        "layouts": layouts,
        "recommendations": _recommendations(layouts, placeholder_counts),
    }


def write_template_profile(pptx_path: Path, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = profile_pptx_template(pptx_path)
    json_path = output_dir / "template-profile.json"
    md_path = output_dir / "layout-catalog.md"
    json_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(layout_catalog_markdown(profile), encoding="utf-8")
    return json_path, md_path


def layout_catalog_markdown(profile: dict[str, Any]) -> str:
    lines = [
        f"# Layout Catalog",
        "",
        f"- Template: `{profile.get('template_path')}`",
        f"- Masters: {profile.get('master_count', 0)}",
        f"- Layouts: {profile.get('layout_count', 0)}",
        f"- Themes: {profile.get('theme_count', 0)}",
        "",
        "## Placeholder Summary",
    ]
    counts = profile.get("placeholder_counts") or {}
    if counts:
        for key, count in sorted(counts.items()):
            lines.append(f"- `{key}`: {count}")
    else:
        lines.append("- No explicit placeholders found.")

    lines.extend(["", "## Layouts"])
    for layout in profile.get("layouts") or []:
        lines.extend(
            [
                "",
                f"### {layout['index']:02d}. {layout['name']}",
                f"- Path: `{layout['path']}`",
                f"- Placeholder count: {len(layout['placeholders'])}",
            ]
        )
        for placeholder in layout["placeholders"]:
            lines.append(
                "- "
                f"`{placeholder['type']}`"
                f" idx={placeholder['idx']}"
                f" name=\"{placeholder['name']}\""
                f" bbox={placeholder['bbox']}"
            )
    lines.extend(["", "## Recommendations"])
    for item in profile.get("recommendations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def _profile_layout(archive: zipfile.ZipFile, path: str) -> dict[str, Any]:
    root = ET.fromstring(archive.read(path))
    c_sld = root.find("p:cSld", NS)
    name = c_sld.attrib.get("name") if c_sld is not None else ""
    placeholders: list[dict[str, Any]] = []
    for shape in root.findall(".//p:sp", NS):
        ph = shape.find(".//p:ph", NS)
        if ph is None:
            continue
        c_nv_pr = shape.find(".//p:cNvPr", NS)
        placeholders.append(
            {
                "id": c_nv_pr.attrib.get("id", "") if c_nv_pr is not None else "",
                "name": c_nv_pr.attrib.get("name", "") if c_nv_pr is not None else "",
                "type": ph.attrib.get("type", "body"),
                "idx": ph.attrib.get("idx", ""),
                "orient": ph.attrib.get("orient", ""),
                "size": ph.attrib.get("sz", ""),
                "bbox": _shape_bbox(shape),
            }
        )
    return {
        "index": _path_index(path),
        "path": path,
        "name": name or Path(path).stem,
        "placeholders": placeholders,
    }


def _shape_bbox(shape: ET.Element) -> dict[str, int | None]:
    off = shape.find(".//a:off", NS)
    ext = shape.find(".//a:ext", NS)
    return {
        "x": _int_attr(off, "x"),
        "y": _int_attr(off, "y"),
        "cx": _int_attr(ext, "cx"),
        "cy": _int_attr(ext, "cy"),
    }


def _int_attr(element: ET.Element | None, name: str) -> int | None:
    if element is None or name not in element.attrib:
        return None
    try:
        return int(element.attrib[name])
    except ValueError:
        return None


def _path_index(path: str) -> int:
    stem = Path(path).stem
    digits = "".join(ch for ch in stem if ch.isdigit())
    return int(digits or 0)


def _recommendations(layouts: list[dict[str, Any]], placeholder_counts: dict[str, int]) -> list[str]:
    recommendations: list[str] = []
    if not layouts:
        return ["No slide layouts were found; use GenPPT built-in templates instead of placeholder mapping."]
    if placeholder_counts.get("title", 0) < len(layouts) // 2:
        recommendations.append("Many layouts do not expose title placeholders; prefer shape-based rendering for those layouts.")
    if placeholder_counts.get("body", 0) + placeholder_counts.get("obj", 0) == 0:
        recommendations.append("No body/object placeholders were detected; treat the file as a theme source rather than a fillable template.")
    if len(layouts) >= 6:
        recommendations.append("Template has enough layout variety for a profile-author-render workflow.")
    else:
        recommendations.append("Template has limited layout variety; combine native theme extraction with GenPPT layout grammar.")
    return recommendations
