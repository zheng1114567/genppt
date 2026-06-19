"""QualityReview ReAct agent — comprehensive review with rule checks + LLM deep analysis."""

from __future__ import annotations

import json
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from ..state import GenPPTState
from ..llm import get_chat_model
from ..tools import rule_check, aggregate_scores, resolve_structure
from ..prompts import get_prompt


_REVIEW_PROMPT = None


def _load_review_prompt() -> str:
    global _REVIEW_PROMPT
    if _REVIEW_PROMPT is None:
        _REVIEW_PROMPT = get_prompt("review", fallback=SYSTEM_PROMPT_HARDCODED)
    return _REVIEW_PROMPT


SYSTEM_PROMPT_HARDCODED = """你是 PPT 质量审查专家。深度审查整套演示文稿。
你在管道末端——你看到的是所有上游 Agent 合并后的完整 deck_info。你的判断决定这套 PPT 是通过还是返工。

## 审查维度

1. **叙事连贯性**: 页面间有因果/递进关系吗？还是列表式堆砌？
2. **内容深度**: 每页是真正的判断还是空洞口号？数据有置信度标注吗？
3. **内容密度**: body 总字数是否在预算内（6页≤600字，8页≤800字）？单页 body 是否过密或过疏？
4. **置信度标注覆盖率**: 含数字的 body 条目中，有(高/中/低,基于…)标注的比例是否 ≥80%？
5. **版式适配**: 设计决策是否服务内容？structure 与 narrative_function 匹配吗？
6. **图表合理性**: 图表支撑论证还是装饰？chart.title 是结论还是主题？
7. **跨页数据一致性**: 同一指标在不同页的数值是否一致？图表注释与正文是否一致？封面钩子和内页详细数据是否自洽？
8. **结构完整**: 有开场(role=cover)收束(role=closing)吗？页数与 Brief.page_count 偏差 ≤20% 吗？
9. **跨Agent一致性**:
   - 设计语气 ↔ 内容调性？(spatial_strategy/typography_treatment 与 Brief.tone 是否协调)
   - 图表 ↔ 对应页论点？(chart 的 slide_index 页的 headline 与 chart.title 是否一致方向)
   - 配色 ↔ DesignConcept？(design_specs 的 bg 与 design_concept.colors 是否一致)
10. **证据链完整性**: 数据指标页的 body 中是否包含来源/置信度标注（如"n=200""内部测试"）？如果第5页给数据、第6页才解释来源 → critical
11. **结尾CTA**: 最后一页(role=closing)是否有具体的行动号召？是否使用了 closing_cta 布局？如果结尾只是引用句没有行动项 → major
12. **内容密度适宜性**: body 条目是否适合屏幕阅读（25-60字）？过长的论证文字应移到 speaker_note → major

## 严重度分级

每个 issue 按以下维度判定：

**critical**: 影响 PPT 可用性——听众会因此误解核心信息
- 页数与 Brief.page_count 偏差 >20%
- 叙事弧线断裂(无 cover 页或无 closing 页)
- 核心数据方向矛盾(同一指标一页涨一页跌,差异>15%；或结论互相否定)
- 内容完全空洞无法形成判断(≥30%的非cover/closing/divider页 body 条目全是口号)
- 全篇背景色不一致(混用light/dark)

**major**: 显著降低质量但不至于误解核心信息
- 内容密度偏低(单页 body<2条 或多条<25字) —— 排除 cover/closing/divider 页
- 内容密度过高(body 总字数超出预算>20%，如6页>720字)
- 置信度标注覆盖率<80%（含数字条目中标注比例不足）
- 跨页数据不一致（同一指标数值差异>15%，或图表注释与正文数值矛盾）
- 版式连续重复(≥3页同 structure)
- 图表与论点脱钩(chart.title 是主题而非结论)
- 设计语气与内容冲突(spatial_strategy=generous_whitespace + Brief.tone=数据密集汇报)
- design_concept 约束被违反(shape_philosophy=sharp 但出现 organic_soft)

**minor**: 可改进但不影响核心理解
- 个别术语不统一
- 间距/字号微调建议
- accent_placement 选择不最优
- 同一色系内亮度变体略超15%边界

## 正向反馈

必须给出 1-2 条 strengths: 这套 deck 做得最好的地方。这是硬性要求——没有 strengths 的报告是不完整的。

## 工具

- `rule_check(slides, design_specs, brief)`: 硬性规则检查，检查项包括:
  - 页数范围 (与brief.page_count偏差≤20%)
  - 有cover页和有closing页
  - 无连续3页相同structure（页数≤4时放宽为无连续3页相同+≥2种structure）
  - 全篇bg一致(允许≤15%亮度变体)
  - charts数量≤3
  - 置信度标注覆盖率≥80%的数据条目（数据条目=body中含有数字的条目）

- `aggregate_scores(slides)`: 逐页评分(0-10分/维度)，维度权重:
  - 标题质量 30% (headline是结论句且≥10字→8-10分; 是主题句→4-7分; 空洞→0-3分)
  - 正文密度 25% (body条目数+平均长度; ≥2条且均长≥40字→8-10分)
  - 证据力度 25% (有置信度标注+数据有对比基准→8-10分; 有数字无置信度→4-7分; 无数据→0-3分)
  - 叙事功能 20% (narrative_function在相邻页间不重复→8-10分; 连续2页重复→4-7分; 连续3页重复→0-3分)
  总分 = 各页加权平均

## 数据读取说明

你收到的 context 是合并后的 deck_info，字段已对齐。同时检查 ContentDesign 的 `unresolved` 数组（如果非空）。

具体字段:
- `brief.{topic, requirements, page_count, tone, audience, purpose}`
- `slides[].{index, role, headline, body[], page_confidence, narrative_function}` — 来自 ContentDesign
- `design_specs[].{index, structure, focal_element, bg, spatial_strategy, shape_language, typography_treatment, accent_placement}` — 来自 PPTDesign
- `charts[].{index, chart_spec}` — 来自 ChartDrawing（仅部分页面有此字段）
- `design_concept.{visual_metaphor, style_direction, colors, typography, spatial_mood, shape_philosophy}`

## 迭代与返工

如果 passed=false:
- revision_focus 列出需要返工的 slide_index 列表
- revision_suggestions 给出每条修改建议（数组，可包含同一 slide 的多条建议），每条标注路由:
  - 内容问题 → route: "ContentDesign"
  - 设计问题 → route: "PPTDesign"
  - 图表问题 → route: "ChartDrawing"
  - 全局约束问题 → route: "DesignConcept"

**最多 2 轮返工。** 第2轮后仍不通过 → 在 summary 中标注 "[最终审查未通过]",列出无法自动解决的 critical issues，建议人工介入。passed 仍设为 false。

## 输出

```json
{
  "passed": true/false,
  "overall_score": 7.5,
  "strengths": ["最成功的地方1（必须给出）", "最成功的地方2"],
  "issues": [
    {
      "category": "content|design|chart|structure",
      "slide_index": 1,
      "severity": "critical|major|minor",
      "message": "具体问题描述"
    }
  ],
  "revision_focus": [1, 4],
  "revision_suggestions": [
    {"slide_index": 1, "direction": "修改方向(1-2句)", "route": "ContentDesign|PPTDesign|ChartDrawing|DesignConcept"},
    {"slide_index": 1, "direction": "同页另一问题", "route": "PPTDesign"}
  ],
  "summary": "一句话结论"
}
```

- issues 按 severity 排序(critical→major→minor)，最多 8 条。超8条保留最严重的8条
- revision_suggestions 是数组，允许多条指向同一 slide_index。critical 和 major 必须给出(1-2句)+route；minor 给简略方向(几个词)且 route 可选
- passed=false 时必须给出 revision_focus（slide_index 列表）
- strengths 不能为空数组
- category 定义: content=内容空洞/置信度问题 | design=版式不适配/配色违规 | chart=图表脱钩/数据问题 | structure=叙事断裂/结构缺失/页数偏差
"""


