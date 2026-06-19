"""Web image search tool — finds and downloads images from the web.

Uses DuckDuckGo image search (no API key required) with fallback to
Unsplash for higher quality results.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def search_web_images(
    query: str,
    output_dir: str | Path,
    max_results: int = 5,
    min_width: int = 800,
    min_height: int = 600,
) -> dict[str, Any]:
    """Search for images on the web and download them.

    Tries Unsplash first (most reliable in China), then DuckDuckGo,
    then Pexels as final fallback.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    images = []
    errors = []

    # Strategy 1: Unsplash (works globally, no API key)
    try:
        unsplash_images = _unsplash_search(query, max_results)
        for i, img_url in enumerate(unsplash_images):
            try:
                filename = f"web_{_hash(query)}_{i}.jpg"
                filepath = output_path / filename
                _download(img_url, filepath)
                if filepath.stat().st_size > 1000:
                    images.append(str(filepath.resolve()))
            except Exception as e:
                errors.append(f"Unsplash dl: {e}")
        if images:
            return {"success": True, "images": images, "source": "unsplash"}
    except Exception as e:
        errors.append(f"Unsplash: {e}")

    # Strategy 2: Pexels (free API)
    try:
        import os
        pexels_key = os.getenv("PEXELS_API_KEY", "")
        if pexels_key:
            pexels_images = _pexels_search(query, max_results, pexels_key)
            for i, img_url in enumerate(pexels_images):
                try:
                    filename = f"web_{_hash(query)}_{i}.jpg"
                    filepath = output_path / filename
                    _download(img_url, filepath)
                    if filepath.stat().st_size > 1000:
                        images.append(str(filepath.resolve()))
                except Exception as e:
                    errors.append(f"Pexels dl: {e}")
            if images:
                return {"success": True, "images": images, "source": "pexels"}
    except Exception as e:
        errors.append(f"Pexels: {e}")

    # Strategy 3: DuckDuckGo (may be blocked in some regions)
    try:
        ddg_images = _ddg_search(query, max_results)
        for i, img_url in enumerate(ddg_images):
            try:
                ext = _guess_ext(img_url)
                filename = f"web_{_hash(query)}_{i}{ext}"
                filepath = output_path / filename
                _download(img_url, filepath)
                if filepath.stat().st_size > 1000:
                    images.append(str(filepath.resolve()))
            except Exception as e:
                errors.append(f"DDG dl: {e}")
        if images:
            return {"success": True, "images": images, "source": "duckduckgo"}
    except Exception as e:
        errors.append(f"DDG: {e}")

    if not images:
        return {"success": False, "error": "; ".join(errors[-3:]) if errors else "未找到合适的图片"}
    return {"success": True, "images": images, "source": "fallback"}


def _pexels_search(query: str, max_results: int, api_key: str) -> list[str]:
    """Search Pexels for photos."""
    import json as _json
    from urllib.request import Request, urlopen

    url = f"https://api.pexels.com/v1/search?query={_url_encode(query)}&per_page={max_results}"
    req = Request(url, headers={"Authorization": api_key, "User-Agent": "GenPPT/1.0"})
    resp = urlopen(req, timeout=15)
    data = _json.loads(resp.read())
    return [p["src"]["large"] for p in data.get("photos", [])[:max_results]]


def _ddg_search(query: str, max_results: int) -> list[str]:
    """Search DuckDuckGo for images."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=max_results))
            return [r["image"] for r in results if r.get("image")]
    except ImportError:
        pass

    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=max_results))
            return [r["image"] for r in results if r.get("image")]
    except ImportError:
        pass

    return []


def _unsplash_search(query: str, max_results: int) -> list[str]:
    """Search Unsplash for photos (source.unsplash.com redirects)."""
    import json as _json

    try:
        url = (
            f"https://unsplash.com/napi/search/photos"
            f"?query={_url_encode(query)}&per_page={max_results}"
        )
        req = Request(url, headers={"User-Agent": "GenPPT/1.0", "Accept": "application/json"})
        resp = urlopen(req, timeout=10)
        data = _json.loads(resp.read())
        return [r["urls"]["regular"] for r in data.get("results", [])[:max_results]]
    except Exception:
        # Unsplash source redirect (lower quality but more reliable)
        try:
            return [f"https://source.unsplash.com/1200x800/?{_url_encode(query)}"]
        except Exception:
            return []


def _download(url: str, path: Path) -> None:
    """Download from URL to local path."""
    req = Request(url, headers={"User-Agent": "GenPPT/1.0"})
    resp = urlopen(req, timeout=30)
    if resp.status == 200:
        path.write_bytes(resp.read())


def _guess_ext(url: str) -> str:
    url_lower = url.split("?")[0]
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        if ext in url_lower:
            return ext
    return ".jpg"


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:8]


def _url_encode(text: str) -> str:
    from urllib.parse import quote
    return quote(text)
