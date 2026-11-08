"""免费门槛：判断一条 RawItem 是否属于「可免费获取、可用于部署」。

与打分分离：分数决定排序，门槛决定去留。这样即使标题没写 free，
只要证据里有 free tier / always free / 赠金，也能被正确保留。
"""

from __future__ import annotations

import re

from .models import RawItem

FREE_TYPES = {"always_free", "free_tier", "student", "startup", "oss", "trial"}
# 明确不是「可领资源」的付费项目：实习、奖学金、研究基金、投资计划、会议
_PAID_PROGRAM_RE = re.compile(
    r"internship|scholarship|fellowship|research\s+grant|investment|funding\s+round"
    r"|conference|ticket|实习|奖学金|研究基金|投资|融资|会议",
    re.IGNORECASE,
)
_FREE_TEXT_RE = re.compile(
    r"free|免费|credit|额度|赠金|trial|试用|always[\s-]?free", re.IGNORECASE
)


def is_paid_program(item: RawItem) -> bool:
    """付费项目/活动：没有任何免费语义，且命中了项目类词。"""
    text = f"{item.title}\n{item.evidence}"
    return bool(_PAID_PROGRAM_RE.search(text)) and not _FREE_TEXT_RE.search(text)


def is_free_resource(item: RawItem) -> bool:
    """硬门槛：满足任意一项即视为可白嫖资源。

    1. offer_type 属于免费类型；
    2. 有 ≥ $5 的赠金；
    3. 有 ≥ 1G 内存 / ≥ 1G 存储的规格；
    4. 标题或证据里明确出现 free / 免费，且不是纯 trial 结束后收费的付费项目。
    """
    if is_paid_program(item):
        return False
    if item.offer_type in FREE_TYPES:
        return True
    if float(item.limits.get("credit_usd") or 0) >= 5:
        return True
    if float(item.resources.get("ram_gb") or 0) >= 1:
        return True
    if float(item.resources.get("storage_gb") or 0) >= 1:
        return True
    return bool(_FREE_TEXT_RE.search(f"{item.title}\n{item.evidence}"))