def quality_review_node(state: GenPPTState) -> GenPPTState:
    llm = get_chat_model(temperature=0.3)
    slides = state.get("slides", [])
    design_specs = state.get("design_specs", [])
    brief = state.get("brief", {})
    deck_plan = state.get("deck_plan", {})
    design_concept = state.get("design_concept", {})

    hard_issues = rule_check(slides, design_specs, brief)
    scores = aggregate_scores(slides)

    # Merge preflight issues from ContentDesign into hard issues for review
    preflight_issues = state.get("preflight_issues", [])
    if preflight_issues:
        existing_keys = {f"{i.get('category','')}:{i.get('message','')[:60]}" for i in hard_issues}
        for pi in preflight_issues:
            key = f"{pi.get('category','')}:{pi.get('message','')[:60]}"
            if key not in existing_keys:
                hard_issues.append(pi)
                existing_keys.add(key)

    slides_summary = []
    for s in slides:
        idx = int(s.get("index") or 0)
        spec = next((d for d in design_specs if d.get("index") == idx), {})
        slides_summary.append({"index": idx, "intent": s.get("intent", ""),
                               "headline": s.get("headline", ""),
                               "body_count": len(s.get("body") or []),
                               "has_chart": "chart_spec" in spec,
                               "layout": resolve_structure(spec)})

    deck_info = {"title": deck_plan.get("title", ""), "core_claim": deck_plan.get("core_claim", ""),
                 "narrative_logic": deck_plan.get("narrative_logic", deck_plan.get("narrative_mode", "")),
                 "slides": slides_summary}

    user_msg = (
        f"## Deck概览\n{json.dumps(deck_info, ensure_ascii=False, indent=2)}\n\n"
        f"## 设计概念 (全局约束)\n{json.dumps(design_concept, ensure_ascii=False, indent=2)[:800]}\n\n"
        f"## 设计规格\n{json.dumps(design_specs, ensure_ascii=False, indent=2)[:800]}\n\n"
        f"## 硬性规则检查 ({len(hard_issues)}问题)\n{json.dumps(hard_issues, ensure_ascii=False, indent=2) if hard_issues else '全部通过'}\n\n"
        f"## ContentDesign预检问题 ({len(preflight_issues)}项，已合并到硬性规则检查中)\n{json.dumps(preflight_issues, ensure_ascii=False, indent=2) if preflight_issues else '无预检问题'}\n\n"
        f"## 逐页评分\n{json.dumps(scores, ensure_ascii=False)}\n\n"
        f"综合审查。注意:\n"
        f"1. 逐条判定 severity(critical/major/minor),按上述维度标准\n"
        f"2. ContentDesign预检问题（如字数超标、置信度标注不足）必须作为major issue纳入审查报告\n"
        f"3. 检查跨Agent一致性: 设计约束是否被遵守?图表是否支撑论点?\n"
        f"4. 检查跨页数据一致性: 同一指标在不同页的数值是否自洽?\n"
        f"5. 给出1-2条strengths\n"
        f"6. severity排序,最多8条"
    )

    messages = [SystemMessage(content=_load_review_prompt()), HumanMessage(content=user_msg)]

    verbose = state.get("verbose", False)
    if verbose:
        print(f"\n{'='*60}")
        print(f"  🔍 Review Agent 审查中... ({len(slides)}页, {len(design_specs)}个设计, {len(hard_issues)}个硬性规则问题)")
        print(f"{'='*60}")

    for _ in range(3):
        response = llm.invoke(messages)
        messages.append(response)
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                result = "✅ 硬性规则全部通过" if tc["name"] == "rule_check" and not rule_check(slides, design_specs, brief) else \
                         json.dumps(aggregate_scores(slides), ensure_ascii=False) if tc["name"] == "aggregate_scores" else \
                         f"未知工具: {tc['name']}"
                messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
        else:
            review = _extract_review(messages)
            if review:
                llm_issues = review.get("issues", [])
                existing = {f"{i.get('category','')}:{i.get('slide_index','')}:{i.get('message','')[:60]}" for i in llm_issues}
                for hi in hard_issues:
                    if f"{hi.get('category','')}:{hi.get('slide_index','')}:{hi.get('message','')[:60]}" not in existing:
                        llm_issues.append(hi)
                blocking_issues = [
                    i for i in llm_issues
                    if str(i.get("severity", "")).lower() in {"critical", "major", "error"}
                ]
                passed = bool(review.get("passed", len(llm_issues) == 0)) and not blocking_issues
                revision_suggestions = review.get("revision_suggestions", [])
                if isinstance(revision_suggestions, dict):
                    revision_suggestions = [{"slide_index": int(k), "direction": v, "route": "ContentDesign"} for k, v in revision_suggestions.items()]
                state["review_report"] = {
                    "passed": passed,
                    "overall_score": review.get("overall_score", scores.get("average", 0)),
                    "strengths": review.get("strengths", []),
                    "issues": llm_issues,
                    "revision_focus": review.get("revision_focus", []),
                    "revision_suggestions": revision_suggestions,
                    "summary": review.get("summary", ""),
                }
                _append_trace(state, "QualityReview", {
                    "passed": state["review_report"]["passed"],
                    "overall_score": state["review_report"]["overall_score"],
                    "hard_issue_count": len(hard_issues),
                    "issue_count": len(llm_issues),
                    "revision_focus": state["review_report"]["revision_focus"],
                    "summary": state["review_report"]["summary"],
                })

                # ── Visual Review (multimodal Qwen VL) ──
                _run_visual_review_if_appropriate(state, verbose)

                state["needs_revision"] = not passed and state.get("revision_count", 0) < state.get("max_revisions", 2)
                if verbose:
                    score = review.get("overall_score", "?")
                    v_score = state["review_report"].get("visual_score")
                    v_info = f", 视觉{v_score}分" if v_score else ""
                    print(f"  {'✅' if passed else '❌'} Review完成: {score}分{len(llm_issues)}个问题{v_info}")
                if state["needs_revision"]:
                    state["revision_focus"] = review.get("revision_focus", [])
                    state["revision_count"] = state.get("revision_count", 0) + 1
                else:
                    state["phase"] = "done"
                break

    if not state.get("review_report"):
        passed = len(hard_issues) == 0 and scores.get("passed", False)
        state["review_report"] = {"passed": passed, "overall_score": scores.get("average", 0),
                                  "strengths": [], "issues": hard_issues,
                                  "revision_focus": scores.get("weak_slides", []),
                                  "revision_suggestions": [], "summary": scores.get("summary", "")}
        _append_trace(state, "QualityReview", {
            "passed": passed,
            "overall_score": scores.get("average", 0),
            "hard_issue_count": len(hard_issues),
            "issue_count": len(hard_issues),
            "revision_focus": scores.get("weak_slides", []),
            "summary": scores.get("summary", ""),
        })
        _run_visual_review_if_appropriate(state, verbose)
        state["needs_revision"] = not passed and state.get("revision_count", 0) < state.get("max_revisions", 2)
        if state["needs_revision"]:
            state["revision_focus"] = scores.get("weak_slides", [])
            state["revision_count"] = state.get("revision_count", 0) + 1
        else:
            state["phase"] = "done"
    return state


