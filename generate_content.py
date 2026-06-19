"""Generate PPT content only via GenPPT LangGraph ReAct workflow. (legacy entry, use genppt.py --content-only instead)"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from genppt.orchestrator import result_to_deck_dict, run_agent_orchestrated_deck
from genppt.trace import agent_trace_markdown, build_agent_trace_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PPT content without rendering PPTX.")
    parser.add_argument("topic", help="PPT topic")
    parser.add_argument("--requirements", "-r", default="", help="Deck requirements")
    parser.add_argument("--output-dir", "-o", default="dist/content", help="Output directory")
    parser.add_argument("--variant-seed", type=int, default=0, help="Variant seed")
    args = parser.parse_args()

    deck = run_agent_orchestrated_deck(args.topic, args.requirements, variant_seed=args.variant_seed)
    payload = result_to_deck_dict(deck.result)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    title = payload["deck_plan"]["title"]
    safe = "".join(ch if ch.isalnum() or ch in "-_" or "一" <= ch <= "鿿" else "-" for ch in title)
    safe = "-".join(p for p in safe.split("-") if p)[:60] or "deck-content"

    json_path = output_dir / f"{safe}.content.json"
    md_path = output_dir / f"{safe}.content.md"
    trace_json_path = output_dir / f"{safe}.agent_trace.json"
    trace_md_path = output_dir / f"{safe}.agent_trace.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_md(payload), encoding="utf-8")
    trace_payload = build_agent_trace_payload(payload)
    trace_json_path.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    trace_md_path.write_text(agent_trace_markdown(trace_payload), encoding="utf-8")
    print(str(md_path))
    print(str(json_path))
    print(str(trace_md_path))
    print(str(trace_json_path))


def _md(payload: dict) -> str:
    lines = [
        f"# {payload.get('deck_plan', {}).get('title') or 'PPT内容稿'}",
        "",
        f"- 工作流：{payload.get('source_workflow', {}).get('mode', '')}",
        "",
        "## 页面内容",
    ]
    for s in payload.get("slides") or []:
        lines.extend(["", f"### {s.get('index')}. {s.get('headline')}", ""])
        for item in s.get("body") or []:
            lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
