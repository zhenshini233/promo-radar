"""共享 HTTP 工具：统一 UA / 超时 / 重试 / 代理。"""

from __future__ import annotations

import html as html_mod
import json
import re
import time
from typing import Any

import httpx

from .config import RadarConfig

USER_AGENT = (
    "Mozilla/5.0 (compatible; promo-radar/0.1; personal promo aggregator)"
)

# 去掉脚本/样式块后再剥标签，避免 JS 里的文案污染正文
_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def make_client(cfg: RadarConfig) -> httpx.Client:
    """共享 HTTP client；bypass 名单中的域名绕过代理直连（部分站点对代理节点 TLS 不稳）。"""
    common = dict(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en,zh-CN;q=0.8"},
        timeout=httpx.Timeout(30.0),
        trust_env=True,
        follow_redirects=True,
    )
    if cfg.proxy_url and cfg.proxy_bypass:
        mounts = {f"all://{host}": httpx.HTTPTransport() for host in cfg.proxy_bypass}
        return httpx.Client(mounts=mounts, transport=httpx.HTTPTransport(proxy=cfg.proxy_url), **common)
    return httpx.Client(proxy=cfg.proxy_url or None, **common)


def get_text(client: httpx.Client, url: str, *, retries: int = 2) -> str:
    """GET 文本，失败指数退避重试，最终失败抛出异常（由 runner 的源隔离兜住）。"""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
        except Exception as e:  # noqa: BLE001 - 统一转译为源失败
            last_err = e
            if attempt < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"GET {url} failed after {retries + 1} attempts: {last_err}") from last_err


def get_json(client: httpx.Client, url: str, *, retries: int = 2) -> Any:
    return json.loads(get_text(client, url, retries=retries))


def strip_html(raw: str) -> str:
    text = _SCRIPT_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html_mod.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def loose_text(raw: str) -> str:
    """宽松文本：只去标签、保留 script 内文本（RSC/JSON 载荷里的促销文案也算数）。

    适合 watchlist 的内容指纹与关键词探测——很多站（如 deepinfra）的 promo
    文案只存在于 <script> 的数据载荷中，strip_html 会把它剥掉。
    """
    text = _TAG_RE.sub(" ", raw)
    text = html_mod.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def extract_text(raw: str) -> str:
    """正文提取（trafilatura 多算法投票），失败回退 strip_html。

    用于文章/帖类源的 evidence 提纯；指纹与关键词探测仍用 loose_text。
    """
    try:
        import trafilatura

        text = trafilatura.extract(
            raw, include_comments=False, include_tables=False, favor_recall=True
        )
        if text:
            return _WS_RE.sub(" ", text).strip()
    except Exception:  # noqa: BLE001 - 提取失败一律回退
        pass
    return strip_html(raw)
