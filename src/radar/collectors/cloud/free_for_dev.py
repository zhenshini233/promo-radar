"""free-for-dev 目录源：README.md → 结构化 RawItem。

源：ripienaar/free-for-dev（800+ 条免费开发者资源，按分类分节）。
只保留「云 / 托管 / 数据库 / 存储 / CI / 监控 / 邮件」分类，
其余（设计工具、代码编辑器、学习资源）不是可部署资源，直接跳过。
"""

from __future__ import annotations

import re

from ...domain.free_gate import is_free_resource
from ...domain.models import RawItem
from ...domain.normalize_units import enrich_item
from ...infra.http import get_text
from ..base import FetchContext, register_source

DEFAULT_URL = "https://cdn.jsdelivr.net/gh/ripienaar/free-for-dev@master/README.md"

_ITEM_RE = re.compile(
    r"^\s*[*-]\s+\[([^\]]+)\]\(([^)\s]+)\)\s*(?:[-–—:]\s*)?(.*)$"
)
_CAT_RE = re.compile(r"^##\s+(.+?)\s*$")

# 分类名 → (vertical, category)；只收录与「部署网站」相关的分类
_CATEGORY_MAP = (
    ("major cloud", ("cloud", "compute")),
    ("cloud management", ("cloud", "compute")),
    ("iaas", ("cloud", "compute")),
    ("paas", ("paas", "hosting")),
    ("baas", ("database", "database")),
    ("hosting", ("paas", "hosting")),
    ("low-code", ("paas", "hosting")),
    ("managed data", ("database", "database")),
    ("database", ("database", "database")),
    ("storage", ("storage", "storage")),
    ("media", ("storage", "storage")),
    ("ci and cd", ("devtool", "ci")),
    ("monitoring", ("devtool", "monitoring")),
    ("log management", ("devtool", "logging")),
    ("email", ("devtool", "email")),
    ("docker", ("devtool", "docker")),
    ("tunneling", ("cdn", "network")),
    ("dns", ("cdn", "dns")),
    ("domain", ("cdn", "domain")),
    ("cdn", ("cdn", "cdn")),
    ("generative ai", ("devtool", "ai_tools")),
    ("apis, data", ("devtool", "ai_tools")),
)


def _classify(title: str) -> tuple[str, str] | None:
    low = title.lower()
    for key, mapped in _CATEGORY_MAP:
        if key in low:
            return mapped
    return None


def parse_readme(text: str, limit: int = 800) -> list[RawItem]:
    category = ""
    items: list[RawItem] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        m = _CAT_RE.match(line)
        if m:
            category = m.group(1).strip()
            continue
        m = _ITEM_RE.match(line)
        if not m:
            continue
        classified = _classify(category)
        if classified is None:
            continue
        name, url, desc = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if not name or not url.startswith("http"):
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        vertical, cat = classified
        item = RawItem(
            source="free_for_dev",
            title=f"{name}: {desc[:80]}" if desc else name,
            url=url,
            provider=name,
            evidence=f"[{category}] {desc}"[:800],
            vertical=vertical,
            offer_type="free_tier",
            category=cat,
            force_keep=True,
            granularity="plan",
            key_basis=f"ffd:{key}",
        )
        item = enrich_item(item, default_type="free_tier")
        if is_free_resource(item):
            items.append(item)
        if len(items) >= limit:
            break
    return items


@register_source("free_for_dev")
class FreeForDevSource:
    name = "free_for_dev"
    full_snapshot = True

    def fetch(self, ctx: FetchContext) -> list[RawItem]:
        url = str(ctx.cfg.source("free_for_dev").get("url", DEFAULT_URL))
        raw = get_text(ctx.http, url, retries=1)
        items = parse_readme(raw)
        print(f"[free_for_dev] 解析出 {len(items)} 条可部署免费资源")
        return items