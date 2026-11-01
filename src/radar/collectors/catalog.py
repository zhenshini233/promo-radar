"""目录快照 diff 基类：models.dev / mnfst / freetoken / litellm 共用。

模式：每轮抓取目录快照（可 JSON 序列化的 dict），与 state 里的上一份对比，
diff 出"新增/变化"事件。首轮只建基线不产生事件（避免存量倾倒）。

子类实现两个方法：
- fetch_catalog(ctx) -> dict        # 本次快照
- diff_to_items(prev, curr) -> list[RawItem]   # 对比 → 事件
"""

from __future__ import annotations

import json

from ..domain.models import RawItem
from .base import FetchContext


class CatalogDiffSource:
    state_key: str = ""  # 子类覆盖
    name: str = ""

    def fetch(self, ctx: FetchContext) -> list[RawItem]:
        curr = self.fetch_catalog(ctx)
        prev_raw = ctx.state.get_state(self.state_key)
        if not prev_raw:
            ctx.state.set_state(
                self.state_key, json.dumps(curr, ensure_ascii=False, sort_keys=True)
            )
            return []  # 首轮建基线
        prev = json.loads(prev_raw)
        items = self.diff_to_items(prev, curr)
        ctx.state.set_state(
            self.state_key, json.dumps(curr, ensure_ascii=False, sort_keys=True)
        )
        return items

    def fetch_catalog(self, ctx: FetchContext) -> dict:
        raise NotImplementedError

    def diff_to_items(self, prev: dict, curr: dict) -> list[RawItem]:
        raise NotImplementedError
