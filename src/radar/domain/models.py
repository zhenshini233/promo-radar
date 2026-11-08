"""领域模型：RawItem（源产出）→ ScoredItem（打分后）→ Offer（唯一实体）。

本包零 IO：只放数据类与纯函数，供所有层引用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """统一存储格式：UTC ISO8601，秒级，Z 后缀（可按字典序排序）。"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def truncate(s: str, limit: int = 300) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


@dataclass
class RawItem:
    """各 source 产出的未打分原始条目。

    key_override: 无稳定 URL 的源（如 watchlist）用自定义字符串参与 dedup key；
    force_keep: 目录站等人工筛选过的源跳过阈值过滤（打分仍用于排序展示）。

    v10 新增字段全部带默认值，旧源无需改动即可继续工作。
    """

    source: str
    title: str
    url: str = ""
    provider: str | None = None
    amount_hint: str | None = None
    card_required_hint: bool | None = None
    evidence: str = ""
    published_at: datetime | None = None
    key_override: str | None = None
    force_keep: bool = False
    # v10：云资源扩展
    vertical: str = "ai_api"
    offer_type: str = "credits"
    category: str = ""
    resources: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    eligibility: dict = field(default_factory=dict)
    regions: list[str] = field(default_factory=list)
    expires_at: str = ""
    claim_steps: str = ""
    difficulty: int = 2
    # activity（厂商级促销）| plan（规格/套餐级方案）
    granularity: str = "activity"
    # 稳定指纹用（例如配置化源给出 provider|plan|cycle），为空时由 offer_key 兜底
    key_basis: str = ""


@dataclass
class Offer:
    """可获取的免费/优惠资源（v10）。

    一条 Offer 可对应多条 offer_evidence（来源、原文、时间）。
    """

    dedup_key: str
    title: str
    provider: str | None = None
    provider_id: int | None = None
    vertical: str = "ai_api"
    offer_type: str = "credits"
    category: str = ""
    amount_hint: str = ""
    status: str = "active"
    resources: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    eligibility: dict = field(default_factory=dict)
    regions: list[str] = field(default_factory=list)
    claim_steps: str = ""
    difficulty: int = 2
    granularity: str = "activity"
    expires_at: str = ""
    terms_hash: str = ""
    last_verified_at: str = ""
    verified_by: str = "rule"
    status_reason: str = ""
    url: str = ""
    source: str = ""
    evidence: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    id: int | None = None
    evidence_count: int = 0


@dataclass
class ScoredItem:
    item: RawItem
    score: float = 0.0
    matched: list[str] = field(default_factory=list)



@dataclass
class SourceResult:
    """单源运行结果，用于 run 报告与故障隔离展示。"""

    name: str
    status: str = "ok"  # ok | error
    fetched: int = 0
    kept: int = 0
    new: int = 0
    updated: int = 0
    error: str = ""
    elapsed_ms: int = 0


@dataclass
class RunReport:
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    results: list[SourceResult] = field(default_factory=list)
    # v10：云资源侧新增的 offer（与 deals 分开统计，站点直接查库）
    new_offers: list["Offer"] = field(default_factory=list)
    expired_count: int = 0
    # 源 → 最近连续失败次数（run 结束时从 source_runs 计算）
    failing_sources: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """至少一个源成功即视为本次运行成功（CLI 退出码语义）。"""
        return any(r.status == "ok" for r in self.results)

    @property
    def success_rate(self) -> float:
        """本轮成功源占比，用于过期门控与健康告警。"""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.status == "ok") / len(self.results)