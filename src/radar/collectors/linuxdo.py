"""linux.do（Discourse）：版块/标签 RSS。

注意：大陆网络对该域 DNS 污染，本地运行需在 config.toml [proxy] 配置代理；
GitHub Actions 等海外环境直连即可。
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone

import feedparser

from ..infra.http import get_text, strip_html
from ..domain.models import RawItem
from .base import register_source

# 剔除 Discourse RSS 摘要尾部的"N 个帖子 - M 位参与者 / 阅读完整话题"
_BOILER_RE = re.compile(r"\s*\d+\s*个帖子\s*-\s*\d+\s*位参与者.*$", re.DOTALL)


def parse_feed(xml_text: str) -> list[RawItem]:
    feed = feedparser.parse(xml_text)
    items: list[RawItem] = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = strip_html(entry.get("summary") or "")
        summary = _BOILER_RE.sub("", summary).strip()
        published = None
        st = entry.get("published_parsed")
        if st:
            published = datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
        items.append(
            RawItem(
                source="linuxdo",
                title=title,
                url=link,
                evidence=summary[:300],
                published_at=published,
            )
        )
    return items


@register_source("linuxdo")
class LinuxDoSource:

    def fetch(self, ctx) -> list[RawItem]:
        feeds = ctx.cfg.source("linuxdo").get("feeds", [])
        if not feeds:
            raise RuntimeError("linuxdo: no feeds configured")
        items: list[RawItem] = []
        for feed_url in feeds:
            items.extend(parse_feed(get_text(ctx.http, feed_url)))
        return items
