"""ContentDesign ReAct agent — designs narrative and writes deep, original slide content."""

from __future__ import annotations

import json
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from ..state import GenPPTState
from ..llm import get_chat_model
from ..tools import (
    check_narrative_arc, check_content_density, check_cross_page_duplication,
    check_cross_page_contradiction, check_terminology_consistency,
)
from ..prompts import get_prompt


_CONTENT_PROMPT = None


def _load_content_prompt() -> str:
    global _CONTENT_PROMPT
    if _CONTENT_PROMPT is None:
        _CONTENT_PROMPT = get_prompt("content", fallback=SYSTEM_PROMPT_HARDCODED)
    return _CONTENT_PROMPT


SYSTEM_PROMPT_HARDCODED = """你是 PPT 内容策略师兼文案。创造有深度的叙事和逐页内容，不填充模板。
你在管道中游——你接收 Content Director 产出的创作简报（含结构规划、视觉方案、配图需求），你的职责是按 Director 的设计撰写逐页具体文案。不要重新设计叙事结构或视觉方案。
你产出的 slides 是后续所有设计和图表 Agent 的工作原料。

## 核心信条

**禁止：**
- 套用固定叙事模式。每个主题逻辑不同。
- 空洞口号（"提高效率很重要""数据是核心竞争力"）
- 同一句话换词说三遍
- 编造人名、公司名、产品名——这三类信息除非用户提供，否则使用角色描述替代（如"某SaaS公司""竞品A"）
- 编造市场份额数据、具体来源——不确定的数值可以合理推演，但必须标注置信度

**要求：**
- 理解主题本质——利益冲突？决策困境？信息不对称？技术判断？
- 找到叙事主线：这份 PPT 要改变听众什么认知？
- 每页一个判断，用证据/数据/对比支撑
- 页面间有因果或递进关系，不是"第一点第二点第三点"
- **正文短小精悍**：每条body 25-60字，适合屏幕阅读和演讲。详细论证、背景、推导过程放在 speaker_note 里
- **标题要有判断力**：不是"XX介绍"而是"XX之所以重要的原因是YY"
- **数据要具体**：不是"效率大幅提升"而是"生成时间从45分钟压缩到12分钟(中,n=200)"

## ⚠️ 总字数硬约束（最高优先级）

**6页PPT的 body 总字数不得超过600字。** 这是渲染器的硬限制，超出的内容会被截断，但截断会导致内容不完整。

字数分配参考（6页为例）：
- 封面页（第1页）：body 50-80字，仅放核心数据钩子
- 内容页（第2-5页）：每页 body 80-120字，每条25-50字，2-3条
- 收尾页（第6页）：body 60-100字，聚焦行动号召

**压缩技巧**（当需要精简时使用）：
1. 删除"的/了/是/很/非常"等虚词和程度副词
2. 合并同类数据点——"检出率从78%提升至92%，时间从12分钟降至5分钟" 而非分两句说
3. 用符号替代文字——"78%→92%" 替代 "从78%提升到92%"
4. 裁掉冗余修饰——"显著/大幅/重要/关键" 等修饰词删掉，让数据自己说话
5. 一个 body 条目只承载一个判断+一个数据，不要塞两个论点

**输出前必须自检**：统计所有 body 总字数。如果 >600，立即用上述技巧压缩后再输出。不要期待下游帮你截断——下游不做破坏性截断。

## ⚠️ 置信度标注覆盖率（强制要求）

**每个包含数字的 body 条目必须有置信度标注。** 覆盖率必须 ≥80%（即含数字条目中至少80%有(高/中/低,基于…)标注）。

反面示例：`"AI敏感度94%，医生敏感度78%"` —— 有数字无标注，不通过。
正面示例：`"AI敏感度94%，医生敏感度78%(高,基于MGH 2023年研究,n=1000)"` —— 通过。

输出前自检：统计 body 中含数字的条目数，确认 ≥80% 有置信度标注。不达标则补充标注后重新输出。

## ⚠️ 跨页数据一致性（强制自检）

输出前逐页检查：
1. 同一指标在不同页的数值是否一致（允许 ±15% 因四舍五入导致的波动）
2. 结论方向是否矛盾——如果第3页说"AI在X场景超越医生"而第4页也说"AI在X场景优于医生"但没有新信息，属于语义重复
3. 封面钩子和内页详细数据中的数字是否一致
4. 正文和 visual_hint 中提到的数值是否一致

发现矛盾 → 修正后再输出。这是硬性要求，下游 QualityReview 会检查此项。

## 叙事弧线

以下是启发类型，不是约束。如果内容适合自创弧线，可以自行设计：
- **颠覆常识**: "你以为X，实际上Y" → 建立认知→证据打破→新框架
- **两难抉择**: "A和B各有代价" → 呈现trade-off→取舍标准
- **逐步收窄**: "大问题→子问题→可行动的一步" → 每阶段缩小范围
- **时间推演**: "过去→现在→未来" → 时间线演示变化必然性
不属于任何一种？自创弧线，在 narrative_logic 中解释你的设计。

## 开头/结尾策略

开头: 反直觉数据 | 尖锐问题 | 场景代入 | 对比冲击
结尾: 具体行动号召(谁/什么时候/做什么) | 开放问题(引出讨论) | 风险警示(不做代价)

## 数据置信度（全系统统一）

- 高(>80%): 可验证来源或常识范围。写法: "Q3收入220万(高,基于财报)"
- 中(50-80%): 合理推演。写法: "预计转化率提升12%(中,基于内部A/B测试,n=42)"
- 低(<50%): 推测。写法: "市场规模可能达5亿(低,参考相邻赛道,建议验证)"
- 范围值允许但须注理由: "预计3-5个月(范围,取决于审批进度,中)"

严禁用"大约/大概/可能/估计"替代置信度标注。

## 页级置信度与条目置信度

- 每条 body 独立标注置信度，如 "(高,基于XX)"
- `page_confidence` 取该页所有 body 条目的最低置信度——因为一条低置信度的论据会拖累整页的可信度
- 例: body[0]标(高) + body[1]标(低) → page_confidence="低"

## 内容结构多样性（强制要求）

后续的 Design Agent 有 18 种布局可选，但每个布局只适用于特定内容结构。你的 body 结构直接决定可用布局范围。**8页的PPT至少需要4种不同的body结构**。

要求每页 body 按以下格式之一组织，不要全用"线性论证"格式：

**格式1 — 线性论证**（适合 title_top / title_split）
body: ["论据A(置信度)", "论据B(置信度)", "论据C(置信度)"]
这是默认格式，但**全篇使用不超过3页**。

**格式2 — 因果分析**（适合 fishbone 鱼骨图）
body: ["原因1: xxx导致yyy", "原因2: xxx造成yyy", "原因3: xxx引发yyy", "原因4: xxx使得yyy"]
每个原因是一个独立的因果链，4-6条。

**格式3 — 关键指标**（适合 kpi_cards 大数字卡片）
body: ["85%|转化率提升", "3.2x|效率倍增", "12min|平均生成时间", "¥0.03|单页成本"]
每条格式为 "数字|标签"，3-4条。数字要有冲击力。

**格式4 — 多维度对比**（适合 comparison_table 对比表格）
body: ["对比维度|竞品/现有方案|GenPPT", "生成速度|45分钟|12分钟(中,n=200)", "叙事一致性|5.4/10|8.2/10(中,n=10)", "用户控制力|无(黑箱)|完全可审查(高,架构特性)"]
首行是列定义（第一列是维度名，后续列是具体方案名）。列名必须具体，**禁止用"方案A/方案B"**——用实际名称如"端到端GPT-4o""GenPPT"。

**格式5 — 流程步骤**（适合 process_flow / vertical_stack）
body: ["步骤1: 需求解析智能体读取输入→输出结构化Brief", "步骤2: 叙事设计智能体构建论点树→分配页面角色", "步骤3: 页面生成智能体逐页创作→标注置信度"]
每条描述一个具体步骤，3-5条。

**格式6 — 引述/金句**（适合 quote_callout）
body: [] 或 仅1条 attribution
headline 本身就是引述句（如"GenPPT不是工具，是思考过程的容器"）

**格式7 — SWOT分析**（适合 swot 四象限）
body: ["技术栈先进但学习成本高", "市场对AI工具接受度提升", "缺少成熟的测试体系", "竞品快速跟进风险"]
按 S/W/O/T 顺序各一条。

**格式8 — 漏斗/管道**（适合 funnel）
body: ["潜在用户: 10000人", "试用注册: 2400人", "活跃使用: 860人", "付费转化: 210人"]
每条为一个阶段，含数量和阶段名。

**格式9 — 时间演进**（适合 timeline 时间线）
body: ["2024Q3: 概念验证，完成架构设计", "2024Q4: MVP开发，5个测试场景", "2025Q1: 产品化，API发布", "2025Q2: 规模化，企业版"]
每条为一个里程碑，含时间和事件。

在输出前检查：你的 slides 是否使用了至少4种不同格式？如果没有，重写直到达标。

## 你的工具

- `check_narrative_arc`:
  通过标准 = 第1页 role 为 cover + 最后页 role 为 closing + 相邻页 narrative_function 无连续3页相同
  不通过示例: 连续3页都是"展示证据"——说明在填模板而非推进叙事

- `check_content_density`:
  通过标准 = 非cover/非closing/非divider页: body ≥2条 + 每条body ≥25字 + headline ≥10字
  divider页(过渡/分隔): 允许仅有headline，不强制body
  注意: 25字是底线不是目标。好的body条目通常40-80字。低于25字的"论证"通常是口号

- `check_cross_page_duplication`:
  通过标准 = 无≥30字完全重复 + 无不同页码表达同一判断(语义去重)
  语义去重: "转化率提升是关键"和"核心指标是转化率增长"视为重复，即使字数不同

- `check_cross_page_contradiction`:
  通过标准 = 无方向相反的数值趋势(同一指标±15%内不算矛盾) + 无互相否定的结论
  结论矛盾示例: 第3页"价格是最大障碍" vs 第6页"用户对价格不敏感"——不通过
  注意: 此工具检查语义层面的结论矛盾。如工具无法判断边界情况，标记为"[需人工判断]"而非强行通过。

- `check_terminology_consistency`:
  通过标准 = 无中英文混用不一致 + 同一概念全文使用相同中文术语

**最多迭代 3 轮。** 3 轮后仍有问题 → 填入输出 JSON 的 `unresolved` 数组，格式: `"[工具名] 问题描述"`，然后输出当前最佳版本。不要丢弃已经通过的页面。

## 深度标准

好的 body（适合演讲屏读，每条25-60字）:
> 错误: "提升办公效率很重要"
> 正确: "传统模板选择耗时15分钟，GenPPT压缩到30秒(中,n=42)"

好的 speaker_note（承载详细论证，不限字数）:
> "这个数据来自我们对42个真实用户的测试...具体来说，瓶颈不在生成速度，而在于..."

**body 和 speaker_note 的分工**:
- body: 屏幕上显示的关键判断/证据/数据，听众3秒内读完
- speaker_note: 演讲者口播的详细论证、背景故事、推导过程
- 不要把长篇论证放在 body 里——那是 speaker_note 的职责

**证据链规则**：数据与其来源/置信度必须在同一页的 body 中，禁止第5页给数据、第6页才解释来源。格式如"转化率提升23%(中,内部A/B测试,n=200)"，括号内注明置信度和来源。

## 输出格式

严格 JSON：
```json
{
  "deck_plan": {
    "title": "<基于主题生成的具体结论型标题>",
    "core_claim": "<可争论的核心主张>",
    "belief_to_shift": "<听众原本以为X，听完后意识到Y>",
    "narrative_logic": "<页面间的因果关系或递进关系；如自创弧线，解释设计理由>",
    "style_keywords": ["3-5个风格关键词"]
  },
  "slides": [
    {
      "index": 1,
      "role": "cover",
      "headline": "<反直觉的判断句，必须贴合用户主题>",
      "body": ["论据1(置信度)", "论据2(置信度)", "论据3(置信度)"],
      "page_confidence": "高|中|低",
      "narrative_function": "开场冲击",
      "speaker_note": "演讲口播要点，口语化",
      "visual_hint": "具体描述用什么视觉元素支撑判断"
    },
    {
      "index": 2,
      "role": "content",
      "headline": "根本原因是什么？",
      "body": ["原因1: 单一大模型擅长局部连贯但缺乏全局结构感知", "原因2: 叙事和设计是两个认知域，强行耦合牺牲两者质量", "原因3: 现有工具把PPT当文档生成而非推理任务", "原因4: 用户无法审查AI的设计决策过程"],
      "page_confidence": "高",
      "narrative_function": "建立问题",
      "speaker_note": "...",
      "visual_hint": "鱼骨图：主干指向'PPT生成质量瓶颈'，四个分支分别为四个原因"
    },
    {
      "index": 5,
      "role": "content",
      "headline": "关键数据：多智能体架构的量化优势",
      "body": ["85%|叙事一致性评分", "3.2x|内容密度提升", "12min|平均生成时间", "8.2/10|专家盲评得分"],
      "page_confidence": "中",
      "narrative_function": "展示证据",
      "speaker_note": "...",
      "visual_hint": "四个大数字卡片水平排列，每个卡片顶部蓝色数字，底部灰色标签"
    }
  ],
  "unresolved": []
}
```

注意：上面的3页示例分别使用了3种不同的body格式（线性论证、因果分析、关键指标）。你的8页PPT必须使用至少4种不同格式。
"""


