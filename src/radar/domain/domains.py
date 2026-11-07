"""域名工具：从 URL 提取注册域（可被 watchlist / enroll / providers 存储共用）。

放在 domain 层，避免 infra.providers_store 与 collectors.watchlist 之间
形成循环导入。
"""

from __future__ import annotations

from urllib.parse import urlsplit

# 多段公共后缀（末两段不是注册域，需取末三段）
MULTI_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk",
    "com.au", "net.au", "org.au", "gov.au", "edu.au",
    "co.jp", "ne.jp", "or.jp", "go.jp", "ac.jp",
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn",
    "com.hk", "org.hk", "gov.hk", "edu.hk",
    "com.tw", "org.tw", "gov.tw", "edu.tw",
    "co.kr", "or.kr", "go.kr", "ne.kr", "re.kr",
    "com.sg", "org.sg", "gov.sg", "edu.sg",
    "co.in", "net.in", "org.in", "gov.in", "edu.in",
    "com.br", "com.mx", "com.ar", "com.tr", "co.za", "co.nz", "org.nz",
}


def registrable_domain(url: str) -> str | None:
    """URL → 注册域（去 www、取末两段；多段公共后缀取末三段）。非 http(s) 返回 None。"""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.split("@")[-1].split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) < 2 or not labels[-1].isalpha():
        return None
    take = 3 if len(labels) >= 3 and ".".join(labels[-2:]) in MULTI_SUFFIXES else 2
    return ".".join(labels[-take:])