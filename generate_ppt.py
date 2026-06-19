"""Generate PPTX via GenPPT LangGraph ReAct workflow. (legacy entry, use genppt.py instead)"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from genppt.orchestrator import run_agent_orchestrated_deck
from genppt.render_artifact import export_pptx


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an editable PPTX from one sentence.")
    parser.add_argument("topic", help="PPT topic")
    parser.add_argument("--requirements", "-r", default="", help="Deck requirements")
    parser.add_argument("--output-dir", "-o", default="dist", help="Directory for final PPTX")
    parser.add_argument("--variant-seed", type=int, default=0, help="Variant seed")
    parser.add_argument("--brand", default=None, help="Path to brand-style.md")
    args = parser.parse_args()

    deck = run_agent_orchestrated_deck(args.topic, args.requirements, variant_seed=args.variant_seed)
    pptx = export_pptx(deck.result, Path(args.output_dir), brand_path=args.brand)
    print(str(pptx))


if __name__ == "__main__":
    main()
