"""mnfst/awesome-free-llm-apis（11.9k star）的 data.json：供应商+免费模型清单。

机器可读数据由仓库每日刷新；raw.githubusercontent 大陆直连不通（DNS 污染），
依赖全局代理或 Actions 网络。
"""

from __future__ import annotations

from ..domain.models import RawItem
from ..infra.http import get_json
from .base import FetchContext, register_source
from .catalog import CatalogDiffSource

DEFAULT_URL = (
    "https://raw.githubusercontent.com/mnfst/awesome-free-llm-apis/main/data.json"
)


def _extract_providers(data) -> dict[str, dict]:
    """{provider_name: {"models": 模型数, "category": 类别}}，防御式解析。"""
    providers = data.get("providers") if isinstance(data, dict) else data
    if not isinstance(providers, list):
        raise RuntimeError("mnfst: unexpected schema (no provider list)")
    out: dict[str, dict] = {}
    for p in providers:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        models = p.get("models") or []
        out[str(p["name"])] = {
            "models": len(models) if isinstance(models, list) else 0,
            "category": str(p.get("category") or ""),
        }
    return out


@register_source("mnfst")
class MnfstSource(CatalogDiffSource):
    state_key = "mnfst:providers"

    def fetch_catalog(self, ctx: FetchContext) -> dict:
        url = ctx.cfg.source("mnfst").get("url", DEFAULT_URL)
        return _extract_providers(get_json(ctx.http, url))

    def diff_to_items(self, prev: dict, curr: dict) -> list[RawItem]:
        items = []
        for name, info in sorted(curr.items()):
            if name in prev:
                continue
            items.append(
                RawItem(
                    source="mnfst",
                    title=f"[free-llm-apis] 供应商清单新增: {name}（{info['models']} 个免费模型）",
                    url="https://github.com/mnfst/awesome-free-llm-apis",
                    provider=name,
                    evidence=(
                        f"awesome-free-llm-apis 清单（{info['category'] or 'uncategorized'}）"
                        f"新增 {name}，标注 {info['models']} 个免费模型。建议进官网确认注册活动并收编 watchlist。"
                    ),
                    key_override=f"mnfst:provider:{name}",
                    force_keep=True,
                )
            )
        return items
