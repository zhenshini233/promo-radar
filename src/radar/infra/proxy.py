"""代理可用性探测：配置了代理但本机端口没开时，自动降级为直连。

背景：`config.local.toml` 里填了代理，但 v2rayN/Clash 没启动时，所有请求
都会卡在连接超时（每个请求 10s + 重试），一轮抓取被拖到 20 分钟以上。
这里在建立 HTTP 客户端前先做一次 TCP 端口探测（默认 0.5s），不通就直连。
"""

from __future__ import annotations

import socket
from urllib.parse import urlsplit

_WARNED: set[str] = set()

_DEFAULT_PORTS = {"http": 8080, "https": 8080, "socks5": 1080, "socks5h": 1080}


def proxy_endpoint(url: str) -> tuple[str, int] | None:
    """代理 URL → (host, port)；无法解析时返回 None。"""
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw)
    host = parts.hostname
    if not host or any(ch.isspace() for ch in host):
        return None
    port = parts.port or _DEFAULT_PORTS.get(parts.scheme.lower(), 8080)
    return host, int(port)


def is_proxy_available(url: str, *, timeout: float = 0.5) -> bool:
    endpoint = proxy_endpoint(url)
    if endpoint is None:
        return False
    try:
        with socket.create_connection(endpoint, timeout=timeout):
            return True
    except OSError:
        return False


def effective_proxy(
    url: str, *, auto_detect: bool = True, timeout: float = 0.5
) -> str:
    """返回本轮实际使用的代理 URL；空串表示直连。"""
    raw = (url or "").strip()
    if not raw or not auto_detect:
        return raw
    if is_proxy_available(raw, timeout=timeout):
        return raw
    if raw not in _WARNED:
        endpoint = proxy_endpoint(raw)
        where = f"{endpoint[0]}:{endpoint[1]}" if endpoint else raw
        print(f"[proxy] {where} 端口不可达，本轮改为直连（检查代理是否启动）")
        _WARNED.add(raw)
    return ""