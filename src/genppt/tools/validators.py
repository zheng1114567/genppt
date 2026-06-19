"""Validation tools for GenPPT ReAct agents.

Each tool is a deterministic Python function that checks one aspect of quality.
They are designed to be used as @tool-decorated functions for LangChain/LangGraph.
"""

from __future__ import annotations

from typing import Any


def validate_brief(brief: dict[str, Any]) -> list[dict[str, str]]:
    """Check Brief completeness and quality. Returns list of issues (empty = pass)."""
    issues: list[dict[str, str]] = []

    if not brief.get("topic", "").strip():
        issues.append({"field": "topic", "severity": "error", "message": "主题为空"})

    audience = brief.get("audience", "")
    generic_audiences = {"通用听众", "所有人", "听众", "观众", "general", "通用"}
    if audience.strip() in generic_audiences:
        issues.append({"field": "audience", "severity": "warning", "message": f"受众描述过于笼统: '{audience}'，应具体描述决策权和关注点"})

    page_count = brief.get("page_count", 0)
    if not isinstance(page_count, int) or page_count < 3:
        issues.append({"field": "page_count", "severity": "error", "message": f"页数{page_count}过少，最少3页"})
    elif page_count > 20:
        issues.append({"field": "page_count", "severity": "warning", "message": f"页数{page_count}可能过多，考虑精简"})

    tone = brief.get("tone", "")
    if not tone.strip() or tone.strip() in {"专业", "正式", "professional"}:
        issues.append({"field": "tone", "severity": "warning", "message": "语气描述过于笼统，应包含具体场景感如'对高管汇报的果断'或'给工程师团队的技术细节'"})

    return issues


