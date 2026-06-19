"""GenPPT render artifact — exports deck.json + renders PPTX via Python renderer.

Image acquisition: reads the Director's image requirements from the creative brief,
searches the web for matching images, and injects them into the PPTX.
"""

from __future__ import annotations

import json
from pathlib import Path

from .orchestrator import DeckResult, result_to_deck_dict
from .renderer import DeckRenderer
from .trace import agent_trace_markdown, build_agent_trace_payload


def _acquire_images(deck: dict, workspace: Path, concept) -> dict[int, str]:
    """Acquire images for slides that need them.

    Strategy: web search first (free, fast) → Qwen generation as fallback.

    Returns a dict mapping slide_index → local image path.
    """
    images_map: dict[int, str] = {}
    image_dir = workspace / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    for slide in deck.get("slides", []):
        idx = int(slide.get("index") or 0)
        intent = str(slide.get("intent", ""))
        role = str(slide.get("narrative_role", slide.get("role", "")))
        headline = str(slide.get("headline", ""))
        visual_hint = str(slide.get("visual_hint", ""))
        body = slide.get("body") or []

        # Determine if this slide needs an image
        needs_image = (
            idx == 1  # cover always
            or role in ("cover", "closing")  # opening/closing pages
            or intent in ("开场冲击", "行动号召", "展示方案细节", "案例展示")
            or any(kw in visual_hint for kw in ("图", "照片", "插画", "配图", "示意", "图标", "icon"))
            or any(kw in str(body) for kw in ("示意图", "配图", "插图"))
        )
        if not needs_image:
            continue

        # Build effective search query
        metaphor = concept.visual_metaphor if concept else ""
        search_query = f"{headline[:40]} {metaphor}" if metaphor else headline[:60]
        # Add "presentation background" context for better results
        search_query = f"{search_query} presentation background"

        print(f"  [images] Slide {idx}: searching '{search_query[:80]}...'")

        # Strategy 1: Web search
        try:
            from .tools.web_image import search_web_images
            result = search_web_images(search_query, image_dir, max_results=1)
            if result.get("success") and result.get("images"):
                images_map[idx] = result["images"][0]
                print(f"  [images] Slide {idx}: ✓ web image found")
                continue
            else:
                print(f"  [images] Slide {idx}: web search returned no results")
        except Exception as e:
            print(f"  [images] Slide {idx}: web search error: {e}")

        # Strategy 2: Qwen generation (if DASHSCOPE_API_KEY is set)
        try:
            import os
            if os.getenv("DASHSCOPE_API_KEY"):
                from .tools.image_gen import generate_qwen_image, build_image_prompt
                ac = concept.accent_hex.lstrip("#") if concept else "2563EB"
                bg = concept.background_hex.lstrip("#") if concept else "F8FAFC"
                prompt = build_image_prompt(
                    visual_metaphor=metaphor or "专业商务演示",
                    accent_hex=f"#{ac}",
                    background_hex=f"#{bg}",
                    description=headline[:100],
                    style_direction=concept.style_direction if concept else "",
                )
                gen = generate_qwen_image(prompt, image_dir, f"slide_{idx}.png")
                if gen.get("success"):
                    images_map[idx] = gen["path"]
                    print(f"  [images] Slide {idx}: ✓ Qwen generated")
                else:
                    print(f"  [images] Slide {idx}: Qwen failed: {gen.get('error', '')}")
        except Exception as e:
            print(f"  [images] Slide {idx}: Qwen error: {e}")

    if images_map:
        print(f"  [images] Acquired {len(images_map)} images for slides: {list(images_map.keys())}")
    else:
        print(f"  [images] No images acquired (web search may need network, or set DASHSCOPE_API_KEY for Qwen)")
    return images_map


def export_pptx(
    result: DeckResult,
    output_dir: Path,
    slug: str | None = None,
    brand_path: str | None = None,
) -> Path:
    output_dir = output_dir.resolve()
    deck_slug = slug or _slugify(result.deck_plan.title)
    final_pptx = output_dir / f"{deck_slug}.pptx"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save deck.json
    deck = result_to_deck_dict(result)
    workspace = output_dir.parent / "outputs" / deck_slug
    workspace.mkdir(parents=True, exist_ok=True)
    deck_json = workspace / "deck.json"
    deck_json.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    trace_payload = build_agent_trace_payload(deck)
    (workspace / "agent_trace.json").write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (workspace / "agent_trace.md").write_text(agent_trace_markdown(trace_payload), encoding="utf-8")

    # Build brand from design concept
    brand = _load_brand_file(brand_path) if brand_path else None

    # Acquire images for slides that need them
    concept = result.design_concept
    if concept is None:
        from .style import DesignConcept
        concept = DesignConcept()
    images_map = _acquire_images(deck, workspace, concept)

    # Render with Python renderer
    renderer = DeckRenderer(
        concept=concept,
        slides=deck["slides"],
        brand=brand,
        images_map=images_map,
    )
    renderer.render(final_pptx)

    # OOXML post-processing effects (shadow, gradient)
    try:
        from .pptx_lxml_effects import apply_effects_to_pptx
        accent = concept.accent_hex.lstrip("#") if concept else "2563EB"
        apply_effects_to_pptx(final_pptx, accent_color=accent)
    except Exception as exc:
        print(f"[effects] OOXML post-processing skipped: {exc}")

    return final_pptx


def _slugify(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_一二三四五六七八九十" or "一" <= ch <= "鿿" else "-" for ch in text)
    cleaned = "-".join(p for p in cleaned.split("-") if p)
    return cleaned[:80] or "deck"


def _load_brand_file(brand_path: str) -> dict[str, str] | None:
    """Load brand colors from a power-design brand-style.md file."""
    import re
    path = Path(brand_path)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")

    def _get(section: str, key: str, default: str = "") -> str:
        sec = re.search(rf"^{section}:\s*\n(.*?)(?=^[a-z])", text, re.MULTILINE | re.DOTALL)
        if not sec:
            return default
        m = re.search(rf"^\s+{key}:\s*\"?([^\"\n]+)\"?", sec.group(1), re.MULTILINE)
        return m.group(1).strip().strip('"') if m else default

    return {
        "bg": _get("colors", "canvas", "F8F9FB"),
        "surface": _get("colors", "surface-1", "FFFFFF"),
        "ink": _get("colors", "ink", "111827"),
        "muted": _get("colors", "ink-muted", "6B7280"),
        "line": _get("colors", "hairline", "E5E7EB"),
        "accent": _get("colors", "primary", "2563EB"),
        "green": _get("colors", "semantic-success", "059669"),
    }