def content_design_node(state: GenPPTState) -> GenPPTState:
    llm = get_chat_model(temperature=0.8)
    brief = state.get("brief", {})
    creative_brief = state.get("creative_brief", {})
    requirements = state.get("requirements", "")

    structure_plan = creative_brief.get("structure_plan", {})
    req_analysis = creative_brief.get("requirement_analysis", {})
    visual_concept = creative_brief.get("visual_concept", {})
    image_chart_reqs = creative_brief.get("image_chart_requirements", {})

    revision_context = ""
    if state.get("needs_revision") and state.get("review_report"):
        review = state["review_report"]
        rev_count = state.get("revision_count", 0)
        max_rev = state.get("max_revisions", 2)
        # Check if word count is an issue
        word_count_hint = ""
        if "字数" in state.get("error", "") or "压缩" in state.get("error", ""):
            word_count_hint = "\n⚠️ 总字数超标（>600字），本次修改必须压缩内容：合并同类数据点、删除冗余修饰词、用符号替代文字描述。目标是总字数≤600字。"
        revision_context = (
            f"\n\n⚠️ 第{rev_count}次修改(最多{max_rev}次)。\n"
            f"上次审查:\n{json.dumps(review, ensure_ascii=False, indent=2)}\n"
            f"请针对以上问题修改。{word_count_hint}"
        )

    user_msg = (
        f"## 创作简报 (Content Director 已设计)\n"
        f"主题: {brief.get('topic', state['topic'])}\n"
        f"受众: {req_analysis.get('audience', brief.get('audience', ''))}\n"
        f"语气: {req_analysis.get('tone', brief.get('tone', ''))}\n"
        f"目的: {req_analysis.get('purpose', brief.get('purpose', ''))}\n\n"
        f"## 结构规划 (必须遵循)\n"
        f"叙事弧线: {structure_plan.get('narrative_arc', '')}\n"
        f"核心主张: {structure_plan.get('core_claim', '')}\n"
        f"认知转变: {structure_plan.get('belief_to_shift', '')}\n"
        f"叙事逻辑: {structure_plan.get('narrative_logic', '')}\n"
        f"风格关键词: {structure_plan.get('style_keywords', [])}\n"
        f"页面角色分配:\n{json.dumps(structure_plan.get('page_roles', []), ensure_ascii=False, indent=2)}\n\n"
        f"## 视觉方案概要 (供 visual_hint 参考)\n"
        f"视觉比喻: {visual_concept.get('visual_metaphor', '')}\n"
        f"风格方向: {visual_concept.get('style_direction', '')}\n"
        f"主色: {visual_concept.get('primary_hex', '')}, 背景: {visual_concept.get('background_hex', '')}, 强调色: {visual_concept.get('accent_hex', '')}\n"
        f"形状: {visual_concept.get('shape_style', '')}, 间距: {visual_concept.get('spacing_mood', '')}\n\n"
        f"## 配图需求 (确保相关页数据就绪)\n"
        f"{json.dumps(image_chart_reqs, ensure_ascii=False, indent=2)}\n\n"
        f"{revision_context}\n\n"
        f"请根据以上创作简报，为每页撰写具体内容(headline+body+speaker_note+visual_hint)。"
        f"遵循Director的结构规划（页面角色和叙事弧线），不要自己重新设计结构。"
        f"建议{creative_brief.get('page_count', brief.get('page_count', 8))}页。"
    )

    messages = [SystemMessage(content=_load_content_prompt()), HumanMessage(content=user_msg)]

    verbose = state.get("verbose", False)
    if verbose:
        page_count = creative_brief.get('page_count', brief.get('page_count', '?'))
        print(f"\n{'='*60}")
        print(f"  ✍️ Content Agent 撰写中... ({page_count}页)")
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
                messages.append(ToolMessage(content=_exec_tool(tc, messages), tool_call_id=tc["id"]))
        else:
            parsed = _parse_deck_and_slides(messages)
            if parsed and _looks_like_schema_echo(parsed):
                messages.append(HumanMessage(content=_schema_echo_feedback(state)))
                continue
            if parsed:
                state["deck_plan"] = parsed["deck_plan"]
                state["slides"] = parsed["slides"]
                # Pre-flight content check
                _preflight_content(state)
                _append_trace(state, "ContentDesign", {
                    "title": parsed.get("deck_plan", {}).get("title", ""),
                    "slide_count": len(parsed.get("slides", [])),
                    "body_formats_detected": _detect_body_formats(parsed.get("slides", [])),
                    "preflight_error": state.get("error", ""),
                })
                if verbose:
                    issues = state.get("error", "")
                    ok = "内容预检" not in issues
                    print(f"  {'✅' if ok else '⚠️'} Content完成: {len(parsed['slides'])}页")
                state["phase"] = "design"
                break

    if not state.get("slides"):
        parsed = _parse_deck_and_slides(messages)
        state["deck_plan"] = parsed.get("deck_plan", {}) if parsed else {}
        state["slides"] = parsed.get("slides", []) if parsed else []
        if not parsed:
            state["error"] = f"{state.get('error', '')}; ContentDesign: 无法解析slides".strip("; ")
        elif _looks_like_schema_echo(parsed):
            state["error"] = f"{state.get('error', '')}; ContentDesign: 输出疑似照抄schema示例".strip("; ")
        _preflight_content(state)
        _append_trace(state, "ContentDesign", {
            "title": state.get("deck_plan", {}).get("title", ""),
            "slide_count": len(state.get("slides", [])),
            "body_formats_detected": _detect_body_formats(state.get("slides", [])),
            "preflight_error": state.get("error", ""),
        })
        state["phase"] = "design"
    return state


