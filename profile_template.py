from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from genppt.template_profile import write_template_profile  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile a PPTX template into a layout catalog.")
    parser.add_argument("pptx", help="Source PPTX template or deck")
    parser.add_argument(
        "--output-dir",
        "-o",
        default="outputs/template-profile",
        help="Directory for template-profile.json and layout-catalog.md",
    )
    args = parser.parse_args()

    json_path, md_path = write_template_profile(Path(args.pptx), Path(args.output_dir))
    print(str(json_path))
    print(str(md_path))


if __name__ == "__main__":
    main()
