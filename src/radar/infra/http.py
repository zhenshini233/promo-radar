"""共享 HTTP 工具：统一 UA / 超时 / 重试 / 代理。"""

from __future__ import annotations

import html as html_mod
import json
import os
import re
import threading
import time
from typing import Any

import httpx

from .config import RadarConfig
from .proxy import effective_proxy

USER_AGENT = (
    "Mozilla/5.0 (compatible; promo-radar/0.1; personal promo aggregator)"
)

# 去掉脚本/样式块后再剥标签，避免 JS 里的文案污染正文
_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def make_client(cfg: RadarConfig) -> httpx.Client:
    """共享 HTTP client；bypass 名单中的域名绕过代理直连（部分站点对代理节点 TLS 不稳）。

    配置了代理但本机端口没开时，effective_proxy 会退回直连，避免每个请求
    都卡在连接超时上。
    """
    proxy = effective_proxy(
        cfg.proxy_url,
        auto_detect=cfg.proxy_auto_detect,
        timeout=cfg.proxy_detect_timeout,
    )
    common = dict(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en,zh-CN;q=0.8"},
        # connect 单独限制：SSL 握手/连接被墙时最多等 3 秒，
        # 否则 httpx 的 read 超时会让单次请求拖到几十秒。
        timeout=httpx.Timeout(
            cfg.general.http_timeout,
            connect=min(3.0, cfg.general.http_timeout),
        ),
        trust_env=True,
        follow_redirects=True,
    )
    if proxy and cfg.proxy_bypass:
        mounts = {f"all://{host}": httpx.HTTPTransport() for host in cfg.proxy_bypass}
        return httpx.Client(mounts=mounts, transport=httpx.HTTPTransport(proxy=proxy), **common)
    # 仅本地调试用：系统证书链异常时可临时关闭校验（CI/线上不要设置）
    if os.environ.get("RADAR_TLS_INSECURE") == "1":
        print("[http] 警告：RADAR_TLS_INSECURE=1，已关闭 TLS 校验（仅限本地调试）")
        common["verify"] = False
    return httpx.Client(proxy=proxy or None, **common)


def _request_with_deadline(
    client: httpx.Client, url: str, kwargs: dict, deadline: float
) -> httpx.Response:
    """带硬性总时长的 GET。

    httpx 的 read timeout 是「每次 socket read」而不是「整个请求」；实测在
    握手后慢速读取时，单次请求可拖到 30s+。这里用 daemon 线程 + join
    施加总 deadline，超时立即返回失败，避免单源拖住整轮。
    """
    box: dict = {}

    def run() -> None:
        try:
            box["resp"] = client.get(url, **kwargs)
        except BaseException as e:  # noqa: BLE001 - 转交给调用方
            box["err"] = e

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(deadline)
    if thread.is_alive():
        raise httpx.ReadTimeout(f"request deadline {deadline:.0f}s exceeded")
    if "err" in box:
        raise box["err"]
    return box["resp"]


def get_text(
    client: httpx.Client,
    url: str,
    *,
    retries: int = 1,
    timeout: float | None = None,
    connect_timeout: float = 3.0,
) -> str:
    """GET 文本，失败指数退避重试，最终失败抛出异常（由 runner 的源隔离兜住）。

    timeout 可覆盖 client 默认值：watchlist 单页探测用更短超时，
    避免个别慢站把整轮拖到 CI 上限。connect 单独限 3s，整体有硬 deadline。
    """
    kwargs = {}
    if timeout is not None:
        kwargs["timeout"] = httpx.Timeout(timeout, connect=min(connect_timeout, timeout))
    deadline = timeout if timeout is not None else (client.timeout.read or 15.0)
    deadline = max(1.0, float(deadline))
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = _request_with_deadline(client, url, kwargs, deadline)
            resp.raise_for_status()
            return resp.text
        except Exception as e:  # noqa: BLE001 - 统一转译为源失败
            last_err = e
            # 超时（连接被墙/站点不响应）重试只会把耗时翻倍，直接失败；
            # 5xx / 连接重置等瞬时错误才值得退避重试。
            if attempt < retries and not isinstance(e, httpx.TimeoutException):
                time.sleep(2**attempt)
    raise RuntimeError(f"GET {url} failed after {retries + 1} attempts: {last_err}") from last_err


def get_json(
    client: httpx.Client, url: str, *, retries: int = 1, timeout: float | None = None
) -> Any:
    return json.loads(get_text(client, url, retries=retries, timeout=timeout))


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