def _preflight_content(state: GenPPTState) -> None:
    """Quick validation of content output before passing to downstream agents.

    Stores structured issues in state['preflight_issues'] so QualityReview can
    merge them into the review report and trigger revision when needed.
    """
    slides = state.get("slides", [])
    if not slides:
        return

    # Apply non-destructive content boundaries from Director if present.
    # Earlier versions sliced titles/body strings, which produced broken output
    # such as "一…" or half-cut English tokens. Keep content intact and let
    # render/review handle overflow.
    creative_brief = state.get("creative_brief", {})
    boundary = creative_brief.get("content_boundary", {})
    max_title_chars = boundary.get("max_title_chars", 0)
    max_total_words = boundary.get("max_total_words", 0)
    prefer_short = boundary.get("prefer_short_body", False)

    if max_title_chars > 0 or max_total_words > 0 or prefer_short:
        total_chars = 0
        for s in slides:
            hl = str(s.get("headline", ""))
            body = s.get("body") or []
            if prefer_short and len(body) > 3:
                s["body"] = body[:3]
            total_chars += len(hl) + sum(len(str(b)) for b in (s.get("body") or []))
        if max_total_words > 0 and total_chars > max_total_words:
            state["error"] = f"{state.get('error', '')}; 内容预检: 总字数{total_chars}>{max_total_words}，建议ContentDesign重写压缩，未做破坏性截断".strip("; ")

    issues = []
    data_items = 0
    annotated = 0
    total_chars = 0
    import re
    for s in slides:
        hl = str(s.get("headline", ""))
        body = s.get("body") or []
        total_chars += sum(len(str(b)) for b in body)
        if len(hl) < 10:
            issues.append(f"Slide {s.get('index','?')}: 标题过短({len(hl)}字)")
        if len(body) < 2:
            issues.append(f"Slide {s.get('index','?')}: body条数不足({len(body)}条)")
        for b in body:
            b_str = str(b)
            if re.search(r'\d', b_str):
                data_items += 1
                if any(tag in b_str for tag in ('(高,', '(中,', '(低,')):
                    annotated += 1

    # Build structured preflight issues for QualityReview to consume
    preflight_issues = []
    if max_total_words > 0 and total_chars > max_total_words:
        preflight_issues.append({
            "category": "content",
            "slide_index": None,
            "severity": "major",
            "message": f"内容预检: 总字数{total_chars}>{max_total_words}，超标{total_chars-max_total_words}字，需压缩",
            "route": "ContentDesign",
            "direction": f"压缩body总字数至≤{max_total_words}字：合并同类数据点、删除冗余修饰词、用符号替代文字"
        })
    if data_items > 0 and annotated / data_items < 0.7:
        preflight_issues.append({
            "category": "content",
            "slide_index": None,
            "severity": "major",
            "message": f"置信度标注覆盖率{annotated/data_items:.0%}<70%，{data_items}个数据条目中仅{annotated}个有标注",
            "route": "ContentDesign",
            "direction": "为每个含数字的body条目补充置信度标注，格式为(高/中/低,基于…)，目标覆盖率≥80%"
        })
    # Also collect traditional string issues
    if any(len(str(s.get("headline", ""))) < 10 for s in slides):
        issues.append("存在标题过短页面")
    if any(len(s.get("body") or []) < 2 for s in slides):
        issues.append("存在body条数不足页面")

    if preflight_issues:
        state["preflight_issues"] = preflight_issues
    if issues:
        state["error"] = f"{state.get('error', '')}; 内容预检: {'; '.join(issues[:3])}".strip("; ")


