"""迁移脚本：把历史 deals（只读）转成统一 Offer。

v10 起 `radar run` 直接写 offers，deals 不再产生新数据。本脚本只用于：
- 首次升级时把已有 deals 回填成规范 Offer + 证据；
- 需要重建 AI 侧 Offer 时手动执行。

云资源 Offer 不受影响（只处理 AI 侧）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar.domain.models import RawItem, ScoredItem, utcnow  # noqa: E402
from radar.domain.offer_infer import apply_ai_offer  # noqa: E402
from radar.infra.config import load_config  # noqa: E402
from radar.storage.repository import SqliteRepository  # noqa: E402


def build_offers(repo: SqliteRepository, now=None, force: bool = False) -> dict:
    """把 deals 回填为 Offer；幂等（默认只在 AI 侧为空时迁移）。"""
    now = now or utcnow()
    existing = repo.conn.execute(
        "SELECT COUNT(*) FROM offers WHERE vertical = 'ai_api'"
    ).fetchone()[0]
    if existing and not force:
        # 已迁移过：不重复删除/重建，避免覆盖 run 写入的最新观察时间
        return {
            "offers": existing,
            "evidence": repo.conn.execute("SELECT COUNT(*) FROM offer_evidence").fetchone()[0],
            "merged": 0,
            "unmatched": 0,
            "skipped": True,
        }
    repo.conn.execute("DELETE FROM offers WHERE vertical = 'ai_api'")
    repo.conn.execute("DELETE FROM offer_evidence WHERE offer_id NOT IN (SELECT id FROM offers)")
    repo.conn.commit()

    candidates = repo.load_recent_offers(days=3650)
    stats = {"offers": 0, "evidence": 0, "merged": 0, "unmatched": 0}
    active_keys: set[str] = set()
    for d in repo.conn.execute("SELECT * FROM deals ORDER BY first_seen_at"):
        item = RawItem(
            source=d["source"],
            title=d["title"],
            url=d["url"] or "",
            provider=d["provider"],
            amount_hint=d["amount_hint"],
            card_required_hint=(
                None if d["card_required_hint"] is None else bool(d["card_required_hint"])
            ),
            evidence=d["evidence"] or "",
        )
        scored = ScoredItem(
            item=item,
            score=d["score"] or 0.0,
            matched=json.loads(d["matched"] or "[]"),
        )
        offer_item = apply_ai_offer(item, scored)
        offer, action = repo.upsert_offer(
            offer_item, now, fuzzy_candidates=candidates,
            score=scored.score, matched=scored.matched,
        )
        if action == "new":
            stats["offers"] += 1
            candidates.append(offer)
        if d["status"] != "expired" and offer is not None:
            active_keys.add(offer.dedup_key)

    # 只有 expired deal 作为证据的 Offer 也归档
    for row in repo.conn.execute("SELECT dedup_key FROM offers WHERE vertical = 'ai_api'"):
        if row["dedup_key"] not in active_keys:
            repo.conn.execute(
                "UPDATE offers SET status='expired', status_reason='legacy_deal_expired'"
                " WHERE dedup_key = ?",
                (row["dedup_key"],),
            )
    repo.conn.commit()

    total = repo.conn.execute("SELECT COUNT(*) FROM offer_evidence").fetchone()[0]
    merged = repo.conn.execute(
        "SELECT COUNT(*) FROM (SELECT offer_id FROM offer_evidence"
        " GROUP BY offer_id HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    unmatched = repo.conn.execute(
        "SELECT COUNT(*) FROM offers WHERE provider_id IS NULL"
    ).fetchone()[0]
    stats.update({"evidence": total, "merged": merged, "unmatched": unmatched})
    return stats


def main() -> None:
    cfg = load_config()
    repo = SqliteRepository(cfg.data_dir / "radar.db")
    stats = build_offers(repo)
    print(
        f"offers={stats['offers']} evidence={stats['evidence']} "
        f"merged={stats['merged']} unmatched={stats['unmatched']}"
    )
    repo.close()


if __name__ == "__main__":
    main()