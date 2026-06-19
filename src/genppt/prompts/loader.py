"""Prompt loader — externalised System Prompts with versioning and A/B test support.

Each agent's System Prompt lives in a YAML file under the `prompts/` directory.
The loader reads these files, supports version tags, and falls back to the
hardcoded default (passed as a parameter) if the file is missing or unreadable.

## File format (YAML)

    version: 1
    model: deepseek-chat
    system_prompt: |
      You are a PPT Content Director...

    # Optional A/B test config
    ab:
      variant: "b"
      prompts:
        a: |
          ...
        b: |
          ...

## Usage

    from genppt.prompts.loader import get_prompt

    prompt = get_prompt("director", fallback=HARDCODED_PROMPT)
    # Or with A/B variant:
    prompt = get_prompt("director", variant="b", fallback=HARDCODED_PROMPT)
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any

_PROMPTS_DIR = Path(__file__).resolve().parent

# Built-in prompt registry — maps agent name → filename
_REGISTRY: dict[str, str] = {
    "director": "director.yaml",
    "content": "content.yaml",
    "design": "design.yaml",
    "chart": "chart.yaml",
    "review": "review.yaml",
}


def _load_yaml(path: Path) -> dict[str, Any] | None:
    """Load a YAML file. Returns None if missing, unreadable, or unparseable."""
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_raw_prompt(agent: str) -> dict[str, Any] | None:
    """Load the raw YAML config for an agent. Returns None if not found."""
    filename = _REGISTRY.get(agent, f"{agent}.yaml")
    path = _PROMPTS_DIR / filename
    if not path.exists():
        return None
    return _load_yaml(path)


def get_prompt(
    agent: str,
    *,
    variant: str | None = None,
    fallback: str = "",
) -> str:
    """Get the System Prompt for an agent.

    Args:
        agent: Agent name (director, content, design, chart, review).
        variant: A/B test variant to use ("a", "b", etc.). If None, uses the
                 default version or randomly picks if `ab_variant: "random"`.
        fallback: Hardcoded prompt to return if the file is missing/unparseable.

    Returns:
        The System Prompt string.
    """
    cfg = _load_raw_prompt(agent)
    if cfg is None:
        return fallback

    # A/B test support
    ab_cfg = cfg.get("ab")
    if isinstance(ab_cfg, dict):
        variants = ab_cfg.get("prompts", {})
        if variants:
            chosen = variant
            if not chosen:
                chosen = ab_cfg.get("variant", "a")
            if chosen == "random":
                chosen = random.choice(list(variants.keys()))
            if chosen in variants:
                return variants[chosen].strip()
            # If specified variant doesn't exist, fall through to default

    # Default: return the main system_prompt
    prompt = cfg.get("system_prompt", "")
    if prompt and isinstance(prompt, str):
        return prompt.strip()

    return fallback


def get_prompt_version(agent: str) -> int:
    """Get the version number of a prompt file. Returns 0 if not found."""
    cfg = _load_raw_prompt(agent)
    if cfg is None:
        return 0
    return cfg.get("version", 0)


def list_prompt_versions() -> dict[str, int]:
    """Return {agent: version} for all registered agents."""
    return {agent: get_prompt_version(agent) for agent in _REGISTRY}


def reload_prompts() -> None:
    """Clear any in-memory caches. (YAML files are read on each call, so
    this is a no-op for now. Reserved for future caching support.)"""
    pass


# ── Convenience: extract the hardcoded SYSTEM_PROMPT from each agent module ──

def _extract_module_prompt(module_path: str, var_name: str = "SYSTEM_PROMPT") -> str:
    """Extract a SYSTEM_PROMPT string from a Python module without importing it."""
    try:
        import ast
        tree = ast.parse(Path(module_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        if isinstance(node.value, ast.Constant):
                            return str(node.value.value)
        return ""
    except Exception:
        return ""


def bootstrap_prompt_files(dry_run: bool = False) -> dict[str, bool]:
    """Generate YAML prompt files from hardcoded SYSTEM_PROMPT in agent modules.

    This is a one-time migration tool. It extracts the SYSTEM_PROMPT constant
    from each agent's .py file and writes it to a .yaml file if one doesn't exist.

    Returns {agent: created (True) / skipped (False)}.
    """
    agent_modules = {
        "director": "director.py",
        "content": "content.py",
        "design": "design.py",
        "chart": "chart.py",
        "review": "review.py",
    }
    agents_dir = _PROMPTS_DIR.parent / "agents"
    results: dict[str, bool] = {}

    for agent, filename in agent_modules.items():
        yaml_path = _PROMPTS_DIR / f"{agent}.yaml"
        if yaml_path.exists():
            results[agent] = False
            continue

        prompt_text = _extract_module_prompt(str(agents_dir / filename))
        if not prompt_text:
            results[agent] = False
            continue

        yaml_content = f"""# GenPPT System Prompt — {agent}
# Auto-generated by bootstrap_prompt_files(). Edit freely.

version: 1
model: default
system_prompt: |
{_indent_text(prompt_text, 2)}
"""
        if not dry_run:
            yaml_path.write_text(yaml_content, encoding="utf-8")
        results[agent] = True

    return results


def _indent_text(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return prefix + text.replace("\n", "\n" + prefix)
