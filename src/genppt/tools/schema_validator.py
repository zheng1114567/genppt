"""JSON Schema validation and auto-correction for agent outputs.

Each agent produces structured JSON. This module validates outputs against
expected schemas and auto-corrects common LLM output errors (missing fields,
type mismatches, None values).
"""

from __future__ import annotations

from typing import Any


# ── Minimal schemas for each agent's critical output ──────────────────────────

CREATIVE_BRIEF_SCHEMA = {
    "required_top": ["topic", "page_count"],
    "required_nested": {
        "requirement_analysis": ["audience", "purpose", "tone"],
        "visual_concept": ["primary_hex", "background_hex", "accent_hex", "font_family", "base_size_pt", "max_title_size_pt"],
        "structure_plan": ["core_claim", "narrative_logic", "page_roles"],
    },
    "type_checks": {
        "page_count": int,
        "visual_concept.base_size_pt": (int, float),
        "visual_concept.max_title_size_pt": (int, float),
        "visual_concept.type_scale_ratio": (int, float),
    },
}

SLIDES_SCHEMA = {
    "required_top": ["slides"],
    "per_item": {
        "index": int,
        "headline": str,
        "body": list,
    },
    "min_items": 2,
}

DESIGN_SPECS_SCHEMA = {
    "required_top": ["designs"],
    "per_item": {
        "index": int,
        "structure": str,
    },
    "min_items": 2,
}


def validate_and_fix(data: dict[str, Any], schema: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate data against a simplified schema. Returns (fixed_data, error_messages).

    Does NOT modify valid data. Only fills in missing required fields with
    sensible defaults and logs what was fixed.
    """
    fixed = dict(data)
    errors: list[str] = []

    # Check top-level required fields
    for field in schema.get("required_top", []):
        if field not in fixed or fixed[field] is None:
            default = _default_for(field)
            fixed[field] = default
            errors.append(f"缺少必填字段 '{field}'，已填充默认值")

    # Check nested required fields
    for parent, children in schema.get("required_nested", {}).items():
        if parent not in fixed or fixed[parent] is None:
            fixed[parent] = {}
            errors.append(f"缺少嵌套对象 '{parent}'，已创建空对象")
        for child in children:
            if child not in fixed.get(parent, {}):
                default = _default_for(child)
                fixed[parent][child] = default
                errors.append(f"缺少嵌套字段 '{parent}.{child}'，已填充默认值")

    # Type checks
    for path, expected_type in schema.get("type_checks", {}).items():
        parts = path.split(".")
        val = fixed
        for p in parts[:-1]:
            val = val.get(p, {}) if isinstance(val, dict) else {}
        key = parts[-1]
        if key in val and val[key] is not None:
            if isinstance(expected_type, tuple):
                if not isinstance(val[key], expected_type):
                    try:
                        val[key] = float(val[key]) if float in expected_type else int(val[key])
                    except (ValueError, TypeError):
                        val[key] = _default_for(key)
                        errors.append(f"字段 '{path}' 类型错误，已修正")
            elif not isinstance(val[key], expected_type):
                try:
                    val[key] = expected_type(val[key])
                except (ValueError, TypeError):
                    val[key] = _default_for(key)
                    errors.append(f"字段 '{path}' 类型错误，已修正")

    # Per-item checks
    items_key = None
    for k in ("slides", "designs"):
        if k in fixed:
            items_key = k
            break
    if items_key and schema.get("per_item"):
        items = fixed.get(items_key, [])
        if not isinstance(items, list):
            fixed[items_key] = []
            errors.append(f"'{items_key}' 不是数组，已重置")
            items = []
        if len(items) < schema.get("min_items", 0):
            errors.append(f"'{items_key}' 条目不足({len(items)}<{schema['min_items']})")
        for item in items:
            for field, ftype in schema["per_item"].items():
                if field not in item or item[field] is None:
                    item[field] = _default_for(field)
                    errors.append(f"'{items_key}[].{field}' 缺失，已填充")

    return fixed, errors


def _default_for(field: str) -> Any:
    defaults = {
        "topic": "", "page_count": 8, "requirements": "",
        "audience": "通用受众", "purpose": "传递信息", "tone": "专业清晰",
        "primary_hex": "#111827", "background_hex": "#F8FAFC", "accent_hex": "#2563EB",
        "font_family": "Microsoft YaHei", "base_size_pt": 14, "max_title_size_pt": 44,
        "type_scale_ratio": 1.333,
        "core_claim": "", "narrative_logic": "", "page_roles": [],
        "index": 0, "headline": "", "body": [], "structure": "title_top",
    }
    return defaults.get(field, "")
