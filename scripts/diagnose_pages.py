"""P0-1 诊断：列出无监控页的 Provider，并判断原因。

只读：输出分类统计与明细，不改配置、不改库。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar.domain.domains import registrable_domain  # noqa: E402
from radar.infra.config import load_config, load_providers  # noqa: E402
from radar.storage.repository import SqliteRepository  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> None:
    cfg = load_config()
    repo = SqliteRepository(cfg.data_dir / "radar.db")

    domain_owner = {
        r["domain"]: r["provider_id"]
        for r in repo.conn.execute("SELECT domain, provider_id FROM provider_domains")
    }
    linked: set[int] = set()
    snap_domains: set[str] = set()
    for r in repo.conn.execute("SELECT url FROM snapshots"):
        d = registrable_domain(r["url"])
        if not d:
            continue
        snap_domains.add(d)
        pid = domain_owner.get(d)
        if pid is not None:
            linked.add(pid)

    rows = [
        r
        for r in repo.conn.execute(
            "SELECT p.id, p.slug, p.name, p.status, p.category,"
            " (SELECT COUNT(*) FROM provider_domains d WHERE d.provider_id = p.id) AS n_dom"
            " FROM providers p WHERE p.status != 'ignored' ORDER BY p.status, p.name"
        )
        if r["id"] not in linked
    ]
    providers = load_providers(cfg.providers_file)
    by_name = {norm(p["name"]): p for p in providers}
    by_domain: dict[str, dict] = {}
    for p in providers:
        for u in p.get("urls", []):
            d = registrable_domain(u["url"])
            if d:
                by_domain.setdefault(d, p)

    buckets = {"no_watchlist_entry": [], "no_urls": [], "never_fetched": [], "fetched_but_unlinked": []}
    details = []
    for r in rows:
        p = by_name.get(norm(r["name"]))
        if p is None:
            # 尝试用域名找
            for d in repo.conn.execute(
                "SELECT domain FROM provider_domains WHERE provider_id = ?", (r["id"],)
            ):
                p = by_domain.get(d["domain"])
                if p:
                    break
        if p is None:
            buckets["no_watchlist_entry"].append(r)
            reason = "清单里没有"
        else:
            urls = p.get("urls") or []
            if not urls:
                buckets["no_urls"].append(r)
                reason = "清单条目无 URL"
            else:
                doms = {registrable_domain(u["url"]) for u in urls}
                doms.discard(None)
                if doms & snap_domains:
                    buckets["fetched_but_unlinked"].append(r)
                    reason = "有快照但域名不在 provider_domains"
                else:
                    buckets["never_fetched"].append(r)
                    reason = "有 URL，从未抓到快照"
        details.append((r["status"], r["name"], r["category"], reason))

    print(f"total_no_pages={len(rows)}")
    for k, v in buckets.items():
        print(f"{k}={len(v)}")
    print("--- details ---")
    for status, name, cat, reason in details:
        print(f"{status}\t{name}\t{cat}\t{reason}")
    repo.close()


if __name__ == "__main__":
    main()