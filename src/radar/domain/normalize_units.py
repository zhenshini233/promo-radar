"""云资源文本归一：单位换算、规格抽取、offer_type / eligibility 推断。

全部为纯函数，不依赖网络与数据库（domain 零 IO 约定）。
原则：只从原文抽取，抽不到就不写；不猜测、不补默认数字。
"""

from __future__ import annotations

import re
from dataclasses import replace

from .models import RawItem

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)\b", re.IGNORECASE)
_VCPU_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:v?CPU|OCPU|cores?|核)\b", re.IGNORECASE)
_RAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|MB)\s*(?:RAM|memory|内存)", re.IGNORECASE)
_DISK_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:SSD|NVMe|HDD|disk|storage|存储|硬盘)", re.IGNORECASE
)
_BW_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:bandwidth|transfer|traffic|egress|流量|带宽)",
    re.IGNORECASE,
)
_RUNTIME_RE = re.compile(r"(\d+)\s*(?:hours?|hrs?)\s*(?:/|per)\s*month", re.IGNORECASE)
_REQ_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(k|K|million|M)?\s*(?:requests?|req)(?:\s*(?:/|per)\s*(day|month))?",
    re.IGNORECASE,
)
_CREDIT_RE = re.compile(
    r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(?:in\s+)?(?:free\s+)?(?:credits?|赠金|试用金|额度)",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(r"(\d+)\s*(days?|天)", re.IGNORECASE)
_TOKENS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(万|亿|千|million|M)?\s*tokens?",
    re.IGNORECASE,
)
_TRIAL_RE = re.compile(r"trial|试用|体验|free\s+for", re.IGNORECASE)

_UNIT_GB = {"MB": 1 / 1024, "GB": 1, "TB": 1024}


def to_gb(num: float, unit: str) -> float:
    return round(float(num) * _UNIT_GB.get(unit.upper(), 1), 3)


def parse_size(text: str) -> float | None:
    m = _SIZE_RE.search(text or "")
    return to_gb(m.group(1), m.group(2)) if m else None


