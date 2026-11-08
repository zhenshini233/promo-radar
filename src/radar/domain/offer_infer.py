"""AI 促销条目 → 统一 Offer 字段。

一条 AI 促销在统一模型里就是：
- vertical = ai_api
- category = ai
- granularity = activity（厂商级活动）
- offer_type 由命中标签推断（free_tier / trial / credits / promo_code / startup）
- limits.credit_usd 由金额文本解析
- eligibility.card_required 由绑卡线索写入
"""

from __future__ import annotations

import re
from dataclasses import replace

from .dedup import make_key
from .models import RawItem, ScoredItem

_CREDIT_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*([kK]?)")

_TYPE_BY_LABEL = {
    "free tier": "free_tier",
    "free trial": "trial",
    "免费试用/领取": "trial",
    "体验额度": "trial",
    "promo code": "promo_code",
    "兑换码": "promo_code",
    "grant/startup credits": "startup",
    "free api/key": "free_tier",
    "no credit card": "free_tier",
}


def _credit_usd(text: str) -> float | None:
    m = _CREDIT_RE.search(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    if m.group(2):
        value *= 1000
    return value if value > 0 else None


def ai_offer_type(matched: list[str], title: str = "") -> str:
    labels = set(matched or [])
    for label, offer_type in _TYPE_BY_LABEL.items():
        if label in labels:
            return offer_type
    low = (title or "").lower()
    if "free tier" in low:
        return "free_tier"
    if "free trial" in low or "试用" in low:
        return "trial"
    if "promo code" in low or "兑换码" in low:
        return "promo_code"
    return "credits"


def apply_ai_offer(item: RawItem, scored: ScoredItem | None = None) -> RawItem:
    """把一条已打分的 AI 条目转成统一 Offer 用的 RawItem。"""
    matched = list(scored.matched) if scored else []
    limits = dict(item.limits)
    credit = _credit_usd(f"{item.amount_hint or ''} {item.evidence or ''}")
    if credit and "credit_usd" not in limits:
        limits["credit_usd"] = credit
    eligibility = dict(item.eligibility)
    if item.card_required_hint is not None:
        eligibility.setdefault("card_required", bool(item.card_required_hint))
    return replace(
        item,
        # 已显式标记领域的来源（如国内社区 devtool）保留自己的领域
        vertical=item.vertical or "ai_api",
        category=item.category or ("ai" if item.vertical in ("", "ai_api") else ""),
        granularity="activity",
        offer_type=(
            item.offer_type
            if item.offer_type not in ("", "credits")
            else ai_offer_type(matched, item.title)
        ),
        limits=limits,
        eligibility=eligibility,
        key_basis=f"deal:{make_key(item)}",
    )