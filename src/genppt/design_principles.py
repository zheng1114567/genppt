"""Codified design principles for PPTX slide generation.

Adapted from the power-design skill's 20 design principles, re-expressed as
actionable rules and constraints for the PPTX rendering pipeline.

Each principle is a dataclass with:
- name: short identifier
- rule: human-readable rule text
- check: what to validate
- apply: how to apply it during design
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class DesignPrinciple:
    name: str
    category: str
    rule_short: str
    rule_detail: str
    apply_guidance: str


# ── The 20 principles, adapted for PPTX generation ────────────────────────────

PRINCIPLES: list[DesignPrinciple] = [
    DesignPrinciple(
        name="one_idea_per_slide",
        category="cognitive",
        rule_short="一页一个判断",
        rule_detail="每页最多一个标题(≤15字)和一个正文区块。如果需要两个标题，就拆成两页。",
        apply_guidance="检查每页body条目是否都服务于同一个标题判断；如果不是，拆页。",
    ),
    DesignPrinciple(
        name="glanceable_3s",
        category="cognitive",
        rule_short="3秒可扫读",
        rule_detail="观众必须在≤3秒内提取页面的核心信息。如果做不到，简化或拆页。",
        apply_guidance="封面≤10词，内容页≤75词，标题要能用一句话说清判断。",
    ),
    DesignPrinciple(
        name="max_5_chunks",
        category="cognitive",
        rule_short="每页最多5个视觉块",
        rule_detail="每页最多7±2个独立视觉元素，理想3-5个。用卡片/分组将元素组织成≤5个块。",
        apply_guidance="正文条目>5时用2列布局分组；图标+文字合并为一个块。",
    ),
    DesignPrinciple(
        name="whitespace_ratio",
        category="spatial",
        rule_short="留白≥40%",
        rule_detail="内容页留白≥40%，封面/转场页≥60%。留白是主动的设计元素，不是空白。",
        apply_guidance="airy间距时margin_multiplier ≥ 1.3；正文区域不超过slide高度的50%。",
    ),
    DesignPrinciple(
        name="safe_zone_5pct",
        category="spatial",
        rule_short="5%安全区",
        rule_detail="所有文字和关键元素离slide边缘至少5%(1920×1080下≥96px)。",
        apply_guidance="默认MARGIN=0.6英寸(约5%)，任何情况下不小于0.4英寸。",
    ),
    DesignPrinciple(
        name="modular_type_scale",
        category="typography",
        rule_short="模块化字号比例",
        rule_detail="所有字号从一个比例尺推导：1.25/1.333/1.414/1.5/1.618，禁止随意字号。",
        apply_guidance="用type_scale_ratio生成所有字号: base_size × ratio^n，取整到最近的整数。",
    ),
    DesignPrinciple(
        name="max_4_sizes_per_slide",
        category="typography",
        rule_short="每页≤4种字号",
        rule_detail="每页最多4种不同字号，整套≤6种。标题、副标题、正文、注释——够了。",
        apply_guidance="全局维护一个sizes[]数组，长度≤6，拒绝不在数组内的字号。",
    ),
    DesignPrinciple(
        name="body_min_24px",
        category="typography",
        rule_short="正文≥12pt(≈16px屏幕)",
        rule_detail="投影场景正文≥18pt，屏幕场景≥12pt。标题≥24pt。注释≥9pt。",
        apply_guidance="base_size_pt范围[10,16]，title_size范围[22,48]。",
    ),
    DesignPrinciple(
        name="line_height_range",
        category="typography",
        rule_short="行高1.2-1.6",
        rule_detail="正文行高1.3-1.6，标题行高1.05-1.2。大字紧，小字松。",
        apply_guidance="body文本使用paraSpaceAfter来模拟行间距效果。",
    ),
    DesignPrinciple(
        name="contrast_AAA_target",
        category="color",
        rule_short="对比度目标AAA(7:1)",
        rule_detail="正文对比度≥4.5:1(AA)，目标7:1(AAA)。投影仪会洗掉30-50%对比度。",
        apply_guidance="深色文字(#111827)配浅色背景(#F8FAFC)对比度≈17:1，安全。中灰色文字(#6B7280)只在≥14pt时使用。",
    ),
    DesignPrinciple(
        name="color_60_30_10",
        category="color",
        rule_short="60-30-10色彩分配",
        rule_detail="60%主色(背景)，30%辅色(文字+面板)，10%强调色(唯一焦点)。强调色不要超过slide面积的15%。",
        apply_guidance="accent色只用于关键视觉元素: 数字、图表高亮、关键分隔线。",
    ),
    DesignPrinciple(
        name="single_accent",
        category="color",
        rule_short="每页一个强调色时刻",
        rule_detail="每页最多一个accent色元素。多个accent = 没有accent。整套PPT一个accent色。",
        apply_guidance="图表中accent色只用于最重要的数据系列，其余用灰色。",
    ),
    DesignPrinciple(
        name="never_hue_alone",
        category="color",
        rule_short="颜色+形状双重编码",
        rule_detail="永远不要只用颜色编码信息。配形状、标签、图标或粗细。约8%男性色盲。",
        apply_guidance="图表中不同系列使用不同的填充图案或标签，不能只靠颜色区分。",
    ),
    DesignPrinciple(
        name="spacing_8pt_grid",
        category="spatial",
        rule_short="8pt间距网格",
        rule_detail="所有间距取值∈{4,8,12,16,24,32,48,64,96,128}，以8为基数。禁止13、27等随意值。",
        apply_guidance="所有x,y,w,h参数对齐到0.05英寸(≈1.3pt)即可，关键在于相对间距关系。",
    ),
    DesignPrinciple(
        name="proximity_rule",
        category="spatial",
        rule_short="相近则相亲",
        rule_detail="相关元素间距≤16px，不相关元素间距≥48px。组间距是组内距的≥2倍。",
        apply_guidance="正文条目间距4-6pt；正文区与其他区之间至少间隔0.3英寸。",
    ),
    DesignPrinciple(
        name="data_ink_80pct",
        category="chart",
        rule_short="数据墨水比≥80%",
        rule_detail="图表中≥80%的像素应该编码数据。禁止3D、阴影、渐变填充、装饰网格线。",
        apply_guidance="图表只用2D平面类型，网格线≤4条水平线且50%透明度，直接标注数据点而非图例。",
    ),
    DesignPrinciple(
        name="chart_title_conclusion",
        category="chart",
        rule_short="图表标题=结论",
        rule_detail="图表标题写结论而非主题。'Q3收入增长22%'而不是'Q3收入'。",
        apply_guidance="chart_spec.title必须包含动词或对比。",
    ),
    DesignPrinciple(
        name="fp_pattern",
        category="layout",
        rule_short="F型/Z型阅读路径",
        rule_detail="标题和关键视觉放在左上到右上的200px首要关注区。文字页用F型，图文页用Z型。",
        apply_guidance="headline固定在slide上部15-25%区域。关键数据放在左侧或中央。",
    ),
    DesignPrinciple(
        name="one_mode_per_deck",
        category="structure",
        rule_short="整份PPT统一模式",
        rule_detail="演讲模式(≤15词/页，图像主导)和文档模式(密集，层次化)，二选一，不混用。",
        apply_guidance="由spacing_mood间接控制: airy=演讲模式，compact=文档模式。",
    ),
    DesignPrinciple(
        name="contrast_first",
        category="layout",
        rule_short="对比优于和谐",
        rule_detail="如果两个元素不同，就让它们非常不同。大小差≥1.5倍，粗细差≥200单位，颜色差≥3:1对比度。",
        apply_guidance="标题字号≥正文×2；bold标题配regular正文；accent色绝不用于正文。",
    ),
]


def get_principle(name: str) -> DesignPrinciple | None:
    for p in PRINCIPLES:
        if p.name == name:
            return p
    return None


def principles_by_category() -> dict[str, list[DesignPrinciple]]:
    result: dict[str, list[DesignPrinciple]] = {}
    for p in PRINCIPLES:
        result.setdefault(p.category, []).append(p)
    return result


def design_cheat_sheet() -> str:
    """Generate a condensed design principles reference for LLM prompts."""
    lines = ["# 设计原则速查表", ""]
    for p in PRINCIPLES:
        lines.append(f"- **{p.name}** ({p.category}): {p.rule_short}")
    return "\n".join(lines)


def principles_checklist() -> list[dict[str, str]]:
    """Return a checklist for pre-render validation."""
    return [
        {"name": p.name, "check": p.rule_short}
        for p in PRINCIPLES
    ]
