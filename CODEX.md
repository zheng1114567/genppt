# CODEX.md

## 项目当前状态

这是一个一句话生成可编辑 PPT 的 Python 项目。当前生成链路由主控 Agent 统一调度，不再使用 pipeline。

当前可用入口：

- `generate_content.py`：生成内容稿和结构化 JSON。
- `generate_ppt.py`：生成内容并导出可编辑 PPTX。
- `profile_template.py`：读取旧 PPTX 模板，生成模板画像和 layout catalog。

核心运行文件：

- `src/genppt/orchestrator.py`：主控 Agent、主题分析、内容设计、PPT 设计、图表绘制、流程审查。
- `src/genppt/render_artifact.py`：把 `DeckResult` 导出为 `deck.json` 并调用 Node 渲染器。
- `scripts/render_pptx.cjs`：根据 `layout` 字段生成 PPTX。
- `src/genppt/pptx_lxml_effects.py`：只做阴影、渐变等 OOXML 视觉效果后处理。

## 默认策略

- 文字 LLM 默认使用千问 / DashScope。
- `DEEPSEEK_API_KEY` 作为备用。
- 没有 LLM 时使用确定性本地生成，保证测试和离线导出可跑。
- 图表由 `chart_drawing` Agent 按页面意图决定是否写入 `chart_spec`。
- 现在先不做动画，避免动画后处理干扰排版质量。

## Agent 工作流

主控 Agent 固定顺序：

1. `theme_analysis`：解析主题、要求、页数和语气。
2. `content_design`：确定叙事模式、页面任务、标题、正文和视觉提示。
3. `ppt_design`：按页面意图选择版式，控制连续重复。
4. `chart_drawing`：只在数据、对比、洞察页需要图表时加入图表规格。
5. `workflow_review`：检查页数、叙事顺序、正文密度、标题重复和版式变化。

代码入口：

```python
from genppt.orchestrator import run_agent_orchestrated_deck

deck = run_agent_orchestrated_deck(
    "AI赋能办公效率",
    "8页，产品团队评审，需要数据图表",
    enable_charts=True,
)
```

返回值包含：

- `deck.result`：导出 PPTX 使用的结构化结果。
- `deck.events`：主控 Agent 的每个步骤记录。

## PPT 生成标准

- 每页只服务一个判断。
- 标题要像结论句，避免只写“背景、问题、方案、总结”。
- 正文必须包含对象、场景、证据、动作、边界或验收指标。
- 版式不能连续重复同一种结构。
- 图表只在支撑判断时出现，并在示意数据中标注说明。
- 渲染结果必须是可编辑 PPTX，不依赖图片整页贴底。

## 模板与版式方向

- 模板画像通过 `profile_template.py` 完成，用于理解旧 PPT 的 master、layout 和 placeholder。
- 主生成链路目前使用内置 layout 名称驱动渲染器。
- 后续优化重点是扩展 `scripts/render_pptx.cjs` 的 layout 族，而不是恢复旧 pipeline。
- `ppt_design` Agent 输出的 `layout` 是渲染器选择页面结构的唯一依据。

## MCP 集成

`genppt.mcp.json` 默认配置 `web-research`，用于需要联网查行业资料、事实、新闻、政策或市场数据的主题。

需要设置：

```powershell
$env:BRAVE_API_KEY="your-key"
```

完整 PowerPoint 控制型 MCP 可以放在 `genppt.mcp.example.json`，只作为人工精修工具，不默认参与自动导出。

## 当前重点

1. 继续提升 `scripts/render_pptx.cjs` 的版式族差异。
2. 让 `chart_spec` 真正渲染成原生可编辑图表。
3. 把联网研究结果接入 `content_design` 或独立研究 Agent。
4. 暂停动画能力，先把排版和模板质量做好。

## 测试

```powershell
pytest -q
```
