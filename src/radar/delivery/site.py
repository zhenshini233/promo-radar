"""输出层：静态 dashboard 站点生成（零 npm，file:// 双击可开）。

产出：
- site/index.html            Jinja2 SSR 完整内容（无 JS 可读）+ 数据内联
                             <script type="application/json">（file:// 下 JS 交互的数据源）
- site/data.json             全量载荷（HTTP 环境下供 JS 增强加载）
- site/monitors/<slug>.json  每监控页明细（含逐日信号历史）
- site/atom.xml              订阅

数据统一来自 Repository；delivery 不感知 collectors。
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..domain.coverage import (
    SOURCE_IDS, SOURCE_NAMES, SOURCE_TYPES, SOURCE_BLURBS,
    build_registries, covered_by, domain_norm, registry_sizes, vendor_links,
)
from ..domain.models import Deal, iso, utcnow
from ..infra.config import RadarConfig, load_providers
from ..storage.repository import SqliteRepository

_STATUS_CN = {"new": "新增", "updated": "有更新", "expired": "已过期"}


def _slug(provider: str, label: str) -> str:
    base = f"{provider}-{label}".lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "monitor"


def _deal_dict(d: Deal) -> dict:
    out = asdict(d)
    out["status_cn"] = _STATUS_CN.get(d.status, d.status)
    return out


def _monitor_rows(repo: SqliteRepository, providers_file: Path, days: int = 30) -> list[dict]:
    """监控页汇总行：快照 + 备注 + 出处 + 最近 N 天信号带（1=有信号 0=无 -=未检查）。"""
    providers = {p["name"]: p for p in load_providers(providers_file)}
    rows = []
    for snap in repo.all_snapshots():
        provider = providers.get(snap["provider"], {})
        by_day: dict[str, dict] = {}
        for h in repo.history_for(snap["url"], days=days + 5):
            day = h["checked_at"][:10]
            entry = by_day.setdefault(day, {"hits": set(), "changed": False})
            entry["hits"].update(k for k in h["promo_keywords"].split(",") if k)
            entry["changed"] = entry["changed"] or bool(h["changed"])
        band = ""
        for i in range(days - 1, -1, -1):
            day = (utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
            if day not in by_day:
                band += "-"
            elif by_day[day]["hits"]:
                band += "1"
            else:
                band += "0"
        rows.append(
            {
                "provider": snap["provider"],
                "label": snap["label"],
                "url": snap["url"],
                "slug": _slug(snap["provider"], snap["label"]),
                "promo_keywords": snap["promo_keywords"],
                "last_checked_at": snap["last_checked_at"],
                "last_changed_at": snap["last_changed_at"],
                "notes": provider.get("notes", ""),
                "monitored": provider.get("enabled", False),
                "band": band,
                "checked_days": len(by_day),
            }
        )
    # 有促销信号的排前面，同组按服务商名
    rows.sort(key=lambda w: (not bool(w["promo_keywords"]), w["provider"], w["label"]))
    return rows



def _catalog_stats(repo: SqliteRepository) -> dict:
    """各目录/雷达源的基线规模（记录在 state 表的快照长度）。"""
    import json

    def size(key: str) -> int:
        v = repo.get_state(key)
        if not v:
            return 0
        try:
            return len(json.loads(v))
        except (ValueError, TypeError):
            return 0

    def openrouter_free_vendors() -> int:
        v = repo.get_state("openrouter:vendors")
        if not v:
            return 0
        try:
            data = json.loads(v)
        except (ValueError, TypeError):
            return 0
        return sum(1 for info in data.values()
                   if isinstance(info, dict) and info.get("free", 0) > 0)

    return {
        "openrouter": openrouter_free_vendors(),
        "modelsdev": size("modelsdev:providers"),
        "mnfst": size("mnfst:providers"),
        "freetoken": size("freetoken:providers"),
        "litellm": size("litellm:prices"),
        "aa": size("aa:creators"),
    }


def build_site(cfg: RadarConfig, repo: SqliteRepository) -> Path:
    now = utcnow()
    data = repo.digest_data(now)
    deals = repo.all_deals()
    monitors = _monitor_rows(repo, cfg.providers_file)
    registries = build_registries(repo, deals, monitors)
    for m in monitors:
        m["covered_by"] = covered_by(m["provider"], registries, extra_keys={domain_norm(m["url"])})
    links = vendor_links(registries, monitors)
    # 登记名单：键 + 显示名（能对上监控厂商时用登记名）+ 站点链接（点击跳转）
    source_vendors = {
        sid: [
            {"k": k, "label": links[sid][k][0] if k in links[sid] else k,
             "url": links[sid][k][1] if k in links[sid] else ""}
            for k in sorted(registries.get(sid, []))
        ]
        for sid in SOURCE_IDS
    }
    last_run = repo.last_run()

    signal_pages = sum(1 for m in monitors if m["promo_keywords"])
    payload = {
        "generated_at": iso(now),
        "kpis": {
            "total_deals": data["total_deals"],
            "active_deals": data["active_deals"],
            "new_this_week": len(data["new_deals"]),
            "expired_deals": data.get("expired_deals", 0),
            "monitors": len(monitors),
            "signal_pages": signal_pages,
        },
        "deals": [_deal_dict(d) for d in deals],
        "monitors": monitors,
        "last_run": last_run,
        "source_runs": repo.latest_source_runs(),
        "catalog_stats": _catalog_stats(repo),
        "source_vendors": source_vendors,
        "registry_sizes": registry_sizes(registries),
        # 源元数据唯一来源是 coverage.py，前端不再手抄
        "source_meta": {
            sid: {"name": SOURCE_NAMES[sid], "type": SOURCE_TYPES[sid], "blurb": SOURCE_BLURBS[sid]}
            for sid in SOURCE_IDS
        },
        "source_order": list(SOURCE_IDS),
        "pending_enroll": json.loads(repo.get_state("enroll:pending") or "[]"),
    }

    site = cfg.data_dir / "site"
    (site / "monitors").mkdir(parents=True, exist_ok=True)

    # data.json + 每监控页明细
    (site / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for m in monitors:
        detail = {**m, "history": repo.history_for(m["url"], days=90)}
        (site / "monitors" / f"{m['slug']}.json").write_text(
            json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    _write_atom(site / "atom.xml", data["new_deals"], now)

    # index.html：SSR + 内联数据（file:// 可用）
    env = Environment(
        loader=FileSystemLoader(str(cfg.templates_dir)),
        autoescape=select_autoescape(("html", "j2")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    inline_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = env.get_template("dashboard.html.j2").render(
        generated_at=iso(now),
        payload_json=inline_json,
        kpis=payload["kpis"],
        last_run=last_run,
        sources=repo.latest_source_runs(),
        new_deals=data["new_deals"],
        needs_review=data["needs_review"],
        expired_all=[d for d in deals if d.status == "expired"],
        monitors=monitors,
        signal_pages=signal_pages,
        status_cn=_STATUS_CN,
    )
    out = site / "index.html"
    out.write_text(html, encoding="utf-8")

    # 静态资产：styles.css / app.js / vendor（Vue 本地文件，无 CDN 依赖）
    web_dir = Path(__file__).parent / "web"
    for fname in ("styles.css", "app.js"):
        src = web_dir / fname
        if src.exists():
            (site / fname).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    vendor_src = web_dir / "vendor"
    if vendor_src.exists():
        (site / "vendor").mkdir(exist_ok=True)
        for f in vendor_src.iterdir():
            (site / "vendor" / f.name).write_bytes(f.read_bytes())
    return out


def _write_atom(path: Path, deals: list[Deal], now) -> None:
    ns = "http://www.w3.org/2005/Atom"
    ET.register_namespace("", ns)  # 输出默认命名空间，避免 ns0: 前缀
    root = ET.Element("{%s}feed" % ns)
    ET.SubElement(root, "{%s}title" % ns).text = "promo-radar: AI API 促销活动"
    ET.SubElement(root, "{%s}id" % ns).text = "urn:promo-radar:feed"
    ET.SubElement(root, "{%s}updated" % ns).text = iso(now)
    for deal in deals:
        entry = ET.SubElement(root, "{%s}entry" % ns)
        ET.SubElement(entry, "{%s}id" % ns).text = f"urn:promo-radar:deal:{deal.dedup_key[:16]}"
        ET.SubElement(entry, "{%s}title" % ns).text = deal.title
        link = ET.SubElement(entry, "{%s}link" % ns)
        link.set("href", deal.url or "about:blank")
        ET.SubElement(entry, "{%s}updated" % ns).text = deal.last_seen_at
        meta = f"[{deal.source}] {deal.provider or ''} {deal.amount_hint or ''}".strip()
        ET.SubElement(entry, "{%s}summary" % ns).text = (meta + " — " + deal.evidence)[:500]
    ET.indent(root, space="  ")
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode"),
        encoding="utf-8",
    )
