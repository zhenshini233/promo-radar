"""云资源采集源：配置化页面 + free-for-dev 目录。"""

from __future__ import annotations

from . import free_for_dev, pages  # noqa: F401 - import 触发注册

__all__ = ["free_for_dev", "pages"]