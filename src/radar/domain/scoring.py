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

# v10：云资源规则包。与 AI 规则分开，避免「免费额度」等词把云条目打成高分、
# 也避免 AI 的「赠送额度」规则把普通云套餐误收。
CLOUD_RULES: list[KeywordRule] = [
    KeywordRule(r"always[\s-]?free|永久免费|永久额度|永久套餐", 5.0, "永久免费"),
    KeywordRule(r"free\s+(tier|plan|forever)|免费(层|套餐|计划|版)", 3.5, "免费层"),
    KeywordRule(r"free\s+credits?|赠金|试用金|免费额度", 3.5, "免费额度"),
    KeywordRule(r"no\s+credit\s+card|无需(信用)?卡|免绑卡|不需要信用卡", 3.0, "免绑卡"),
    KeywordRule(r"\$\s?\d[\d,.]*\s*(in\s+)?(free\s+)?credits?", 3.0, "$X 赠金"),
    KeywordRule(r"student|学生认证|\.edu", 2.5, "学生"),
    KeywordRule(r"startup|创业|加速器", 2.0, "创业计划"),
    KeywordRule(r"open[\s-]?source|开源项目", 1.5, "开源计划"),
    KeywordRule(r"docker|git\s*push|一键部署|deploy", 1.5, "可部署"),
    KeywordRule(r"serverless|edge|边缘", 1.0, "Serverless"),
    KeywordRule(r"object\s+storage|bucket|对象存储|图床", 1.5, "对象存储"),
    KeywordRule(r"postgres|mysql|redis|database|数据库", 1.2, "数据库"),
    KeywordRule(r"trial|试用|体验", 1.0, "试用"),
    KeywordRule(r"lifetime|终身|买断", 2.0, "终身"),
    KeywordRule(r"free", 0.5, "free(弱)"),
]

VPS_RULES: list[KeywordRule] = [
    KeywordRule(r"\$\s?\d+[\d,.]*\s*/?\s*(yr|year|年)|年付", 3.5, "年付低价"),
    KeywordRule(r"lifetime|终身|传家宝", 2.5, "终身/传家宝"),
    KeywordRule(r"restock|back\s+in\s+stock|补货|补仓", 3.0, "补货"),
    KeywordRule(r"sold\s*out|out\s+of\s+stock|售罄|无货", -2.0, "售罄"),
    KeywordRule(r"KVM|NVMe|RAID", 1.5, "KVM/NVMe"),
    KeywordRule(r"unmetered|unlimited|不限流量|无限流量", 1.5, "不限流量"),
    KeywordRule(r"CN2|GIA|9929|CMIN2|优化线路", 1.5, "优化线路"),
    KeywordRule(r"dedicated|独服|独立服务器", 1.5, "独立服务器"),
    KeywordRule(r"black\s*friday|cyber\s*monday|黑五|网一", 2.5, "大促"),
    KeywordRule(r"free\s+trial|免费试用", 1.5, "免费试用"),
    KeywordRule(r"free", 0.5, "free(弱)"),
]


def rules_for(vertical: str) -> list[KeywordRule]:
    """按垂直领域选择规则包；未知领域回落 AI 规则（保持旧行为）。"""
    if vertical == "vps":
        return VPS_RULES
    if vertical in ("cloud", "paas", "storage", "database", "cdn"):
        return CLOUD_RULES
    return DEFAULT_RULES


def score_item(
    item: RawItem,
    extra_rules: list[KeywordRule] | None = None,
    vertical: str | None = None,
) -> ScoredItem:
    base = rules_for(vertical or item.vertical)
    rules = base if extra_rules is None else base + list(extra_rules)
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
