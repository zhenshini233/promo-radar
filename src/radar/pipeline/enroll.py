"""盲区自动收编：发现层登记了、但没有监控在盯的厂商，自动纳入 watchlist。

每轮 run 末尾执行：
1. 盲区识别：各发现源登记名单并集 − 已监控键（名字/域名，含别名变体匹配，
   规则与覆盖计算一致）；
2. URL 解析：brands 静态品牌表 → modelsdev 的 doc 字段（其余源不带官网，
   猜域名不可靠，不强收）；
3. 收编：解析出官网的按注册域去重后追加进 providers.toml（下一轮 watchlist
   生效）；解析不出的记入 state「enroll:pending」，站点厂商页展示待收编清单。

无网络操作，只追加文件与写 state；幂等（已监控域跳过）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..collectors.watchlist import _AUTO_BLOCKLIST, _registrable
from ..domain.brands import BRANDS
from ..domain.coverage import _keys_match, build_registries, domain_norm, norm
from ..infra.config import RadarConfig, load_providers
from ..storage.repository import SqliteRepository

PENDING_STATE_KEY = "enroll:pending"


def _escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', "'")


def compute_enroll_plan(
    registries: dict[str, list[str]],
    tracked_keys: set[str],
    modelsdev: dict[str, dict],
    brands: dict[str, tuple[str, str]],
) -> tuple[list[dict], list[dict]]:
    """盲区 → (收编条目, 待收编键)。纯计算，无 I/O。

    收编条目 {name, url, label, source}；待收编 {key, sources}。
    """
    tracked = list(tracked_keys)
    blind: dict[str, list[str]] = {}
    for sid, keys in registries.items():
        if sid == "watchlist":  # 追踪层自身不参与盲区
            continue
        for k in keys:
            if k and not _keys_match({k}, tracked):
                blind.setdefault(k, []).append(sid)

    # URL 解析：brands（官网）优先，modelsdev doc 兜底
    md_lookup: dict[str, tuple[str, str]] = {}
    for pid, info in (modelsdev or {}).items():
        if not isinstance(info, dict):
            continue
        doc = str(info.get("doc") or "").strip()
        if not doc:
            continue
        label = str(info.get("label") or pid)
        for key in (str(pid).lower(), label.lower()):
            md_lookup.setdefault(key, (label, doc))

    entries: dict[str, dict] = {}
    pending: list[dict] = []
    for k, srcs in sorted(blind.items()):
        hit = None
        if k in brands and brands[k][1]:
            hit = {"name": brands[k][0], "url": brands[k][1], "source": "brands"}
        elif k in md_lookup:
            label, doc = md_lookup[k]
            hit = {"name": label, "url": doc, "source": "modelsdev"}
        if hit is None:
            pending.append({"key": k, "sources": srcs})
            continue
        dom = _registrable(hit["url"])
        if not dom:
            pending.append({"key": k, "sources": srcs})
            continue
        # 同域多键只收编一次（一个注册域一个监控条目）
        if dom not in entries:
            entries[dom] = {
                "name": hit["name"] or dom,
                "url": hit["url"],
                "label": "docs" if "docs." in (hit["url"].split("//", 1)[-1].split("/")[0]) else "home",
                "source": hit["source"],
            }
    return list(entries.values()), pending


def auto_enroll_blindspots(cfg: RadarConfig, repo: SqliteRepository) -> tuple[int, list[dict]]:
    """盲区收编入口：追加 providers.toml、更新待收编 state。返回 (收编数, 待收编)。"""
    deals = repo.all_deals()
    monitors = [{"provider": s["provider"], "url": s["url"]} for s in repo.all_snapshots()]
    registries = build_registries(repo, deals, monitors)

    tracked: set[str] = set()
    for p in load_providers(cfg.providers_file):
        tracked.add(norm(p["name"]))
        for u in p["urls"]:
            tracked.add(domain_norm(u["url"]))
    tracked.discard("")

    md_raw = repo.get_state("modelsdev:providers")
    modelsdev = json.loads(md_raw) if md_raw else {}
    entries, pending = compute_enroll_plan(registries, tracked, modelsdev, dict(BRANDS))

    known = {p["name"].lower() for p in load_providers(cfg.providers_file)}
    for u in (u for p in load_providers(cfg.providers_file) for u in p["urls"]):
        d = _registrable(u["url"])
        if d:
            known.add(d)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    blocks: list[str] = []
    for e in entries:
        dom = _registrable(e["url"])
        if dom in known or dom in _AUTO_BLOCKLIST or e["name"].lower() in known:
            continue
        known.add(dom)
        blocks.append(
            f'\n[[provider]]\nname = "{_escape(e["name"])}"\n'
            f'urls = [\n    {{ label = "{e["label"]}", url = "{_escape(e["url"])}" }},\n]\n'
            f'notes = "auto-enrolled from {e["source"]} {today}"\n'
        )
    if blocks:
        with open(cfg.providers_file, "a", encoding="utf-8") as f:
            f.write("\n".join(blocks))

    repo.set_state(PENDING_STATE_KEY, json.dumps(pending, ensure_ascii=False))
    return len(blocks), pending