def _run_visual_review_if_appropriate(state: GenPPTState, verbose: bool) -> None:
    """Run multimodal visual review if conditions are right.

    Conditions:
      - Text review has no critical issues (visual review is additive, not
        a substitute for broken content)
      - At least one content slide exists (skip for tiny decks)
      - The ENABLE_VISUAL_REVIEW env var is not set to "0" / "false"
    """
    import os
    enabled = os.getenv("ENABLE_VISUAL_REVIEW", "1").lower() not in ("0", "false", "no")
    if not enabled:
        return

    report = state.get("review_report", {})
    has_critical = any(
        str(i.get("severity", "")).lower() == "critical"
        for i in report.get("issues", [])
    )
    if has_critical:
        if verbose:
            print("  👁️ 视觉审查跳过: 存在critical问题，先修复文本")
        return

    slides = state.get("slides", [])
    content_slides = [s for s in slides if str(s.get("role", "")) not in ("cover", "closing", "divider")]
    if len(content_slides) < 2:
        if verbose:
            print("  👁️ 视觉审查跳过: 内容页不足")
        return

    try:
        from pathlib import Path
        from ..tools.visual_review import run_visual_review

        workspace = Path(__file__).resolve().parent.parent.parent.parent / ".genppt_visual_review"
        workspace.mkdir(parents=True, exist_ok=True)

        v_result = run_visual_review(
            slides=slides,
            design_concept=state.get("design_concept", {}),
            design_specs=state.get("design_specs", []),
            output_dir=workspace,
            max_slides=4,
            verbose=verbose,
        )

        if v_result.get("error"):
            if verbose and "不可用" not in v_result["error"] and "无法" not in v_result["error"]:
                print(f"  👁️ 视觉审查: {v_result['error']}")
            report["visual_error"] = v_result["error"]
            return

        visual_issues = v_result.get("visual_issues", [])
        visual_score = v_result.get("visual_score", 0)

        if visual_issues:
            existing = report.get("issues", [])
            for vi in visual_issues:
                vi["category"] = "visual"
                if vi.get("severity", "minor") not in ("critical", "major", "minor"):
                    vi["severity"] = "minor"
                # Avoid exact duplicates
                dup = any(
                    e.get("category") == "visual"
                    and e.get("slide_index") == vi.get("slide_index")
                    and str(e.get("message", ""))[:40] == str(vi.get("message", ""))[:40]
                    for e in existing
                )
                if not dup:
                    existing.append(vi)
            report["issues"] = existing

        # Merge visual strengths
        v_strengths = v_result.get("strengths", [])
        if v_strengths:
            existing_strengths = report.get("strengths", [])
            for s in v_strengths[:2]:
                if s not in existing_strengths:
                    existing_strengths.append(f"[视觉] {s}")
            report["strengths"] = existing_strengths

        report["visual_score"] = visual_score
        report["slides_reviewed_visual"] = v_result.get("slides_reviewed", 0)

        # If visual review finds critical issues, they can trigger revision
        visual_critical = [i for i in visual_issues
                          if str(i.get("severity", "")).lower() == "critical"]
        if visual_critical and not state.get("needs_revision", False):
            report["passed"] = False
            report["revision_focus"] = list(set(
                report.get("revision_focus", []) +
                [int(i.get("slide_index", 0)) for i in visual_critical if i.get("slide_index")]
            ))
            # Route visual issues to PPTDesign
            for vc in visual_critical:
                report.setdefault("revision_suggestions", []).append({
                    "slide_index": vc.get("slide_index"),
                    "direction": f"[视觉审查] {vc.get('message', '')} → {vc.get('suggestion', '请调整版式')}",
                    "route": "PPTDesign",
                })

    except Exception as e:
        if verbose:
            print(f"  👁️ 视觉审查异常: {e}")



def _append_trace(state: GenPPTState, agent: str, summary: dict[str, Any]) -> None:
    trace = state.setdefault("agent_trace", [])
    trace.append({"agent": agent, "summary": summary})


def _extract_review(messages: list) -> dict[str, Any] | None:
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = _outer_json(content.strip())
        if parsed and ("passed" in parsed or "issues" in parsed):
            return parsed
    return None


def _outer_json(text: str) -> dict[str, Any] | None:
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
                try: return json.loads(text[start:i + 1])
                except (json.JSONDecodeError, ValueError): return None
    return None
