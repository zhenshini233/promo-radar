"""去重：URL 规范化 → 稳定 dedup key → 跨源标题模糊匹配。"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Deal, RawItem

# 追踪参数与邀请参数：同一活动页不同人分享 → 归一为同一 key
_DROP_PARAMS = {"ref", "aff", "invite", "invite_code", "share", "share_token"}
_DROP_PREFIXES = ("utm_", "spm_", "fbclid", "gclid")
_FUZZY_THRESHOLD = 0.80
_AMOUNT_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*([kK]?)")


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    host = parts.netloc.lower()
    # www. 归一（少量误伤可接受，换取转发链接合并）
    if host.startswith("www."):
        host = host[4:]
    kept = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        lk = k.lower()
        if lk in _DROP_PARAMS or any(lk.startswith(p) for p in _DROP_PREFIXES):
            continue
        kept.append((k, v))
    query = urlencode(kept)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, query, ""))


def norm_title(title: str) -> str:
    return re.sub(r"[\s\W_]+", "", title.lower(), flags=re.UNICODE)


def title_similarity(a: str, b: str) -> float:
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # 一方是另一方的前缀（转发截断标题）视为高度相似
    if na.startswith(nb) or nb.startswith(na):
        return 0.95
    return SequenceMatcher(None, na, nb).ratio()


def make_key(item: RawItem) -> str:
    """稳定 key：key_override > 规范化 URL > source+标题 hash。"""
    basis = item.key_override or canonical_url(item.url) if item.url else None
    if not basis:
        basis = f"{item.source}:{norm_title(item.title)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _amounts(deal_or_item_amount: str | None, evidence: str = "") -> set[float]:
    """从 amount_hint / evidence 提取美元数字（'5k'→5000），无则空集。"""
    text = f"{deal_or_item_amount or ''} {evidence}"
    out: set[float] = set()
    for m in _AMOUNT_RE.finditer(text):
        val = float(m.group(1).replace(",", ""))
        if m.group(2).lower() == "k":
            val *= 1000
        out.add(val)
    return out


def amounts_compatible(a: set[float], b: set[float]) -> bool:
    """双方都有金额且对不上（差>10%）视为不同活动；有一方为空则不否决。"""
    if not a or not b:
        return True
    return any(abs(x - y) <= 0.1 * max(x, y) for x in a for y in b)


def find_fuzzy_match(item: RawItem, candidates: list[Deal]) -> Deal | None:
    """在近两周的已有 deal 中找同一活动的转发/重复帖。

    双重金额护栏（防"同服务商不同档位"误合并，如 Google for Startups 的
    Scale Tier vs AI Track）：hint/evidence 金额对不上不合并，标题内金额
    对不上也不合并——目录站常给同一服务商的不同档位写相同的总述金额。
    """
    best: tuple[float, Deal] | None = None
    for deal in candidates:
        if deal.status == "expired":
            continue
        if item.provider and deal.provider and item.provider.lower() != deal.provider.lower():
            continue
        if not amounts_compatible(
            _amounts(item.amount_hint, item.evidence), _amounts(deal.amount_hint, deal.evidence)
        ):
            continue
        if not amounts_compatible(_amounts(item.title), _amounts(deal.title)):
            continue
        ratio = title_similarity(item.title, deal.title)
        if ratio >= _FUZZY_THRESHOLD and (best is None or ratio > best[0]):
            best = (ratio, deal)
    return best[1] if best else None
