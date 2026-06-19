"""Qwen (Tongyi Wanxiang) image generation tool.

Integrates with DashScope's text-to-image API to generate images that
match the DesignConcept's visual style.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any


def generate_qwen_image(
    prompt: str,
    output_dir: str | Path,
    filename: str = "generated.png",
    size: str = "1024*1024",
    negative_prompt: str = "",
    api_key: str | None = None,
) -> dict[str, Any]:
    """Generate an image using Qwen (Tongyi Wanxiang) via DashScope.

    Args:
        prompt: Chinese or English image description.
        output_dir: Directory to save the generated image.
        filename: Output filename (default: generated.png).
        size: Image size, e.g. "1024*1024", "720*1280", "1280*720".
        negative_prompt: What to avoid in the image.
        api_key: DashScope API key. Falls back to DASHSCOPE_API_KEY env var.

    Returns:
        {"success": True, "path": "/abs/path/to/image.png"}
        or {"success": False, "error": "..."}
    """
    import os

    key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
    if not key:
        return {"success": False, "error": "缺少 DASHSCOPE_API_KEY，设置环境变量或传入 api_key 参数"}

    try:
        import dashscope
    except ImportError:
        return {"success": False, "error": "dashscope 未安装，请执行 pip install dashscope"}

    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from dashscope import ImageSynthesis

        result = ImageSynthesis.call(
            model="wanx-v1",
            api_key=key,
            prompt=prompt,
            negative_prompt=negative_prompt or "低质量, 模糊, 水印, 文字, 扭曲, 丑陋",
            n=1,
            size=size,
        )

        if result.status_code == 200 and result.output and result.output.results:
            img_url = result.output.results[0].url
            if img_url:
                _download_image(img_url, output_path)
                return {"success": True, "path": str(output_path.resolve())}

        return {"success": False, "error": f"API返回失败: {result.message if hasattr(result, 'message') else result.status_code}"}

    except Exception as exc:
        # Fallback: try HTTP API directly
        return _fallback_http_api(key, prompt, negative_prompt, size, output_path)


def _fallback_http_api(
    api_key: str, prompt: str, negative_prompt: str, size: str, output_path: Path
) -> dict[str, Any]:
    """Fallback: call DashScope HTTP API directly."""
    import requests

    try:
        # Submit task
        resp = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            json={
                "model": "wanx-v1",
                "input": {
                    "prompt": prompt,
                    "negative_prompt": negative_prompt or "低质量, 模糊, 水印, 文字",
                },
                "parameters": {"size": size, "n": 1},
            },
            timeout=30,
        )
        data = resp.json()
        task_id = data.get("output", {}).get("task_id", "")

        if not task_id:
            return {"success": False, "error": f"提交任务失败: {data}"}

        # Poll for result
        for _ in range(20):
            time.sleep(2)
            poll = requests.get(
                f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            poll_data = poll.json()
            status = poll_data.get("output", {}).get("task_status", "")
            if status == "SUCCEEDED":
                img_url = poll_data.get("output", {}).get("results", [{}])[0].get("url", "")
                if img_url:
                    _download_image(img_url, output_path)
                    return {"success": True, "path": str(output_path.resolve())}
                return {"success": False, "error": "任务完成但无图片URL"}
            if status == "FAILED":
                return {"success": False, "error": f"任务失败: {poll_data.get('output', {}).get('message', '')}"}

        return {"success": False, "error": "任务超时"}

    except Exception as exc:
        return {"success": False, "error": f"HTTP API调用失败: {exc}"}


def _download_image(url: str, path: Path) -> None:
    """Download image from URL, supporting both direct URL and base64 data."""
    import requests

    if url.startswith("data:"):
        header, encoded = url.split(",", 1)
        path.write_bytes(base64.b64decode(encoded))
        return

    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    path.write_bytes(resp.content)


def build_image_prompt(
    visual_metaphor: str,
    accent_hex: str,
    background_hex: str,
    description: str,
    style_direction: str = "",
) -> str:
    """Build a Qwen-optimized image prompt from DesignConcept fields.

    Produces Chinese prompts optimized for Tongyi Wanxiang's understanding.
    """
    color_desc = f"主色调{accent_hex}，背景{background_hex}"
    style = style_direction or "现代专业演示文稿配图"
    metaphor = visual_metaphor or "抽象几何"

    return (
        f"专业PPT演示配图: {description}。"
        f"视觉风格: {style}，{metaphor}风格。"
        f"配色方案: {color_desc}。"
        f"干净简洁，适合商务演示，无文字标签，高质量矢量感，16:9比例构图。"
    )