def extract_specs(text: str) -> dict:
    """从一段描述里抽取可比较的规格数字；抽不到就不加该键。

    带范围校验：异常大的数字（价格、请求数误配）直接丢弃，宁缺毋滥。
    """
    text = text or ""
    out: dict = {}
    m = _VCPU_RE.search(text)
    if m and 0 < float(m.group(1)) <= 256:
        out["vcpu"] = float(m.group(1))
    m = _RAM_RE.search(text)
    if m:
        v = to_gb(m.group(1), m.group(2))
        if 0 < v <= 4096:
            out["ram_gb"] = v
    m = _DISK_RE.search(text)
    if m:
        v = to_gb(m.group(1), m.group(2))
        if 0 < v <= 1_000_000:
            out["disk_gb"] = v
    m = _BW_RE.search(text)
    if m:
        v = to_gb(m.group(1), m.group(2))
        if 0 < v <= 1_000_000:
            out["bandwidth_gb"] = v
    # token 额度必须与「免费/赠送/额度」同句或邻近，否则只是换算说明或用量示例；
    # 多个候选时取离关键词最近的那个（示例句里常有「共200万，达到100万时用完免费包」）
    best_dist = None
    best_n = None
    fallback_dist = None
    fallback_n = None
    for cand in _TOKENS_RE.finditer(text):
        lo = max(0, cand.start() - 40)
        hi = min(len(text), cand.end() + 40)
        ctx = text[lo:hi].lower()
        if not any(w in ctx for w in ("免费", "赠送", "额度", "free")):
            continue
        # 换算/示例语句里的 token 数不是额度
        if any(w in ctx for w in ("约消耗", "字符比", "估算", "换算", "兑换")):
            continue
        n = float(cand.group(1))
        unit = (cand.group(2) or "").lower()
        n *= {"千": 1_000, "万": 10_000, "亿": 100_000_000, "m": 1_000_000,
              "million": 1_000_000}.get(unit, 1)
        if not (1_000 <= n <= 10_000_000_000):
            continue
        dist = min(
            abs(idx - cand.start())
            for idx in (text.lower().find(w, lo) for w in ("免费", "赠送", "额度", "free"))
            if idx >= 0
        )
        # 「剩余/余额/已用」是示例中的扣减后数值，不能当额度
        if any(w in ctx for w in ("剩余", "余额", "已用", "剩余额度")):
            if fallback_dist is None or dist < fallback_dist:
                fallback_dist, fallback_n = dist, int(n)
            continue
        if best_dist is None or dist < best_dist:
            best_dist, best_n = dist, int(n)
    if best_n is None:
        best_n = fallback_n
    if best_n is not None:
        out["tokens_free"] = best_n
    m = _RUNTIME_RE.search(text)
    if m and 0 < float(m.group(1)) <= 744:
        out["runtime_hours_month"] = float(m.group(1))
    m = _REQ_RE.search(text)
    if m:
        n = float(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit == "k":
            n *= 1000
        elif unit in ("m", "million"):
            n *= 1_000_000
        if (m.group(3) or "").lower() == "day":
            n *= 30
        if 0 < n <= 10_000_000_000:
            out["requests_month"] = int(n)
    return out


def extract_limits(text: str) -> dict:
    text = text or ""
    out: dict = {}
    m = _CREDIT_RE.search(text)
    if m:
        v = float(m.group(1).replace(",", ""))
        if 0 < v <= 1_000_000:
            out["credit_usd"] = v
    # 时长只在试用语境下才可信；"30 days" 在定价页里常是数据保留期
    if _TRIAL_RE.search(text):
        m = _DURATION_RE.search(text)
        if m and 0 < int(m.group(1)) <= 3650:
            out["valid_days"] = int(m.group(1))
    if re.search(r"per\s+month|monthly|每月|按月", text, re.IGNORECASE):
        out["renew"] = "monthly"
    return out


def infer_offer_type(text: str, default: str = "free_tier") -> str:
    low = (text or "").lower()
    if re.search(r"always[\s-]?free|永久免费|永久额度", low):
        return "always_free"
    if re.search(r"student|学生认证|\.edu", low):
        return "student"
    if re.search(r"startup|创业|加速器", low):
        return "startup"
    if re.search(r"open[\s-]?source|开源项目", low):
        return "oss"
    if re.search(r"lifetime|终身|买断", low):
        return "lifetime"
    if re.search(r"trial|试用|体验", low):
        return "trial"
    if re.search(r"free\s+credits?|赠金|试用金|额度", low):
        return "credits"
    if re.search(r"free\s+(tier|plan|forever)|免费(层|套餐|计划|版)", low):
        return "free_tier"
    return default


def infer_card_required(text: str) -> bool | None:
    low = (text or "").lower()
    if re.search(r"(no|without)\s+(credit\s+card|payment)|无需(信用)?卡|免绑卡|不需要信用卡", low):
        return False
    if re.search(r"(credit\s+card|payment\s+method)\s*(required|needed)|需(要)?绑(定)?卡|需信用卡", low):
        return True
    return None


def infer_eligibility(text: str) -> dict:
    low = (text or "").lower()
    out: dict = {}
    card = infer_card_required(text)
    if card is not None:
        out["card_required"] = card
    if re.search(r"student|学生", low):
        out["student"] = True
    if re.search(r"phone\s*(number|verification)|手机(号|验证)", low):
        out["phone"] = True
    if re.search(r"not\s+available\s+in\s+(china|mainland)|不支持(中国)?大陆|仅限海外", low):
        out["region_block"] = ["CN"]
    return out


_CN_PROVIDER_HINTS = (
    "智谱", "glm", "minimax", "deepseek", "深度求索", "通义", "qwen", "阿里", "百炼",
    "豆包", "火山", "字节", "混元", "腾讯", "文心", "ernie", "百度", "千帆",
    "kimi", "moonshot", "月之暗面", "阶跃", "stepfun", "零一", "百川", "baichuan",
    "讯飞", "星火", "昆仑", "天工", "skywork", "商汤", "sensenova", "美团", "longcat",
    "小米", "mimo", "硅基流动", "siliconflow", "魔搭", "modelscope",
    "ucloud", "青云", "qingcloud", "华为", "huawei", "京东", "jdcloud",
)
# 第三方托管平台（NVIDIA/OpenRouter 等）上跑的中国模型不算国内渠道
_CN_BLOCKING_HOSTS = (
    "nvidia", "openrouter", "aws", "azure", "google", "cloudflare", "lepton",
    "together", "groq", "fireworks", "replicate", "huggingface",
)


def infer_regions(provider: str) -> list[str]:
    """按厂商名推断服务地区；只在采集端没有显式标注时使用。"""
    name = (provider or "").strip().lower()
    if not name or name.startswith(_CN_BLOCKING_HOSTS):
        return []
    return ["CN"] if any(h in name for h in _CN_PROVIDER_HINTS) else []


def enrich_item(item: RawItem, default_type: str = "free_tier") -> RawItem:
    """用标题 + 证据补全 offer_type / resources / limits / eligibility。

    只补空缺：解析器已经写好的字段优先，避免二次推断覆盖精确值。
    """
    text = f"{item.title}\n{item.evidence}"
    offer_type = item.offer_type
    if offer_type in ("", "credits") and default_type != "credits":
        offer_type = infer_offer_type(text, default_type)
    resources = dict(item.resources)
    for k, v in extract_specs(text).items():
        resources.setdefault(k, v)
    limits = dict(item.limits)
    for k, v in extract_limits(text).items():
        limits.setdefault(k, v)
    eligibility = dict(item.eligibility)
    for k, v in infer_eligibility(text).items():
        eligibility.setdefault(k, v)
    return replace(
        item,
        offer_type=offer_type,
        resources=resources,
        limits=limits,
        eligibility=eligibility,
    )