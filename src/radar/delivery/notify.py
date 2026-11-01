"""Telegram 推送：纯 sendMessage，无 SDK 依赖。

- 无 token/chat_id 或 enabled=false → 静默跳过（推送失败不影响 run 本身）；
- 消息 >4096 自动拆分；
- 不用 parse_mode，规避 Markdown/HTML 转义问题；
- 推送频率极低（每次 run 至多一次），独立建短生命周期 client，与抓取共用代理配置。
"""

from __future__ import annotations

import httpx

from ..domain.models import Deal
from ..infra.config import RadarConfig

MAX_LEN = 3800  # 留出余量，Telegram 上限 4096


def _format_deals(deals: list[Deal]) -> list[str]:
    messages: list[str] = []
    buf: list[str] = [f"promo-radar：发现 {len(deals)} 条新活动", ""]
    for i, deal in enumerate(deals, 1):
        card = (
            " | 需绑卡"
            if deal.card_required_hint is True
            else " | 无需绑卡"
            if deal.card_required_hint is False
            else ""
        )
        block = "\n".join(
            [
                f"{i}. {deal.title}",
                (deal.provider or "未知服务商")
                + (f" | {deal.amount_hint}" if deal.amount_hint else "")
                + card,
                deal.url or "(无链接)",
                f"来源 {deal.source}"
                + (f" / 也见于 {'、'.join(deal.also_seen_in)}" if deal.also_seen_in else "")
                + f" · score {deal.score:g}",
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


def push_new_deals(cfg: RadarConfig, deals: list[Deal]) -> tuple[bool, str]:
    if not deals:
        return True, "no new deals"
    if not cfg.telegram_enabled:
        return False, "telegram disabled or not configured"

    ok, errors = True, []
    with httpx.Client(timeout=30.0, proxy=cfg.proxy_url or None, trust_env=True) as client:
        for msg in _format_deals(deals):
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
