"""编排：并行抓取 → 打分 → 阈值过滤 → 串行落库 → 去重 → 过期归档。

并行只发生在网络 fetch 阶段：每个源使用独立的 HTTP client 与独立 SQLite
连接（sqlite3 连接不能跨线程复用）；打分/落库/归档仍在主线程串行执行，
保证确定性与事务安全。

故障隔离：单源抛异常只影响该源的 SourceResult，不影响其他源与本次运行。
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor

from ..collectors import FetchContext, build_sources
from ..domain.dedup import make_key
from ..domain.models import RawItem, RunReport, SourceResult, utcnow
from ..domain.scoring import score_item
from ..infra.config import RadarConfig, load_providers
from ..infra.http import make_client
from ..storage.repository import SqliteRepository


def run(cfg: RadarConfig, repo: SqliteRepository, only: list[str] | None = None) -> RunReport:
    """only: 指定只跑这些源（细分刷新）；None = 全部启用源。"""
    report = RunReport(started_at=utcnow())
    sources = [s for s in build_sources(cfg) if not only or s.name in only]
    # 模糊去重候选：近两周活跃 deal，随新增动态扩充（仅主线程读写）
    candidates = repo.load_recent_deals(days=14)

    fetched: list[tuple[list[RawItem], str, int]] = []
    if sources:
        workers = max(1, min(cfg.general.max_source_workers, len(sources)))
        if len(sources) > 1:
            print(f"[run] 并行抓取 {len(sources)} 个源（并发 {workers}）")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fetched = list(
                pool.map(lambda src: _fetch_source(src, cfg, repo.db_path), sources)
            )

    for src, (raw_items, error, elapsed_ms) in zip(sources, fetched):
        res = SourceResult(name=src.name, elapsed_ms=elapsed_ms)
        if error:
            res.status = "error"
            res.error = error
            report.results.append(res)
            continue
        try:
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
            if getattr(src, "full_snapshot", False):
                gone = _sync_full_snapshot_keys(repo, src.name, raw_items)
                if gone:
                    print(f"[catalog] {src.name} 有 {gone} 条从上游消失，已归档")
        except Exception as e:  # noqa: BLE001 - 源级故障隔离（落库阶段）
            res.status = "error"
            res.error = f"{type(e).__name__}: {e}"
        report.results.append(res)

    # 盲区自动收编：发现层有、监控没有的厂商，能解析出官网的进 watchlist
    from .enroll import auto_enroll_blindspots

    enrolled, pending = auto_enroll_blindspots(cfg, repo)
    if enrolled or pending:
        print(f"[auto-enroll] 盲区收编 {enrolled} 家进 watchlist，待收编 {len(pending)} 家")

    # 过期归档必须建立在「本轮抓取基本健康」的前提上：故障期间 last_seen
    # 不会刷新，若无门控，45 天后会把仍有效的活动一次性全部误标过期。
    threshold = cfg.general.expire_min_success_rate
    if not report.results:
        print("[expire] 跳过归档：本轮没有实际运行任何源（检查 --only 参数）")
    elif report.success_rate < threshold:
        print(
            f"[expire] 跳过归档：本轮源成功率 {report.success_rate:.0%} "
            f"< {threshold:.0%}（避免故障期批量误伤）"
        )
    else:
        report.expired_count = repo.expire_old(days=cfg.general.expire_days)

    _prune_orphan_snapshots(cfg, repo)
    report.finished_at = utcnow()
    repo.record_run(report)
    # 必须在本轮写入 source_runs 之后再统计，否则看到的是上一轮的连续失败数
    report.failing_sources = repo.consecutive_failures()
    if report.failing_sources:
        detail = ", ".join(f"{k}×{v}" for k, v in sorted(report.failing_sources.items()))
        print(f"[health] 连续失败的源: {detail}")
    repo.prune_history()
    return report


def _fetch_source(
    src, cfg: RadarConfig, db_path
) -> tuple[list[RawItem], str, int]:
    """worker 线程内完成单个源的网络抓取与状态写入。

    每个 worker 独立 HTTP client + 独立 SQLite 连接（init=False，主线程已
    完成建表/迁移），避免 sqlite3 跨线程复用报错。
    """
    worker_repo = SqliteRepository(db_path, init=False)
    client = make_client(cfg)
    ctx = FetchContext(cfg=cfg, http=client, state=worker_repo)
    t0 = time.perf_counter()
    try:
        items = src.fetch(ctx)
        return items, "", int((time.perf_counter() - t0) * 1000)
    except Exception as e:  # noqa: BLE001 - 源级故障隔离（抓取阶段）
        return [], f"{type(e).__name__}: {e}", int((time.perf_counter() - t0) * 1000)
    finally:
        client.close()
        worker_repo.close()


def _sync_full_snapshot_keys(repo: SqliteRepository, source: str, items: list[RawItem]) -> int:
    """全量快照型源（aicredits）：上游消失的条目归档。

    防御：本轮解析出 0 条或条目数骤降 >50% 时，视为上游格式/网络异常，
    不归档（否则一次解析失败会把整库标成过期）。
    """
    state_key = f"catalog_keys:{source}"
    prev_raw = repo.get_state(state_key)
    try:
        prev = set(json.loads(prev_raw)) if prev_raw else set()
    except (ValueError, TypeError):
        prev = set()

    curr = {make_key(it) for it in items}
    if not curr:
        print(f"[catalog] {source} 本轮解析出 0 条，跳过归档（疑似上游异常）")
        return 0
    if prev and len(curr) < len(prev) * 0.5:
        print(
            f"[catalog] {source} 条目数骤降 {len(prev)} → {len(curr)}，"
            "跳过归档（疑似上游异常），基线已更新"
        )
        repo.set_state(state_key, json.dumps(sorted(curr)))
        return 0

    gone = prev - curr
    for key in gone:
        repo.mark_expired_resolved(key)
    repo.set_state(state_key, json.dumps(sorted(curr)))
    return len(gone)


def _prune_orphan_snapshots(cfg: RadarConfig, repo: SqliteRepository) -> None:
    """清理 providers.toml 里已不存在的监控页快照（含历史），避免无限增长。"""
    try:
        providers = load_providers(cfg.providers_file)
    except Exception as e:  # noqa: BLE001 - 配置读取失败不中断运行
        print(f"[cleanup] 跳过快照清理（providers.toml 读取失败: {e}）")
        return
    valid = {u["url"] for p in providers for u in p["urls"] if u.get("url")}
    pruned = repo.prune_orphan_snapshots(valid)
    if pruned:
        print(f"[cleanup] 清理 {pruned} 个已移除厂商的监控快照")