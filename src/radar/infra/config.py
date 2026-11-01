"""配置加载：config.toml → RadarConfig。

优先级：环境变量 > config.toml > 内置默认。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.models import utcnow
from ..domain.scoring import KeywordRule


@dataclass
class GeneralConfig:
    data_dir: str = "data"
    expire_days: int = 45
    promo_threshold: float = 4.0


@dataclass
class RadarConfig:
    root: Path
    general: GeneralConfig = field(default_factory=GeneralConfig)
    proxy_url: str = ""
    proxy_bypass: list[str] = field(default_factory=list)
    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    sources: dict[str, dict] = field(default_factory=dict)
    keywords: list[KeywordRule] = field(default_factory=list)
    watchlist_keywords: list[str] = field(default_factory=list)

    @property
    def data_dir(self) -> Path:
        p = Path(self.general.data_dir)
        return p if p.is_absolute() else self.root / p

    @property
    def templates_dir(self) -> Path:
        return self.root / "templates"

    @property
    def providers_file(self) -> Path:
        return self.root / "providers.toml"

    def source(self, name: str) -> dict:
        return self.sources.get(name, {})

    def source_enabled(self, name: str) -> bool:
        return bool(self.source(name).get("enabled", False))


def _load_keywords(raw: dict) -> list[KeywordRule]:
    return [
        KeywordRule(
            pattern=str(k.get("pattern", "")),
            weight=float(k.get("weight", 1.0)),
            label=str(k.get("label", k.get("pattern", ""))),
        )
        for k in raw.get("keywords", [])
        if k.get("pattern")
    ]


def load_config(path: str | Path | None = None) -> RadarConfig:
    if path is None:
        # src/radar/infra/config.py → parents[3] = 项目根（config.toml 所在目录）
        # config.local.toml（gitignore）存在时优先：本地代理/密钥不入库
        root = Path(__file__).resolve().parents[3]
        path = os.environ.get("RADAR_CONFIG") or None
        if path is None:
            local = root / "config.local.toml"
            path = local if local.exists() else root / "config.toml"
    path = Path(path)
    raw: dict = {}
    if path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))

    general_raw = raw.get("general", {})
    general = GeneralConfig(
        data_dir=str(general_raw.get("data_dir", "data")),
        expire_days=int(general_raw.get("expire_days", 45)),
        promo_threshold=float(general_raw.get("promo_threshold", 4.0)),
    )

    proxy_raw = raw.get("proxy", {})
    proxy_url = str(proxy_raw.get("url", "") or "").strip() or os.environ.get("RADAR_PROXY", "")
    proxy_bypass = [str(h).strip() for h in proxy_raw.get("bypass", []) if str(h).strip()]

    tg_raw = raw.get("notify", {}).get("telegram", {})
    telegram_token = str(tg_raw.get("bot_token", "") or "").strip() or os.environ.get("RADAR_TG_TOKEN", "")
    telegram_chat_id = str(tg_raw.get("chat_id", "") or "").strip() or os.environ.get("RADAR_TG_CHAT_ID", "")
    telegram_enabled = bool(tg_raw.get("enabled", False)) and bool(telegram_token) and bool(telegram_chat_id)

    sources = {name: dict(conf) for name, conf in raw.get("sources", {}).items() if isinstance(conf, dict)}

    return RadarConfig(
        root=path.resolve().parent,
        general=general,
        proxy_url=proxy_url,
        proxy_bypass=proxy_bypass,
        telegram_enabled=telegram_enabled,
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        sources=sources,
        keywords=_load_keywords(raw),
        watchlist_keywords=[str(k) for k in raw.get("sources", {}).get("watchlist", {}).get("keywords", [])],
    )


def load_providers(path: Path) -> list[dict]:
    """providers.toml → list[{name, urls: [{label, url}], enabled, notes}]。"""
    if not path.exists():
        return []
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    providers = []
    for p in raw.get("provider", []):
        providers.append(
            {
                "name": str(p.get("name", "")).strip(),
                "urls": [
                    {"label": str(u.get("label", "home")), "url": str(u.get("url", "")).strip()}
                    for u in p.get("urls", [])
                    if u.get("url")
                ],
                "enabled": bool(p.get("enabled", True)),
                "notes": str(p.get("notes", "")),
            }
        )
    return [p for p in providers if p["name"] and p["urls"]]


def snapshot_now() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
