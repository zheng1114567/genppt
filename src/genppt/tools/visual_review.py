"""Visual layout review using Qwen VL multimodal model.

Renders slides to images and sends them to a vision-capable LLM
for aesthetic quality review. Runs as an optional step within the
quality review phase.

Multi-backend slide capture (tried in order):
  1. LibreOffice headless (soffice --headless --convert-to png)
  2. PowerPoint COM automation (Windows only)
  3. Falls back gracefully — visual review skipped, text review stands
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


# ── Slide image capture ──

def capture_slide_images(pptx_path: Path, output_dir: Path) -> list[Path]:
    """Convert a PPTX file to a list of PNG images, one per slide.

    Returns a list of image file paths sorted by slide number.
    Returns an empty list if no backend is available.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Try backends in order
    for backend in (_via_libreoffice, _via_powerpoint_com):
        try:
            paths = backend(pptx_path, output_dir)
            if paths:
                return sorted(paths, key=_slide_number_from_filename)
        except Exception:
            continue

    return []


def _slide_number_from_filename(path: Path) -> int:
    """Extract slide number from filename like 'slide_3.png' or 'Slide3.png'."""
    import re
    name = path.stem
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0


def _via_libreoffice(pptx_path: Path, output_dir: Path) -> list[Path]:
    """Convert PPTX to PNG using LibreOffice headless mode."""
    soffice = shutil.which("soffice")
    if not soffice:
        soffice_paths = [
            "C:\\Program Files\\LibreOffice\\program\\soffice.exe",
            "C:\\Program Files (x86)\\LibreOffice\\program\\soffice.exe",
            "/usr/bin/soffice",
        ]
        soffice = next((p for p in soffice_paths if Path(p).exists()), None)
    if not soffice:
        return []

    subprocess.run(
        [
            soffice, "--headless", "--convert-to", "png",
            f"--outdir", str(output_dir), str(pptx_path),
        ],
        timeout=120,
        capture_output=True,
    )
    return list(output_dir.glob("*.png"))


def _via_powerpoint_com(pptx_path: Path, output_dir: Path) -> list[Path]:
    """Convert PPTX to PNG using PowerPoint COM automation (Windows)."""
    if os.name != "nt":
        return []

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("PowerPoint.Application")
        app.Visible = False  # type: ignore[union-attr]
        pres = app.Presentations.Open(str(pptx_path), ReadOnly=True, WithWindow=False)  # type: ignore[union-attr]
        paths = []
        for i in range(1, pres.Slides.Count + 1):
            out_path = output_dir / f"slide_{i:02d}.png"
            pres.Slides(i).Export(str(out_path), "PNG")
            paths.append(out_path)
        pres.Close()
        app.Quit()  # type: ignore[union-attr]
        return paths
    except Exception:
        return []
    finally:
        pythoncom.CoUninitialize()


# ── Vision model review ──

VISUAL_REVIEW_PROMPT = """你是 PPT 视觉排版审查专家。请仔细查看这张幻灯片截图，从以下维度诊断排版与设计问题：

## 审查维度

1. **文字可读性**: 字号是否足够大？对比度是否足够？文字是否有被裁切/溢出？
2. **视觉层次**: 标题和正文的视觉权重对比是否清晰？观众能在3秒内找到核心信息吗？
3. **留白平衡**: 页面的空白区域是否充足（应≥30%）？是否有拥挤感或空旷感？
4. **色彩和谐**: 强调色使用是否克制（每页最多一个accent色时刻）？配色是否协调？
5. **元素对齐**: 文字、形状、图表是否明显对齐？有没有悬浮/偏移的元素？
6. **整体专业感**: 这页幻灯片看起来专业吗？还是像草稿/半成品？

## 上下文信息

这是整套PPT的第 {slide_index} 页（共 {total_slides} 页）。
页面使命: {intent}
标题: {headline}
正文概要: {body_summary}
全局设计概念: {design_rationale}

## 输出格式

严格 JSON（不要输出 Markdown）：
{{
  "slide_index": {slide_index},
  "readable": true/false,
  "professional": true/false,
  "overall_score": 7.5,
  "issues": [
    {{
      "category": "visual",
      "severity": "critical|major|minor",
      "message": "具体问题描述（中文，≤40字）",
      "suggestion": "修改建议（中文，≤50字）"
    }}
  ],
  "strengths": ["这页做得好的地方（必须给1条）"]
}}

## 严重度标准

- critical: 严重影响可读性或专业感（文字截断、对比度极低、元素重叠）
- major: 明显降低质量（留白不足、字号过小、对齐偏差）
- minor: 可优化点（间距微调、强调色位置不最优）

注意：
- 如果没有问题，issues 可以为空数组
- strengths 不能为空，至少给1条
- 如果页面整体 OK，overall_score 可以给 7+
- 这是演讲稿的幻灯片截图，评判标准应适合演讲/阅读场景"""


