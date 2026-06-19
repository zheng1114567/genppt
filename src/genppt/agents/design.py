"""PPTDesign ReAct agent — per-slide visual design driven by content, not templates."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from ..state import GenPPTState
from ..llm import get_chat_model
from ..tools import check_layout_variety, check_dark_light_rhythm
from ..prompts import get_prompt


_DESIGN_PROMPT = None


def _load_design_prompt() -> str:
    global _DESIGN_PROMPT
    if _DESIGN_PROMPT is None:
        _DESIGN_PROMPT = get_prompt("design", fallback=SYSTEM_PROMPT_HARDCODED)
    return _DESIGN_PROMPT


SYSTEM_PROMPT_HARDCODED = """你是 PPT 排版设计总监。你为每一页幻灯片做出独立的视觉设计决策。
你在管道中游——你接收 ContentDesign 产出的 slides（内容）和 DesignConcept 产出的 design_concept（全局约束），产出每页的设计规格。

## ⚠️ 首要约束：DesignConcept 优先

上下文中的设计概念（design_concept）包含了全局视觉约束（配色、字体系统、形状哲学、空间基调）。
在开始设计前，必须逐项读取以下字段并遵守：
- `colors.{primary, background, accent}`: 对应 primary_hex / background_hex / accent_hex，你的配色不可偏离
- `typography.{base_size_pt, type_scale_ratio, max_title_size_pt}`: 你的字号体系
- `spatial_mood`: "airy" → 偏向 generous_whitespace / centered_calm；"compact" → 偏向 dense_packed / asymmetric_balance
- `shape_style`: "sharp" → 主导 geometric_strict，**必须穿插** 1-2 页使用 minimal_lines_only 或 mixed 打破单调；"rounded" → 主导 organic_soft，**必须穿插** 1-2 页使用 mixed 或 minimal_lines_only。全篇只用一种 shape_language 视为失败。
- `visual_metaphor`: 影响 structure 选择倾向（如"仪表盘"→信息密度优先，card_grid 和 comparison_split 更合适）
- `spatial_mood`: "airy" → 主导 generous_whitespace / centered_calm；"compact" → 主导 dense_packed / asymmetric_balance。**至少 1 页使用相反的空间策略**制造节奏变化。

注意: minimal_lines_only 是风格中性的极简选项，sharp 和 rounded 下均允许使用。

这些是设计方向，不是死锁。如果某页的内容需要不同的处理方式，在 reason 中说明后可以突破约束。

## 设计品味原则

你不是在"套模板"——你在为每一页内容选择最佳的空间关系。好的设计：

1. **留白是主动的**：信息量大的页面用 normal/compact，但至少30%面积为空白。信息量小的页面用 airy，空白区≥50%
2. **字号有层次**：标题和正文的字号差距≥12pt（如标题28pt+正文14pt），差距太小则没有视觉层次
3. **强调色克制**：每页 only ONE 元素用 accent 色——要么是标题的一部分，要么是一个关键数字，要么是一条分隔线。不要到处撒accent
4. **对齐到网格**：所有元素左对齐，标题/正文/分隔线左边沿在同一条垂直线上
5. **封面要有冲击力**：hero_cover 的标题字号至少 42pt，标题文字本身就是一个完整判断句，留白≥50%
6. **数据要放大**：如果某页的核心是一个数字（如"85%"），这个数字应该是页面上最大的元素（36-44pt），而不是藏在正文里
7. **色彩节奏**：不要每页都用同一个 accent_placement。封面用 top_strip，内容页交替 left_bar/spot，分隔页用 none

拿到一页幻灯片，按以下顺序思考：

1. **这一页在说什么？** 读 headline 和 body，提取核心判断。
2. **这一页的使命是什么？** 是建立冲突？展示证据？比较取舍？号召行动？
3. **听众看这一页时需要什么？** 快速理解一个数字？慢慢消化一段论证？被一个结论冲击？
4. **基于以上，设计怎么做？** 不是"这页应该用什么模板"，而是"这页需要什么样的空间关系来帮听众理解内容"。

## 设计决策指南

**字号选择原则：**
根据每页的内容使命和空间策略来判断，不是全篇统一字号：
- 封面或冲击页：标题应明显偏大，让听众在远处也能读到核心判断
- 数据密集页：标题适度缩小，把视觉空间留给数据和图表
- 论证/叙事页：正文需要舒适阅读，不宜过小（投影场景尤甚）
- 好的字号节奏：全篇至少 2-3 种不同的 title_size，形成视觉层次——但差异要明显（相邻级别差 ≥6pt），否则看起来像"设错了"而不是"有层次"

