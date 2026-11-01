"""models.dev 供应商名录（sst/models.dev，7.5k star，MIT）：api.json 免 key。

新 provider 出现在名录 → 事件；同时其 doc/baseUrl 可作为 watchlist 收编线索。
"""

from __future__ import annotations

from ..domain.models import RawItem
from ..infra.http import get_json
from .base import FetchContext, register_source
from .catalog import CatalogDiffSource

DEFAULT_URL = "https://models.dev/api.json"


def _extract_providers(data) -> dict[str, dict]:
    """{provider_id: {"label": 名称, "models": 模型数, "doc": 文档链接}}，防御式解析。"""
    if not isinstance(data, dict):
        raise RuntimeError("modelsdev: unexpected schema (not a dict)")
    out: dict[str, dict] = {}
    for pid, info in data.items():
        if not isinstance(info, dict):
            continue
        models = info.get("models") or {}
        out[str(pid)] = {
            "label": str(info.get("name") or pid),
            "models": len(models) if isinstance(models, dict) else 0,
            "doc": str(info.get("doc") or ""),
        }
    return out


@register_source("modelsdev")
class ModelsDevSource(CatalogDiffSource):
    state_key = "modelsdev:providers"

    def fetch_catalog(self, ctx: FetchContext) -> dict:
        url = ctx.cfg.source("modelsdev").get("url", DEFAULT_URL)
        return _extract_providers(get_json(ctx.http, url))

    def diff_to_items(self, prev: dict, curr: dict) -> list[RawItem]:
        items = []
        for pid, info in sorted(curr.items()):
            if pid in prev:
                continue
            items.append(
                RawItem(
                    source="modelsdev",
                    title=f"[models.dev] 新供应商入库: {info['label']}（{info['models']} 个模型）",
                    url=info["doc"] or f"https://models.dev/#{pid}",
                    provider=info["label"],
                    evidence=(
                        f"models.dev 名录出现新 provider {pid}（{info['models']} 个模型）。"
                        "新进名录的供应商通常在拉新期，建议查看其官网注册活动并收编 watchlist。"
                    ),
                    key_override=f"modelsdev:provider:{pid}",
                    force_keep=True,
                )
            )
        return items
