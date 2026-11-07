"""Day 14：把厂商宇宙导入 Provider 实体表（schema v7）。

输入：data/universe/universe_annotated_v0.json
- 只导入代表条目（duplicate_of 为空），同品牌重复条目转为别名/来源；
- 非厂商（vendor_like=False）入库但 status=ignored，不进覆盖率分母；
- 幂等：重复运行不新增行，slug 不变，域名/别名冲突不抢占。

输出：data/radar.db 的 providers / provider_domains / provider_aliases / provider_sources
      + docs/discovery/PROVIDER_IMPORT_v0.md
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar.domain.domains import registrable_domain  # noqa: E402
from radar.domain.models import iso, utcnow  # noqa: E402
from radar.infra.config import load_config, load_providers  # noqa: E402
from radar.storage.repository import SqliteRepository  # noqa: E402

SRC = ROOT / "data/universe/universe_annotated_v0.json"
OUT_MD = ROOT / "data/universe/provider_import.md"


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _pick_slug(conn, rep: dict) -> str:
    """稳定的 slug：优先 brand_key，其次原 slug/名称；同名占用视为自己（幂等）。"""
    base = _slugify(rep.get("brand_key") or rep.get("slug") or rep["name"])
    candidates = [base, _slugify(rep.get("slug") or "")]
    for cand in candidates:
        if not cand:
            continue
        row = conn.execute("SELECT name FROM providers WHERE slug = ?", (cand,)).fetchone()
        if row is None or row["name"] == rep["name"]:
            return cand
    i = 2
    while True:
        cand = f"{base}-{i}"
        row = conn.execute("SELECT name FROM providers WHERE slug = ?", (cand,)).fetchone()
        if row is None or row["name"] == rep["name"]:
            return cand
        i += 1


def _alias_tokens(rec: dict) -> set[str]:
    out = {_slugify(rec.get("name") or ""), _slugify(rec.get("slug") or "")}
    out.discard("")
    return out


def import_records(conn, entries: list[dict], now=None, watch_domains=None) -> dict:
    now_s = iso(now or utcnow())
    watch_domains = watch_domains or {}
    # 宇宙是全量输入，重建而不是增量：避免归并规则变化后残留旧行。
    for table in ("provider_sources", "provider_aliases", "provider_domains", "providers"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()

    reps = [r for r in entries if not r.get("duplicate_of")]
    dups: dict[str, list[dict]] = {}
    for r in entries:
        if r.get("duplicate_of"):
            dups.setdefault(r["duplicate_of"], []).append(r)

    stats = {
        "providers": 0, "monitored": 0, "ignored": 0, "in_universe": 0,
        "domains": 0, "aliases": 0, "sources": 0, "watch_domains": 0,
    }
    conflicts = {"domain": [], "alias": [], "slug": []}

    for rep in reps:
        slug = _pick_slug(conn, rep)
        if slug != _slugify(rep.get("brand_key") or rep.get("slug") or rep["name"]):
            conflicts["slug"].append((rep["name"], slug))

        status = (
            "ignored" if not rep.get("vendor_like")
            else "monitored" if rep.get("monitored")
            else "in_universe"
        )
        conn.execute(
            """
            INSERT INTO providers
                (slug, name, category, regions, relevance, confidence, status,
                 vendor_like, brand_key, first_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                category = excluded.category,
                regions = excluded.regions,
                relevance = excluded.relevance,
                confidence = excluded.confidence,
                status = excluded.status,
                vendor_like = excluded.vendor_like,
                brand_key = excluded.brand_key,
                updated_at = excluded.updated_at
            """,
            (
                slug, rep["name"], rep["category"], json.dumps(rep["regions"], ensure_ascii=False),
                float(rep["relevance"]), rep["confidence"], status,
                1 if rep.get("vendor_like") else 0, rep.get("brand_key") or "",
                now_s, now_s,
            ),
        )
        pid = conn.execute("SELECT id FROM providers WHERE slug = ?", (slug,)).fetchone()["id"]
        stats["providers"] += 1
        stats[status] = stats.get(status, 0) + 1

        members = [rep] + dups.get(rep["slug"], [])

        domains: set[str] = set()
        aliases: set[tuple[str, str]] = set()
        sources: dict[str, str] = {}
        for item in members:
            domains |= set(item.get("domains") or [])
            for tok in _alias_tokens(item):
                aliases.add((tok, "name"))
            for d in item.get("domains") or []:
                aliases.add((_slugify(d), "domain"))
            for s in item.get("sources") or []:
                sources[s] = now_s

        # 监控清单里存在、但 4 个发现来源都没收录（HF 外圈 / 人工补录）。
        if not sources and rep.get("monitored"):
            sources["watchlist"] = now_s

        # 用 watchlist 的 URL 补 Provider 域名：宇宙里只有 8 条有快照但缺域名。
        if watch_domains:
            matched: set[str] = set()
            for key in (_norm(rep["name"]), _norm(rep.get("brand_key")), _norm(rep.get("slug"))):
                if key and watch_domains.get(key):
                    matched = watch_domains[key]
                    break
            if matched - domains:
                domains |= matched
                stats["watch_domains"] += 1

        for d in sorted(domains):
            owner = conn.execute(
                "SELECT provider_id FROM provider_domains WHERE domain = ?", (d,)
            ).fetchone()
            if owner is None:
                conn.execute(
                    "INSERT INTO provider_domains (domain, provider_id, is_primary) VALUES (?, ?, 1)",
                    (d, pid),
                )
                stats["domains"] += 1
            elif owner["provider_id"] != pid:
                conflicts["domain"].append((d, rep["name"], owner["provider_id"]))

        for alias, kind in sorted(aliases):
            if not alias:
                continue
            owner = conn.execute(
                "SELECT provider_id FROM provider_aliases WHERE alias = ?", (alias,)
            ).fetchone()
            if owner is None:
                conn.execute(
                    "INSERT INTO provider_aliases (alias, provider_id, kind) VALUES (?, ?, ?)",
                    (alias, pid, kind),
                )
                stats["aliases"] += 1
            elif owner["provider_id"] != pid:
                conflicts["alias"].append((alias, rep["name"], owner["provider_id"]))

        for source, seen in sources.items():
            conn.execute(
                """
                INSERT INTO provider_sources (provider_id, source, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider_id, source) DO UPDATE SET last_seen_at = excluded.last_seen_at
                """,
                (pid, source, seen, seen),
            )
            stats["sources"] += 1

    conn.commit()
    return {"stats": stats, "conflicts": conflicts}


def main() -> None:
    cfg = load_config()
    repo = SqliteRepository(cfg.data_dir / "radar.db")
    data = json.loads(SRC.read_text(encoding="utf-8"))
    providers = load_providers(cfg.providers_file)
    watch_domains: dict[str, set[str]] = {}
    for p in providers:
        doms = {registrable_domain(u["url"]) for u in p.get("urls") or []}
        doms.discard(None)
        if doms:
            watch_domains.setdefault(_norm(p["name"]), set()).update(doms)
    result = import_records(repo.conn, data["entries"], watch_domains=watch_domains)
    sql = repo.provider_stats()
    stats = result["stats"]
    conflicts = result["conflicts"]

    # 与标注脚本口径对账：代表条目里真厂商 / 已监控
    reps = [r for r in data["entries"] if not r.get("duplicate_of")]
    vendor_reps = [r for r in reps if r.get("vendor_like")]
    vendor_monitored = [r for r in vendor_reps if r.get("monitored")]
    script_cov = len(vendor_monitored) / len(vendor_reps) if vendor_reps else 0.0

    lines = [
        "# Provider 实体导入 v0（Day 14）\n",
        "> 输入：`universe_annotated_v0.json`（425 条 → 代表 385 条）。",
        "> 目标：`data/radar.db` 的 4 张 v7 新表；旧表未改动。\n",
        "## 导入结果\n",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| providers | {stats['providers']} |",
        f"| monitored | {stats['monitored']} |",
        f"| in_universe | {stats['in_universe']} |",
        f"| ignored（非厂商） | {stats['ignored']} |",
        f"| provider_domains | {stats['domains']} |",
        f"| 其中 watchlist 补域名 | {stats['watch_domains']} |",
        f"| provider_aliases | {stats['aliases']} |",
        f"| provider_sources | {stats['sources']} |\n",
        "## 覆盖率对账\n",
        "| 口径 | 分母 | 分子 | 覆盖率 |",
        "|---|---:|---:|---:|",
        f"| 宇宙脚本（未去重、含非厂商） | {len(data['entries'])} | "
        f"{sum(1 for r in data['entries'] if r.get('monitored'))} | "
        f"{sum(1 for r in data['entries'] if r.get('monitored')) / len(data['entries']):.1%} |",
        f"| 代表条目（真厂商） | {len(vendor_reps)} | {len(vendor_monitored)} | {script_cov:.1%} |",
        f"| SQL（排除 ignored） | {sql['universe']} | {sql['monitored']} | {sql['coverage']:.1%} |\n",
        "> 差异来自两点：同品牌重复条目被归并（425 → 385），非厂商不计入分母（376）。",
        "> SQL 口径是落库后的正式口径。\n",
        "## 冲突\n",
        f"- 域名冲突：**{len(conflicts['domain'])}**（不抢占，保留原 owner）",
        f"- 别名冲突：**{len(conflicts['alias'])}**",
        f"- slug 避让：**{len(conflicts['slug'])}**\n",
    ]
    if conflicts["domain"]:
        lines += ["### 域名冲突明细\n", "| 域名 | 新厂商 | 已有 provider_id |", "|---|---|---:|"]
        lines += [f"| {d} | {name} | {owner} |" for d, name, owner in conflicts["domain"][:30]]
        lines.append("")
    if conflicts["alias"]:
        lines += ["### 别名冲突明细\n", "| 别名 | 新厂商 | 已有 provider_id |", "|---|---|---:|"]
        lines += [f"| {a} | {name} | {owner} |" for a, name, owner in conflicts["alias"][:30]]
        lines.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    repo.close()

    print(
        f"providers={stats['providers']} monitored={stats['monitored']} "
        f"in_universe={stats['in_universe']} ignored={stats['ignored']} "
        f"domains={stats['domains']} aliases={stats['aliases']} sources={stats['sources']}"
    )
    print(
        f"sql_universe={sql['universe']} sql_monitored={sql['monitored']} "
        f"coverage={sql['coverage']:.1%} script_cov={script_cov:.1%}"
    )
    print(
        f"conflicts domain={len(conflicts['domain'])} alias={len(conflicts['alias'])} "
        f"slug={len(conflicts['slug'])}"
    )


if __name__ == "__main__":
    main()