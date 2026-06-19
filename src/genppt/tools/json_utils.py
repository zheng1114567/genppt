"""Shared JSON extraction utilities used by all agents.

Consolidates the 6 duplicate _extract_json implementations into one place.
"""

from __future__ import annotations

import json, re
from typing import Any


def extract_json(text: str) -> dict[str, Any] | None:
    """Extract the outermost JSON object from text using brace counting.

    Handles:
    - Nested braces within JSON strings
    - Unicode escape sequences
    - Trailing commas (common in LLM output)
    """
    start = text.find("{")
    if start < 0:
        return None
    depth, in_string, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    return json.loads(candidate)
                except (json.JSONDecodeError, ValueError):
                    return None
    return None


def extract_json_from_messages(messages: list) -> dict[str, Any] | None:
    """Scan a list of LangChain messages for the most recent valid JSON object.

    Searches in reverse (newest message first), extracting the first valid
    JSON with a ``{`` character.
    """
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = extract_json(content.strip())
        if parsed:
            return parsed
    return None


def parse_slides_from_messages(messages: list) -> list[dict[str, Any]]:
    """Extract slides array or full deck JSON from messages.

    If the parsed JSON contains a ``slides`` key, returns that list.
    Otherwise returns the parsed value itself if it's a list.
    """
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = extract_json(content.strip())
        if parsed:
            slides = parsed.get("slides") or parsed
            if isinstance(slides, list) and slides:
                return slides
    return []


def parse_deck_and_slides(messages: list) -> dict[str, Any] | None:
    """Extract a deck JSON (with ``slides`` or ``deck_plan`` key) from messages."""
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = extract_json(content.strip())
        if parsed and ("slides" in parsed or "deck_plan" in parsed):
            return parsed
    return None


def extract_outermost_json(text: str) -> dict[str, Any] | None:
    """Same as extract_json — kept for naming consistency with design.py."""
    return extract_json(text)


def extract_page_count(requirements: str) -> int:
    """Parse a page count hint from a requirements string."""
    for token in re.split(r"[\s,，]+", str(requirements).lower()):
        digit = re.match(r"(\d+)(?:页|pages?|slides?|p)?", token)
        if digit:
            return max(3, min(20, int(digit.group(1))))
    return 8