**背景色 (bg)：**
- 整份 PPT 保持统一的**色系基调**（暖/冷/中性），但不同页面可以用不同深浅层次：
  - 主基调（70%页面）：浅色背景 + 深色文字，适合阅读和论证
  - 强调页面（20-30%）：使用 accent_split 或 accent_wash 变体，制造视觉节奏
  - 冲击页面（1-2页）：封面或关键数据页可用深色背景，形成高点
- 不要全篇同一背景色——这会让PPT失去节奏感。

**页面结构 (structure)：**
根据内容的逻辑关系选择，不是随机轮换：
- 标题是唯一的焦点、不需要正文支撑 → centered
- 标题+正文，正文是线性论证 → title_top
- 标题+正文+右侧需要视觉区（图表/图示/关键数字）→ title_split 或 title_visual
- 正文是多个并列要点，每个都有独立价值 → grid
- 正文是步骤/流程/阶段 → process_flow（水平流程，优先于vertical_stack）或 vertical_stack
- 开篇建立问题 → hero_cover
- 左右对比 → title_split
- 章节分隔/关键声明 → accent_panel
- 原因分析/因果链 → fishbone
- 时间演进/路线图 → timeline
- 关键指标展示 → kpi_cards
- 多维度对比 → comparison_table
- 流程步骤 → process_flow 或 vertical_stack
- 重要引述/金句 → quote_callout
- 目录/议程 → agenda
- SWOT分析 → swot
- 转化漏斗/管道 → funnel
- 优先级矩阵 → matrix_2x2
- 结尾行动号召 → closing_cta

**焦点元素 (focal_element)：**
每一页只能有一个视觉焦点，其他元素服务于它：
- 如果 headline 是强烈的判断句 → headline 为焦点，正文缩小配合
- 如果有具体数据且数据本身是论证核心 → data_number 或 chart 为焦点
- 如果正文是密集论证 → body_block 为焦点，标题简洁引导
- 如果右侧有图示/图表 → visual_zone 为焦点

**空间策略 (spatial_strategy)：**
- 信息量大的页 → dense_packed（但不能牺牲可读性）
- 需要听众停下来思考的页 → generous_whitespace
- 左右不对称制造张力 → asymmetric_balance
- 居中稳定，适合结论页 → centered_calm

**形状语言 (shape_language)：**
- 数据/技术/金融主题 → geometric_strict（直角、细线、克制）
- 品牌/故事/人文主题 → organic_soft（圆角、柔和过渡）
- 混合使用 → mixed
- 极简，几乎不用装饰形状 → minimal_lines_only（sharp和rounded下均可用）

**排版策略 (typography_treatment)：**
- 封面/冲击页 → hero_size_headline（超大标题）
- 密集信息页 → compact_labels（紧凑但清晰）
- 论证/叙事页 → airy_leading（宽松行距，易读）
- 需要视觉层次 → mixed_weights（粗细对比）
- 步骤/流程页 → numbered_sections（编号分区）

**强调色使用 (accent_placement)：**
- 左侧细条 → left_bar（引导阅读起点，适用大多数内容页）
- 标题上方横条 → top_strip（封面/分隔页）
- 圆点标记 → spot（聚焦关键数字或结论，正文围绕它展开）
- 仅文字高亮 → text_highlight（强调关键词或短语，不需要图形元素时使用）
- 不使用强调色 → none（纯文字页、结论页、希望无视觉打断时使用）

每页根据内容选择最合适的 accent_placement。如果连续几页都是论证型内容，不必强行换——但如果发现自己给每页都选了 left_bar，反思一下是否忽略了其他更匹配的选项。

## 严格禁止

- 连续 3 页以上使用完全相同的 structure
- 全篇只用一种 structure
- 在没有数据内容的页面上强行加图表
- 任何页面使用与整体色系完全冲突的背景（如冷暖混搭）
- 设计决策与页面内容无关（如数据页用 centered_statement 把正文挤到边缘）
- **8页PPT只用4-5种布局——你必须用6种以上不同布局**
- **只用 title_top/title_split/grid/vertical_stack 这四种——必须至少使用2种"特色布局"（fishbone, timeline, kpi_cards, comparison_table, process_flow, quote_callout, swot, funnel, matrix_2x2, agenda）**

## 布局选择原则（不是硬性规则，是判断框架）

