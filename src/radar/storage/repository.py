"""SQLite 持久层：Repository + StateStore 协议与唯一实现。

原则：
- 只归档不删除：过期 deal 置 status='expired'，历史可追溯；
- last_seen_at 每次见到都刷新，last_changed_at 只在有意义变化时刷新；
- snapshot_history 每轮追加，支撑 dashboard 的信号历史条形带；
- 运行记录 runs/source_runs 支撑故障隔离的可观测性。

collectors 只依赖 StateStore 协议（本模块定义），不感知 SQLite 实现。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain.dedup import find_fuzzy_match, make_key, norm_title
from ..domain.models import Deal, RunReport, ScoredItem, iso, utcnow

SCHEMA_VERSION = 4
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _row_to_deal(r: sqlite3.Row) -> Deal:
    return Deal(
        dedup_key=r["dedup_key"],
        source=r["source"],
        title=r["title"],
        url=r["url"],
        provider=r["provider"],
        amount_hint=r["amount_hint"],
        card_required_hint=None if r["card_required_hint"] is None else bool(r["card_required_hint"]),
        score=r["score"],
        evidence=r["evidence"],
        first_seen_at=r["first_seen_at"],
        last_seen_at=r["last_seen_at"],
        last_changed_at=r["last_changed_at"],
        status=r["status"],
        matched=json.loads(r["matched"] or "[]"),
        also_seen_in=json.loads(r["also_seen_in"] or "[]"),
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


class SqliteRepository(StateStore):
    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        self.conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        if version < SCHEMA_VERSION:
            if version >= 1:  # 旧库升级：补 matched 列（新库已在 DDL 里）
                try:
                    self.conn.execute("ALTER TABLE deals ADD COLUMN matched TEXT NOT NULL DEFAULT '[]'")
                except sqlite3.OperationalError:
                    pass  # 列已存在
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- aliases ----------

    def resolve_alias(self, key: str) -> str | None:
        """转发帖 key → 主条目 key（带环保护）。"""
        current = key
        for _ in range(5):
            row = self.conn.execute(
                "SELECT master_key FROM aliases WHERE aliased_key = ?", (current,)
            ).fetchone()
            if row is None:
                return None if current == key else current
            current = row["master_key"]
        return None

    def add_alias(self, aliased: str, master: str) -> None:
        if aliased == master:
            return
        self.conn.execute(
            "INSERT INTO aliases (aliased_key, master_key) VALUES (?, ?)"
            " ON CONFLICT(aliased_key) DO UPDATE SET master_key = excluded.master_key",
            (aliased, master),
        )
        self.conn.commit()

    # ---------- deals ----------

    def get_deal(self, key: str) -> Deal | None:
        row = self.conn.execute("SELECT * FROM deals WHERE dedup_key = ?", (key,)).fetchone()
        return _row_to_deal(row) if row else None

    def upsert_scored(
        self,
        scored: ScoredItem,
        now,
        fuzzy_candidates: list[Deal] | None = None,
    ) -> tuple[Deal, str]:
        """入库或合并。返回 (deal, action)：action ∈ new|updated|unchanged。

        合并规则：同 key 精确命中；否则在 fuzzy_candidates（近两周）里做标题
        模糊匹配，命中则合并进老条目（also_seen_in 记录额外来源）。
        """
        item = scored.item
        now_s = iso(now)
        key = make_key(item)

        # 已知的转发帖：直达主条目，只记"见到"，不算内容变化（幂等）
        master_key = self.resolve_alias(key)
        if master_key:
            existing = self.get_deal(master_key)
            if existing is not None:
                return self._merge_sighting(existing, scored, now_s), "unchanged"
            key = master_key  # 主条目不存在（被清理）则落到其 key 上重建
            existing = None
            via = "fuzzy"
        else:
            existing = self.get_deal(key)
            if existing is not None:
                via = "exact"
            elif fuzzy_candidates:
                match = find_fuzzy_match(item, fuzzy_candidates)
                if match is not None:
                    existing = match
                    key = match.dedup_key
                    via = "fuzzy"
                    self.add_alias(make_key(item), key)
                else:
                    via = "exact"
            else:
                via = "exact"

        if existing is None:
            deal = Deal(
                dedup_key=key,
                source=item.source,
                title=item.title,
                url=item.url,
                provider=item.provider,
                amount_hint=item.amount_hint,
                card_required_hint=item.card_required_hint,
                score=scored.score,
                evidence=item.evidence,
                first_seen_at=now_s,
                last_seen_at=now_s,
                last_changed_at=now_s,
                status="new",
                matched=list(scored.matched),
                also_seen_in=[],
            )
            self.conn.execute(
                "INSERT INTO deals (dedup_key, source, title, url, provider, amount_hint,"
                " card_required_hint, score, evidence, first_seen_at, last_seen_at,"
                " last_changed_at, status, matched, also_seen_in)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    deal.dedup_key, deal.source, deal.title, deal.url, deal.provider,
                    deal.amount_hint,
                    None if deal.card_required_hint is None else int(deal.card_required_hint),
                    deal.score, deal.evidence, deal.first_seen_at, deal.last_seen_at,
                    deal.last_changed_at, deal.status,
                    json.dumps(deal.matched, ensure_ascii=False), json.dumps(deal.also_seen_in),
                ),
            )
            self.conn.commit()
            return deal, "new"

        # ---- 合并进已有条目 ----
        also = list(existing.also_seen_in)
        if item.source != existing.source and item.source not in also:
            also.append(item.source)
        matched = list(existing.matched) + [m for m in scored.matched if m not in existing.matched]

        if via == "exact":
            # 同一 URL/主题：内容可演进（编辑、加码），标题允许更新
            title_changed = norm_title(item.title) != norm_title(existing.title)
            changed = (
                title_changed
                or (item.provider or "").lower() != (existing.provider or "").lower()
                or (item.amount_hint or "") != (existing.amount_hint or "")
            )
            title = item.title if title_changed else existing.title
        else:
            # 模糊合并：主条目标题锁定，只允许填补空缺字段——
            # 否则不同档位/转发的标题会来回覆盖主条目，破坏幂等
            title = existing.title
            provider_fill = bool(item.provider) and not existing.provider
            amount_fill = bool(item.amount_hint) and not existing.amount_hint
            changed = provider_fill or amount_fill
            title_changed = False

        revived = existing.status == "expired"

        status = existing.status
        if revived or changed:
            status = "updated"

        deal = Deal(
            dedup_key=key,
            source=existing.source,
            title=title,
            url=existing.url or item.url,
            provider=existing.provider or item.provider,
            amount_hint=existing.amount_hint or item.amount_hint,
            card_required_hint=(
                existing.card_required_hint
                if existing.card_required_hint is not None
                else item.card_required_hint
            ),
            score=max(existing.score, scored.score),
            evidence=item.evidence or existing.evidence,
            first_seen_at=existing.first_seen_at,
            last_seen_at=now_s,
            last_changed_at=now_s if (changed or revived) else existing.last_changed_at,
            status=status,
            matched=matched,
            also_seen_in=also,
        )
        self.conn.execute(
            "UPDATE deals SET title=?, url=?, provider=?, amount_hint=?, card_required_hint=?,"
            " score=?, evidence=?, last_seen_at=?, last_changed_at=?, status=?, matched=?,"
            " also_seen_in=? WHERE dedup_key=?",
            (
                deal.title, deal.url, deal.provider, deal.amount_hint,
                None if deal.card_required_hint is None else int(deal.card_required_hint),
                deal.score, deal.evidence, deal.last_seen_at, deal.last_changed_at,
                deal.status, json.dumps(deal.matched, ensure_ascii=False),
                json.dumps(deal.also_seen_in), key,
            ),
        )
        self.conn.commit()
        return deal, ("updated" if (changed or revived) else "unchanged")

    def _merge_sighting(self, existing: Deal, scored: ScoredItem, now_s: str) -> Deal:
        """转发帖 sighting：只补空缺字段并刷新 last_seen，不触发状态/时间变化。"""
        item = scored.item
        also = list(existing.also_seen_in)
        if item.source != existing.source and item.source not in also:
            also.append(item.source)
        matched = list(existing.matched) + [m for m in scored.matched if m not in existing.matched]
        deal = Deal(
            dedup_key=existing.dedup_key,
            source=existing.source,
            title=existing.title,
            url=existing.url or item.url,
            provider=existing.provider or item.provider,
            amount_hint=existing.amount_hint or item.amount_hint,
            card_required_hint=(
                existing.card_required_hint
                if existing.card_required_hint is not None
                else item.card_required_hint
            ),
            score=max(existing.score, scored.score),
            evidence=item.evidence or existing.evidence,
            first_seen_at=existing.first_seen_at,
            last_seen_at=now_s,
            last_changed_at=existing.last_changed_at,
            status=existing.status,
            matched=matched,
            also_seen_in=also,
        )
        self.conn.execute(
            "UPDATE deals SET url=?, provider=?, amount_hint=?, card_required_hint=?,"
            " score=?, evidence=?, last_seen_at=?, matched=?, also_seen_in=? WHERE dedup_key=?",
            (
                deal.url, deal.provider, deal.amount_hint,
                None if deal.card_required_hint is None else int(deal.card_required_hint),
                deal.score, deal.evidence, deal.last_seen_at,
                json.dumps(deal.matched, ensure_ascii=False), json.dumps(deal.also_seen_in),
                deal.dedup_key,
            ),
        )
        self.conn.commit()
        return deal

    def load_recent_deals(self, days: int) -> list[Deal]:
        """近 N 天活跃 deal，作为模糊去重候选。"""
        cutoff = iso(utcnow() - timedelta(days=days))
        rows = self.conn.execute(
            "SELECT * FROM deals WHERE status != 'expired' AND last_seen_at >= ?"
            " ORDER BY last_seen_at DESC LIMIT 2000",
            (cutoff,),
        ).fetchall()
        return [_row_to_deal(r) for r in rows]

    def all_deals(self, limit: int = 3000) -> list[Deal]:
        """全量 deal（含过期），dashboard 数据源。"""
        rows = self.conn.execute(
            "SELECT * FROM deals ORDER BY last_changed_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_deal(r) for r in rows]

    def expire_old(self, days: int, now=None) -> int:
        cutoff = iso((now or utcnow()) - timedelta(days=days))
        cur = self.conn.execute(
            "UPDATE deals SET status='expired' WHERE status != 'expired' AND last_seen_at < ?",
            (cutoff,),
        )
        self.conn.commit()
        return cur.rowcount

    def mark_expired(self, key: str) -> bool:
        cur = self.conn.execute(
            "UPDATE deals SET status='expired' WHERE dedup_key = ? AND status != 'expired'",
            (key,),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def digest_data(self, now) -> dict:
        c7 = iso(now - timedelta(days=7))
        c30 = iso(now - timedelta(days=30))
        q = "SELECT * FROM deals WHERE {} ORDER BY {} LIMIT ?"
        new = self.conn.execute(
            q.format("status != 'expired' AND first_seen_at >= ?", "score DESC, first_seen_at DESC"),
            (c7, 200),
        ).fetchall()
        updated = self.conn.execute(
            q.format(
                "status != 'expired' AND last_changed_at >= ? AND first_seen_at < ?",
                "last_changed_at DESC",
            ),
            (c7, c7, 200),
        ).fetchall()
        needs_review = self.conn.execute(
            "SELECT * FROM deals WHERE status != 'expired' AND last_seen_at < ?"
            " ORDER BY last_seen_at ASC LIMIT 100",
            (c30,),
        ).fetchall()
        expired_recent = self.conn.execute(
            q.format("status = 'expired' AND last_changed_at >= ?", "last_changed_at DESC"),
            (c30, 50),
        ).fetchall()
        totals = self.conn.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN status != 'expired' THEN 1 ELSE 0 END) AS active,"
            " SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) AS expired"
            " FROM deals"
        ).fetchone()
        return {
            "new_deals": [_row_to_deal(r) for r in new],
            "updated_deals": [_row_to_deal(r) for r in updated],
            "needs_review": [_row_to_deal(r) for r in needs_review],
            "expired_recent": [_row_to_deal(r) for r in expired_recent],
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
                                   last_checked_at, last_changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                provider = excluded.provider,
                label = excluded.label,
                content_hash = excluded.content_hash,
                promo_keywords = excluded.promo_keywords,
                last_checked_at = excluded.last_checked_at,
                last_changed_at = CASE WHEN snapshots.content_hash != excluded.content_hash
                                       THEN excluded.last_checked_at
                                       ELSE snapshots.last_changed_at END
            """,
            (url, provider, label, content_hash, promo_keywords, now_s, now_s),
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
                len(report.new_deals),
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
            "SELECT d.source AS source, f.vote AS vote, COUNT(*) AS n"
            " FROM feedback f JOIN deals d ON d.dedup_key = f.dedup_key"
            " GROUP BY d.source, f.vote"
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
