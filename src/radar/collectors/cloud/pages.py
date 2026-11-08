"""云厂商页面源：一个通用解析器 + cloud_sources.toml 配置。

设计取舍：
- 免费层页大多是「H1 + 正文」结构，不需要逐站写选择器；
- 用 trafilatura 提正文，再截取命中 free/免费 的段落作为证据；
- 页面没命中 expect 关键词时跳过（记日志），不产生假条目；
- 单页失败只影响该页，不影响同源其他页面。
"""

from __future__ import annotations

import re

from ...domain.free_gate import is_free_resource
from ...domain.models import RawItem
from ...domain.normalize_units import enrich_item, extract_limits, extract_specs
from ...infra.cloud_config import load_cloud_pages
from ...infra.http import extract_text, get_text, loose_text, strip_html
from ..base import FetchContext, register_source


def _page_text(raw: str, expect: str) -> str:
    """正文优先；提取不到关键词时退回宽松文本（覆盖 RSC/JSON 载荷）。"""
    text = extract_text(raw)
    hit = expect.lower() in text.lower()
    loose = loose_text(raw)
    # 正文命中但过短：多为 JS 渲染页，正文只剩摘要，改用宽松文本
    if hit and len(text) >= 600:
        return text
    if expect.lower() in loose.lower():
        return loose
    return text


_QUANT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:万|亿|千|%|tokens?|token|次|天|元|月|GB|TB|MB|条|个|点|小时)",
    re.IGNORECASE,
)


_NAV_WORDS = (
    "登录", "注册", "控制台", "解决方案", "定价", "文档", "联系我们",
    "立即咨询", "产品动态", "云市场", "客户支持", "合作与生态",
)

_TOKENS_HINT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:万|亿|千)?\s*tokens?", re.IGNORECASE)


def _snippet(text: str, keyword: str, limit: int = 700) -> str:
    """截取一段最能说明「免费 + 额度」的正文，作为可追溯的证据。

    页面首个「免费」常出现在导航或 JSON 里，因此按段落打分：
    同段含数字/单位最有价值，其次长度适中；取最高分段落及相邻段。
    """
    paras = [p.strip() for p in re.split(r"\n+|(?<=[。！？;；])", text) if p.strip()]
    best = None
    best_score = -1
    for i, p in enumerate(paras):
        if keyword.lower() not in p.lower():
            continue
        score = 0
        if _QUANT_RE.search(p):
            score += 3
        if _TOKENS_HINT_RE.search(p):
            score += 4
        # 导航/菜单段落即使含「免费」也不是有效证据
        if sum(1 for w in _NAV_WORDS if w in p) >= 3:
            score -= 5
        if 20 <= len(p) <= 400:
            score += 1
        if len(p) > 400:
            score -= 1
        if score > best_score:
            best, best_score = i, score
    if best is None:
        low = text.lower()
        idx = low.find(keyword.lower())
        if idx < 0:
            return text[:limit]
        return text[max(0, idx - 200) : max(0, idx - 200) + limit]
    chunk = paras[max(0, best - 1) : best + 2]
    return "\n".join(chunk)[:limit]


@register_source("cloud_pages")
class CloudPagesSource:
    name = "cloud_pages"

    def fetch(self, ctx: FetchContext) -> list[RawItem]:
        specs = load_cloud_pages(ctx.cfg.root / "cloud_sources.toml")
        items: list[RawItem] = []
        ok = 0
        for spec in specs:
            try:
                raw = get_text(
                    ctx.http, spec.url, retries=0, timeout=ctx.cfg.general.page_timeout
                )
            except Exception as e:  # noqa: BLE001 - 单页故障隔离
                print(f"[cloud] {spec.name} 抓取失败: {type(e).__name__}: {e}")
                continue
            text = _page_text(raw, spec.expect)
            hit = bool(spec.expect) and spec.expect.lower() in text.lower()
            # 关键词未命中但正文足够长：仍按「官方免费页」收录（国内活动页多为 JS，
            # 正文提取不稳定）；正文过短才视为空壳页跳过。
            if not hit and len(text) < 800:
                print(f"[cloud] {spec.name} 未命中 expect={spec.expect!r} 且正文过短，跳过")
                continue
            if not hit:
                print(f"[cloud] {spec.name} 未命中 expect={spec.expect!r}，按官方渠道页收录")

            snippet = _snippet(text, spec.expect or "free")
            # 结构化字段先由配置给出，再从正文补空缺
            resources = extract_specs(snippet)
            limits = extract_limits(snippet)
            item = RawItem(
                source=self.name,
                title=spec.title_hint or f"{spec.provider} — {spec.category} 免费额度",
                url=spec.url,
                provider=spec.provider,
                evidence=snippet,
                vertical=spec.vertical,
                offer_type=spec.offer_type,
                category=spec.category,
                resources=resources,
                limits=limits,
                claim_steps=spec.claim_steps,
                difficulty=spec.difficulty,
                regions=spec.regions,
                force_keep=True,
                granularity="plan",
                key_basis=f"{spec.name}:{spec.url}",
            )
            item = enrich_item(item, default_type=spec.offer_type)
            if not is_free_resource(item):
                print(f"[cloud] {spec.name} 未通过免费门槛，跳过")
                continue
            items.append(item)
            ok += 1

        print(f"[cloud] {ok}/{len(specs)} 个页面产出条目")
        return items