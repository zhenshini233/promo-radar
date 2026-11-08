"""Telegram 推送：纯 sendMessage，无 SDK 依赖。

- 无 token/chat_id 或 enabled=false → 静默跳过（推送失败不影响 run 本身）；
- 消息 >4096 自动拆分；
- 不用 parse_mode，规避 Markdown/HTML 转义问题；
- v10 起统一推送 Offer（AI 与云同一个来源）。
"""

from __future__ import annotations

import httpx

from ..domain.models import Offer
from ..infra.config import RadarConfig
from ..infra.proxy import effective_proxy

MAX_LEN = 3800  # 留出余量，Telegram 上限 4096


def _format_offers(offers: list[Offer]) -> list[str]:
    messages: list[str] = []
    buf: list[str] = [f"promo-radar：发现 {len(offers)} 条新资源", ""]
    for i, offer in enumerate(offers, 1):
        card = offer.eligibility.get("card_required")
        card_text = "需绑卡" if card is True else ("免绑卡" if card is False else "")
        meta = " | ".join(
            x for x in [offer.provider or "未知厂商", offer.offer_type, card_text] if x
        )
        block = "\n".join(
            [
                f"{i}. {offer.title}",
                meta + (f" | {offer.amount_hint}" if offer.amount_hint else ""),
                offer.url or "(无链接)",
                f"领域 {offer.vertical} · 来源 {offer.source} · 证据 {offer.evidence_count} 条",
                "",
            ]
        )
        if sum(len(b) for b in buf) + len(block) > MAX_LEN:
            messages.append("\n".join(buf))
            buf = [block]
        else:
            buf.append(block)
    if any(b.strip() for b in buf):
        messages.append("\n".join(buf))
    return messages


def push_new_offers(cfg: RadarConfig, offers: list[Offer]) -> tuple[bool, str]:
    if not offers:
        return True, "no new offers"
    if not cfg.telegram_enabled:
        return False, "telegram disabled or not configured"

    ok, errors = True, []
    proxy = effective_proxy(
        cfg.proxy_url,
        auto_detect=cfg.proxy_auto_detect,
        timeout=cfg.proxy_detect_timeout,
    )
    with httpx.Client(timeout=30.0, proxy=proxy or None, trust_env=True) as client:
        for msg in _format_offers(offers):
            try:
                resp = client.post(
                    f"https://api.telegram.org/bot{cfg.telegram_token}/sendMessage",
                    json={
                        "chat_id": cfg.telegram_chat_id,
                        "text": msg,
                        "disable_web_page_preview": True,
                    },
                )
                resp.raise_for_status()
            except Exception as e:  # noqa: BLE001
                ok = False
                errors.append(f"{type(e).__name__}: {e}")
    return ok, ("; ".join(errors) if errors else "sent")