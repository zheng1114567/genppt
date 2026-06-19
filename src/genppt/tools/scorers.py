"""Scoring utilities for GenPPT quality evaluation."""

from __future__ import annotations

from typing import Any


def score_slide_density(slide: dict[str, Any]) -> dict[str, Any]:
    """Score a single slide on content density and quality (0-10 scale per dimension)."""
    headline = str(slide.get("headline", ""))
    body = slide.get("body") or []
    role = str(slide.get("role", slide.get("intent", ""))).lower()

    scores: dict[str, Any] = {}

    # Headline quality (30%): judgment vs label
    if len(headline) >= 15 and any(kw in headline for kw in ["需要", "应该", "必须", "关键", "问题", "机会", "风险", "增长", "下降", "不是", "而是"]):
        scores["headline_quality"] = {"score": 9, "reason": "标题是一个可争论的判断"}
    elif len(headline) >= 10:
        scores["headline_quality"] = {"score": 6, "reason": "标题可读但不够有力"}
    else:
        scores["headline_quality"] = {"score": 3, "reason": "标题过短或像标签"}

    # Body density (25%): exclude cover/closing/divider
    if role in {"cover", "closing", "divider"}:
        scores["body_density"] = {"score": 10, "reason": f"role={role}页正文密度合理"}
    elif len(body) >= 4:
        total_chars = sum(len(str(b)) for b in body)
        if total_chars >= 200:
            scores["body_density"] = {"score": 9, "reason": f"{len(body)}条正文，共{total_chars}字"}
        else:
            scores["body_density"] = {"score": 6, "reason": f"正文{len(body)}条但内容量不足({total_chars}字)"}
    elif len(body) >= 2:
        avg_len = sum(len(str(b)) for b in body) / len(body)
        if avg_len >= 40:
            scores["body_density"] = {"score": 7, "reason": f"正文{len(body)}条均长{avg_len:.0f}字"}
        else:
            scores["body_density"] = {"score": 5, "reason": f"正文{len(body)}条但条目偏短(均长{avg_len:.0f}字)"}
    else:
        scores["body_density"] = {"score": 2, "reason": "正文不足2条"}

    # Evidence (25%): confidence annotations + data quality
    body_text = " ".join(str(b) for b in body)
    import re
    has_numbers = bool(re.search(r"\d+", body_text))
    has_comparison = any(kw in body_text for kw in ["相比", "对比", "提升", "下降", "增加", "减少", "高于", "低于"])
    has_confidence = any(tag in body_text for tag in ["(高,", "(中,", "(低,"])
    if has_numbers and has_comparison and has_confidence:
        scores["evidence"] = {"score": 9, "reason": "包含数据、对比和置信度标注"}
    elif has_numbers and has_confidence:
        scores["evidence"] = {"score": 7, "reason": "包含数据和置信度标注但缺少对比参照"}
    elif has_numbers:
        scores["evidence"] = {"score": 5, "reason": "包含数据但缺少对比参照和置信度标注"}
    else:
        scores["evidence"] = {"score": 3, "reason": "缺少具体数据支撑"}

    # Narrative function (20%): checked by QualityReview across adjacent slides, per-slide baseline
    narrative_func = str(slide.get("narrative_function", slide.get("intent", "")))
    if narrative_func:
        scores["narrative"] = {"score": 7, "reason": f"叙事功能: {narrative_func}"}
    else:
        scores["narrative"] = {"score": 5, "reason": "缺少叙事功能标注"}

    # Overall (weighted)
    weights = {"headline_quality": 0.30, "body_density": 0.25, "evidence": 0.25, "narrative": 0.20}
    overall = sum(v.get("score", 5) * weights.get(k, 0.25) for k, v in scores.items())
    scores["overall"] = round(overall, 1)
    return scores


def aggregate_scores(slides: list[dict[str, Any]]) -> dict[str, Any]:
    """Score all slides and produce an aggregate report."""
    per_slide: dict[int, dict[str, Any]] = {}
    total = 0

    for s in slides:
        idx = int(s.get("index") or 0)
        scores = score_slide_density(s)
        per_slide[idx] = scores
        total += scores.get("overall", 0)

    avg = round(total / len(slides), 1) if slides else 0

    # Identify weak slides (< 6.0)
    weak = [idx for idx, s in per_slide.items() if s.get("overall", 0) < 6.0]

    return {
        "per_slide": per_slide,
        "average": avg,
        "weak_slides": weak,
        "passed": avg >= 7.0 and len(weak) <= len(slides) * 0.3,
        "summary": f"均分{avg}/10，{len(weak)}页低于6分" if weak else f"均分{avg}/10，全部通过",
    }
