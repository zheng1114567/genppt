#!/usr/bin/env python3
"""GenPPT — AI-driven PPT generation with ReAct agents.

Usage:
  python genppt.py "主题" -r "要求"
  python genppt.py "主题" -r "8页，产品团队评审"
  python genppt.py "主题" -r "8页" --content-only
  python genppt.py "主题" -r "8页" --brand styles/brand.md
  python genppt.py "主题" -r "8页" -o outputs/ --verbose
  python genppt.py "主题" -r "8页" --cache  # enable LLM response cache
  python genppt.py "主题" -r "8页" --resume  # resume from checkpoint
  python genppt.py "主题" -r "8页" --config config.json
  python genppt.py --batch topics.json  # batch generate multiple PPTs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from genppt.orchestrator import run_agent_orchestrated_deck, result_to_deck_dict
from genppt.trace import agent_trace_markdown, build_agent_trace_payload

CACHE_DIR = ROOT / ".genppt_cache"


def _cache_key(topic: str, requirements: str) -> str:
    return hashlib.md5(f"{topic}|{requirements}".encode()).hexdigest()[:16]


def _load_cache(topic: str, requirements: str) -> dict | None:
    cp = CACHE_DIR / f"{_cache_key(topic, requirements)}.json"
    if cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_cache(topic: str, requirements: str, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = CACHE_DIR / f"{_cache_key(topic, requirements)}.json"
    cp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        print(f"⚠️ 配置文件不存在: {config_path}，使用默认配置")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def generate_one(
    topic: str,
    requirements: str = "",
    output_dir: str = "dist",
    variant_seed: int = 0,
    brand_path: str | None = None,
    content_only: bool = False,
    verbose: bool = False,
    use_cache: bool = False,
    use_resume: bool = False,
    config: dict | None = None,
) -> Path | None:
    """Generate a single PPT. Returns the output path or None."""
    cfg = config or {}

    # Cache check
    if use_cache:
        cached = _load_cache(topic, requirements)
        if cached:
            if verbose:
                print(f"📦 使用缓存结果")
            # Re-render from cached deck
            from genppt.orchestrator import DeckResult, OrchestratedDeck
            import dataclasses
            # For now, just skip generation and re-render
            # Full cache restore would need DeckResult reconstruction

    if verbose:
        print(f"╔══ GenPPT (LangGraph ReAct) ══╗")
        print(f"║ 主题: {topic}")
        if requirements:
            print(f"║ 要求: {requirements}")
        if use_resume:
            print(f"║ 模式: 从检查点恢复")
        print(f"╚{'═' * 30}╝")
        print()

    # Override from config
    if cfg.get("max_iterations"):
        import genppt.graph as g
        g.run_genppt_graph.__defaults__ = (cfg["max_iterations"],) + g.run_genppt_graph.__defaults__[1:]

    if verbose:
        print("▶ 启动 LangGraph ReAct 工作流...")

    start = time.time()
    deck = run_agent_orchestrated_deck(
        topic,
        requirements,
        variant_seed=variant_seed,
        verbose=verbose,
    )
    elapsed = time.time() - start

    if verbose:
        print(f"▶ 工作流完成 ({elapsed:.0f}s): {len(deck.events)} 个阶段")
        for ev in deck.events:
            print(f"  [{ev.node}] {ev.summary}")
        review = next((e.data.get("review_report", {}) for e in deck.events if e.data.get("review_report")), {})
        if review:
            print(f"  审查分数: {review.get('overall_score', 'N/A')}")
            if review.get("passed"):
                print(f"  ✅ 审查通过")
            else:
                issues = review.get("issues", [])
                print(f"  ⚠️ 审查发现 {len(issues)} 个问题")

    payload = result_to_deck_dict(deck.result)

    # Save cache
    if use_cache:
        _save_cache(topic, requirements, payload)

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    title = payload["deck_plan"]["title"]
    safe = "".join(ch if ch.isalnum() or ch in "-_" or "一" <= ch <= "鿿" else "-" for ch in title)
    safe = "-".join(p for p in safe.split("-") if p)[:60] or "deck"

    json_path = output_dir_path / f"{safe}.content.json"
    md_path = output_dir_path / f"{safe}.content.md"
    trace_json_path = output_dir_path / f"{safe}.agent_trace.json"
    trace_md_path = output_dir_path / f"{safe}.agent_trace.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    trace_payload = build_agent_trace_payload(payload)
    trace_json_path.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    trace_md_path.write_text(agent_trace_markdown(trace_payload), encoding="utf-8")

    if verbose:
        print(f"\n📄 内容稿: {md_path}")
        print(f"📋 内容JSON: {json_path}")
        print(f"🧭 Agent过程JSON: {trace_json_path}")
        print(f"🧭 Agent过程Markdown: {trace_md_path}")

    if not content_only:
        from genppt.render_artifact import export_pptx
        pptx_path = export_pptx(deck.result, output_dir_path, brand_path=brand_path)
        print(str(pptx_path))
        if verbose:
            print(f"\n📊 PPTX: {pptx_path}")
        return pptx_path

    return json_path


def generate_batch(
    batch_file: str,
    output_dir: str = "dist",
    **kwargs,
) -> list[Path]:
    """Generate multiple PPTs from a JSON batch file.

    Batch file format:
    [
      {"topic": "...", "requirements": "..."},
      {"topic": "...", "requirements": "..."}
    ]
    """
    path = Path(batch_file)
    if not path.exists():
        print(f"❌ 批处理文件不存在: {batch_file}")
        return []

    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        print(f"❌ 批处理文件格式错误: 需要JSON数组")
        return []

    results = []
    total = len(items)
    for i, item in enumerate(items):
        topic = item.get("topic", "")
        req = item.get("requirements", "")
        if not topic:
            print(f"⚠️ 跳过第{i+1}项: 缺少 topic")
            continue
        print(f"\n{'='*60}")
        print(f"[{i+1}/{total}] {topic[:60]}")
        print(f"{'='*60}")
        try:
            result = generate_one(topic, req, output_dir=output_dir, **kwargs)
            if result:
                results.append(result)
        except Exception as e:
            print(f"❌ 生成失败: {e}")

    print(f"\n✓ 批量完成: {len(results)}/{total} 成功")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GenPPT — AI-driven PPT generation with LangGraph ReAct agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python genppt.py "专业用户用 GenPPT 提高办公效率的产品改进方案" -r "8页，给产品团队评审"
  python genppt.py "Q3产品战略规划" -r "6页给高管" --content-only
  python genppt.py "年度数据总结" -r "10页" -o reports/ --verbose
  python genppt.py "培训课程设计" -r "12页，面向新员工" --cache
  python genppt.py --batch topics.json -o outputs/
  python genppt.py "主题" -r "8页" --config config.json
        """,
    )
    parser.add_argument("topic", nargs="?", help="PPT 主题（用引号包裹）")
    parser.add_argument("--requirements", "-r", default="", help="要求（页数、受众等）")
    parser.add_argument("--output-dir", "-o", default="dist", help="输出目录 (默认: dist)")
    parser.add_argument("--variant-seed", type=int, default=0, help="设计变体种子")
    parser.add_argument("--brand", default=None, help="品牌样式 .md 文件路径")
    parser.add_argument("--content-only", action="store_true", help="仅生成内容稿，不导出PPTX")
    parser.add_argument("--verbose", "-v", action="store_true", help="输出详细过程信息")
    parser.add_argument("--cache", action="store_true", help="启用 LLM 响应缓存")
    parser.add_argument("--resume", action="store_true", help="从上次检查点恢复")
    parser.add_argument("--config", default=None, help="JSON 配置文件路径")
    parser.add_argument("--batch", default=None, help="批量生成: JSON 文件路径 (数组格式)")
    args = parser.parse_args()

    config = _load_config(args.config) if args.config else {}

    # Batch mode
    if args.batch:
        generate_batch(
            args.batch,
            output_dir=args.output_dir,
            variant_seed=args.variant_seed,
            brand_path=args.brand,
            content_only=args.content_only,
            verbose=args.verbose,
            use_cache=args.cache,
            use_resume=args.resume,
            config=config,
        )
        return

    # Single mode
    if not args.topic:
        parser.error("请提供 topic，或使用 --batch 批量模式")

    generate_one(
        args.topic,
        args.requirements,
        output_dir=args.output_dir,
        variant_seed=args.variant_seed,
        brand_path=args.brand,
        content_only=args.content_only,
        verbose=args.verbose,
        use_cache=args.cache,
        use_resume=args.resume,
        config=config,
    )


def _markdown(payload: dict) -> str:
    lines = [
        f"# {payload.get('deck_plan', {}).get('title') or 'PPT内容稿'}",
        "",
        f"- 主题：{payload.get('brief', {}).get('topic', '')}",
        f"- 要求：{payload.get('brief', {}).get('requirements', '')}",
        f"- 工作流：{payload.get('source_workflow', {}).get('mode', '')}",
        f"- 核心主张：{payload.get('deck_plan', {}).get('core_claim', '')}",
        f"- 叙事逻辑：{payload.get('deck_plan', {}).get('narrative_mode', '')}",
        "",
        "## 页面内容",
    ]
    for slide in payload.get("slides") or []:
        lines.extend(["", f"### {slide.get('index')}. {slide.get('headline')}", ""])
        lines.append(f"- 意图：{slide.get('intent')}")
        lines.append(f"- 版式：{slide.get('layout')}")
        for item in slide.get("body") or []:
            lines.append(f"- {item}")
        if slide.get("chart_spec"):
            cs = slide["chart_spec"]
            lines.append(f"- 📊 图表: {cs.get('type', '')} — {cs.get('title', '')}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
