"""源注册表：import 触发各模块装饰器注册；顺序即运行顺序。"""

from __future__ import annotations

from .base import FetchContext, Source, build_sources, register_source
from . import (  # noqa: F401 - import 触发注册
    aicredits,
    linuxdo,
    hackernews,
    openrouter,
    modelsdev,
    mnfst,
    freetoken,
    litellm,
    watchlist,
    aa_providers,
    reddit,
)

__all__ = ["FetchContext", "Source", "build_sources", "register_source"]
