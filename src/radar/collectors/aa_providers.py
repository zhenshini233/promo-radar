"""Artificial Analysis 官方 Data API（免费 key）——"新模型厂商上榜"事件源。

真实 schema（实测 2026-11）：GET /api/v2/data/llms/models 返回
{"data": [{id, name, slug, model_creator: {name, slug}, ...}]}，模型对象
没有 providers 数组，因此发现信号锚定 model_creator：新 AI 实验室进入
榜单 → 事件（新厂商首发通常伴随免费额度与拉新）。

API 细见 https://artificialanalysis.ai/api-reference ；默认关闭，配 key 启用
（config api_key 或环境变量 RADAR_AA_KEY）。AA 对部分代理节点 TLS 不稳，
建议在 [proxy] bypass 名单中直连。
"""

from __future__ import annotations

import os

from ..domain.models import RawItem
from .base import FetchContext, register_source
from .catalog import CatalogDiffSource

STATE_KEY = "aa:creators"
DEFAULT_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"


def _extract_creators(data) -> dict[str, dict]:
    """{creator_slug: {"name": 名称, "models": 模型数}}，防御式解析。"""
    models = data.get("data") if isinstance(data, dict) else data
    if not isinstance(models, list):
        raise RuntimeError("aa_providers: unexpected API schema (no model list)")
    out: dict[str, dict] = {}
    for m in models:
        if not isinstance(m, dict):
            continue
        creator = m.get("model_creator") or {}
        slug = str(creator.get("slug") or "").strip()
        if not slug:
            continue
        entry = out.setdefault(slug, {"name": str(creator.get("name") or slug), "models": 0})
        entry["models"] += 1
    return out


@register_source("aa_providers")
class AAProvidersSource(CatalogDiffSource):
    state_key = STATE_KEY

    def fetch_catalog(self, ctx: FetchContext) -> dict:
        conf = ctx.cfg.source("aa_providers")
        key = str(conf.get("api_key", "") or "").strip() or os.environ.get("RADAR_AA_KEY", "")
        if not key:
            raise RuntimeError("aa_providers: missing api key (config api_key or RADAR_AA_KEY)")
        url = str(conf.get("url", DEFAULT_URL))
        resp = ctx.http.get(url, headers={"x-api-key": key})
        resp.raise_for_status()
        return _extract_creators(resp.json())

    def diff_to_items(self, prev: dict, curr: dict) -> list[RawItem]:
        items = []
        for slug, info in sorted(curr.items()):
            if slug in prev:
                continue
            items.append(
                RawItem(
                    source="aa_providers",
                    title=f"[ArtificialAnalysis] 新模型厂商上榜: {info['name']}（{info['models']} 个模型）",
                    url="https://artificialanalysis.ai/models",
                    provider=info["name"],
                    evidence=(
                        f"{info['name']}（{slug}）首次进入 Artificial Analysis 榜单，"
                        f"当前 {info['models']} 个模型。新厂商上榜通常伴随发布与拉新活动，"
                        "建议查看其官网注册赠送并收编 watchlist。"
                    ),
                    key_override=f"aa:creator:{slug}",
                    force_keep=True,
                )
            )
        return items