def check_narrative_arc(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Verify narrative structure has opening, progression, and closing."""
    issues: list[dict[str, Any]] = []
    if not slides:
        return [{"category": "structure", "slide_index": None, "severity": "error", "message": "幻灯片列表为空"}]

    first = slides[0]
    first_role = str(first.get("role", first.get("intent", ""))).lower()
    if "cover" not in first_role and "开场" not in str(first.get("headline", "")):
        issues.append({"category": "structure", "slide_index": 1, "severity": "warning", "message": "第一页 role 应为 cover，承担开场功能"})

    last = slides[-1]
    last_role = str(last.get("role", last.get("intent", ""))).lower()
    if "closing" not in last_role and "收束" not in str(last.get("headline", "")):
        issues.append({"category": "structure", "slide_index": len(slides), "severity": "warning", "message": "最后一页 role 应为 closing，承担收束功能"})

    # Check middle pages have narrative progression
    funcs = [str(s.get("narrative_function", s.get("intent", ""))) for s in slides[1:-1]]
    for i in range(2, len(funcs)):
        if funcs[i] == funcs[i-1] == funcs[i-2]:
            issues.append({"category": "structure", "slide_index": i + 2, "severity": "warning", "message": f"连续3页 narrative_function 相同({funcs[i]})，叙事缺乏推进"})
            break

    return issues


def check_content_density(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check each slide has enough substantive content. Excludes cover, closing, divider pages."""
    issues: list[dict[str, Any]] = []
    excluded_roles = {"cover", "closing", "divider"}
    for s in slides:
        idx = int(s.get("index") or 0)
        role = str(s.get("role", s.get("intent", ""))).lower()
        body = s.get("body") or []
        headline = str(s.get("headline", ""))

        # Divider/cover/closing pages exempt from body requirements
        if role in excluded_roles:
            continue

        # Headline must be a judgment (≥10字)
        if len(headline) < 10:
            issues.append({"category": "content", "slide_index": idx, "severity": "warning", "message": f"标题过短({len(headline)}字)'{headline[:30]}'，应≥10字的判断句"})

        # Non-excluded pages need ≥2 body items
        if len(body) < 2:
            issues.append({"category": "content", "slide_index": idx, "severity": "error", "message": f"第{idx}页正文少于2条，内容密度不足"})

        # Each body item ≥25字
        for bi, item in enumerate(body):
            item_str = str(item)
            if len(item_str) < 25:
                issues.append({"category": "content", "slide_index": idx, "severity": "warning", "message": f"第{idx}页第{bi+1}条过短({len(item_str)}字)，需≥25字包含证据或推理"})

    return issues


def check_cross_page_duplication(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect headline duplication and significant content overlap across pages."""
    issues: list[dict[str, Any]] = []
    headlines: dict[str, int] = {}
    for s in slides:
        hl = str(s.get("headline", "")).strip()
        idx = int(s.get("index") or 0)
        if hl in headlines:
            issues.append({"category": "content", "slide_index": idx, "severity": "error", "message": f"标题与第{headlines[hl]}页重复: '{hl}'"})
        else:
            headlines[hl] = idx

    # Check for body item overlap (simple substring match)
    for i in range(len(slides)):
        for j in range(i + 1, len(slides)):
            body_i = " ".join(str(b) for b in (slides[i].get("body") or []))
            body_j = " ".join(str(b) for b in (slides[j].get("body") or []))
            if len(body_i) > 30 and len(body_j) > 30:
                # Simple overlap: if they share a long enough common substring
                common = _longest_common_substring(body_i, body_j)
                if len(common) >= 30:
                    issues.append({"category": "content", "slide_index": int(slides[j].get("index", 0)), "severity": "warning", "message": f"与第{slides[i].get('index')}页正文存在重复段落"})

    return issues


def check_terminology_consistency(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check that key terms are used consistently across all slides."""
    issues: list[dict[str, Any]] = []
    # Extract all Chinese/English compound terms (2-6 chars) from all slides
    all_text = []
    for s in slides:
        text = str(s.get("headline", "")) + " " + " ".join(str(b) for b in (s.get("body") or []))
        all_text.append(text)

    # Look for potential inconsistent abbreviations or terms
    # e.g., if "AI" appears in some slides and "人工智能" in others without introduction
    term_variants: dict[str, set[int]] = {}
    for idx, text in enumerate(all_text):
        for term in ["AI", "人工智能", "ROI", "投入产出比", "KPI", "指标", "SaaS", "软件即服务"]:
            if term in text:
                term_variants.setdefault(term, set()).add(idx)

    # Check related pairs for inconsistent usage
    pairs = [("AI", "人工智能"), ("ROI", "投入产出比"), ("KPI", "指标")]
    for a, b in pairs:
        if a in term_variants and b in term_variants:
            if term_variants[a] != term_variants[b]:
                issues.append({"category": "terminology", "slide_index": None, "severity": "warning", "message": f"'{a}'和'{b}'在不同页面混用，建议统一"})

    return issues


def check_cross_page_contradiction(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check for logical contradictions between slides beyond text duplication."""
    issues: list[dict[str, Any]] = []
    import re

    num_claims: dict[int, list[str]] = {}
    for s in slides:
        idx = int(s.get("index") or 0)
        text = str(s.get("headline", "")) + " " + " ".join(str(b) for b in (s.get("body") or []))
        directions = []
        if re.search(r"(增长|提升|增加|上升|提高)\s*\d+", text):
            directions.append("上升")
        if re.search(r"(下降|减少|降低|下滑|缩减)\s*\d+", text):
            directions.append("下降")
        if directions:
            num_claims[idx] = directions

    for i in num_claims:
        for j in num_claims:
            if i >= j:
                continue
            if "上升" in num_claims[i] and "下降" in num_claims[j]:
                issues.append({"category": "logic", "slide_index": None, "severity": "warning",
                               "message": f"第{i}页和第{j}页趋势方向相反，请确认是否指向同一指标还是不同指标"})
                break

    return issues


def check_layout_variety(design_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check layout distribution — prevent monotony. Short decks (≤4 pages) have relaxed requirements."""
    issues: list[dict[str, Any]] = []
    if not design_specs:
        return issues

    layouts = [resolve_structure(d) for d in design_specs]

    # Check consecutive repeats
    for i in range(2, len(layouts)):
        if layouts[i] == layouts[i-1] == layouts[i-2]:
            issues.append({"category": "design", "slide_index": i + 1, "severity": "error", "message": f"连续3页使用相同版式({layouts[i]})，视觉单调"})

    # Check overall variety — scaled to available layout count (18+)
    unique = set(layouts)
    if len(layouts) <= 4:
        min_variety = 3 if len(layouts) >= 3 else len(layouts)
    elif len(layouts) <= 7:
        min_variety = 4
    else:
        min_variety = 5
    if len(unique) < min(min_variety, len(layouts)):
        issues.append({"category": "design", "slide_index": None, "severity": "warning", "message": f"仅{len(unique)}种版式，整套PPT缺乏视觉变化(需要≥{min_variety}种)"})

    return issues


def check_dark_light_rhythm(design_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Allow 1-2 accent pages (dark in light deck or vice versa) for visual rhythm."""
    issues: list[dict[str, Any]] = []
    if len(design_specs) < 3:
        return issues

    bg_sequence = []
    for d in design_specs:
        ct = d.get("color_treatment", {})
        bg = ct.get("bg", d.get("design", {}).get("bg", "light"))
        base = "dark" if bg == "dark" else "light"
        bg_sequence.append(base)

    # Count minority pages
    dark_count = sum(1 for b in bg_sequence if b == "dark")
    light_count = len(bg_sequence) - dark_count
    minority = min(dark_count, light_count)
    max_minority = max(2, len(bg_sequence) // 4)  # up to 25% can be accent pages

    if minority > max_minority:
        issues.append({"category": "design", "slide_index": None, "severity": "warning",
                       "message": f"深/浅色页面比例失衡：少数色有{minority}页，建议不超过{max_minority}页。封面和关键数据页用深色即可。"})

    return issues


def quantify_data_presence(slides: list[dict[str, Any]]) -> dict[int, int]:
    """Count data points per slide with quality weighting: unit-bearing data ×2, raw numbers ×0.5."""
    import re
    result: dict[int, int] = {}
    for s in slides:
        idx = int(s.get("index") or 0)
        text = str(s.get("headline", "")) + " " + " ".join(str(b) for b in (s.get("body") or []))
        with_unit = len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|％|倍|个|项|元|万|亿|天|月|年|人|次|家)", text))
        raw = len(re.findall(r"(?<!\w)\d+(?:\.\d+)?(?!\s*(?:%|％|倍|[个项元万亿天月年人家]|\w))", text))
        result[idx] = with_unit * 2 + int(raw * 0.5)
    return result


def check_contrast_ratio(design_concept: dict[str, Any]) -> list[dict[str, Any]]:
    """Check that text/background contrast meets WCAG AA (≥4.5:1)."""
    issues: list[dict[str, Any]] = []
    primary = str(design_concept.get("primary_hex", "#111827")).lstrip("#")
    bg = str(design_concept.get("background_hex", "#F8FAFC")).lstrip("#")

    def _relative_luminance(hex_color: str) -> float:
        try:
            r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        except (ValueError, IndexError):
            return 0.0
        rs = r / 255.0
        gs = g / 255.0
        bs = b / 255.0
        rs = rs / 12.92 if rs <= 0.03928 else ((rs + 0.055) / 1.055) ** 2.4
        gs = gs / 12.92 if gs <= 0.03928 else ((gs + 0.055) / 1.055) ** 2.4
        bs = bs / 12.92 if bs <= 0.03928 else ((bs + 0.055) / 1.055) ** 2.4
        return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs

    try:
        l1, l2 = _relative_luminance(primary), _relative_luminance(bg)
        ratio = (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)
        if ratio < 3.0:
            issues.append({"category": "design", "slide_index": None, "severity": "error",
                           "message": f"正文对比度{ratio:.1f}:1低于最低标准3:1（当前{design_concept.get('primary_hex','?')} vs {design_concept.get('background_hex','?')}）"})
        elif ratio < 4.5:
            issues.append({"category": "design", "slide_index": None, "severity": "warning",
                           "message": f"正文对比度{ratio:.1f}:1未达AA标准4.5:1"})
    except Exception:
        pass
    return issues


def check_type_scale_consistency(design_concept: dict[str, Any]) -> list[dict[str, Any]]:
    """Check that max_title / base_size ratio is within reasonable bounds."""
    issues: list[dict[str, Any]] = []
    try:
        base = float(design_concept.get("base_size_pt", 12))
        max_title = float(design_concept.get("max_title_size_pt", 36))
        ratio_val = float(design_concept.get("type_scale_ratio", 1.333))

        if base < 10:
            issues.append({"category": "design", "slide_index": None, "severity": "warning",
                           "message": f"正文字号{base:.0f}pt偏小，投影场景建议≥14pt"})
        if max_title < 28:
            issues.append({"category": "design", "slide_index": None, "severity": "warning",
                           "message": f"最大标题字号{max_title:.0f}pt偏小，封面冲击力不足"})
        if ratio_val < 1.2 or ratio_val > 1.8:
            issues.append({"category": "design", "slide_index": None, "severity": "warning",
                           "message": f"字号比例{ratio_val:.3f}超出推荐范围[1.2, 1.8]"})
    except Exception:
        pass
    return issues


def check_word_count_per_slide(slides: list[dict[str, Any]], max_words: int = 75) -> list[dict[str, Any]]:
    """Check that each slide doesn't exceed the glanceable word limit."""
    issues: list[dict[str, Any]] = []
    for s in slides:
        idx = int(s.get("index") or 0)
        role = str(s.get("role", s.get("narrative_role", "")))
        if role == "cover":
            continue  # cover pages have different rules
        headline = str(s.get("headline", ""))
        body_text = " ".join(str(b) for b in (s.get("body") or []))
        total_words = len(headline) + len(body_text)
        if total_words > max_words * 2:  # Chinese chars ≈ words × 2
            issues.append({"category": "content", "slide_index": idx, "severity": "warning",
                           "message": f"第{idx}页约{total_words}字，超出{max_words*2}字建议上限，观众难以快速扫读"})
    return issues


def rule_check(
    slides: list[dict[str, Any]],
    design_specs: list[dict[str, Any]],
    brief: dict[str, Any],
) -> list[dict[str, Any]]:
    """Aggregate all hard-rule checks into one report."""
    all_issues: list[dict[str, Any]] = []

    # Page count (±20% tolerance)
    expected = brief.get("page_count", 0)
    actual = len(slides)
    if expected and actual:
        deviation = abs(actual - expected) / expected
        if deviation > 0.2:
            all_issues.append({"category": "structure", "slide_index": None, "severity": "critical", "message": f"页数{actual}与要求{expected}偏差{deviation:.0%}>20%"})

    # Narrative
    all_issues.extend(check_narrative_arc(slides))

    # Content density
    all_issues.extend(check_content_density(slides))

    # Duplication
    all_issues.extend(check_cross_page_duplication(slides))

    # Contradiction
    all_issues.extend(check_cross_page_contradiction(slides))

    # Terminology
    all_issues.extend(check_terminology_consistency(slides))

    # Layout variety
    all_issues.extend(check_layout_variety(design_specs))

    # Dark/light rhythm
    all_issues.extend(check_dark_light_rhythm(design_specs))

    # Confidence annotation coverage (≥80% of data-containing body items)
    import re
    total_data_items = 0
    annotated_items = 0
    for s in slides:
        for b in (s.get("body") or []):
            b_str = str(b)
            if re.search(r"\d+", b_str):
                total_data_items += 1
                if "(高," in b_str or "(中," in b_str or "(低," in b_str:
                    annotated_items += 1
    if total_data_items > 0:
        coverage = annotated_items / total_data_items
        if coverage < 0.8:
            all_issues.append({"category": "content", "slide_index": None, "severity": "major", "message": f"置信度标注覆盖率{coverage:.0%}<80%({annotated_items}/{total_data_items})"})

    # Charts count
    chart_count = sum(1 for d in design_specs if d.get("chart_spec"))
    if chart_count > 3:
        all_issues.append({"category": "chart", "slide_index": None, "severity": "major", "message": f"图表数量({chart_count})超过上限(3)"})

    # Word count per slide (新增)
    all_issues.extend(check_word_count_per_slide(slides))

    return all_issues


def check_design_quality(design_concept: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate design concept quality: contrast + type scale."""
    issues: list[dict[str, Any]] = []
    issues.extend(check_contrast_ratio(design_concept))
    issues.extend(check_type_scale_consistency(design_concept))
    return issues

    return all_issues


def _longest_common_substring(a: str, b: str) -> str:
    """Return the longest common substring of a and b."""
    if not a or not b:
        return ""
    m, n = len(a), len(b)
    best = ""
    for i in range(m):
        for j in range(i + 10, min(m, i + 100) + 1):
            sub = a[i:j]
            if sub in b and len(sub) > len(best):
                best = sub
    return best


def resolve_structure(spec: dict[str, Any]) -> str:
    """Unified accessor for slide layout/structure field across all data formats.

    Handles these patterns:
      - design["design"]["structure"] (from PPTDesign agent)
      - design["layout"] (from legacy/deck_dict serialization)
      - spec["structure"] (from renderer format)
      - spec["design"]["structure"] (nested format)

    Also normalizes agent-output names to renderer-canonical names.

    Returns canonical structure name, defaulting to "title_top".
    """
    # Alias map: agent output → renderer canonical
    ALIASES: dict[str, str] = {
        "card_grid": "grid",
        "centered_statement": "centered",
        "comparison_split": "title_split",
        "accent_panel": "accent_panel",
        "fishbone": "fishbone",
        "timeline": "timeline",
        "kpi_cards": "kpi_cards",
        "comparison_table": "comparison_table",
        "process_flow": "process_flow",
        "quote_callout": "quote_callout",
        "swot": "swot",
        "funnel": "funnel",
        "matrix_2x2": "matrix_2x2",
        "agenda": "agenda",
        "closing_cta": "closing_cta",
    }

    raw: str | None = None

    # Direct structure field (renderer format)
    if "structure" in spec and isinstance(spec.get("structure"), str):
        raw = str(spec["structure"])

    # Nested in "design" dict
    if not raw:
        design = spec.get("design")
        if isinstance(design, dict):
            s = design.get("structure")
            if s and isinstance(s, str):
                raw = str(s)

    # Legacy "layout" field (deck_dict serialization)
    if not raw:
        layout = spec.get("layout")
        if layout and isinstance(layout, str) and layout != "dynamic":
            raw = str(layout)

    if not raw:
        return "title_top"

    return ALIASES.get(raw, raw)
