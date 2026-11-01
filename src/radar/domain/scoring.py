"""促销打分：中英关键词加权，附带金额/绑卡线索抽取。

设计取舍：
- 不收录裸词 "free"/"免费"（噪音太大），只收短语与结构化模式；
- "随优惠死掉的证据"（金额数字、绑卡要求）抽出来存进 Deal，便于后续复核；
- 规则 = 内置 DEFAULT_RULES + config.toml [[keywords]] 追加，全部正则、大小写不敏感。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import RawItem, ScoredItem, truncate


@dataclass(frozen=True)
class KeywordRule:
    pattern: str
    weight: float
    label: str


DEFAULT_RULES: list[KeywordRule] = [
    # 英文
    KeywordRule(r"free\s+credits?", 3.0, "free credits"),
    KeywordRule(r"\$\s?\d[\d,.]*\s*(in\s+)?(free\s+)?(trial\s+)?credits?", 3.0, "$X credits"),
    KeywordRule(r"sign[- ]?up\s+bonus", 3.0, "signup bonus"),
    KeywordRule(r"welcome\s+(credit|bonus|grant)", 3.0, "welcome credit"),
    KeywordRule(r"signup\s+credit", 3.0, "signup credit"),
    KeywordRule(r"free\s+tier", 1.5, "free tier"),
    KeywordRule(r"free\s+trial", 1.5, "free trial"),
    KeywordRule(r"free\s+(api|key)", 2.0, "free api/key"),
    KeywordRule(r"promo\s+code", 2.0, "promo code"),
    KeywordRule(r"no\s+credit\s+card", 2.0, "no credit card"),
    KeywordRule(r"try\s+\w+\s+for\s+free", 1.5, "try for free"),
    KeywordRule(r"hackathon\s+grant|startup\s+credits?", 2.0, "grant/startup credits"),
    # 中文
    KeywordRule(r"免费额度", 4.0, "免费额度"),
    KeywordRule(r"免费\s*(试用|体验|领取)", 2.5, "免费试用/领取"),
    KeywordRule(r"免费\s*(使用|送|赠)", 2.0, "免费使用/送"),
    KeywordRule(r"送\s*额度", 3.0, "送额度"),
    KeywordRule(r"额度\s*送", 3.0, "额度送"),
    KeywordRule(r"送.{0,10}(credit|额度|刀|美元)", 2.5, "送…额度/刀"),
    KeywordRule(r"注册.{0,6}送|赠送\s*\d+\s*(刀|美元|额度)", 3.0, "注册送/赠送额度"),
    KeywordRule(r"新人.{0,8}(送|领|福利|额度)|新用户.{0,8}(福利|额度|送|领)", 2.5, "新人福利"),
    KeywordRule(r"体验(卡|金|额度|plan)|token\s*plan", 2.0, "体验额度"),
    KeywordRule(r"兑换码", 2.0, "兑换码"),
    KeywordRule(r"绑卡", 2.0, "绑卡"),
    KeywordRule(r"白嫖", 1.5, "白嫖"),
    KeywordRule(r"羊毛", 1.0, "羊毛"),
    KeywordRule(r"公益站|打窝", 1.0, "公益站"),
    KeywordRule(r"留\s*id.{0,8}送", 2.5, "留ID送"),
    KeywordRule(r"额度", 0.5, "额度(弱)"),
]

_AMOUNT_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s*[kK]?")
_NO_CARD_RE = re.compile(r"(no|without|无需|免|不用)[\sa-z]{0,12}(credit\s*card|绑卡|信用卡|payment)")
_CARD_RE = re.compile(r"credit\s*card|绑卡|信用卡|payment\s+method|储蓄卡|debit\s+card")


def score_item(item: RawItem, extra_rules: list[KeywordRule] | None = None) -> ScoredItem:
    rules = DEFAULT_RULES if extra_rules is None else DEFAULT_RULES + list(extra_rules)
    text = f"{item.title}\n{item.evidence}"
    low = text.lower()

    matched: list[str] = []
    total = 0.0
    for rule in rules:
        if re.search(rule.pattern, low, re.IGNORECASE):
            total += rule.weight
            matched.append(rule.label)

    if item.amount_hint is None:
        m = _AMOUNT_RE.search(text)
        if m:
            item.amount_hint = m.group(0).strip()

    if item.card_required_hint is None:
        if _NO_CARD_RE.search(low):
            item.card_required_hint = False
        elif _CARD_RE.search(low):
            item.card_required_hint = True

    item.evidence = truncate(item.evidence) if item.evidence else ""
    return ScoredItem(item=item, score=total, matched=matched)
