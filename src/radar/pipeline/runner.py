"""编排：并行抓取 → 打分 → 阈值过滤 → 串行落库 → 去重 → 过期归档。

并行只发生在网络 fetch 阶段：每个源使用独立的 HTTP client 与独立 SQLite
连接（sqlite3 连接不能跨线程复用）；打分/落库/归档仍在主线程串行执行，
保证确定性与事务安全。

故障隔离：单源抛异常只影响该源的 SourceResult，不影响其他源与本次运行。

v10 起所有来源统一写入 offers（唯一展示实体），deals 表只读保留，不再写入。
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from ..collectors import FetchContext, build_sources
from ..domain.dedup import make_key, offer_key
from ..domain.free_gate import is_free_resource, is_paid_program
from ..domain.models import RawItem, RunReport, SourceResult, utcnow
from ..domain.normalize_units import infer_regions
from ..domain.offer_infer import apply_ai_offer
from ..domain.scoring import score_item
from ..infra.config import RadarConfig, load_providers
from ..infra.http import make_client
from ..storage.repository import SqliteRepository

# 云资源源：产出 plan 粒度的 Offer，跳过 AI 的促销阈值判定。
CLOUD_SOURCES = {"free_for_dev", "cloud_pages"}




def _fill_regions(item: RawItem) -> RawItem:
    """采集端没标地区时，按厂商名补 CN，让国内/海外筛选能用。"""
    if item.regions:
        return item
    regs = infer_regions(item.provider)
    return replace(item, regions=regs) if regs else item


def run(
    cfg: RadarConfig,
    repo: SqliteRepository,
    only: list[str] | None = None,
    vertical: str | None = None,
) -> RunReport:
    """only: 指定只跑这些源；vertical: "cloud" / "ai_api" 只跑对应领域。"""
    report = RunReport(started_at=utcnow())
    sources = [s for s in build_sources(cfg) if not only or s.name in only]
    if vertical == "cloud":
        sources = [s for s in sources if s.name in CLOUD_SOURCES]
    elif vertical == "ai_api":
        sources = [s for s in sources if s.name not in CLOUD_SOURCES]
    # 转发合并候选：近两周活跃 Offer（仅主线程读写）
    candidates = repo.load_recent_offers(days=14)

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
            all_items = list(raw_items)  # 归档基线用：过滤前的完整集合

            if src.name in CLOUD_SOURCES:
                valid = [it for it in raw_items if is_free_resource(it)]
                for it in valid:
                    it = _fill_regions(it)
                    offer, action = repo.upsert_offer(
                        it, utcnow(), fuzzy_candidates=candidates
                    )
                    if action == "new":
                        res.new += 1
                        report.new_offers.append(offer)
                        candidates.append(offer)
                    elif action == "updated":
                        res.updated += 1
                res.kept = len(valid)
                if getattr(src, "full_snapshot", False):
                    gone = _sync_full_snapshot_keys(repo, src.name, valid)
                    if gone:
                        print(f"[catalog] {src.name} 有 {gone} 条从上游消失，已归档")
                report.results.append(res)
                continue

            # AI 侧收紧：付费项目（实习/奖学金/投资/会议）不进统一目录
            raw_items = [it for it in raw_items if not is_paid_program(it)]
            scored = [score_item(it, cfg.keywords) for it in raw_items]
            # 源级阈值：社区类源信号弱，可单独放宽；目录/促销源仍用全局阈值
            threshold = float(cfg.source(src.name).get("threshold", cfg.general.promo_threshold))
            kept = [s for s in scored if s.item.force_keep or s.score >= threshold]

            batch: dict[str, object] = {}
            for s in kept:
                k = make_key(s.item)
                if k not in batch or s.score > batch[k].score:  # type: ignore[operator]
                    batch[k] = s

            built: list[RawItem] = []
            for s in sorted(
                batch.values(), key=lambda x: -x.score  # type: ignore[attr-defined,union-attr]
            ):
                item = _fill_regions(apply_ai_offer(s.item, s))
                built.append(item)
                offer, action = repo.upsert_offer(
                    item, utcnow(), fuzzy_candidates=candidates,
                    score=s.score, matched=s.matched,
                )
                if action == "new":
                    res.new += 1
                    report.new_offers.append(offer)
                    candidates.append(offer)
                elif action == "updated":
                    res.updated += 1
            res.kept = len(batch)
            if getattr(src, "full_snapshot", False):
                gone = _sync_full_snapshot_keys(repo, src.name, built)
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
        report.expired_count = repo.expire_offers(stale_days=cfg.general.expire_days)

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

    curr = {offer_key(it) for it in items}
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
        repo.mark_expired_offer(key)
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