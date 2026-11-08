"""SQLite 持久层：Repository + StateStore 协议与唯一实现。

原则：
- 只归档不删除：过期 deal 置 status='expired'，历史可追溯；
- last_seen_at 每次见到都刷新，last_changed_at 只在有意义变化时刷新；
- snapshot_history 每轮追加，支撑 dashboard 的信号历史条形带；
- 运行记录 runs/source_runs 支撑故障隔离的可观测性。

collectors 只依赖 StateStore 协议（本模块定义），不感知 SQLite 实现。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain.dedup import canonical_terms, find_fuzzy_match, make_key, norm_title, offer_key
from ..domain.domains import registrable_domain
from ..domain.models import Offer, RunReport, iso, utcnow

SCHEMA_VERSION = 10
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"




def _json_obj(raw: str | None, default):
    """容错解析 JSON 列：坏数据回退默认值，避免整站崩。"""
    try:
        v = json.loads(raw or "")
    except (ValueError, TypeError):
        return default
    return v if isinstance(v, type(default)) else default


def _row_to_offer(r: sqlite3.Row) -> Offer:
    keys = set(r.keys())
    return Offer(
        id=r["id"],
        dedup_key=r["dedup_key"],
        title=r["title"],
        provider=(r["provider_name"] or None),
        provider_id=r["provider_id"],
        vertical=r["vertical"],
        offer_type=r["offer_type"],
        granularity=r["granularity"],
        category=r["category"],
        amount_hint=r["amount_hint"] or "",
        status=r["status"],
        resources=_json_obj(r["resources"], {}),
        limits=_json_obj(r["limits"], {}),
        eligibility=_json_obj(r["eligibility"], {}),
        regions=_json_obj(r["regions"], []),
        claim_steps=r["claim_steps"],
        difficulty=int(r["difficulty"] or 2),
        expires_at=r["expires_at"],
        terms_hash=r["terms_hash"],
        last_verified_at=r["last_verified_at"],
        verified_by=r["verified_by"],
        status_reason=r["status_reason"],
        url=r["url"],
        source=r["source"],
        evidence=r["evidence"],
        first_seen_at=r["first_seen_at"],
        last_seen_at=r["last_seen_at"],
        evidence_count=(int(r["evidence_count"]) if "evidence_count" in keys else 0),
        score=(float(r["offer_score"]) if "offer_score" in keys else 0.0),
    )


@runtime_checkable
class StateStore(Protocol):
    """collectors 需要的最小持久接口（抓取状态与快照）。"""

    def get_state(self, key: str) -> str | None: ...

    def set_state(self, key: str, value: str) -> None: ...

    def get_snapshot(self, url: str) -> dict | None: ...

    def upsert_snapshot(
        self, *, url: str, provider: str, label: str, content_hash: str,
        promo_keywords: str, now, changed: bool,
    ) -> None: ...

    def record_history(self, *, url: str, checked_at: str, promo_keywords: str, changed: bool) -> None: ...

    def record_snapshot_failure(
        self, *, url: str, provider: str, label: str, error: str, now
    ) -> None: ...

    def schedule_snapshot(
        self, *, url: str, tier: int, next_check_at: str
    ) -> None: ...

    def provider_stats(self) -> dict: ...


class SqliteRepository(StateStore):
    def __init__(self, db_path: Path, *, init: bool = True):
        """init=False：只开连接，不建表/不迁移。

        源级并行抓取时每个 worker 线程需要独立 SQLite 连接（sqlite3 默认
        禁止跨线程复用连接），由主线程先完成初始化，worker 连接只读写。
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")
        if init:
            self.conn.execute("PRAGMA journal_mode=WAL")
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            # 旧库必须先补 v10 列，再执行 schema：schema.sql 里有
            # idx_offers_vertical / idx_providers_vertical，列不存在时建索引会直接
            # 抛 "no such column"（CI 从 data 分支恢复的旧快照就会命中）。
            # _ensure_v10_columns 幂等：新库没有表时跳过，由 schema.sql 连列一起建。
            self._ensure_v10_columns()
            self.conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
            if version < SCHEMA_VERSION:
                self._migrate(version)
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.commit()

    def _ensure_v10_columns(self) -> None:
        for col, ddl in (
            ("vertical", "TEXT NOT NULL DEFAULT 'ai_api'"),
            ("categories", "TEXT NOT NULL DEFAULT '[]'"),
            ("deploy_modes", "TEXT NOT NULL DEFAULT '[]'"),
            ("free_tier_url", "TEXT NOT NULL DEFAULT ''"),
            ("pricing_url", "TEXT NOT NULL DEFAULT ''"),
        ):
            self._add_column("providers", col, ddl)
        for col, ddl in (
            ("vertical", "TEXT NOT NULL DEFAULT 'ai_api'"),
            ("offer_type", "TEXT NOT NULL DEFAULT 'credits'"),
            ("granularity", "TEXT NOT NULL DEFAULT 'activity'"),
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("resources", "TEXT NOT NULL DEFAULT '{}'"),
            ("limits", "TEXT NOT NULL DEFAULT '{}'"),
            ("eligibility", "TEXT NOT NULL DEFAULT '{}'"),
            ("regions", "TEXT NOT NULL DEFAULT '[]'"),
            ("claim_steps", "TEXT NOT NULL DEFAULT ''"),
            ("difficulty", "INTEGER NOT NULL DEFAULT 2"),
            ("expires_at", "TEXT NOT NULL DEFAULT ''"),
            ("terms_hash", "TEXT NOT NULL DEFAULT ''"),
            ("last_verified_at", "TEXT NOT NULL DEFAULT ''"),
            ("verified_by", "TEXT NOT NULL DEFAULT 'rule'"),
            ("status_reason", "TEXT NOT NULL DEFAULT ''"),
            ("url", "TEXT NOT NULL DEFAULT ''"),
            ("source", "TEXT NOT NULL DEFAULT ''"),
            ("evidence", "TEXT NOT NULL DEFAULT ''"),
            ("provider_name", "TEXT NOT NULL DEFAULT ''"),
        ):
            self._add_column("offers", col, ddl)
        for col, ddl in (
            ("title", "TEXT NOT NULL DEFAULT ''"),
            ("evidence", "TEXT NOT NULL DEFAULT ''"),
            ("amount_hint", "TEXT NOT NULL DEFAULT ''"),
            ("matched", "TEXT NOT NULL DEFAULT '[]'"),
            ("score", "REAL NOT NULL DEFAULT 0"),
            ("first_seen_at", "TEXT NOT NULL DEFAULT ''"),
            ("last_seen_at", "TEXT NOT NULL DEFAULT ''"),
        ):
            self._add_column("offer_evidence", col, ddl)

    def _migrate(self, version: int) -> None:
        """按版本补齐新增列；CREATE TABLE IF NOT EXISTS 不会改旧表结构。"""
        if version and version < 4:
            self._add_column("deals", "matched", "TEXT NOT NULL DEFAULT '[]'")
        if version < 5:
            self._add_column("snapshots", "fail_count", "INTEGER NOT NULL DEFAULT 0")
            self._add_column("snapshots", "last_error", "TEXT NOT NULL DEFAULT ''")
        if version < 6:
            self._add_column("snapshots", "tier", "INTEGER NOT NULL DEFAULT 2")
            self._add_column("snapshots", "next_check_at", "TEXT NOT NULL DEFAULT ''")
        if version < 7:
            # v7 只新增 providers / provider_domains / provider_aliases / provider_sources，
            # 由 schema.sql 的 CREATE TABLE IF NOT EXISTS 完成；旧表不加列。
            pass
        if version < 8:
            # v8 只新增 offers / offer_evidence，同样由 schema.sql 建表。
            pass
        if version < 9:
            self._add_column("deals", "verified_at", "TEXT NOT NULL DEFAULT ''")
            self._add_column("deals", "verified_by", "TEXT NOT NULL DEFAULT ''")
        if version < 10:
            # v10：垂直领域 + 免费资源结构化字段；新表由 schema.sql 建。
            self._ensure_v10_columns()

    def _add_column(self, table: str, name: str, ddl: str) -> None:
        # 表还不存在（首次建库）时跳过：schema.sql 会连列一起建出来
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            return
        cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        if name not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def close(self) -> None:
        self.conn.close()

    def mark_expired_offer(self, key: str) -> bool:
        """按 offer 指纹归档（全量目录源上游消失时使用）。"""
        cur = self.conn.execute(
            "UPDATE offers SET status='expired', status_reason='upstream_removed'"
            " WHERE dedup_key = ? AND status != 'expired'",
            (key,),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def digest_data(self, now) -> dict:
        """首页数据：统一从 offers 取（AI + 云同一个目录）。"""
        c7 = iso(now - timedelta(days=7))
        c30 = iso(now - timedelta(days=30))
        q = (
            "SELECT o.*, COALESCE(o.provider_name, p.name) AS provider_name"
            " FROM offers o LEFT JOIN providers p ON p.id = o.provider_id"
            " WHERE {} ORDER BY {} LIMIT ?"
        )
        new = self.conn.execute(
            q.format("o.status = 'active' AND o.first_seen_at >= ?", "o.first_seen_at DESC"),
            (c7, 200),
        ).fetchall()
        updated = self.conn.execute(
            q.format(
                "o.status = 'active' AND o.last_seen_at >= ? AND o.first_seen_at < ?",
                "o.last_seen_at DESC",
            ),
            (c7, c7, 200),
        ).fetchall()
        needs_review = self.conn.execute(
            q.format("o.status = 'active' AND o.last_seen_at < ?", "o.last_seen_at ASC"),
            (c30, 100),
        ).fetchall()
        expired_recent = self.conn.execute(
            q.format("o.status = 'expired' AND o.last_seen_at >= ?", "o.last_seen_at DESC"),
            (c30, 50),
        ).fetchall()
        totals = self.conn.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,"
            " SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) AS expired"
            " FROM offers"
        ).fetchone()
        return {
            "new_deals": [_row_to_offer(r) for r in new],
            "updated_deals": [_row_to_offer(r) for r in updated],
            "needs_review": [_row_to_offer(r) for r in needs_review],
            "expired_recent": [_row_to_offer(r) for r in expired_recent],
            "total_deals": totals["total"] or 0,
            "active_deals": totals["active"] or 0,
            "expired_deals": totals["expired"] or 0,
            "snapshots": self.all_snapshots(),
        }

    # ---------- watchlist snapshots ----------

    def get_snapshot(self, url: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM snapshots WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None

    def upsert_snapshot(
        self, *, url: str, provider: str, label: str, content_hash: str,
        promo_keywords: str, now, changed: bool,
    ) -> None:
        now_s = iso(now)
        self.conn.execute(
            """
            INSERT INTO snapshots (url, provider, label, content_hash, promo_keywords,
                                   last_checked_at, last_changed_at, fail_count, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, '')
            ON CONFLICT(url) DO UPDATE SET
                provider = excluded.provider,
                label = excluded.label,
                content_hash = excluded.content_hash,
                promo_keywords = excluded.promo_keywords,
                last_checked_at = excluded.last_checked_at,
                last_changed_at = CASE WHEN snapshots.content_hash != excluded.content_hash
                                       THEN excluded.last_checked_at
                                       ELSE snapshots.last_changed_at END,
                fail_count = 0,
                last_error = ''
            """,
            (url, provider, label, content_hash, promo_keywords, now_s, now_s),
        )
        self.conn.commit()

    def record_snapshot_failure(
        self, *, url: str, provider: str, label: str, error: str, now
    ) -> None:
        """记录一次页面抓取失败；成功抓取会由 upsert_snapshot 清零。"""
        now_s = iso(now)
        self.conn.execute(
            """
            INSERT INTO snapshots (url, provider, label, content_hash, promo_keywords,
                                   last_checked_at, last_changed_at, fail_count, last_error)
            VALUES (?, ?, ?, '', '', ?, ?, 1, ?)
            ON CONFLICT(url) DO UPDATE SET
                provider = excluded.provider,
                label = excluded.label,
                fail_count = snapshots.fail_count + 1,
                last_error = excluded.last_error,
                last_checked_at = excluded.last_checked_at
            """,
            (url, provider, label, now_s, now_s, (error or "")[:300]),
        )
        self.conn.commit()

    def schedule_snapshot(self, *, url: str, tier: int, next_check_at: str) -> None:
        """写入分层与下次检查时间（分层调度核心状态）。"""
        self.conn.execute(
            "UPDATE snapshots SET tier = ?, next_check_at = ? WHERE url = ?",
            (int(tier), next_check_at, url),
        )
        self.conn.commit()

    def all_snapshots(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM snapshots ORDER BY provider, label").fetchall()
        return [dict(r) for r in rows]

    def remove_snapshots(self, urls: list[str]) -> int:
        """删除监控页快照及其历史（provider 从 providers.toml 移除时清理残留）。"""
        cur = self.conn.executemany(
            "DELETE FROM snapshot_history WHERE url = ?", [(u,) for u in urls]
        )
        cur = self.conn.executemany(
            "DELETE FROM snapshots WHERE url = ?", [(u,) for u in urls]
        )
        self.conn.commit()
        return cur.rowcount

    def prune_orphan_snapshots(self, valid_urls: set[str]) -> int:
        """删除不在 providers.toml 中的快照及其历史。

        valid_urls 为空视为配置读取异常（或用户清空了 watchlist），此时不删，
        避免一次误操作把全部历史清空。
        """
        if not valid_urls:
            return 0
        rows = self.conn.execute("SELECT url FROM snapshots").fetchall()
        orphans = [r["url"] for r in rows if r["url"] not in valid_urls]
        if not orphans:
            return 0
        self.remove_snapshots(orphans)
        return len(orphans)

    def record_history(self, *, url: str, checked_at: str, promo_keywords: str, changed: bool) -> None:
        self.conn.execute(
            "INSERT INTO snapshot_history (url, checked_at, promo_keywords, changed)"
            " VALUES (?, ?, ?, ?)",
            (url, checked_at, promo_keywords, int(changed)),
        )
        self.conn.commit()

    def history_for(self, url: str, days: int = 90) -> list[dict]:
        cutoff = iso(utcnow() - timedelta(days=days))
        rows = self.conn.execute(
            "SELECT checked_at, promo_keywords, changed FROM snapshot_history"
            " WHERE url = ? AND checked_at >= ? ORDER BY checked_at",
            (url, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]

    def prune_history(self, days: int = 120) -> int:
        cutoff = iso(utcnow() - timedelta(days=days))
        cur = self.conn.execute("DELETE FROM snapshot_history WHERE checked_at < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount

    # ---------- runs ----------

    def record_run(self, report: RunReport) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, finished_at, new_deals, updated_deals, errors, expired)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                iso(report.started_at), iso(report.finished_at or utcnow()),
                len(report.new_offers),
                sum(r.updated for r in report.results),
                sum(1 for r in report.results if r.status == "error"),
                report.expired_count,
            ),
        )
        run_id = cur.lastrowid
        for r in report.results:
            self.conn.execute(
                "INSERT INTO source_runs (run_id, source, status, fetched, kept, new, updated,"
                " error, elapsed_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, r.name, r.status, r.fetched, r.kept, r.new, r.updated, r.error, r.elapsed_ms),
            )
        self.conn.commit()
        return run_id

    def latest_source_runs(self) -> list[dict]:
        """每个源最近一次的运行状态（细分刷新后侧栏仍显示全部源）。"""
        rows = self.conn.execute(
            "SELECT sr.rowid AS rid, sr.* FROM source_runs sr"
            " WHERE sr.rowid IN (SELECT MAX(rowid) FROM source_runs GROUP BY source)"
            " ORDER BY source"
        ).fetchall()
        return [dict(r) for r in rows]

    def last_run(self) -> dict | None:
        run = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if not run:
            return None
        sources = self.conn.execute(
            "SELECT * FROM source_runs WHERE run_id = ? ORDER BY rowid", (run["id"],)
        ).fetchall()
        return {"run": dict(run), "sources": [dict(s) for s in sources]}

    def last_success_at(self, min_sources: int = 0) -> str | None:
        """最近一次「基本健康」的抓取时间，用于判断数据新鲜度。

        口径：错误源 <= 20%（errors*5 <= total），且至少一个源成功。
        min_sources > 0 时还要求该轮源数达到阈值，用于区分「全量轮次」与
        `--only` 局部刷新：否则单源成功会把全源故障掩盖成绿色横幅。
        不用「全源成功」，否则一个长期失效的源（如 AA 410）会让站点永远红色。
        """
        row = self.conn.execute(
            """
            SELECT MAX(r.finished_at) AS t
            FROM runs r
            WHERE (
                SELECT COUNT(*) FROM source_runs sr3 WHERE sr3.run_id = r.id
            ) >= ?
              AND (
                SELECT COUNT(*) FROM source_runs sr
                WHERE sr.run_id = r.id AND sr.status = 'error'
            ) < (
                SELECT COUNT(*) FROM source_runs sr4 WHERE sr4.run_id = r.id
            )
              AND (
                SELECT COUNT(*) FROM source_runs sr
                WHERE sr.run_id = r.id AND sr.status = 'error'
              ) * 5 <= (
                SELECT COUNT(*) FROM source_runs sr2 WHERE sr2.run_id = r.id
            )
            """,
            (max(1, min_sources),),
        ).fetchone()
        return row["t"] if row and row["t"] else None

    def consecutive_failures(self, limit: int = 5) -> dict[str, int]:
        """每个源最近连续失败的次数（只看最近 limit 条运行记录）。"""
        rows = self.conn.execute(
            "SELECT source, status FROM ("
            "  SELECT source, status, row_number() OVER"
            "    (PARTITION BY source ORDER BY rowid DESC) AS rn"
            "  FROM source_runs"
            ") WHERE rn <= ? ORDER BY source, rn",
            (limit,),
        ).fetchall()
        out: dict[str, int] = {}
        done: set[str] = set()
        for r in rows:
            src = r["source"]
            if src in done:
                continue
            if r["status"] == "error":
                out[src] = out.get(src, 0) + 1
            else:
                done.add(src)
        return out

    # ---------- digest / verify ----------

    def today_digest(self, now=None, stale_days: int = 7) -> dict:
        """首页三问：今天新增、最近仍可用、本周漏抓。"""
        now = now or utcnow()
        today = now.date().isoformat()
        cutoff = iso(now - timedelta(days=stale_days))

        today_new = self.conn.execute(
            "SELECT COUNT(*) AS n FROM offers WHERE substr(first_seen_at, 1, 10) = ?", (today,)
        ).fetchone()["n"]
        recent_active = self.conn.execute(
            "SELECT COUNT(*) AS n FROM offers"
            " WHERE status = 'active' AND last_seen_at >= ?",
            (cutoff,),
        ).fetchone()["n"]

        owners = {
            r["domain"]: r["provider_id"]
            for r in self.conn.execute("SELECT domain, provider_id FROM provider_domains")
        }
        last_success: dict[int, str] = {}
        failed_pages: dict[int, int] = {}
        global_last = ""
        for r in self.conn.execute("SELECT url, last_checked_at, fail_count FROM snapshots"):
            dom = registrable_domain(r["url"])
            pid = owners.get(dom) if dom else None
            if pid is None:
                continue
            if r["fail_count"] == 0:
                if r["last_checked_at"] > last_success.get(pid, ""):
                    last_success[pid] = r["last_checked_at"]
                if r["last_checked_at"] > global_last:
                    global_last = r["last_checked_at"]
            else:
                failed_pages[pid] = failed_pages.get(pid, 0) + 1

        missed: list[dict] = []
        for p in self.conn.execute(
            "SELECT id, name, slug FROM providers WHERE status = 'monitored' ORDER BY name"
        ):
            last = last_success.get(p["id"], "")
            if last and last >= cutoff:
                continue
            missed.append({
                "name": p["name"],
                "slug": p["slug"],
                "last_success": last[:10],
                "failed_pages": failed_pages.get(p["id"], 0),
                "reason": "从未成功抓取" if not last else f"{stale_days} 天未成功",
            })

        return {
            "today": today,
            "today_new": today_new or 0,
            "recent_active": recent_active or 0,
            "missed_count": len(missed),
            "missed": missed[:10],
            "last_success": global_last,
        }

    

    # ---------- providers ----------

    def provider_for_domain(self, domain: str) -> dict | None:
        """按注册域查 Provider 实体（自动收编闸门用）；未命中返回 None。"""
        if not domain:
            return None
        row = self.conn.execute(
            "SELECT p.* FROM providers p"
            " JOIN provider_domains d ON d.provider_id = p.id"
            " WHERE d.domain = ?",
            (domain,),
        ).fetchone()
        return dict(row) if row else None

    def provider_stats(self) -> dict:
        """Provider 实体的覆盖口径：ignored 不进分母，coverage = monitored / universe。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN status = 'monitored' THEN 1 ELSE 0 END) AS monitored,"
            " SUM(CASE WHEN status = 'ignored' THEN 1 ELSE 0 END) AS ignored,"
            " SUM(CASE WHEN status = 'in_universe' THEN 1 ELSE 0 END) AS in_universe"
            " FROM providers"
        ).fetchone()
        total = row["total"] or 0
        ignored = row["ignored"] or 0
        monitored = row["monitored"] or 0
        universe = total - ignored
        return {
            "total": total,
            "monitored": monitored,
            "ignored": ignored,
            "in_universe": row["in_universe"] or 0,
            "universe": universe,
            "coverage": (monitored / universe) if universe else 0.0,
        }

    def provider_page_stats(self, limit: int = 20) -> dict:
        """只读：用注册域把 snapshots 关联到 provider。

        SQLite 没有可注册域函数，且 `url LIKE '%' || domain || '%'` 会误配
        （notexample.com 命中 example.com），因此关联放在 Python 层做。
        """
        providers = {
            r["id"]: dict(r)
            for r in self.conn.execute(
                "SELECT id, slug, name, category, status FROM providers"
            )
        }
        by_domain = {
            r["domain"]: r["provider_id"]
            for r in self.conn.execute("SELECT domain, provider_id FROM provider_domains")
        }
        pages = self.conn.execute(
            "SELECT url, provider, label, tier FROM snapshots"
        ).fetchall()

        linked_ids: set[int] = set()
        ignored_pages = 0
        by_cat: dict[str, dict] = {}
        mismatch: list[dict] = []
        unlinked: list[dict] = []
        for p in pages:
            dom = registrable_domain(p["url"])
            pid = by_domain.get(dom) if dom else None
            prov = providers.get(pid) if pid is not None else None
            if prov is None:
                unlinked.append({"url": p["url"], "provider": p["provider"]})
                continue
            if prov["status"] == "ignored":
                ignored_pages += 1
                continue
            linked_ids.add(pid)
            bucket = by_cat.setdefault(prov["category"], {"pages": 0, "providers": set()})
            bucket["pages"] += 1
            bucket["providers"].add(pid)
            if norm_title(prov["name"]) != norm_title(p["provider"] or ""):
                mismatch.append({
                    "url": p["url"],
                    "snapshot_provider": p["provider"],
                    "provider": prov["name"],
                })

        universe_ids = {pid for pid, v in providers.items() if v["status"] != "ignored"}
        missing = [
            {
                "slug": providers[pid]["slug"],
                "name": providers[pid]["name"],
                "status": providers[pid]["status"],
            }
            for pid in sorted(universe_ids - linked_ids)
        ]
        total = len(pages)
        linked = sum(b["pages"] for b in by_cat.values())
        return {
            "total_pages": total,
            "linked_pages": linked,
            "unlinked_pages": total - linked - ignored_pages,
            "ignored_pages": ignored_pages,
            "link_rate": (linked / total) if total else 0.0,
            "providers_with_pages": len(linked_ids),
            "providers_without_pages": len(missing),
            "by_category": {
                k: {"pages": v["pages"], "providers": len(v["providers"])}
                for k, v in sorted(by_cat.items(), key=lambda x: -x[1]["pages"])
            },
            "mismatch_total": len(mismatch),
            "mismatch": mismatch[:limit],
            "unlinked_total": len(unlinked),
            "unlinked_samples": unlinked[:limit],
            "missing_samples": missing[:limit],
        }

    def provider_category_stats(self) -> list[dict]:
        """按 category 汇总 Provider/监控/页数，盲区 = in_universe。"""
        page_map = self.provider_page_stats(limit=0)["by_category"]
        rows = self.conn.execute(
            "SELECT category, COUNT(*) AS providers,"
            " SUM(CASE WHEN status = 'monitored' THEN 1 ELSE 0 END) AS monitored,"
            " SUM(CASE WHEN status = 'in_universe' THEN 1 ELSE 0 END) AS in_universe"
            " FROM providers WHERE status != 'ignored' GROUP BY category"
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            prov = r["providers"] or 0
            mon = r["monitored"] or 0
            page = page_map.get(r["category"], {})
            out.append({
                "category": r["category"],
                "providers": prov,
                "monitored": mon,
                "in_universe": r["in_universe"] or 0,
                "pages": page.get("pages", 0),
                "coverage": (mon / prov) if prov else 0.0,
            })
        out.sort(key=lambda x: (-x["providers"], x["category"]))
        return out

    # ---------- offers (v10) ----------

    def _provider_id_for(self, name: str | None) -> int | None:
        if not name:
            return None
        n = name.strip().lower()
        row = self.conn.execute(
            "SELECT id FROM providers WHERE LOWER(slug) = ? OR LOWER(name) = ? LIMIT 1",
            (n, n),
        ).fetchone()
        return row["id"] if row else None

    def _touch_evidence(
        self, offer_id: int, key: str, item, now_s: str,
        score: float = 0.0, matched: list[str] | None = None,
    ) -> None:
        """同一 offer 的每个来源各留一条证据；重复观察刷新 last_seen。"""
        self.conn.execute(
            "INSERT INTO offer_evidence"
            " (offer_id, deal_key, url, source, seen_at, title, evidence,"
            "  amount_hint, matched, score, first_seen_at, last_seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(offer_id, deal_key) DO UPDATE SET"
            " url = excluded.url, seen_at = excluded.seen_at,"
            " evidence = excluded.evidence, amount_hint = excluded.amount_hint,"
            " matched = excluded.matched, score = excluded.score,"
            " last_seen_at = excluded.last_seen_at",
            (
                offer_id, f"{item.source}:{key}", item.url, item.source, now_s,
                item.title, (item.evidence or "")[:1000], item.amount_hint or "",
                json.dumps(matched or [], ensure_ascii=False), float(score),
                now_s, now_s,
            ),
        )

    def get_offer(self, key: str) -> Offer | None:
        row = self.conn.execute(
            "SELECT o.*, COALESCE(o.provider_name, p.name) AS provider_name FROM offers o"
            " LEFT JOIN providers p ON p.id = o.provider_id WHERE o.dedup_key = ?",
            (key,),
        ).fetchone()
        return _row_to_offer(row) if row else None

    def upsert_offer(
        self, item, now, provider_id=None, fuzzy_candidates=None,
        score: float = 0.0, matched: list[str] | None = None,
    ) -> tuple[Offer, str]:
        """按 offer 指纹入库或合并。所有来源（AI / 云）都走这一个入口。

        返回 (offer, action)：new | updated（条款有变化）| unchanged。
        fuzzy_candidates 用于把「同一活动的转发帖」并入同一 Offer 的证据，
        而不是每条帖子都生成一个 Offer。
        """
        key = offer_key(item)
        now_s = iso(now)
        terms = canonical_terms(item.resources, item.limits)
        th = hashlib.sha1(
            json.dumps(terms, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        pid = provider_id if provider_id is not None else self._provider_id_for(item.provider)
        row = self.conn.execute("SELECT * FROM offers WHERE dedup_key = ?", (key,)).fetchone()

        # 指纹未命中时，尝试与近两周 Offer 做标题 + 金额模糊匹配（转发帖合并）
        if row is None and fuzzy_candidates:
            match = find_fuzzy_match(item, fuzzy_candidates)
            if match is not None:
                key = match.dedup_key
                row = self.conn.execute(
                    "SELECT * FROM offers WHERE dedup_key = ?", (key,)
                ).fetchone()

        res = dict(item.resources or {})
        lim = dict(item.limits or {})
        elig = dict(item.eligibility or {})
        regs = list(item.regions or [])

        if row is None:
            cur = self.conn.execute(
                "INSERT INTO offers (provider_id, title, amount_hint, status, first_seen_at,"
                " last_seen_at, dedup_key, vertical, offer_type, category, resources, limits,"
                " eligibility, regions, claim_steps, difficulty, expires_at, terms_hash,"
                " last_verified_at, verified_by, status_reason, url, source, evidence, provider_name, granularity)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pid, item.title, item.amount_hint or "", "active", now_s, now_s, key,
                    item.vertical, item.offer_type, item.category,
                    json.dumps(res, ensure_ascii=False),
                    json.dumps(lim, ensure_ascii=False),
                    json.dumps(elig, ensure_ascii=False),
                    json.dumps(regs, ensure_ascii=False),
                    item.claim_steps, int(item.difficulty), item.expires_at, th, now_s,
                    "rule", "", item.url, item.source, (item.evidence or "")[:1000],
                    item.provider or "", item.granularity,
                ),
            )
            self._touch_evidence(int(cur.lastrowid), key, item, now_s, score, matched)
            self.conn.commit()
            return self.get_offer(key), "new"  # type: ignore[return-value]

        old = {
            "resources": _json_obj(row["resources"], {}),
            "limits": _json_obj(row["limits"], {}),
            "eligibility": _json_obj(row["eligibility"], {}),
            "regions": _json_obj(row["regions"], []),
        }
        new = {"resources": res, "limits": lim, "eligibility": elig, "regions": regs}
        changed = [k for k in old if old[k] != new[k]]

        if changed:
            self.conn.execute(
                "INSERT INTO offer_terms_history"
                " (offer_id, terms_hash, snapshot, changed_fields, changed_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (row["id"], th, json.dumps(new, ensure_ascii=False),
                 json.dumps(changed), now_s),
            )
        self.conn.execute(
            "UPDATE offers SET provider_id=?, title=?, amount_hint=?, vertical=?, offer_type=?,"
            " granularity=?, category=?, resources=?, limits=?, eligibility=?, regions=?, claim_steps=?,"
            " difficulty=?, expires_at=?, terms_hash=?, last_verified_at=?, verified_by=?,"
            " url=?, source=?, evidence=?, provider_name=?, last_seen_at=?, status='active', status_reason=''"
            " WHERE dedup_key=?",
            (
                pid or row["provider_id"], item.title or row["title"],
                item.amount_hint or row["amount_hint"], item.vertical, item.offer_type, item.granularity,
                item.category or row["category"],
                json.dumps(res, ensure_ascii=False), json.dumps(lim, ensure_ascii=False),
                json.dumps(elig, ensure_ascii=False), json.dumps(regs, ensure_ascii=False),
                item.claim_steps or row["claim_steps"], int(item.difficulty),
                item.expires_at or row["expires_at"], th, now_s, "rule",
                item.url or row["url"], item.source, (item.evidence or row["evidence"])[:1000], item.provider or row["provider_name"],
                now_s, key,
            ),
        )
        self._touch_evidence(row["id"], key, item, now_s, score, matched)
        self.conn.commit()
        if changed:
            self.record_signal(
                "terms_changed", vertical=item.vertical, source=item.source,
                page_url=item.url, offer_id=row["id"],
                payload={"fields": changed}, now=now,
            )
        return self.get_offer(key), ("updated" if changed else "unchanged")  # type: ignore[return-value]

    def load_recent_offers(self, days: int = 14, limit: int = 2000) -> list[Offer]:
        """近 N 天活跃 Offer，作为转发合并候选。"""
        cutoff = iso(utcnow() - timedelta(days=days))
        rows = self.conn.execute(
            "SELECT o.*, COALESCE(o.provider_name, p.name) AS provider_name"
            " FROM offers o LEFT JOIN providers p ON p.id = o.provider_id"
            " WHERE o.status != 'expired' AND o.last_seen_at >= ?"
            " ORDER BY o.last_seen_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        return [_row_to_offer(r) for r in rows]

    def all_offers(self, vertical: str | None = None, limit: int = 5000) -> list[Offer]:
        sql = (
            "SELECT o.*, COALESCE(o.provider_name, p.name) AS provider_name,"
            " (SELECT COUNT(*) FROM offer_evidence e WHERE e.offer_id = o.id) AS evidence_count,"
            " COALESCE((SELECT MAX(score) FROM offer_evidence e WHERE e.offer_id = o.id), 0) AS offer_score"
            " FROM offers o LEFT JOIN providers p ON p.id = o.provider_id"
        )
        args: list = []
        if vertical:
            sql += " WHERE o.vertical = ?"
            args.append(vertical)
        sql += " ORDER BY o.last_seen_at DESC LIMIT ?"
        args.append(limit)
        return [_row_to_offer(r) for r in self.conn.execute(sql, args)]

    def vertical_stats(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT vertical, COUNT(*) AS total,"
            " SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,"
            " SUM(CASE WHEN offer_type IN ('always_free', 'free_tier') THEN 1 ELSE 0 END) AS always"
            " FROM offers GROUP BY vertical ORDER BY total DESC"
        ).fetchall()
        return [
            {
                "id": r["vertical"],
                "total": r["total"] or 0,
                "active": r["active"] or 0,
                "always_free": r["always"] or 0,
            }
            for r in rows
        ]

    def expire_offers(self, now=None, stale_days: int = 0) -> int:
        """统一的过期归档：只改状态，不删除。

        两条规则：
        1. 有明确截止时间且已过 → expired（reason=expires_at）；
        2. stale_days > 0 时，超过 N 天没有再被任何来源观察到 → expired（reason=stale）。
           全量目录源每轮都会刷新 last_seen，因此不会被误判；社区源长期没人再提
           才会落到这条规则。
        """
        now_dt = now or utcnow()
        cur = self.conn.execute(
            "UPDATE offers SET status='expired', status_reason='expires_at'"
            " WHERE status='active' AND expires_at != '' AND expires_at < ?",
            (iso(now_dt),),
        )
        count = cur.rowcount
        if stale_days > 0:
            cutoff = iso(now_dt - timedelta(days=stale_days))
            cur = self.conn.execute(
                "UPDATE offers SET status='expired', status_reason='stale'"
                " WHERE status='active' AND last_seen_at < ?",
                (cutoff,),
            )
            count += cur.rowcount
        self.conn.commit()
        return count

    def verify_offer(self, key: str, *, by: str = "user", now=None) -> bool:
        cur = self.conn.execute(
            "UPDATE offers SET last_verified_at = ?, verified_by = ? WHERE dedup_key = ?",
            (iso(now or utcnow()), by, key),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def record_signal(
        self, kind: str, *, vertical: str = "ai_api", source: str = "",
        page_url: str = "", provider_id: int | None = None,
        offer_id: int | None = None, payload: dict | None = None, now=None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO signals (kind, vertical, provider_id, offer_id, source, page_url,"
            " payload, observed_at) VALUES (?,?,?,?,?,?,?,?)",
            (kind, vertical, provider_id, offer_id, source, page_url,
             json.dumps(payload or {}, ensure_ascii=False), iso(now or utcnow())),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def recent_signals(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM signals ORDER BY observed_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {
                "id": r["id"], "kind": r["kind"], "vertical": r["vertical"],
                "source": r["source"], "page_url": r["page_url"],
                "payload": _json_obj(r["payload"], {}), "observed_at": r["observed_at"],
            }
            for r in rows
        ]

    def claims_map(self) -> dict[int, dict]:
        return {
            r["offer_id"]: {
                "state": r["state"], "claimed_at": r["claimed_at"],
                "expires_at": r["expires_at"], "note": r["note"],
            }
            for r in self.conn.execute("SELECT * FROM claims")
        }

    def set_claim(
        self, offer_id: int, state: str, *, note: str = "",
        account: str = "", expires_at: str = "", now=None,
    ) -> None:
        if state not in ("todo", "claimed", "rejected", "expired", "skipped"):
            raise ValueError(f"bad claim state: {state!r}")
        now_s = iso(now or utcnow())
        self.conn.execute(
            "INSERT INTO claims (offer_id, state, claimed_at, expires_at, account, note, updated_at)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(offer_id) DO UPDATE SET state=excluded.state,"
            " claimed_at=excluded.claimed_at, expires_at=excluded.expires_at,"
            " account=excluded.account, note=excluded.note, updated_at=excluded.updated_at",
            (
                offer_id, state, now_s if state == "claimed" else "",
                expires_at, account, note, now_s,
            ),
        )
        self.conn.commit()

    def vendor_summary(self) -> list[dict]:
        """统一厂商视图：从 offers 聚合，覆盖 AI 与云，不依赖 providers 表是否已导入。

        monitored/pages 来自 watchlist 快照；云厂商通常没有官网监控页，
        但仍有目录/官方页证据，因此照样出现在厂商列表里。
        """
        agg: dict[str, dict] = {}
        for r in self.conn.execute(
            "SELECT provider_name, vertical, category, status, last_seen_at"
            " FROM offers WHERE provider_name != ''"
        ):
            name = (r["provider_name"] or "").strip()
            if not name:
                continue
            key = name.lower()
            v = agg.setdefault(
                key,
                {
                    "name": name,
                    "verticals": {},
                    "categories": set(),
                    "offers": 0,
                    "active": 0,
                    "last_seen": "",
                },
            )
            v["offers"] += 1
            if r["status"] == "active":
                v["active"] += 1
            v["verticals"][r["vertical"]] = v["verticals"].get(r["vertical"], 0) + 1
            if r["category"]:
                v["categories"].add(r["category"])
            if (r["last_seen_at"] or "") > v["last_seen"]:
                v["last_seen"] = r["last_seen_at"] or ""

        pages: dict[str, int] = {}
        for r in self.conn.execute(
            "SELECT provider, COUNT(*) AS n FROM snapshots GROUP BY provider"
        ):
            pages[((r["provider"] or "").strip().lower())] = r["n"]

        out: list[dict] = []
        for key, v in agg.items():
            vertical = max(v["verticals"].items(), key=lambda kv: kv[1])[0]
            out.append(
                {
                    "name": v["name"],
                    "vertical": vertical,
                    "offers": v["offers"],
                    "active": v["active"],
                    "categories": sorted(v["categories"]),
                    "last_seen": v["last_seen"],
                    "monitored": key in pages,
                    "pages": pages.get(key, 0),
                }
            )
        out.sort(key=lambda x: (-x["offers"], x["name"].lower()))
        return out

    def offer_stats(self) -> dict:
        """Offer 层统计：活动数、状态、多来源合并数、未匹配厂商数。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,"
            " SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) AS expired,"
            " SUM(CASE WHEN provider_id IS NULL THEN 1 ELSE 0 END) AS unmatched"
            " FROM offers"
        ).fetchone()
        evidence = self.conn.execute("SELECT COUNT(*) AS n FROM offer_evidence").fetchone()["n"]
        merged = self.conn.execute(
            "SELECT COUNT(*) AS n FROM ("
            " SELECT offer_id FROM offer_evidence GROUP BY offer_id HAVING COUNT(*) > 1"
            ")"
        ).fetchone()["n"]
        return {
            "total": row["total"] or 0,
            "active": row["active"] or 0,
            "expired": row["expired"] or 0,
            "unmatched": row["unmatched"] or 0,
            "evidence": evidence,
            "merged": merged,
        }

    # ---------- feedback ----------

    def record_feedback(self, dedup_key: str, vote: str, note: str = "", now=None) -> None:
        """upsert：同一 deal 只留最新一次反馈；vote 传空串/None = 清除反馈。"""
        if vote not in ("up", "down", "snooze", ""):
            raise ValueError(f"bad vote: {vote!r}")
        now_s = iso(now or utcnow())
        if not vote:
            self.conn.execute("DELETE FROM feedback WHERE dedup_key = ?", (dedup_key,))
            self.conn.commit()
            return
        self.conn.execute(
            """
            INSERT INTO feedback (dedup_key, vote, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(dedup_key) DO UPDATE SET
                vote = excluded.vote,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (dedup_key, vote, note, now_s, now_s),
        )
        self.conn.commit()

    def feedback_map(self) -> dict[str, str]:
        """{dedup_key: vote}，dashboard 渲染时合并进 deal dict。"""
        rows = self.conn.execute("SELECT dedup_key, vote FROM feedback").fetchall()
        return {r["dedup_key"]: r["vote"] for r in rows}

    def feedback_stats(self) -> dict:
        """按来源统计 up/down/snooze 数量，用于关键词复盘面板。"""
        row = self.conn.execute(
            "SELECT "
            " SUM(CASE WHEN vote='up' THEN 1 ELSE 0 END) AS up,"
            " SUM(CASE WHEN vote='down' THEN 1 ELSE 0 END) AS down,"
            " SUM(CASE WHEN vote='snooze' THEN 1 ELSE 0 END) AS snooze,"
            " COUNT(*) AS total FROM feedback"
        ).fetchone()
        by_source = self.conn.execute(
            "SELECT o.source AS source, f.vote AS vote, COUNT(*) AS n"
            " FROM feedback f JOIN offers o ON o.dedup_key = f.dedup_key"
            " GROUP BY o.source, f.vote"
        ).fetchall()
        per_source: dict[str, dict[str, int]] = {}
        for r in by_source:
            per_source.setdefault(r["source"], {})[r["vote"]] = r["n"]
        return {
            "up": row["up"] or 0,
            "down": row["down"] or 0,
            "snooze": row["snooze"] or 0,
            "total": row["total"] or 0,
            "by_source": per_source,
        }

    # ---------- kv state ----------

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO state (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()