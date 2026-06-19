from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any, Protocol

# Load .env from project root
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(_env_path)
except Exception:
    pass


class LLMClient(Protocol):
    def generate_json(self, system_prompt: str, user_prompt: str, schema_hint: str) -> dict[str, Any]:
        """Generate structured JSON from an LLM provider."""


@dataclass(slots=True)
class GatewayConfig:
    base_url: str
    api_key: str
    model: str
    provider: str = "openai-compatible"
    timeout_seconds: int = 60


def config_from_env() -> GatewayConfig:
    """Build the text-generation LLM config.

    DeepSeek is the default text gateway for this project.
    Qwen/DashScope and OpenAI remain available as fallbacks.
    """

    if os.getenv("DEEPSEEK_API_KEY"):
        return deepseek_config_from_env()
    if os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY"):
        return qwen_config_from_env()
    if os.getenv("OPENAI_API_KEY"):
        return GatewayConfig(
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            provider="openai",
            timeout_seconds=int(os.getenv("OPENAI_TIMEOUT_SECONDS", "60")),
        )
    raise RuntimeError("Missing API key. Set DASHSCOPE_API_KEY, QWEN_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY.")


def deepseek_config_from_env() -> GatewayConfig:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing API key. Set DEEPSEEK_API_KEY.")
    return GatewayConfig(
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        provider="deepseek",
        timeout_seconds=int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60")),
    )


def qwen_config_from_env() -> GatewayConfig:
    api_key = (
        os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("QWEN_API_KEY")
    )
    if not api_key:
        raise RuntimeError("Missing API key. Set DASHSCOPE_API_KEY or QWEN_API_KEY.")

    return GatewayConfig(
        base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key=api_key,
        model=os.getenv("QWEN_MODEL", "qwen-plus"),
        provider="qwen",
        timeout_seconds=int(os.getenv("QWEN_TIMEOUT_SECONDS", "60")),
    )


class GatewayLLMClient:
    """OpenAI-compatible adapter for Qwen/DashScope or similar gateway APIs.

    Qwen's DashScope compatible mode accepts the familiar chat completions
    request shape, so this class intentionally stays provider-light.
    """

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config

    def generate_json(self, system_prompt: str, user_prompt: str, schema_hint: str) -> dict[str, Any]:
        last_error = None
        for attempt in range(3):
            try:
                content = self.generate_text(
                    system_prompt=system_prompt,
                    user_prompt=f"{user_prompt}\n\n请严格输出 JSON，不要输出 Markdown。\nJSON 结构提示：\n{schema_hint}",
                )
                if not content or not content.strip():
                    last_error = RuntimeError("LLM returned empty response")
                    continue
                return _parse_json_content(content)
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"generate_json failed after 3 attempts: {last_error}")

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
        }
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            safe_detail = re.sub(r'(sk-[a-zA-Z0-9]+)', '[REDACTED]', detail)
            safe_detail = re.sub(r'("api_key"\s*:\s*)"[^"]+"', r'\1"[REDACTED]"', safe_detail)
            raise RuntimeError(f"LLM gateway HTTP {exc.code}: {safe_detail[:500]}") from exc
        except URLError as exc:
            raise RuntimeError(f"LLM gateway request failed: {exc.reason}") from exc

        try:
            return response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected LLM response shape: {response_payload}") from exc


def default_llm_client() -> GatewayLLMClient:
    return GatewayLLMClient(config_from_env())


def get_chat_model(model_name: str | None = None, temperature: float = 0.7) -> "Any":
    """Return a LangChain-compatible ChatOpenAI instance configured from env vars.

    Provider priority: DeepSeek > DashScope/Qwen > OpenAI.
    """
    from langchain_openai import ChatOpenAI

    config = config_from_env()
    return ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        model=model_name or config.model,
        temperature=temperature,
        timeout=config.timeout_seconds,
    )


def vision_config_from_env() -> GatewayConfig:
    """Build config for a vision-capable model.

    Vision models require multimodal API support. Currently only Qwen VL
    (via DashScope compatible mode) is supported.
    """
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
    if not api_key:
        raise RuntimeError(
            "视觉审查需要设置 DASHSCOPE_API_KEY 或 QWEN_API_KEY。\n"
            "当前没有配置 DashScope API Key，视觉审查将被跳过。"
        )
    return GatewayConfig(
        base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key=api_key,
        model=os.getenv("QWEN_VL_MODEL", "qwen-vl-max"),
        provider="qwen-vl",
        timeout_seconds=int(os.getenv("QWEN_VL_TIMEOUT_SECONDS", "90")),
    )


def get_vision_model(temperature: float = 0.3) -> "Any":
    """Return a LangChain ChatOpenAI instance configured for vision tasks.

    Uses Qwen VL via DashScope compatible-mode endpoint.
    Falls back to None if no DashScope key is configured.
    """
    from langchain_openai import ChatOpenAI

    try:
        config = vision_config_from_env()
    except RuntimeError:
        return None

    return ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        temperature=temperature,
        timeout=config.timeout_seconds,
    )


def _parse_json_content(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        cleaned = cleaned.removesuffix("```").strip()

    import re
    # Remove trailing comma before closing bracket/brace
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try balancing braces to extract the JSON object
        brace_start = cleaned.find("{")
        if brace_start >= 0:
            depth = 0
            in_string = False
            escape_next = False
            end = brace_start
            for i in range(brace_start, len(cleaned)):
                ch = cleaned[i]
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\":
                    escape_next = True
                    continue
                if ch == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    # Allow newlines in strings by replacing them
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            candidate = cleaned[brace_start:end]
            # Replace literal newlines inside JSON strings with \\n
            candidate = _sanitize_json_newlines(candidate)
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                raise RuntimeError(f"LLM did not return valid JSON: {candidate[:300]}")
        else:
            raise RuntimeError(f"LLM did not return valid JSON: {cleaned[:300]}")

    if not isinstance(parsed, dict):
        parsed = {"items": parsed}
    return parsed


def _sanitize_json_newlines(text: str) -> str:
    """Replace literal newlines inside JSON string values with \\n."""
    import re
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == "\\":
            result.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch in "\r\n":
            result.append("\\n")
            continue
        result.append(ch)
    return "".join(result)