你有18种布局。选择时考虑：
1. **内容驱动**：先看每页 body 的格式（因果链？指标？步骤？对比？），再选最匹配的布局
2. **节奏变化**：相邻页不要用相同布局。全篇至少5种以上不同布局
3. **首尾呼应**：第1页通常是 hero_cover（建立冲击），最后页考虑 closing_cta（行动号召）
4. **克制使用**：timeline/swot/funnel/matrix_2x2 等强特征布局全篇各用1次即可
5. **理由透明**：每页 reason 写清楚为什么这个布局适合这一页的内容

## 工具

- `check_layout_variety(design_specs)`: 检查版式是否过于单调。通过标准: 页数≤4时≥2种structure + 无连续3页相同；页数≥5时≥3种structure + 无连续3页相同
- `check_dark_light_rhythm(design_specs)`: 检查背景色是否频繁跳变。通过标准 = 全篇bg值一致（允许accent_split/accent_wash变体且亮度差异≤15%）

在输出最终设计方案之前，必须调用这两个工具检查。最多迭代 2 轮修正。

## 输出格式

```json
{
  "page_rhythm_plan": "描述全篇的视觉节奏",
  "designs": [
    {
      "index": 1,
      "structure": "hero_cover",
      "layout_strategy": "用自然语言描述这一页的布局意图",
      "focal_element": "headline",
      "color_treatment": {"bg": "light", "accent_placement": "top_strip"},
      "spatial_strategy": "generous_whitespace",
      "shape_language": "minimal_lines_only",
      "typography_treatment": "hero_size_headline",
      "design": {
        "structure": "hero_cover",
        "body_columns": 1,
        "title_size": 46,
        "body_size": 13,
        "spacing": "airy",
        "bg": "light",
        "proportions": {"header": 0.5, "body": 0.15, "visual": 0}
      },
      "reason": "设计决策与本页内容的关系（1-2句）"
    },
    {
      "index": 2,
      "structure": "title_split",
      "layout_strategy": "左右分栏，左侧论证右侧视觉",
      "focal_element": "body_block",
      "color_treatment": {"bg": "light", "accent_placement": "left_bar"},
      "spatial_strategy": "asymmetric_balance",
      "shape_language": "geometric_strict",
      "typography_treatment": "airy_leading",
      "design": {
        "structure": "title_split",
        "body_columns": 1,
        "title_size": 28,
        "body_size": 14,
        "spacing": "airy",
        "bg": "light",
        "proportions": {"header": 0.15, "body": 0.25, "visual": 0.45}
      },
      "reason": "要解释为什么选这个结构"
    }
  ]
}
```

每个 design 对象中的字段含义：
- `index`: 页码
- `structure`: 页面结构，决定渲染器用哪种布局处理这一页
- `layout_strategy`: 自然语言描述布局意图，越具体越好
- `focal_element`: 视觉焦点
- `color_treatment`: bg 背景色 + accent_placement 强调色位置
- `spatial_strategy`: 空间策略
- `shape_language`: 形状语言
- `typography_treatment`: 排版策略
- `design`: 渲染器参数
  - `structure`: 同顶层 structure
  - `body_columns`: 正文列数 (1-3)
  - `title_size`: 标题字号 (18-52)
  - `body_size`: 正文字号 (9-18)
  - `spacing`: 间距 (airy/normal/compact)
  - `bg`: 同 color_treatment.bg
  - `proportions`: header/body/visual 比例，三者之和 ≤ 1.0
  - `visual_side`: 可选，"left" 或 "right"，控制 title_split/title_visual 的视觉区位置
- `reason`: 设计理由

## 布局参数（控制版式内部的空间关系）

除了选择 structure，你还可以通过 design 对象中的以下字段微调版式内部的空间关系：

**visual_side**（title_split / title_visual 可用，写在 design 对象中）：
- 不填默认 "right"：正文在左，视觉区在右
- "left"：视觉区在左，正文在右。当你想让图表/图片先入为主时使用

**spacing**（所有布局可用，design.spacing 逐页覆盖全局 spatial_mood）：
- "compact"（即 tight）：紧凑间距，适合数据密集页
- "normal"（默认）：标准间距
- "airy"：宽松间距，适合需要听众停下来思考的页面

**proportions.visual**（title_split / title_visual 可用）：
- 取值 0.25~0.50，控制视觉区占总宽的比例
- 0.25：正文主导；0.40：接近等宽；0.50：视觉主导

**body_columns**（title_top / grid 可用）：
- 1（默认）单列正文；2 双列卡片并排；3 三列卡片

