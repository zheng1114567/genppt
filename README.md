# GenPPT

一句话生成可编辑 PPT 的项目骨架。

当前流程分两步：

1. 主控 Agent 先组织主题分析、内容设计、PPT 设计、图表绘制和流程审查。
2. 渲染器读取主控 Agent 输出的 `deck.json`，生成可编辑 PPTX。

当前生成入口不再使用 pipeline。

## 现在可用的入口

- `generate_content.py` - 只生成 PPT 内容稿，不导出 PPTX
- `generate_ppt.py` - 生成内容并导出 PPTX
- `profile_template.py` - 读取现有 PPTX 模板，生成 layout catalog 和 placeholder profile

## 默认 LLM

- 文字生成默认使用千问 / DashScope
- `DEEPSEEK_API_KEY` 仍可作为备用
- 视觉侧保留 Qwen 兼容配置

## 内容生成流程

内容层会依次生成：

- `Brief`
- `DeckPlan`
- `SlidePlan`
- `SlideCopy`
- 工作流审查结果

内容稿输出为：

- `.content.md`
- `.content.json`

示例：

```powershell
python generate_content.py "专业用户用 GenPPT 提高办公效率的产品改进方案" -r "8页，给产品团队评审"
```

## PPT 生成流程

```powershell
python generate_ppt.py "专业用户用 GenPPT 提高办公效率的产品改进方案" -r "8页，给产品团队评审"
```

输出包括：

- `.pptx`
- `deck.json`
- OOXML 视觉效果后处理日志

## 模板画像流程

如果有公司模板或旧 PPT，先做模板画像，再决定是否使用真实占位符、只复用主题，还是继续走 GenPPT 内置布局语法：

```powershell
python profile_template.py "template.pptx" -o outputs/template-profile
```

输出：

- `template-profile.json`
- `layout-catalog.md`

该流程借鉴 profile-author-render 的做法：先识别 slide master、layout 和 placeholder，再把模板能力作为可审资料交给内容/版式节点，而不是把模板当背景图硬贴文本。

## Agent 工作流

主控 Agent 固定调度这些职责：

- `theme_analysis`：解析主题、页数和语气。
- `content_design`：确定叙事模式、页面任务和单页文案。
- `ppt_design`：为每页选择版式，避免单一模板重复。
- `chart_drawing`：仅在页面需要图表支撑判断时写入图表规格。
- `workflow_review`：检查页数、叙事顺序、正文密度和版式重复。

代码入口：

```python
from genppt.orchestrator import run_agent_orchestrated_deck

deck = run_agent_orchestrated_deck(
    "专业用户用 GenPPT 提高办公效率的产品改进方案",
    "8页，给产品团队评审",
    enable_charts=True,
)
```

返回结果包含 `deck.result` 和 `deck.events`，导出时会把工作流信息写入 `deck.json`。

## 当前重点

- 内容不要空泛
- 每页只讲一个判断
- 避免跨页复读
- 版式不要再只靠一个模板族
- 图表只在支撑判断时出现

## 模板与版式

- 页面版式由主控 Agent 的 `ppt_design` 结果决定，渲染器按 `layout` 字段选择对应模板族。
- `chart_drawing` Agent 可以为数据页、对比页和洞察页写入 `chart_spec`。
- `pptx_lxml_effects.py` 只负责阴影、渐变等视觉效果，不再处理动画。

## MCP 集成

默认 `genppt.mcp.json` 只保留本项目的本地 PPT 后处理示例。联网 MCP 应作为主控 Agent 的研究工具接入，不参与默认离线生成。

`genppt.mcp.example.json` 额外给出 `ppt-mcp-powerpoint` 示例：

```json
{
  "command": "uvx",
  "args": ["ppt-mcp"],
  "role": "manual_refine",
  "autoPostprocess": false
}
```

这类完整 PowerPoint 控制型 MCP 适合打开最终 PPT 后做人工/Agent 精修，不默认参与自动导出后处理，避免误调用不匹配的工具。

## 测试

```powershell
pytest -q
```

当前测试应保持通过。