def review_slide_visual(
    image_path: Path,
    slide_context: dict[str, Any],
    vision_llm: Any,
) -> dict[str, Any]:
    """Send one slide image to the vision model for aesthetic review.

    Args:
        image_path: Path to the slide PNG image.
        slide_context: Dict with keys: slide_index, total_slides, intent,
                       headline, body_summary, design_rationale.
        vision_llm: A LangChain ChatOpenAI instance configured for vision.

    Returns:
        A review dict with keys: slide_index, readable, professional,
        overall_score, issues, strengths.
    """
    image_b64 = _encode_image_base64(image_path)
    if not image_b64:
        return _fallback_review(slide_context.get("slide_index", 0))

    prompt_text = VISUAL_REVIEW_PROMPT.format(
        slide_index=slide_context.get("slide_index", "?"),
        total_slides=slide_context.get("total_slides", "?"),
        intent=slide_context.get("intent", "未知"),
        headline=slide_context.get("headline", "")[:80],
        body_summary=slide_context.get("body_summary", "无正文")[:200],
        design_rationale=slide_context.get("design_rationale", "无")[:200],
    )

    from langchain_core.messages import HumanMessage

    message = HumanMessage(content=[
        {"type": "text", "text": prompt_text},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{image_b64}",
            },
        },
    ])

    try:
        response = vision_llm.invoke([message])
        content = str(response.content) if hasattr(response, "content") else str(response)
        return _parse_visual_review(content, slide_context.get("slide_index", 0))
    except Exception:
        return _fallback_review(slide_context.get("slide_index", 0))


def _encode_image_base64(path: Path) -> str:
    """Read an image file and return its base64-encoded string."""
    try:
        data = path.read_bytes()
        if len(data) > 10 * 1024 * 1024:  # 10MB limit
            # Resize would need Pillow; skip for now
            return ""
        return base64.b64encode(data).decode("ascii")
    except Exception:
        return ""


def _parse_visual_review(content: str, slide_index: int) -> dict[str, Any]:
    """Parse the VL model JSON response into a structured review dict."""
    import re
    # Strip markdown fences
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        cleaned = cleaned.removesuffix("```").strip()
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    # Extract outermost JSON object
    start = cleaned.find("{")
    if start < 0:
        return _fallback_review(slide_index)
    depth, in_str, esc = 0, False, False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if esc:
            esc = False; continue
        if ch == "\\":
            esc = True; continue
        if ch == '"' and not esc:
            in_str = not in_str; continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start:i + 1])
                except (json.JSONDecodeError, ValueError):
                    return _fallback_review(slide_index)
                return {
                    "slide_index": int(parsed.get("slide_index", slide_index)),
                    "readable": bool(parsed.get("readable", True)),
                    "professional": bool(parsed.get("professional", True)),
                    "overall_score": float(parsed.get("overall_score", 6.0)),
                    "issues": _normalize_visual_issues(parsed.get("issues", [])),
                    "strengths": parsed.get("strengths", []),
                }
    return _fallback_review(slide_index)


def _normalize_visual_issues(issues: list[dict]) -> list[dict[str, Any]]:
    """Ensure visual issues have the standard category/severity/message shape."""
    out = []
    for iss in (issues or []):
        sev = str(iss.get("severity", "minor")).lower()
        if sev not in ("critical", "major", "minor", "error", "warning"):
            sev = "minor"
        out.append({
            "category": "visual",
            "slide_index": iss.get("slide_index"),
            "severity": sev,
            "message": str(iss.get("message", iss.get("description", "")))[:120],
            "suggestion": str(iss.get("suggestion", ""))[:150],
        })
    return out


def _fallback_review(slide_index: int) -> dict[str, Any]:
    return {
        "slide_index": slide_index,
        "readable": True,
        "professional": True,
        "overall_score": 6.0,
        "issues": [],
        "strengths": ["视觉模型不可用，跳过视觉审查"],
    }


