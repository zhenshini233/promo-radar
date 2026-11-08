"""国内社区 / 资讯 RSS：按“免费、试用、优惠、送”等关键词筛选资源线索。

与 linuxdo 的区别：这里只做“发现”，不假设帖子一定是促销；
条目仍走评分与阈值过滤，避免把普通资讯收进目录。
"""

from __future__ import annotations

import feedparser

from ..domain.models import RawItem
from ..domain.normalize_units import enrich_item
from ..infra.http import get_text
from .base import FetchContext, register_source

DEFAULT_FEEDS = [
    "https://juejin.cn/rss",
    "https://www.oschina.net/news/rss",
    "https://feed.cnblogs.com/blog/sitehome/rss",
]
# 只要“可领取”的组合信号；单字“免费/送”噪音太大
KEYWORDS = (
    "免费额度", "免费试用", "免费领取", "免费服务器", "免费云",
    "试用", "领取", "0元", "代金券", "优惠券", "羊毛", "白嫖", "赠送", "限时免费",
    "优惠", "补货", "补仓", "促销", "特价", "年付", "闪购",
)


@register_source("cn_rss")
class CnRssSource:
    name = "cn_rss"

    def fetch(self, ctx: FetchContext) -> list[RawItem]:
        feeds = ctx.cfg.source("cn_rss").get("feeds", DEFAULT_FEEDS)
        items: list[RawItem] = []
        for feed_url in feeds:
            try:
                raw = get_text(
                    ctx.http, str(feed_url), retries=0,
                    timeout=ctx.cfg.general.http_timeout,
                )
                parsed = feedparser.parse(raw)
            except Exception as e:  # noqa: BLE001 - 单个 feed 失败不影响其他
                print(f"[cn_rss] {feed_url} 抓取失败: {type(e).__name__}: {e}")
                continue
            # VPS 测评站产出的是「低价/补货」而不是免费资源，单独归到 vps 领域
            is_vps = "vps" in str(feed_url).lower()
            vertical = "vps" if is_vps else "devtool"
            category = "vps" if is_vps else "community"
            default_type = "promo_code" if is_vps else "free_tier"
            kept = 0
            for entry in parsed.entries[:40]:
                title = str(entry.get("title", "")).strip()
                summary = str(entry.get("summary", entry.get("description", ""))).strip()
                link = str(entry.get("link", "")).strip()
                text = f"{title}\n{summary}"
                if not title or not link:
                    continue
                if not any(k in text for k in KEYWORDS):
                    continue
                item = RawItem(
                    source="cn_rss",
                    title=title,
                    url=link,
                    provider=None,
                    evidence=summary[:800],
                    vertical=vertical,
                    category=category,
                    offer_type=default_type,
                    granularity="activity",
                    force_keep=is_vps,
                )
                items.append(enrich_item(item, default_type=default_type))
                kept += 1
            print(f"[cn_rss] {feed_url} 命中 {kept} 条")
        return items