"""config.local.toml 的最小安全更新：只改 [proxy] 段，保留其余内容与注释。

用于 `radar serve` 的代理设置面板：用户填代理地址 → 保存 → 下一轮刷新
重新加载配置生效。所有写入走原子替换，写前/写后用 tomllib 校验。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from .providers_store import atomic_write_text

_ALLOWED_SCHEMES = {"http", "https", "socks5", "socks5h"}


class LocalConfigError(RuntimeError):
    """本地配置无法解析或输入不合法。"""


def normalize_proxy_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if len(raw) > 200:
        raise LocalConfigError("代理地址过长")
    if any(ch in raw for ch in ('"', "'", "\n", "\r", " ", "\t")):
        raise LocalConfigError("代理地址不能包含引号、空白或换行")
    if "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise LocalConfigError("只支持 http/https/socks5 代理")
    if not parts.hostname:
        raise LocalConfigError("代理地址缺少主机名")
    return raw


def read_proxy(path: Path) -> dict:
    """读取本地 [proxy]；文件不存在或损坏时返回默认值。"""
    path = Path(path)
    if not path.exists():
        return {"url": "", "auto_detect": True}
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return {"url": "", "auto_detect": True, "error": f"config.local.toml 解析失败: {e}"}
    proxy = raw.get("proxy", {}) if isinstance(raw.get("proxy"), dict) else {}
    return {
        "url": str(proxy.get("url", "") or "").strip(),
        "auto_detect": bool(proxy.get("auto_detect", True)),
    }


def _set_scalar(text: str, table: str, key: str, literal: str) -> str:
    """在 [table] 段内设置 key = literal；不存在则追加到段尾或文件尾。"""
    table_re = re.compile(rf"(?m)^\[{re.escape(table)}\][ \t]*$")
    match = table_re.search(text)
    if not match:
        prefix = text.rstrip("\n")
        sep = "\n\n" if prefix else ""
        return f"{prefix}{sep}[{table}]\n{key} = {literal}\n"

    start = match.end()
    nxt = re.compile(r"(?m)^\[", re.MULTILINE).search(text, start)
    end = nxt.start() if nxt else len(text)
    segment = text[start:end]

    key_re = re.compile(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=.*$")
    if key_re.search(segment):
        segment = key_re.sub(f"{key} = {literal}", segment, count=1)
    else:
        segment = segment.rstrip("\n") + f"\n{key} = {literal}\n\n"
    return text[:start] + segment + text[end:]


def update_proxy(path: Path, url: str, auto_detect: bool = True) -> dict:
    """更新 [proxy] url/auto_detect；返回保存后的配置。"""
    path = Path(path)
    normalized = normalize_proxy_url(url)

    if path.exists():
        text = path.read_text(encoding="utf-8")
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise LocalConfigError(f"config.local.toml 已损坏，拒绝写入: {e}") from e
    else:
        text = (
            "# promo-radar 本地配置（不入库）\n"
            "# 由 radar serve 的代理面板或手工编辑；优先于 config.toml\n"
        )

    text = _set_scalar(text, "proxy", "url", f'"{normalized}"')
    text = _set_scalar(text, "proxy", "auto_detect", "true" if auto_detect else "false")

    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:  # 理论上不会发生，兜底保护
        raise LocalConfigError(f"写入前校验失败: {e}") from e

    atomic_write_text(path, text)
    proxy = parsed.get("proxy", {})
    return {
        "url": str(proxy.get("url", "") or ""),
        "auto_detect": bool(proxy.get("auto_detect", True)),
    }