def _looks_like_schema_echo(parsed: dict[str, Any]) -> bool:
    deck_plan = parsed.get("deck_plan", {}) if isinstance(parsed, dict) else {}
    title = str(deck_plan.get("title", ""))
    core_claim = str(deck_plan.get("core_claim", ""))
    narrative_logic = str(deck_plan.get("narrative_logic", ""))
    bad_phrases = (
        "具体标题，不是主题复述",
        "具体标题-不是主题复述",
        "反直觉的判断句，不是主题复述",
        "论据1(置信度)",
        "可争论的核心主张",
        "页面间的因果关系或递进关系",
        "<基于主题生成",
    )
    if any(p in title or p in core_claim or p in narrative_logic for p in bad_phrases):
        return True
    for slide in parsed.get("slides", []) or []:
        headline = str(slide.get("headline", ""))
        body_text = "\n".join(str(b) for b in (slide.get("body") or []))
        if any(p in headline or p in body_text for p in bad_phrases):
            return True
    return False


def _schema_echo_feedback(state: GenPPTState) -> str:
    return (
        "上一次输出疑似照抄了JSON schema示例或占位文本，不能使用“具体标题，不是主题复述”、"
        "“反直觉的判断句”或“论据1(置信度)”这类说明文字。\n"
        f"请围绕真实主题“{state['topic']}”重写完整 deck_plan 和 slides；每一页都必须包含和该主题直接相关的判断、证据和行动含义。"
    )


