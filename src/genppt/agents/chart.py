"""ChartDrawing ReAct agent — determines when charts are actually needed and designs them."""

from __future__ import annotations

import json
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from ..state import GenPPTState
from ..llm import get_chat_model
from ..tools import quantify_data_presence
from ..prompts import get_prompt


_CHART_PROMPT = None


def _load_chart_prompt() -> str:
    global _CHART_PROMPT
    if _CHART_PROMPT is None:
        _CHART_PROMPT = get_prompt("chart", fallback=SYSTEM_PROMPT_HARDCODED)
    return _CHART_PROMPT


SYSTEM_PROMPT_HARDCODED = """你是 PPT 图表策略师。判断哪些页面需要数据可视化，设计图表来增强论证。
你在管道中游——你基于 ContentDesign 的 slides（取 body 中的数据）和 PPTDesign 的 design_specs（取 focal_element），决定哪些页面需要图表。

## 重要：某些布局已有视觉元素，禁止加图表

以下布局类型已有丰富的视觉呈现，叠加图表会造成视觉混乱。即使数据质量分很高，也**不要**为这些页面添加图表：
- hero_cover（封面页）
- fishbone（鱼骨图——已有因果分析可视化）
- process_flow（流程图——已有步骤可视化）
- timeline（时间线——已有里程碑可视化）
- kpi_cards（KPI大数字卡片——已有数据可视化）
- quote_callout（大引述页）
- agenda（目录页）
- swot（SWOT四象限）
- funnel（漏斗图——已有阶段可视化）
- matrix_2x2（2×2矩阵）

只有这些布局类型适合叠加图表：title_top, title_split, title_visual, grid, centered, vertical_stack

## 判断标准

一个页面需要图表，必须同时满足：
1. 正文包含可量化数据（百分比、趋势、对比、占比）
2. 图表能帮助听众更快理解——不是装饰
3. 没有图表时说服力会明显下降

## 图表优先级

候选页超过 3 个时，按以下得分排序（取前 3）：
得分 = 数据论证关键度(1-5) × 图表理解效率提升(1-5)

数据论证关键度锚定：
- 5分: 页面的核心判断直接依赖这个数据（headline 本身就是数据结论）
- 4分: 该页 page_confidence 为"高"——可信数据驱动
- 3分: 数据支撑判断但不是唯一支柱（还有其他论证线索）
- 2分: 该页 page_confidence 为"低"——数据推演成分大，图表价值打折
- 1分: 数据是背景信息或锦上添花

图表理解效率提升锚定：
- 5分: 数据关系需要视觉化才能理解（如多维度对比、趋势走向、占比构成）
- 3分: 文字已能传达但图表可加速理解
- 1分: 文字表述已足够清晰，图表仅起装饰作用

**外部锚定**: 数据论证关键度受 ContentDesign 该页 page_confidence 字段约束——page_confidence="高"的页面数据可信，优先考虑制图；page_confidence="低"的页面即使数据点多，也应降权。

## 数据质量

用 `quantify_data_presence(slides)` 查看每页数据质量分：
- 基数 = 该页 body 中可识别的数据点数量（一个百分比/绝对值/趋势描述 = 1个数据点）
- 权重: 带单位的数据点(如"23%""8万")×2 | 裸数字(如"增长了5")×0.5 | 有对比基准(如"从X到Y""高于行业均值Z")额外×1.5
- 最终得分 = (带单位数据点数×2 + 裸数字数据点数×0.5) × 基准乘数
- 基准乘数映射: 0%数据有对比基准→1.0 | 1-49%→1.2 | 50-79%→1.35 | 80%+→1.5
- 得分 ≥4 的页面图表价值更高
在 rationale 中说明数据质量如何影响你的选择。

## 图表类型

根据数据关系选择，解释为什么此类型比次优选项更好：
- bar: 比较大小/排名。对比 line: line 更适合连续趋势而非离散对比
- line: 时间趋势/连续变化。对比 bar: bar 更适合独立类别
- pie/doughnut: 占比构成(≤5个类别)。对比 bar: 类别≤5用饼图,>5用横向bar
- radar: 多维度对比(≥3维度同一尺度)。对比 bar: 维度间有可比性用雷达
- funnel: 转化/递减。对比 bar: 漏斗有方向性
- scatter: 分布/相关性
- 如果数据关系跨类型，选最能突出核心洞察的类型，在 rationale 中解释跨类型判断

## 色盲安全

- 不用纯红(#FF0000)和纯绿(#00FF00)对比
- 方案A: 蓝#2563EB + 橙#D97706 + 灰#9CA3AF
- 方案B: 蓝#3B82F6 + 橙#F59E0B + 绿#10B981
- 方案C(4类别): 蓝#2563EB + 橙#D97706 + 紫#7C3AED + 灰#9CA3AF
- 在 rationale 中确认所用配色满足色盲友好

## 标注

- chart_spec.note 格式: "数据来源: [来源或置信度] | 标注策略: [关键数据点callout/异常值标注/基准线说明] | 标注位置: [图表下方/数据点旁/图例中]"

## 工具

- `quantify_data_presence(slides)`: 返回每页数据质量分（加权计分，规则见"数据质量"节）

## 输出

```json
{
  "charts": [
    {
      "index": 3,
      "priority_score": 25,
      "chart_spec": {
        "type": "bar",
        "title": "图表标题=结论（不是主题）",
        "categories": ["类别1", "类别2"],
        "values": [42, 58],
        "rationale": "①为什么需要图表(数据关系+听众理解需求) ②优先级得分计算(关键度X分×效率提升X分=XX) ③为什么选此类型而非次优(对比说明) ④色盲配色确认(使用方案X)",
        "note": "数据来源: [源/置信度] | 标注策略: [关键点/异常值/基准线] | 标注位置: [建议]"
      }
    }
  ]
}
```

最多 3 个图表。如果确实有 >3 页符合条件，选择 priority_score 最高的 3 个，其余在 rationale 末尾注明 "另有 X 页(索引 Y)符合条件但优先级较低未制图"。
values 如实反映数据差距，不人为拉平也不人为夸大。
"""