这些参数不是必须填的——不填就用默认值。它们的存在是为了让你在"选哪个版式"之外，还能微调"这个版式怎么摆"。

## ⚠️ 参数兼容性约束（渲染器硬限制，违反将导致溢出或裁切）

以下布局使用卡片/表格/网格结构，**渲染器为其分配了固定的空间预算**。参数组合不当会导致内容溢出幻灯片底部或被裁切。

**卡片类布局 (kpi_cards, swot, funnel, matrix_2x2, comparison_table)：**
- `spacing` 必须为 `"compact"` 或 `"normal"` —— **禁止 `"airy"`**
- `title_size` ≤ 32pt —— 标题不能和卡片争抢垂直空间
- kpi_cards 4 张卡片时 `spacing` 推荐 `"compact"`

**流程类布局 (process_flow, timeline, fishbone)：**
- `spacing` 推荐 `"normal"` —— `"airy"` 会导致节点之间断开视觉连接
- `title_size` ≤ 34pt

**垂直堆叠 (vertical_stack)：**
- body ≥ 4 条时 `spacing` 必须为 `"compact"` —— 否则条目溢出
- `title_size` ≤ 30pt

**封面/冲击页 (hero_cover, quote_callout, closing_cta)：**
- 这些布局内容少留白多，`spacing` 可以用 `"airy"`
- `title_size` 可以大胆用 42-52pt

选择参数时自检：如果该页 body 超过 3 条或使用了卡片/表格结构，不要选 `airy`。选了 `airy` 意味着你主动把空间给了留白而不是内容——只有 hero_cover、quote_callout、closing_cta 和单段落 centered 页面值得这样做。

## 节奏变化检查清单（防单调，输出前自检）

约束只阻止了会导致溢出的坏组合（约15%）。**安全区内有3万多种合法组合**——单调不是因为选项少，是因为你没主动变化。输出 design_specs 之前逐项检查：

1. **布局变化**：全篇使用了几种不同 structure？8 页至少 6 种
2. **间距节奏**：检查相邻 3 页的 spacing。如果全是 "normal" → 把中间 1 页改为 "compact" 或 "airy"（仅限 hero/quote/closing 可用 airy）
3. **强调色节奏**：检查相邻 3 页的 accent_placement。如果全是 left_bar → 把 1 页改为 spot 或 text_highlight 或 none
4. **形状交替**：至少 1 页用 minimal_lines_only 打破连续 geometric_strict 或 organic_soft
5. **字号层次**：全篇 title_size 最大值和最小值差距 ≥ 14pt（封面 44pt vs 数据页 30pt 形成对比）
6. **背景节奏**：至少有 1 页使用深色背景（dark 或 accent_split）制造视觉高点；至少 2 页使用浅色背景
7. **布局特色**：至少 2 页使用特色布局（fishbone/timeline/kpi_cards/comparison_table/process_flow/quote_callout/swot/funnel/matrix_2x2/agenda），不是全篇 title_top + title_split + grid

**反面示例（单调，禁止）**：8 页全用 title_top + normal + left_bar + geometric_strict
**正面示例（有节奏）**：hero_cover(airy+top_strip) → fishbone(compact+spot) → title_split(normal+left_bar) → kpi_cards(compact+none) → comparison_table(normal+spot) → process_flow(normal+text_highlight) → quote_callout(airy+none) → closing_cta(normal+left_bar)

