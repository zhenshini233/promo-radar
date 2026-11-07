"""P0-1 调度引导：把 monitored 但从未抓过的页排到本轮。

只改 snapshots 的调度字段（next_check_at/tier），不写内容；
下一轮 watchlist 会真实抓取并更新 content_hash。
"""

from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar.domain.domains import registrable_domain  # noqa: E402
from radar.domain.models import iso, utcnow  # noqa: E402
from radar.infra.config import load_config, load_providers  # noqa: E402
from radar.storage.repository import SqliteRepository  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> None:
    cfg = load_config()
    repo = SqliteRepository(cfg.data_dir / "radar.db")
    now = utcnow()
    past = iso(now - timedelta(minutes=1))

    owners = {
        r["domain"]: r["provider_id"]
        for r in repo.conn.execute("SELECT domain, provider_id FROM provider_domains")
    }
    linked = {
        owners[registrable_domain(r["url"])]
        for r in repo.conn.execute("SELECT url FROM snapshots")
        if registrable_domain(r["url"]) in owners
    }
    missing = [
        r
        for r in repo.conn.execute(
            "SELECT id, slug, name FROM providers WHERE status = 'monitored'"
        )
        if r["id"] not in linked
    ]

    providers = load_providers(cfg.providers_file)
    by_name = {norm(p["name"]): p for p in providers}
    by_domain: dict[str, dict] = {}
    for p in providers:
        for u in p.get("urls") or []:
            d = registrable_domain(u["url"])
            if d:
                by_domain.setdefault(d, p)

    queued = 0
    skipped: list[str] = []
    for r in missing:
        p = by_name.get(norm(r["name"]))
        if p is None:
            doms = [
                x["domain"]
                for x in repo.conn.execute(
                    "SELECT domain FROM provider_domains WHERE provider_id = ?", (r["id"],)
                )
            ]
            for d in doms:
                p = by_domain.get(d)
                if p is not None:
                    break
        if p is None or not p.get("urls"):
            skipped.append(r["name"])
            continue
        for u in p["urls"]:
            repo.conn.execute(
                """
                INSERT INTO snapshots
                    (url, provider, label, content_hash, promo_keywords,
                     last_checked_at, last_changed_at, fail_count, last_error,
                     tier, next_check_at)
                VALUES (?, ?, ?, '', '', ?, ?, 0, '', 1, ?)
                ON CONFLICT(url) DO UPDATE SET
                    tier = 1,
                    next_check_at = excluded.next_check_at
                """,
                (
                    u["url"], r["name"], u.get("label", ""),
                    past, past, past,
                ),
            )
            queued += 1
    repo.conn.commit()
    repo.close()
    print(f"queued_urls={queued} providers={len(missing) - len(skipped)} skipped={len(skipped)}")
    if skipped:
        print("skipped:", ", ".join(skipped))


if __name__ == "__main__":
    main()