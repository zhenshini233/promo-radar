"""Reddit 源（v2 计划，暂未实现）。

调研结论：公开 .json/.rss 端点已对数据中心 IP 全面封锁（2023 API 政策后），
换 UA 无效。接入方案：
1. https://www.reddit.com/prefs/apps 注册 script 类型 app；
2. client_credentials 取只读 token（无需用户授权）；
3. GET https://oauth.reddit.com/r/LocalLLaMA/new?limit=100，
   字段 data.children[].data.{title, permalink, created_utc, url_overridden_by_dest}；
4. 免费额度对每日几次的监控频率足够。

当前 r/LocalLLaMA 的促销帖多数会转发进 HN，第一梯队已可覆盖。
"""

from __future__ import annotations
from .base import register_source


@register_source("reddit")
class RedditSource:

    def fetch(self, ctx):
        raise RuntimeError(
            "reddit source not implemented (v2): register an OAuth app first, see module docstring"
        )
