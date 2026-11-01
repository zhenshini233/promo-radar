"""aicredits.dev 目录站：/llms-full.txt 全量数据库（免鉴权，结构化 Markdown）。

目录站内容人工筛选过，条目默认 force_keep（打分仍用于排序与展示）。
"""

from __future__ import annotations

import re

from ..infra.http import get_text
from ..domain.models import RawItem
from .base import register_source

DEFAULT_URL = "https://aicredits.dev/llms-full.txt"

_SUBMISSION_RE = re.compile(r"^##\s+Submission\s+(\d+):\s*(.+?)\s*$", re.MULTILINE)
_FIELD_RE = re.compile(
    r"^-\s*(Category|Source Link|Amount|Difficulty|Expires At):\s*(.*?)\s*$", re.MULTILINE
)
_DESCRIPTION_RE = re.compile(r"###\s*Description\s*\n(.*?)(?=\n##\s|\Z)", re.DOTALL)
_PROVIDER_BRACKET_RE = re.compile(r"^\[([^\]\-]+)\]")
_PROVIDER_SPLIT_RE = re.compile(r"\s+[—–-]\s+|\s*:\s+")


def _guess_provider(title: str) -> str | None:
    m = _PROVIDER_BRACKET_RE.match(title)
    if m:
        return m.group(1).strip()
    if _PROVIDER_SPLIT_RE.search(title):
        first = _PROVIDER_SPLIT_RE.split(title, maxsplit=1)[0].strip()
        if 0 < len(first) <= 40:
            return first
    # 无分隔符时截掉金额尾巴："Leonardo AI $5 Free API Credits" → "Leonardo AI"
    if " $" in title:
        head = title.split(" $", 1)[0].strip()
        if 0 < len(head) <= 40:
            return head
    return None


def parse_llms_full(text: str) -> list[RawItem]:
    """解析 llms-full.txt：按 `## Submission N: Title` 分段，抽取字段与描述。"""
    items: list[RawItem] = []
    heads = list(_SUBMISSION_RE.finditer(text))
    for i, head in enumerate(heads):
        sub_id, title = head.group(1), head.group(2).strip()
        seg = text[head.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        fields = dict(_FIELD_RE.findall(seg))
        desc = ""
        dm = _DESCRIPTION_RE.search(seg)
        if dm:
            desc = re.sub(r"\s+", " ", dm.group(1)).strip().rstrip(" -")
        amount = fields.get("Amount", "").strip()
        items.append(
            RawItem(
                source="aicredits",
                title=title,
                url=fields.get("Source Link", "").strip(),
                provider=_guess_provider(title),
                amount_hint=amount if amount and amount.upper() != "N/A" else None,
                evidence=desc[:300],
                key_override=f"aicredits:{sub_id}",
                force_keep=True,
            )
        )
    return items


@register_source("aicredits")
class AICreditsSource:

    def fetch(self, ctx) -> list[RawItem]:
        url = ctx.cfg.source("aicredits").get("url", DEFAULT_URL)
        text = get_text(ctx.http, url)
        items = parse_llms_full(text)
        # 域名自动收编：目录里出现没监控过的服务商域名 → 追加进 providers.toml
        try:
            from .watchlist import auto_enroll_from_items

            auto_enroll_from_items(ctx, items)
        except Exception as e:  # noqa: BLE001 - 收编失败不影响本源产出
            print(f"[aicredits] 自动收编失败: {e}")
        return items
