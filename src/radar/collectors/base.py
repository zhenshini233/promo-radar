"""Source 协议、抓取上下文与装饰器注册表（学 pyplugs 模式）。

加源方法：
1. 在本包新建文件，实现 fetch(ctx) -> list[RawItem]，类上加 @register_source("名字")；
2. 在本包 __init__.py import 该模块（触发注册）；
3. 在 config.toml [sources.名字] 设 enabled = true。

外部扩展预留：将来第三方源可通过 pyproject entry_points 声明加载，
当前内置源全部走本注册表。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import httpx

    from ..domain.models import RawItem
    from ..infra.config import RadarConfig
    from ..storage.repository import StateStore

_REGISTRY: dict[str, type] = {}
_ORDER: list[str] = []


def register_source(name: str):
    """类装饰器：把 Source 实现登记进注册表（保持声明顺序）。"""

    def deco(cls):
        if name in _REGISTRY:
            raise ValueError(f"source {name!r} 已注册")
        cls.name = name
        _REGISTRY[name] = cls
        _ORDER.append(name)
        return cls

    return deco


def build_sources(cfg: "RadarConfig") -> list:
    """按注册顺序实例化所有 enabled 的源。"""
    return [_REGISTRY[name]() for name in _ORDER if cfg.source_enabled(name)]


def registered_names() -> list[str]:
    return list(_ORDER)


@dataclass
class FetchContext:
    """一次运行的抓取上下文：配置 + 共享 HTTP client + 状态存储（协议）。"""

    cfg: "RadarConfig"
    http: "httpx.Client"
    state: "StateStore"


@runtime_checkable
class Source(Protocol):
    name: str

    def fetch(self, ctx: FetchContext) -> list["RawItem"]: ...
