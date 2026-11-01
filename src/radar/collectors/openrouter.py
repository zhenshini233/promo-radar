"""OpenRouter 供应商发现：公开 /api/v1/models（免鉴权）。

基线存全部供应商目录：{vendor_slug: {models: 模型数, free: :free 模型数}}。
事件规则：某供应商的 :free 模型数从 0（或不存在）变为 >0 时产生事件——
新供应商上线就送免费模型，基本等于在拉新。纯付费供应商静默记录，
将来加免费模型时才触发。

口径：登记粒度是模型 ID 首段的实验室 slug（openai/、deepseek/...），
不是 OpenRouter 官网宣传的"400+ providers"（那是上游托管路由商，一家
实验室的模型可由多家托管）。~ 前缀的 latest 别名（~openai/...）归一化
后并入正式 slug，因此登记名单按品牌计数（2026-11 实测 67 slug → 59 品牌）。
"""

from __future__ import annotations

import json

from ..domain.models import RawItem
from ..infra.http import get_json
from .base import FetchContext, register_source
from .catalog import CatalogDiffSource

API = "https://openrouter.ai/api/v1/models"
PROVIDERS_API = "https://openrouter.ai/api/v1/providers"
STATE_KEY = "openrouter:vendors"
PROVIDERS_STATE_KEY = "openrouter:providers"


def _extract_vendors(data) -> dict[str, dict]:
    """{vendor_slug: {"models": 模型数, "free": :free 模型数}}，防御式解析。"""
    models = data.get("data") if isinstance(data, dict) else data
    if not isinstance(models, list):
        raise RuntimeError("openrouter: unexpected API schema (no model list)")
    out: dict[str, dict] = {}
    for m in models:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "")
        if "/" not in mid:
            continue
        vendor = mid.split("/", 1)[0]
        pricing = m.get("pricing") or {}
        is_free = mid.endswith(":free") or str(pricing.get("prompt", "1")) in ("0", "0.0")
        entry = out.setdefault(vendor, {"models": 0, "free": 0})
        entry["models"] += 1
        if is_free:
            entry["free"] += 1
    return out


def _extract_providers(data) -> dict[str, dict]:
    """{provider_slug: {"name": 显示名}}：上游托管商全量名单，防御式解析。"""
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise RuntimeError("openrouter: unexpected providers schema (no list)")
    out: dict[str, dict] = {}
    for p in rows:
        if not isinstance(p, dict):
            continue
        slug = str(p.get("slug") or "").strip()
        if slug:
            out[slug] = {"name": str(p.get("name") or slug)}
    return out


@register_source("openrouter")
class OpenRouterSource(CatalogDiffSource):
    state_key = STATE_KEY

    def fetch_catalog(self, ctx: FetchContext) -> dict:
        url = ctx.cfg.source("openrouter").get("url", API)
        return _extract_vendors(get_json(ctx.http, url))

    def fetch(self, ctx: FetchContext) -> list[RawItem]:
        items = super().fetch(ctx)
        # 全量上游托管商（DeepInfra/Together/Lambda...）：只用于覆盖登记，
        # 不参与 diff/事件；抓取失败不影响事件产出
        try:
            url = ctx.cfg.source("openrouter").get("providers_url", PROVIDERS_API)
            provs = _extract_providers(get_json(ctx.http, url))
            if provs:
                ctx.state.set_state(
                    PROVIDERS_STATE_KEY, json.dumps(provs, ensure_ascii=False, sort_keys=True)
                )
        except Exception:
            pass
        return items

    def diff_to_items(self, prev: dict, curr: dict) -> list[RawItem]:
        items = []
        for vendor, info in sorted(curr.items()):
            old = prev.get(vendor)
            was_free = old.get("free", 0) if isinstance(old, dict) else 0
            if was_free == 0 and info["free"] > 0:
                kind = "恢复免费" if vendor in prev else "新增"
                items.append(
                    RawItem(
                        source="openrouter",
                        title=f"[OpenRouter] {kind}免费模型供应商: {vendor}（{info['free']} 个 :free 模型）",
                        url=f"https://openrouter.ai/{vendor}",
                        provider=vendor,
                        evidence=(
                            f"{vendor} 在 OpenRouter 上有 {info['free']} 个 :free 模型"
                            f"（共 {info['models']} 个模型），可 0 成本调用。"
                            "新供应商挂免费模型通常在拉新，值得查看其官网注册活动。"
                        ),
                        key_override=f"openrouter:vendor:{vendor}",
                        force_keep=True,
                    )
                )
        return items
