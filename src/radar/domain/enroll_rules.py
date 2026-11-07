"""自动收编相关性闸门：纯规则、无 IO。

两个调用方共用：
- `collectors/watchlist.auto_enroll_from_items`：aicredits 发现的新域名；
- `pipeline/enroll.auto_enroll_blindspots`：发现层有、监控层没有的厂商。

分层判定：
1. 硬排除：内容/社区/基础设施域名、政府/学术后缀；
2. 有 Provider 实体时以实体字段为准（ignored/retired、非厂商、低相关、relay）；
3. 无实体时退回名称启发式（awesome 列表、目录、博客、社区等）。
"""

from __future__ import annotations

import re

# 自动收编排除：内容/社区/基础设施域名（不提供模型 API 优惠，进监控只添噪）
AUTO_BLOCKLIST = {
    "github.com", "youtube.com", "medium.com", "x.com", "twitter.com",
    "discord.gg", "discord.com", "reddit.com", "huggingface.co",
    "linkedin.com", "substack.com", "notion.site", "apple.com",
    "ycombinator.com", "news.ycombinator.com", "aicredits.dev",
    "aicredits.tech", "openrouter.ai", "artificialanalysis.ai",
    # 政府/学术/公共机构域（aicredits 活动页常见，非模型厂商）
    "gov.uk", "ac.uk", "org.uk", "gov.sg", "gov.in", "org.au",
    "europa.eu", "edu.cn", "gov.cn",
}

# 无实体时按名称词判定：命中即视为目录/内容而非厂商
_NON_VENDOR_WORDS = {
    "awesome", "curated", "directory", "catalog", "catalogue",
    "list", "lists", "collection", "blog", "news", "newsletter",
    "community", "forum", "wiki", "tutorial", "course", "cheatsheet",
}

# relay（中转/镜像）默认不监控；只有高相关才放行
_RELAY_MIN_RELEVANCE = 0.6
# 实体相关度下限：低于该值不自动收编（避免把长尾噪音拉进抓取预算）
_MIN_RELEVANCE = 0.3


def enroll_allowed(
    name: str, domain: str, provider: dict | None = None
) -> tuple[bool, str]:
    """返回 (是否允许收编, 原因)。provider 为 Provider 实体行（可缺省）。"""
    if not domain:
        return False, "no-domain"
    if domain in AUTO_BLOCKLIST:
        return False, "blocklist"

    if provider:
        status = str(provider.get("status") or "")
        if status in {"ignored", "retired"}:
            return False, f"status:{status}"
        if not int(provider.get("vendor_like", 1)):
            return False, "not-vendor"
        try:
            relevance = float(provider.get("relevance") or 0)
        except (TypeError, ValueError):
            relevance = 0.0
        if relevance < _MIN_RELEVANCE:
            return False, f"low-relevance:{relevance:.2f}"
        if str(provider.get("category") or "") == "relay" and relevance < _RELAY_MIN_RELEVANCE:
            return False, "relay"
        return True, "provider-entity"

    tokens = {t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t}
    hit = tokens & _NON_VENDOR_WORDS
    if hit:
        return False, f"name:{sorted(hit)[0]}"
    return True, "heuristic"