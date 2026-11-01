"""编排：逐源抓取 → 打分 → 阈值过滤 → 批内与库内去重 → 过期归档。

故障隔离：单源抛异常只影响该源的 SourceResult，不影响其他源与本次运行。
"""

from __future__ import annotations

import time

from ..collectors import FetchContext, build_sources
from ..domain.dedup import make_key
from ..domain.models import RunReport, SourceResult, utcnow
from ..domain.scoring import score_item
from ..infra.config import RadarConfig
from ..infra.http import make_client
from ..storage.repository import SqliteRepository


def run(cfg: RadarConfig, repo: SqliteRepository, only: list[str] | None = None) -> RunReport:
    """only: 指定只跑这些源（细分刷新）；None = 全部启用源。"""
    client = make_client(cfg)
    ctx = FetchContext(cfg=cfg, http=client, state=repo)
    report = RunReport(started_at=utcnow())
    # 模糊去重候选：近两周活跃 deal，随新增动态扩充
    candidates = repo.load_recent_deals(days=14)

    for src in build_sources(cfg):
        if only and src.name not in only:
            continue
        res = SourceResult(name=src.name)
        t0 = time.perf_counter()
        try:
            raw_items = src.fetch(ctx)
            res.fetched = len(raw_items)

            scored = [score_item(it, cfg.keywords) for it in raw_items]
            kept = [s for s in scored if s.item.force_keep or s.score >= cfg.general.promo_threshold]

            batch: dict[str, object] = {}
            for s in kept:
                k = make_key(s.item)
                if k not in batch or s.score > batch[k].score:  # type: ignore[operator]
                    batch[k] = s

            for s in sorted(
                batch.values(), key=lambda x: -x.score  # type: ignore[attr-defined,union-attr]
            ):
                deal, action = repo.upsert_scored(s, utcnow(), fuzzy_candidates=candidates)
                if action == "new":
                    res.new += 1
                    report.new_deals.append(deal)
                    candidates.append(deal)
                elif action == "updated":
                    res.updated += 1
            res.kept = len(batch)
        except Exception as e:  # noqa: BLE001 - 源级故障隔离
            res.status = "error"
            res.error = f"{type(e).__name__}: {e}"
        res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        report.results.append(res)

    # 盲区自动收编：发现层有、监控没有的厂商，能解析出官网的进 watchlist
    from .enroll import auto_enroll_blindspots

    enrolled, pending = auto_enroll_blindspots(cfg, repo)
    if enrolled or pending:
        print(f"[auto-enroll] 盲区收编 {enrolled} 家进 watchlist，待收编 {len(pending)} 家")

    report.expired_count = repo.expire_old(days=cfg.general.expire_days)
    report.finished_at = utcnow()
    repo.record_run(report)
    repo.prune_history()
    client.close()
    return report
