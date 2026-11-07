"""A1：从 deals 生成 Offer 实体（schema v8）。

一个 Offer = 某厂商的一个促销活动；deals 是它的证据。
归并键：provider_id + 金额 + 标题归一。全量重建，幂等。

输出：data/radar.db 的 offers / offer_evidence
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar.domain.dedup import norm_title  # noqa: E402
from radar.domain.domains import registrable_domain  # noqa: E402
from radar.domain.models import iso, utcnow  # noqa: E402
from radar.infra.config import load_config  # noqa: E402
from radar.storage.repository import SqliteRepository  # noqa: E402


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _resolve(conn, name: str, url: str) -> int | None:
    alias = _slug(name)
    if alias:
        row = conn.execute(
            "SELECT provider_id FROM provider_aliases WHERE alias = ?", (alias,)
        ).fetchone()
        if row:
            return row["provider_id"]
    dom = registrable_domain(url or "")
    if dom:
        row = conn.execute(
            "SELECT provider_id FROM provider_domains WHERE domain = ?", (dom,)
        ).fetchone()
        if row:
            return row["provider_id"]
    return None


def build_offers(conn, now=None) -> dict:
    now_s = iso(now or utcnow())
    conn.execute("DELETE FROM offer_evidence")
    conn.execute("DELETE FROM offers")

    groups: dict[str, dict] = {}
    for d in conn.execute("SELECT * FROM deals"):
        pid = _resolve(conn, d["provider"] or "", d["url"] or "")
        key = f"{pid if pid is not None else 'x'}|{_slug(d['amount_hint'] or '')}|{norm_title(d['title'] or '')}"
        g = groups.setdefault(key, {
            "provider_id": pid,
            "title": d["title"],
            "amount": d["amount_hint"] or "",
            "statuses": set(),
            "first": d["first_seen_at"],
            "last": d["last_seen_at"],
            "evidence": [],
        })
        g["statuses"].add(d["status"])
        g["first"] = min(g["first"], d["first_seen_at"])
        g["last"] = max(g["last"], d["last_seen_at"])
        g["evidence"].append((d["dedup_key"], d["url"] or "", d["source"] or "", d["last_seen_at"]))

    for key, g in groups.items():
        if g["statuses"] & {"new", "active"}:
            status = "active"
        elif g["statuses"] == {"expired"}:
            status = "expired"
        else:
            status = "unknown"
        conn.execute(
            "INSERT INTO offers (provider_id, title, amount_hint, status,"
            " first_seen_at, last_seen_at, dedup_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (g["provider_id"], g["title"], g["amount"], status, g["first"], g["last"], key),
        )
        oid = conn.execute("SELECT id FROM offers WHERE dedup_key = ?", (key,)).fetchone()["id"]
        for deal_key, url, source, seen in g["evidence"]:
            conn.execute(
                "INSERT OR IGNORE INTO offer_evidence (offer_id, deal_key, url, source, seen_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (oid, deal_key, url, source, seen),
            )
    conn.commit()
    return {
        "offers": len(groups),
        "evidence": sum(len(g["evidence"]) for g in groups.values()),
        "merged": sum(1 for g in groups.values() if len(g["evidence"]) > 1),
        "unmatched": sum(1 for g in groups.values() if g["provider_id"] is None),
    }


def main() -> None:
    cfg = load_config()
    repo = SqliteRepository(cfg.data_dir / "radar.db")
    stats = build_offers(repo.conn)
    print(
        f"offers={stats['offers']} evidence={stats['evidence']} "
        f"merged={stats['merged']} unmatched={stats['unmatched']}"
    )
    repo.close()


if __name__ == "__main__":
    main()