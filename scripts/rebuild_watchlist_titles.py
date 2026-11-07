"""一次性迁移：用新标题规则刷新老的 watchlist deal。

老标题形如 "[Modal] 页面出现促销信号: free credit, free credits"
新标题形如 "Modal — free credit"。
从 snapshots.promo_keywords 拿当前命中的关键词，按 _best_promo_phrase 重算。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from radar.collectors.watchlist import _best_promo_phrase
from radar.infra.config import load_config
from radar.storage.repository import SqliteRepository


def main() -> None:
    cfg = load_config(None)
    repo = SqliteRepository(cfg.data_dir / "radar.db")
    conn = repo.conn
    rows = conn.execute(
        "SELECT dedup_key, url, provider FROM deals WHERE source = 'watchlist'"
    ).fetchall()
    updated = 0
    for r in rows:
        snap = conn.execute(
            "SELECT promo_keywords FROM snapshots WHERE url = ?", (r["url"],)
        ).fetchone()
        if not snap:
            continue
        hits = [h for h in snap["promo_keywords"].split(";;") if h]
        if not hits:
            continue
        new_title = f"{r['provider']} — {_best_promo_phrase(hits)}"
        if new_title != r["dedup_key"]:  # dedup_key 是 key_override，不是 title；这里只是判断非空
            conn.execute(
                "UPDATE deals SET title = ? WHERE dedup_key = ?",
                (new_title, r["dedup_key"]),
            )
            updated += 1
    conn.commit()
    print(f"updated {updated}/{len(rows)} watchlist deal titles")


if __name__ == "__main__":
    main()
