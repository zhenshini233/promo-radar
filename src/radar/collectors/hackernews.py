"""Hacker News（Algolia API，免鉴权）。

Algolia 端点不支持 OR 组合查询，因此每个 query 单独请求后按 objectID 合并；
用 state 表存上次成功抓取时间做增量（带 1 小时重叠余量防漏）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..infra.http import get_json, strip_html
from ..domain.models import RawItem, iso, parse_iso, utcnow
from .base import register_source

API = "https://hn.algolia.com/api/v1/search_by_date"
DEFAULT_QUERIES = ['"free credits"']
STATE_KEY = "hn:last_run"


def _parse_hits(data: dict) -> list[RawItem]:
    items = []
    for hit in data.get("hits", []):
        hid = str(hit.get("objectID") or "")
        title = (hit.get("title") or "").strip()
        if not hid or not title:
            continue
        hn_link = f"https://news.ycombinator.com/item?id={hid}"
        article = (hit.get("url") or "").strip()
        story_text = strip_html(hit.get("story_text") or "")
        created_i = int(hit.get("created_at_i") or 0)
        items.append(
            RawItem(
                source="hackernews",
                title=title,
                url=article or hn_link,
                evidence=story_text[:300],
                published_at=(
                    datetime.fromtimestamp(created_i, tz=timezone.utc) if created_i else None
                ),
                key_override=f"hn:{hid}",
            )
        )
    return items


@register_source("hackernews")
class HackerNewsSource:

    def fetch(self, ctx) -> list[RawItem]:
        conf = ctx.cfg.source("hackernews")
        queries = conf.get("queries") or DEFAULT_QUERIES
        lookback_hours = int(conf.get("lookback_hours", 36))

        last = ctx.state.get_state(STATE_KEY)
        if last:
            since = int(parse_iso(last).timestamp()) - 3600
        else:
            since = int((utcnow() - timedelta(hours=lookback_hours)).timestamp())

        by_id: dict[str, RawItem] = {}
        for query in queries:
            qs = urlencode(
                {
                    "query": query,
                    "tags": "story",
                    "hitsPerPage": 50,
                    "numericFilters": f"created_at_i>{since}",
                }
            )
            for item in _parse_hits(get_json(ctx.http, f"{API}?{qs}")):
                hid = str(item.key_override).split(":", 1)[1]
                by_id.setdefault(hid, item)

        ctx.state.set_state(STATE_KEY, iso(utcnow()))
        return list(by_id.values())