def chart_drawing_node(state: GenPPTState) -> GenPPTState:
    llm = get_chat_model(temperature=0.5)
    slides = state.get("slides", [])
    requirements = state.get("requirements", "")
    data_counts = quantify_data_presence(slides)
    candidates = []
    design_specs = state.get("design_specs", [])
    # Build layout lookup from design specs
    layout_by_page: dict[int, str] = {}
    for ds in design_specs:
        idx = int(ds.get("index", 0))
        struct = (ds.get("design") or {}).get("structure", ds.get("structure", ""))
        if struct:
            layout_by_page[idx] = struct

    for s in slides:
        idx = int(s.get("index", 0))
        score = data_counts.get(idx, 0)
        page_layout = layout_by_page.get(idx, "unknown")
        if score >= 2:
            candidates.append({"index": idx, "intent": s.get("intent", ""),
                               "headline": s.get("headline", ""), "body": s.get("body", []),
                               "visual_hint": s.get("visual_hint", ""), "data_quality_score": score,
                               "layout": page_layout})
    if not candidates:
        _append_trace(state, "ChartDrawing", {
            "candidate_count": 0,
            "selected_count": 0,
            "reason": "no slide met data threshold",
        })
        state["phase"] = "review"
        return state

    user_msg = (f"要求: {requirements}\n最多3个图表\n候选页(数据质量分=带单位×2+裸×0.5+有基准×1.5):\n"
                f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n\n用优先级公式排序，选最重要的最多3个。")

    messages = [SystemMessage(content=_load_chart_prompt()), HumanMessage(content=user_msg)]

    verbose = state.get("verbose", False)
    if verbose and candidates:
        print(f"\n{'='*60}")
        print(f"  📊 Chart Agent 分析中... ({len(candidates)}个候选页)")
        print(f"{'='*60}")

    for _ in range(3):
        response = llm.invoke(messages)
        messages.append(response)
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                messages.append(ToolMessage(
                    content=json.dumps({f"第{k}页": f"质量分{v}" for k, v in sorted(data_counts.items())}, ensure_ascii=False)
                    if tc["name"] == "quantify_data_presence" else f"未知工具: {tc['name']}",
                    tool_call_id=tc["id"]))
        else:
            charts = _extract_charts(messages)
            if charts is not None:
                # Hard-filter: remove charts from layouts that don't support them
                NO_CHART_LAYOUTS = {
                    "hero_cover", "fishbone", "process_flow", "timeline",
                    "kpi_cards", "quote_callout", "agenda", "swot", "funnel",
                    "matrix_2x2", "comparison_table"
                }
                filtered = []
                seen_pages: set[int] = set()
                for c in charts:
                    idx = int(c.get("index", 0))
                    page_layout = layout_by_page.get(idx, "")
                    if page_layout in NO_CHART_LAYOUTS:
                        continue  # skip — this layout already has rich visuals
                    if idx in seen_pages:
                        continue
                    seen_pages.add(idx)
                    filtered.append(c)
                    if len(filtered) >= 3:
                        break
                _inject(state, filtered)
                _append_trace(state, "ChartDrawing", {
                    "candidate_count": len(candidates),
                    "selected_count": len(filtered),
                    "selected_pages": [int(c.get("index", 0)) for c in filtered],
                    "filtered_pages": [
                        int(c.get("index", 0)) for c in charts
                        if layout_by_page.get(int(c.get("index", 0)), "") in NO_CHART_LAYOUTS
                    ],
                })
                if verbose:
                    print(f"  ✅ Chart完成: {len(filtered)}个图表")
                state["phase"] = "review"
                break

    if state.get("phase") != "review":
        charts = _extract_charts(messages)
        if charts:
            _inject(state, charts)
        else:
            state["error"] = f"{state.get('error', '')}; ChartDrawing: 解析失败".strip("; ")
        _append_trace(state, "ChartDrawing", {
            "candidate_count": len(candidates),
            "selected_count": len(charts or []),
            "error": state.get("error", ""),
        })
        state["phase"] = "review"
    return state


def _inject(state: GenPPTState, charts: list) -> None:
    specs = state.get("design_specs", [])
    count = 0
    seen_pages: set[int] = set()
    for c in charts:
        if count >= 3: break
        idx = int(c.get("index") or 0)
        if idx in seen_pages: continue
        cs = c.get("chart_spec")
        if idx < 1 or not cs: continue
        for s in specs:
            if int(s.get("index") or 0) == idx:
                seen_pages.add(idx)
                s["chart_spec"] = cs; count += 1; break


def _extract_charts(messages: list) -> list[dict[str, Any]] | None:
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = _outer_json(content.strip())
        if parsed:
            charts = parsed.get("charts") or parsed
            if isinstance(charts, list): return charts
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


def _append_trace(state: GenPPTState, agent: str, summary: dict[str, Any]) -> None:
    trace = state.setdefault("agent_trace", [])
    trace.append({"agent": agent, "summary": summary})