# ── Main orchestrator ──

def run_visual_review(
    slides: list[dict[str, Any]],
    design_concept: dict[str, Any],
    design_specs: list[dict[str, Any]],
    output_dir: Path,
    max_slides: int = 4,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run visual review on rendered slide images.

    Args:
        slides: Slide dicts from ContentDesign (headline, body, intent, etc.).
        design_concept: Global design concept dict.
        design_specs: Per-slide design decisions from PPTDesign.
        output_dir: Temp directory for rendering.
        max_slides: Max number of slides to send to VL model (controls cost).
        verbose: Print progress.

    Returns:
        Dict with keys: visual_score (float), visual_issues (list),
        slides_reviewed (int), strengths (list), error (str).
    """
    # 1. Get vision model
    from ..llm import get_vision_model
    vision_llm = get_vision_model()
    if vision_llm is None:
        return {
            "visual_score": 0, "visual_issues": [],
            "slides_reviewed": 0, "strengths": [],
            "error": "视觉模型不可用：未配置DASHSCOPE_API_KEY",
        }

    # 2. Render temp PPTX from current state
    temp_pptx = _render_temp_pptx(slides, design_concept, design_specs, output_dir)
    if temp_pptx is None:
        return {
            "visual_score": 0, "visual_issues": [],
            "slides_reviewed": 0, "strengths": [],
            "error": "无法渲染临时PPTX",
        }

    # 3. Capture slide images
    img_dir = output_dir / "review_images"
    slide_images = capture_slide_images(temp_pptx, img_dir)
    if not slide_images:
        if verbose:
            print("  👁️ 视觉审查: 无法将PPTX转换为图片 (LibreOffice/PowerPoint不可用)，跳过")
        # Clean up temp file
        try:
            temp_pptx.unlink(missing_ok=True)
        except Exception:
            pass
        return {
            "visual_score": 0, "visual_issues": [],
            "slides_reviewed": 0, "strengths": [],
            "error": "无法将PPTX转换为图片 (需要LibreOffice或PowerPoint)",
        }

    if verbose:
        print(f"  👁️ 视觉审查: 捕获了 {len(slide_images)} 张幻灯片图片")

    # 4. Select slides to review (sample if too many)
    slides_to_review = _select_review_slides(slides, slide_images, max_slides)

    # 5. Review each selected slide
    total_slides = len(slides)
    design_rationale = design_concept.get("design_rationale", "")
    all_issues: list[dict[str, Any]] = []
    all_strengths: list[str] = []
    scores: list[float] = []

    for slide_idx, img_path in slides_to_review:
        ctx = _build_slide_context(slides, slide_idx, total_slides, design_rationale)
        try:
            result = review_slide_visual(img_path, ctx, vision_llm)
            all_issues.extend(result.get("issues", []))
            all_strengths.extend(result.get("strengths", []))
            scores.append(result.get("overall_score", 6.0))
            if verbose:
                n_issues = len(result.get("issues", []))
                score = result.get("overall_score", "?")
                status = "✅" if n_issues == 0 else f"⚠️ {n_issues}个问题"
                print(f"    第{slide_idx}页: {score}分 {status}")
        except Exception as e:
            if verbose:
                print(f"    第{slide_idx}页: ❌ 审查失败 ({e})")

    # 6. Clean up temp files
    try:
        temp_pptx.unlink(missing_ok=True)
        shutil.rmtree(img_dir, ignore_errors=True)
    except Exception:
        pass

    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    return {
        "visual_score": avg_score,
        "visual_issues": all_issues,
        "slides_reviewed": len(scores),
        "strengths": all_strengths[:4],
        "error": "",
    }


def _render_temp_pptx(
    slides: list[dict[str, Any]],
    design_concept: dict[str, Any],
    design_specs: list[dict[str, Any]],
    output_dir: Path,
) -> Path | None:
    """Render a temporary PPTX from current agent state for visual review."""
    try:
        from ..renderer import DeckRenderer
        from ..style import DesignConcept

        # Merge design_specs into slides (same logic as render_artifact)
        design_by_idx: dict[int, dict[str, Any]] = {}
        for ds in design_specs:
            idx = int(ds.get("index", 0))
            if idx > 0:
                design_by_idx[idx] = ds

        merged_slides: list[dict[str, Any]] = []
        for s in slides:
            idx = int(s.get("index", 0))
            ds = design_by_idx.get(idx, {})
            merged = dict(s)
            merged["layout"] = ds.get("structure", "")
            merged["design"] = ds.get("design", {})
            merged["color_treatment"] = ds.get("color_treatment", {})
            merged["shape_language"] = ds.get("shape_language", "")
            if ds.get("chart_spec"):
                merged["chart_spec"] = ds["chart_spec"]
            merged_slides.append(merged)

        concept = DesignConcept(
            visual_metaphor=str(design_concept.get("visual_metaphor", "")),
            style_direction=str(design_concept.get("style_direction", "")),
            primary_hex=str(design_concept.get("primary_hex", "#111827")),
            background_hex=str(design_concept.get("background_hex", "#F8FAFC")),
            accent_hex=str(design_concept.get("accent_hex", "#2563EB")),
            accent_secondary_hex=str(design_concept.get("accent_secondary_hex", "#10B981")),
            semantic_colors=design_concept.get("semantic_colors", {}),
            font_family=str(design_concept.get("font_family", "Microsoft YaHei")),
            base_size_pt=int(design_concept.get("base_size_pt", 14)),
            max_title_size_pt=int(design_concept.get("max_title_size_pt", 44)),
            type_scale_ratio=float(design_concept.get("type_scale_ratio", 1.333)),
            spacing_mood=str(design_concept.get("spacing_mood", "normal")),
            shape_style=str(design_concept.get("shape_style", "sharp")),
            decoration_level=str(design_concept.get("decoration_level", "minimal")),
            design_rationale=str(design_concept.get("design_rationale", "")),
        )

        temp_pptx = output_dir / "_visual_review_temp.pptx"
        renderer = DeckRenderer(concept=concept, slides=merged_slides)
        renderer.render(temp_pptx)
        return temp_pptx
    except Exception:
        return None


def _select_review_slides(
    slides: list[dict[str, Any]],
    slide_images: list[Path],
    max_slides: int,
) -> list[tuple[int, Path]]:
    """Select which slides to send to the vision model.

    Prioritizes: cover (page 1), content pages with charts/visuals,
    closing page. Ensures diverse layout sampling.
    """
    if max_slides <= 0:
        return []

    # Build index → image path map
    img_map: dict[int, Path] = {}
    for img_path in slide_images:
        n = _slide_number_from_filename(img_path)
        if n > 0:
            img_map[n] = img_path

    selected: list[tuple[int, Path]] = []
    seen: set[int] = set()

    # Always include cover (index 1)
    if 1 in img_map:
        selected.append((1, img_map[1]))
        seen.add(1)

    # Prioritize: closing page, chart pages, then fill remaining
    priorities: list[int] = []
    for s in slides:
        idx = int(s.get("index", 0))
        if idx in seen or idx not in img_map:
            continue
        role = str(s.get("role", ""))
        has_chart = bool(s.get("chart_spec"))
        if role == "closing":
            priorities.insert(0, idx)
        elif has_chart:
            priorities.append(idx)

    for idx in priorities:
        if len(selected) >= max_slides:
            break
        if idx not in seen and idx in img_map:
            selected.append((idx, img_map[idx]))
            seen.add(idx)

    # Fill remaining with evenly-spaced content pages
    remaining = [int(s.get("index", 0)) for s in slides
                 if int(s.get("index", 0)) not in seen and int(s.get("index", 0)) in img_map]
    step = max(len(remaining) // (max_slides - len(selected)), 1) if remaining else 1
    for i, idx in enumerate(remaining):
        if len(selected) >= max_slides:
            break
        if i % step == 0 and idx in img_map:
            selected.append((idx, img_map[idx]))

    return selected[:max_slides]


def _build_slide_context(
    slides: list[dict[str, Any]],
    slide_index: int,
    total_slides: int,
    design_rationale: str,
) -> dict[str, Any]:
    """Build context dict for a single slide to send to the vision model."""
    slide = next((s for s in slides if int(s.get("index", 0)) == slide_index), {})
    body = slide.get("body") or []
    body_summary = "; ".join(str(b)[:60] for b in body[:3])
    return {
        "slide_index": slide_index,
        "total_slides": total_slides,
        "intent": str(slide.get("intent", slide.get("narrative_function", ""))),
        "headline": str(slide.get("headline", "")),
        "body_summary": body_summary,
        "design_rationale": design_rationale,
    }