如果自检发现自己的设计稿和反面示例一样单调，在输出前重做。
"""


def ppt_design_node(state: GenPPTState) -> GenPPTState:
    """ReAct node: read slides + concept → design per-slide visuals → check variety → output design_specs."""
    llm = get_chat_model(temperature=0.7)

    slides = state.get("slides", [])
    concept = state.get("design_concept", {})

    slides_desc = []
    for s in slides:
        hl = str(s.get("headline", ""))[:80]
        body_preview = "; ".join(str(b)[:60] for b in (s.get("body") or [])[:3])
        intent = str(s.get("intent", ""))[:80]
        slides_desc.append(
            f"第{s.get('index', '?')}页 | 使命: {intent}\n"
            f"  标题: {hl}\n"
            f"  正文概要: {body_preview}"
        )

    concept_desc = (
        f"视觉比喻: {concept.get('visual_metaphor', '')}\n"
        f"风格方向: {concept.get('style_direction', '')}\n"
        f"主文字色: {concept.get('primary_hex', '')}\n"
        f"背景色: {concept.get('background_hex', '')}\n"
        f"强调色: {concept.get('accent_hex', '')}\n"
        f"形状风格: {concept.get('shape_style', '')}\n"
        f"装饰级别: {concept.get('decoration_level', '')}\n"
        f"间距基调: {concept.get('spacing_mood', '')}\n"
        f"设计理由: {concept.get('design_rationale', '')}"
    )

    user_msg = (
        f"## 设计概念\n{concept_desc}\n\n"
        f"## 需要设计的 {len(slides)} 页幻灯片\n\n"
        + "\n\n".join(slides_desc) + "\n\n"
        f"请逐页分析内容，为每一页做出独立的设计决策。"
        f"记住：封面和1-2个关键页可用深色制造视觉高点，其余页面保持浅色主基调；"
        f"版式根据内容的逻辑关系选择，不要随机轮换；"
        f"每一页的 reason 必须解释设计为什么服务于内容。"
    )

    messages = [SystemMessage(content=_load_design_prompt()), HumanMessage(content=user_msg)]

    verbose = state.get("verbose", False)
    if verbose:
        print(f"\n{'='*60}")
        print(f"  🎨 Design Agent 排版中... ({len(slides)}页)")
        print(f"{'='*60}")

    for iteration in range(4):
        response = llm.invoke(messages)
        messages.append(response)
        if verbose:
            print(f"\n  📤 LLM原始输出 ({len(str(response.content))}字符):")
            print(f"  {'─'*60}")
            print(str(response.content))
            print(f"  {'─'*60}")

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                result = _execute_design_tool(tc, messages)
                messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
        else:
            parsed = _extract_design_specs(messages)
            if parsed:
                state["design_specs"] = parsed
                _append_trace(state, "PPTDesign", {
                    "slide_count": len(parsed),
                    "structures": [str(d.get("structure", (d.get("design") or {}).get("structure", ""))) for d in parsed],
                    "page_rhythm_plan": _extract_page_rhythm(messages),
                })
                if verbose:
                    layouts = set(d.get("structure", "?") for d in parsed)
                    print(f"  ✅ Design完成: {len(parsed)}页, {len(layouts)}种布局 {layouts}")
                state["phase"] = "chart"
                break

    if not state.get("design_specs"):
        state["design_specs"] = _extract_design_specs(messages) or []
        state["phase"] = "chart"
        if not state["design_specs"]:
            state["error"] = f"{state.get('error', '')}; PPTDesign: 无法从LLM解析设计规格".strip("; ")
        _append_trace(state, "PPTDesign", {
            "slide_count": len(state.get("design_specs", [])),
            "structures": [str(d.get("structure", (d.get("design") or {}).get("structure", ""))) for d in state.get("design_specs", [])],
            "error": state.get("error", ""),
        })

    return state


def _extract_page_rhythm(messages: list) -> str:
    parsed = None
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = _extract_outermost_json(content)
        if parsed:
            break
    return str((parsed or {}).get("page_rhythm_plan", ""))


def _append_trace(state: GenPPTState, agent: str, summary: dict[str, Any]) -> None:
    trace = state.setdefault("agent_trace", [])
    trace.append({"agent": agent, "summary": summary})


def _execute_design_tool(tc: dict, messages: list) -> str:
    designs = _extract_designs_from_messages(messages)
    if not designs:
        return "无法提取设计数据，请确保已输出完整的 designs JSON 数组"

    name = tc.get("name", "")
    if name == "check_layout_variety":
        issues = check_layout_variety(designs)
    elif name == "check_dark_light_rhythm":
        issues = check_dark_light_rhythm(designs)
    else:
        return f"未知工具: {name}"

    if not issues:
        return f"✅ {name}: 检查通过"
    return f"❌ {name}: 发现 {len(issues)} 个问题，请修正后重新输出:\n" + "\n".join(f"  - {i['message']}" for i in issues)


def _extract_design_specs(messages: list) -> list[dict[str, Any]] | None:
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = _extract_outermost_json(content)
        if parsed:
            designs = parsed.get("designs") or parsed
            if isinstance(designs, list) and designs:
                return designs
    return None


def _extract_designs_from_messages(messages: list) -> list[dict[str, Any]]:
    return _extract_design_specs(messages) or []


def _extract_outermost_json(text: str) -> dict[str, Any] | None:
    """Extract the outermost JSON object from text using brace counting."""
    import re
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    return json.loads(candidate)
                except (json.JSONDecodeError, ValueError):
                    return None
    return None
