"""Day 3：只读生成厂商宇宙基线报告。

不修改数据库。读取 state 表、deals 表、providers.toml：
- 各来源厂商规模
- 两两重叠（Jaccard）与独有厂商率
- 宇宙规模 / 已监控覆盖率
- 盲区 Top 50
- 监控中但不在宇宙（疑似误收编）
输出：docs/discovery/UNIVERSE_REPORT_v0.md + data/universe/universe_v0.json
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from radar.domain.brands import BRANDS
from radar.domain.domains import registrable_domain
from radar.infra.config import load_config, load_providers

OUT_MD = Path("data/universe/universe_snapshot.md")
OUT_JSON = Path("data/universe/universe_v0.json")

IGNORE_DOMAINS = {
    "aicredits.dev", "aicredits.tech", "openrouter.ai", "models.dev",
    "github.com", "huggingface.co", "artificialanalysis.ai",
    "linux.do", "ycombinator.com", "news.ycombinator.com", "reddit.com",
    "x.com", "twitter.com", "discord.com", "medium.com", "youtube.com",
    # 政府/学术/公共机构域：按口径排除，不作为厂商
    "europa.eu", "gov.uk", "gov.sg", "ac.uk", "edu.cn", "gov.cn",
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


@dataclass
class UniverseBuild:
    """一次宇宙构建的完整结果，供报告与标注脚本共用。"""

    universe: dict[str, dict]
    source_sets: dict[str, set[str]]
    providers: list[dict]
    ignored: set[str]


def build_universe(cfg) -> UniverseBuild:
    """只读构建厂商宇宙：4 个现有来源 + 别名/域名映射 + 监控匹配。"""
    db_path = cfg.data_dir / "radar.db"
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    def state(key: str):
        row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    openrouter_vendors = json.loads(state("openrouter:vendors") or "{}")
    openrouter_providers = json.loads(state("openrouter:providers") or "{}")
    modelsdev = json.loads(state("modelsdev:providers") or "{}")
    litellm = json.loads(state("litellm:prices") or "{}")

    entries: dict[str, dict] = {}
    name_index: dict[str, str] = {}
    source_sets: dict[str, set[str]] = defaultdict(set)

    alias_path = Path("docs/discovery/aliases.json")
    alias_data = json.loads(alias_path.read_text(encoding="utf-8")) if alias_path.exists() else {}
    aliases: dict[str, str] = alias_data.get("aliases", {})
    domain_map: dict[str, list[str]] = alias_data.get("domains", {})
    display_names: dict[str, str] = alias_data.get("names", {})
    ignored: set[str] = set(alias_data.get("ignored", {}))

    # 先按人工映射预建 canonical 条目，把官网补齐
    for slug, doms in domain_map.items():
        entries[slug] = {
            "name": display_names.get(slug) or slug.title(),
            "domains": {registrable_domain(d if "://" in d else f"https://{d}") or d for d in doms},
            "sources": set(),
        }
        name_index[slug] = slug

    def add(name: str, domain: str | None, source: str) -> str | None:
        name = (name or "").strip()
        n = norm(name)
        if n in ignored:
            return None
        if not name and not domain:
            return None
        key = aliases.get(n) or name_index.get(n)
        if key is None:
            key = domain or n
            if not key:
                return None
            entries.setdefault(key, {"name": "", "domains": set(), "sources": set()})
            if n:
                name_index[n] = key
        e = entries[key]
        if not e.get("name") and name:
            e["name"] = name
        if domain:
            e["domains"].add(domain)
        if key in domain_map:
            e["domains"] |= set(domain_map[key])
        e["sources"].add(source)
        source_sets[source].add(key)
        return key

    # 1) models.dev：有 label + doc，先建域名主键
    for pid, info in modelsdev.items():
        if not isinstance(info, dict):
            continue
        label = str(info.get("label") or pid)
        domain = registrable_domain(str(info.get("doc") or ""))
        add(label, domain, "modelsdev")

    # 2) LiteLLM：provider 名；用品牌表补域名
    for _model, info in litellm.items():
        if not isinstance(info, dict):
            continue
        p = str(info.get("p") or "").strip()
        if not p:
            continue
        brand = BRANDS.get(norm(p))
        if brand:
            add(brand[0], registrable_domain(brand[1]), "litellm")
        else:
            add(p, None, "litellm")

    # 3) OpenRouter：模型供应商 slug + 上游托管商
    for slug, info in openrouter_vendors.items():
        label = str((info or {}).get("name") or slug)
        brand = BRANDS.get(norm(slug))
        add(brand[0] if brand else label, registrable_domain(brand[1]) if brand else None, "openrouter")
    for slug, info in openrouter_providers.items():
        label = str((info or {}).get("name") or slug)
        add(label, None, "openrouter")

    # 4) aicredits：provider + 来源链接域名
    for row in conn.execute("SELECT provider, url FROM deals WHERE source = 'aicredits'"):
        add(str(row["provider"] or ""), registrable_domain(str(row["url"] or "")), "aicredits")

    # 5) 监控清单
    providers = load_providers(cfg.providers_file)
    mon_names = {norm(p["name"]) for p in providers if p.get("name")}
    mon_domains = {
        registrable_domain(u["url"]) for p in providers for u in p.get("urls", [])
    }
    mon_domains.discard(None)

    for key, e in entries.items():
        names = {norm(e["name"])} | {norm(a) for a in e.get("aliases", [])}
        # 严格匹配：注册域精确 / 名称精确。包含匹配会把 "AI" 之类误判为已监控。
        matched = bool(e["domains"] & mon_domains) or bool(names & mon_names)
        e["monitored"] = matched

    universe = {
        k: v for k, v in entries.items()
        if k not in ignored and not (v["domains"] & IGNORE_DOMAINS)
    }
    conn.close()
    return UniverseBuild(
        universe=universe,
        source_sets=source_sets,
        providers=providers,
        ignored=ignored,
    )


def main() -> None:
    cfg = load_config()
    built = build_universe(cfg)
    universe = built.universe
    source_sets = built.source_sets
    providers = built.providers
    ignored = built.ignored

    total = len(universe)
    monitored = sum(1 for e in universe.values() if e["monitored"])
    coverage = monitored / total if total else 0.0

    # 来源规模 / 独有率
    source_stats = []
    all_keys = set(universe)
    for src, keys in sorted(source_sets.items()):
        keys = keys & all_keys
        others = set().union(*(v for k, v in source_sets.items() if k != src)) & all_keys
        unique = keys - others
        source_stats.append({
            "source": src,
            "size": len(keys),
            "unique": len(unique),
            "unique_rate": (len(unique) / len(keys)) if keys else 0.0,
            "covered": sum(1 for k in keys if universe.get(k, {}).get("monitored")),
        })

    # Jaccard
    srcs = [s["source"] for s in source_stats]
    jaccard = {}
    for i, a in enumerate(srcs):
        for b in srcs[i + 1:]:
            A = source_sets[a] & all_keys
            B = source_sets[b] & all_keys
            union = A | B
            jaccard[f"{a}|{b}"] = (len(A & B) / len(union)) if union else 0.0

    # 盲区：按“是否有官网”分成可监控 / 待补官网两类
    blind_all = [e for e in universe.values() if not e["monitored"]]
    blind_domain = [
        e for e in blind_all
        if e["domains"] and not (e["domains"] & IGNORE_DOMAINS)
    ]
    blind_nodomain = [e for e in blind_all if not e["domains"]]
    blind_domain.sort(key=lambda e: (-len(e["sources"]), e["name"]))
    blind_nodomain.sort(key=lambda e: (-len(e["sources"]), e["name"]))
    blind_top = blind_domain[:50]
    blind_nodomain_top = blind_nodomain[:20]

    # 监控中但不在宇宙
    extra = []
    universe_domains = set().union(*(e["domains"] for e in universe.values())) if universe else set()
    universe_names = {norm(e["name"]) for e in universe.values()}
    for p in providers:
        name = p["name"]
        domains = {registrable_domain(u["url"]) for u in p.get("urls", [])}
        domains.discard(None)
        if (domains & universe_domains) or norm(name) in universe_names:
            continue
        extra.append({"name": name, "domains": sorted(domains)})

    # 输出
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# 厂商宇宙基线报告 v0（Day 3）\n")
    lines.append("> 只读分析：4 个现有来源（models.dev / LiteLLM / OpenRouter / aicredits）。")
    lines.append("> HuggingFace 暂不可达（本机证书链），未纳入本版。\n")
    lines.append("## 摘要\n")
    lines.append(f"- 宇宙条目（去重后）：**{total}**")
    lines.append(f"- 已监控（严格匹配）：**{monitored}**")
    lines.append(f"- 来源内覆盖率：**{coverage:.1%}**")
    lines.append(f"- 盲区（有官网、可监控）：**{len(blind_domain)}**")
    lines.append(f"- 盲区（无官网、待补）：**{len(blind_nodomain)}**")
    lines.append(f"- 已排除（非厂商/占位）：**{len(ignored)}**")
    lines.append(f"- 监控清单中但不在宇宙：**{len(extra)}**\n")

    lines.append("## 各来源规模与独有率\n")
    lines.append("| 来源 | 厂商数 | 独有厂商 | 独有率 | 已监控 |")
    lines.append("|---|---:|---:|---:|---:|")
    for s in source_stats:
        lines.append(
            f"| {s['source']} | {s['size']} | {s['unique']} | {s['unique_rate']:.1%} | {s['covered']} |"
        )
    lines.append("")

    lines.append("## 两两重叠（Jaccard）\n")
    lines.append("| 来源对 | 交集占比 |")
    lines.append("|---|---:|")
    for pair, value in sorted(jaccard.items(), key=lambda x: -x[1]):
        lines.append(f"| {pair.replace('|', ' ↔ ')} | {value:.1%} |")
    lines.append("")

    lines.append("## 盲区 Top 50（有官网、按被几个独立来源收录排序）\n")
    lines.append("| # | 厂商 | 域名 | 来源 |")
    lines.append("|---:|---|---|---|")
    for i, e in enumerate(blind_top, 1):
        lines.append(
            f"| {i} | {e['name']} | {', '.join(sorted(e['domains']))} | "
            f"{', '.join(sorted(e['sources']))} |"
        )
    lines.append("")

    lines.append("## 待补官网 Top 20（有收录、无域名）\n")
    lines.append("| # | 厂商 | 来源 |")
    lines.append("|---:|---|---|")
    for i, e in enumerate(blind_nodomain_top, 1):
        lines.append(
            f"| {i} | {e['name']} | {', '.join(sorted(e['sources']))} |"
        )
    lines.append("")

    lines.append("## 监控中但不在宇宙（疑似误收编或新厂商）\n")
    lines.append("| 厂商 | 域名 |")
    lines.append("|---|---|")
    for e in extra[:50]:
        lines.append(f"| {e['name']} | {', '.join(e['domains'])} |")
    lines.append("")

    lines.append("## 口径警告（本版数字不能直接当市场覆盖率）\n")
    lines.append("1. **自我循环**：现有监控清单本身主要由 aicredits / models.dev 自动收编而来，"
                 "用这两个来源的并集做分母，覆盖率天然偏高。本版只能说明“来源内部覆盖”，"
                 "不能说明“市场覆盖”。")
    lines.append("2. **键不一致**：OpenRouter slug、models.dev label、LiteLLM provider 的写法不同，"
                 "同一厂商可能被算成两个条目，导致 Jaccard 低估、独有率偏高。")
    lines.append("3. **第五个独立来源缺失**：HuggingFace 当前不可达（本机证书链），"
                 "Product Hunt / 搜索引擎 / 中文平台尚未接入，真正的盲区还没被测量出来。")
    lines.append("4. **严格匹配**：已监控只用注册域精确 + 名称精确，可能低估覆盖（子品牌、别名未归并）。\n")

    lines.append("## 数据质量与局限\n")
    lines.append("- 名称归一为“小写去符号”，未做人工别名确认；同名不同域可能被误合并。")
    lines.append("- OpenRouter 的上游托管商与模型实验室混在同一集合，未区分角色。")
    lines.append("- 未做分类与地区标注，覆盖率只按总量计算。")
    lines.append("- 监控匹配使用名称包含 + 注册域，可能把同域子品牌算作已监控。")
    lines.append("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(
            {
                "summary": {
                    "universe": total,
                    "monitored": monitored,
                    "coverage": round(coverage, 4),
                    "blind_with_domain": len(blind_domain),
                    "blind_without_domain": len(blind_nodomain),
                    "monitored_not_in_universe": len(extra),
                },
                "sources": source_stats,
                "jaccard": jaccard,
                "blind_top": [
                    {"key": k, "name": universe[k]["name"], "domains": sorted(universe[k]["domains"]), "sources": sorted(universe[k]["sources"])}
                    for k in [next((kk for kk, vv in universe.items() if vv is e), "") for e in blind_top]
                ],
                "blind_without_domain_all": [
                    {"key": k, "name": e["name"], "sources": sorted(e["sources"])}
                    for k, e in sorted(universe.items(), key=lambda kv: kv[1]["name"])
                    if not e["monitored"] and not e["domains"]
                ],
                "monitored_not_in_universe": extra[:200],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"universe={total} monitored={monitored} coverage={coverage:.1%} "
        f"blind_domain={len(blind_domain)} blind_nodomain={len(blind_nodomain)}"
    )


if __name__ == "__main__":
    main()