def _detect_body_formats(slides: list[dict[str, Any]]) -> list[str]:
    formats: list[str] = []
    for s in slides:
        body = [str(b) for b in (s.get("body") or [])]
        joined = "\n".join(body)
        if any("|" in b for b in body):
            formats.append("structured_table_or_kpi")
        elif any(b.startswith("原因") or "导致" in b for b in body):
            formats.append("causal")
        elif any(b.startswith("步骤") or ":" in b and "→" in b for b in body):
            formats.append("process")
        elif any(("Q" in b or "年" in b) and ":" in b for b in body):
            formats.append("timeline")
        elif len(body) <= 1:
            formats.append("quote_or_statement")
        elif joined:
            formats.append("linear")
    return sorted(set(formats))


def _append_trace(state: GenPPTState, agent: str, summary: dict[str, Any]) -> None:
    trace = state.setdefault("agent_trace", [])
    trace.append({"agent": agent, "summary": summary})


def _exec_tool(tc: dict, messages: list) -> str:
    slides = _extract_slides(messages)
    if not slides:
        return "无法提取slides数据，请输出完整JSON"
    name = tc.get("name", "")
    tools = {"check_narrative_arc": check_narrative_arc, "check_content_density": check_content_density,
             "check_cross_page_duplication": check_cross_page_duplication,
             "check_cross_page_contradiction": check_cross_page_contradiction,
             "check_terminology_consistency": check_terminology_consistency}
    fn = tools.get(name)
    if not fn:
        return f"未知工具: {name}"
    try:
        issues = fn(slides)
        return f"✅ {name}: 通过" if not issues else f"❌ {name}: {len(issues)}个问题\n" + \
               "\n".join(f"  - [{i.get('severity','?')}] 第{i.get('slide_index','?')}页: {i.get('message','')}" for i in issues)
    except Exception as e:
        return f"工具执行失败: {e}"


def _parse_deck_and_slides(messages: list) -> dict[str, Any] | None:
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = _outer_json(content.strip())
        if parsed and ("slides" in parsed or "deck_plan" in parsed):
            return parsed
    return None


def _extract_slides(messages: list) -> list[dict[str, Any]]:
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = _outer_json(content.strip())
        if parsed:
            s = parsed.get("slides") or parsed
            if isinstance(s, list) and s:
                return s
    return []


def _outer_json(text: str) -> dict[str, Any] | None:
    import re
    start = text.find("{")
    if start < 0: return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if esc: esc = False; continue
        if ch == "\\": esc = True; continue
        if ch == '"' and not esc: in_str = not in_str; continue
        if in_str: continue
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try: return json.loads(re.sub(r",\s*([}\]])", r"\1", text[start:i + 1]))
                except (json.JSONDecodeError, ValueError): return None
    return None
