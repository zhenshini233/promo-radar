"""代理探测：端口不通自动直连。"""

import socket

from radar.infra.proxy import effective_proxy, is_proxy_available, proxy_endpoint


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_endpoint_parsing():
    assert proxy_endpoint("http://127.0.0.1:10808") == ("127.0.0.1", 10808)
    assert proxy_endpoint("127.0.0.1:7890") == ("127.0.0.1", 7890)
    assert proxy_endpoint("socks5://127.0.0.1") == ("127.0.0.1", 1080)
    assert proxy_endpoint("") is None
    assert proxy_endpoint("not a url") is None


def test_unavailable_proxy_falls_back_to_direct():
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    assert is_proxy_available(url, timeout=0.2) is False
    assert effective_proxy(url, timeout=0.2) == ""


def test_available_proxy_is_kept(monkeypatch):
    # 端口探测本身由 test_unavailable 覆盖；这里只验证探测通过时的返回值
    monkeypatch.setattr("radar.infra.proxy.is_proxy_available", lambda url, timeout=0.5: True)
    url = "http://127.0.0.1:10808"
    assert effective_proxy(url, timeout=0.5) == url


def test_auto_detect_off_keeps_configured_proxy():
    url = "http://127.0.0.1:1"
    assert effective_proxy(url, auto_detect=False) == url