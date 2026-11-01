"""AIPMAndy/FreeToken（148 star）：中文"免费 AI API 额度大全"，providers.json 台账。

字段（防御式解析）：名称/分类/官方文档/核验日期。新条目 → 事件。
"""

from __future__ import annotations

from ..domain.models import RawItem
from ..infra.http import get_json
from .base import FetchContext, register_source
from .catalog import CatalogDiffSource

DEFAULT_URL = "https://raw.githubusercontent.com/AIPMAndy/FreeToken/main/data/providers.json"


def _extract_providers(data) -> dict[str, dict]:
    """{名称: {"doc": 文档, "verified": 核验日期}}；兼容 list 或 {"providers": [...]}。"""
    providers = data.get("providers") if isinstance(data, dict) else data
    if not isinstance(providers, list):
        raise RuntimeError("freetoken: unexpected schema (no provider list)")
    out: dict[str, dict] = {}
    for p in providers:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or p.get("platform") or p.get("id") or "").strip()
        if not name:
            continue
        out[name] = {
            "doc": str(p.get("doc") or p.get("url") or p.get("official") or ""),
            "verified": str(p.get("verified") or p.get("verified_date") or p.get("date") or ""),
        }
    return out


@register_source("freetoken")
class FreeTokenSource(CatalogDiffSource):
    state_key = "freetoken:providers"

    def fetch_catalog(self, ctx: FetchContext) -> dict:
        url = ctx.cfg.source("freetoken").get("url", DEFAULT_URL)
        return _extract_providers(get_json(ctx.http, url))

    def diff_to_items(self, prev: dict, curr: dict) -> list[RawItem]:
        items = []
        for name, info in sorted(curr.items()):
            if name in prev:
                continue
            items.append(
                RawItem(
                    source="freetoken",
                    title=f"[FreeToken] 中文清单新增: {name}",
                    url=info["doc"] or "https://github.com/AIPMAndy/FreeToken",
                    provider=name,
                    evidence=(
                        f"FreeToken（中文免费 AI API 额度大全）新增条目 {name}"
                        + (f"，核验日期 {info['verified']}" if info["verified"] else "")
                        + "。建议查看其注册活动并收编 watchlist。"
                    ),
                    key_override=f"freetoken:provider:{name}",
                    force_keep=True,
                )
            )
        return items
