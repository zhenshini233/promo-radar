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
import shutil
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..domain.coverage import (
    SOURCE_IDS, SOURCE_NAMES, SOURCE_TYPES, SOURCE_BLURBS,
    build_registries, covered_by, domain_norm, registry_sizes, vendor_links,
)
from ..domain.models import Deal, iso, parse_iso, utcnow
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
            entry["hits"].update(k for k in h["promo_keywords"].split(";;") if k)
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


def _compact_json(obj) -> str:
    """紧凑 JSON：去掉 indent 的空白，站点体积可降 20% 以上。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# 首屏内联兜底的数据上限：全量数据放在 data.js，内联只保留可交互的最小集，
# 避免 index.html 随 deals/厂商清单线性膨胀（P0-H：index < 200KB）。
INLINE_DEAL_LIMIT = 60
INLINE_MONITOR_LIMIT = 80


def _inline_payload(payload: dict) -> dict:
    """裁剪内联到 index.html 的载荷；全量仍写 data.json / data.js。"""
    deals = payload.get("deals", [])
    monitors = payload.get("monitors", [])
    active = [d for d in deals if d.get("status") != "expired"][:INLINE_DEAL_LIMIT]
    inline = dict(payload)
    inline["deals"] = active
    inline["monitors"] = monitors[:INLINE_MONITOR_LIMIT]
    # 厂商清单占 80KB+，file:// 场景由 data.js 提供，内联不再重复
    inline["source_vendors"] = {}
    inline["inline_meta"] = {
        "deals_total": len(deals),
        "deals_inline": len(active),
        "monitors_total": len(monitors),
        "monitors_inline": len(inline["monitors"]),
        "full_data": "data.js",
    }
    return inline


def _freshness(repo: SqliteRepository, now, min_sources: int = 0) -> dict:
    """数据新鲜度：以「最近一次全量健康抓取」为准，而不是本次构建时间。

    否则抓取持续失败时 generated_at 会不断前移，站点看起来永远新鲜；
    也不能把 `--only watchlist` 这类局部刷新算进来，否则单源成功会掩盖
    全源故障（min_sources 由 config 的 full_run_min_sources 控制）。
    """
    last = repo.last_success_at(min_sources=min_sources)
    if not last:
        return {
            "last_success_at": None,
            "age_hours": None,
            "level": "critical",
            "message": "尚未成功完成一次全量抓取，当前内容来自历史数据。",
        }
    age = max(0.0, (now - parse_iso(last)).total_seconds() / 3600)
    if age > 24:
        level = "critical"
        message = f"全量抓取已 {age / 24:.1f} 天未成功，当前内容可能已失效。"
    elif age > 6:
        level = "warn"
        message = f"全量抓取已 {age:.0f} 小时未成功，请查看数据源状态。"
    else:
        level = "ok"
        message = f"数据更新于 {age:.0f} 小时前（全量抓取）。"
    return {
        "last_success_at": last,
        "age_hours": round(age, 1),
        "level": level,
        "message": message,
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
    feedback = repo.feedback_map()
    freshness = _freshness(repo, now, cfg.general.full_run_min_sources)

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
        "deals": [{**_deal_dict(d), "vote": feedback.get(d.dedup_key, "")} for d in deals],
        "monitors": monitors,
        "last_run": last_run,
        "source_runs": repo.latest_source_runs(),
        "catalog_stats": _catalog_stats(repo),
        "source_vendors": source_vendors,
        "registry_sizes": registry_sizes(registries),
        "feedback_stats": repo.feedback_stats(),
        "provider_categories": repo.provider_category_stats(),
        "digest": repo.today_digest(),
        # 源元数据唯一来源是 coverage.py，前端不再手抄
        "source_meta": {
            sid: {"name": SOURCE_NAMES[sid], "type": SOURCE_TYPES[sid], "blurb": SOURCE_BLURBS[sid]}
            for sid in SOURCE_IDS
        },
        "source_order": list(SOURCE_IDS),
        "pending_enroll": json.loads(repo.get_state("enroll:pending") or "[]"),
        "freshness": freshness,
    }

    site = cfg.data_dir / "site"
    site.mkdir(parents=True, exist_ok=True)

    # data.json：紧凑格式（HTTP 场景供前端按需加载）
    full_json = _compact_json(payload)
    (site / "data.json").write_text(full_json, encoding="utf-8")
    # data.js：全量数据的脚本形态。file:// 下外部 <script> 可加载，
    # 而 fetch(data.json) 会被 CORS 拦截，用它保证双击打开仍有完整功能。
    (site / "data.js").write_text(
        "window.__RADAR_FULL__=" + full_json + ";", encoding="utf-8"
    )

    # v1 遗留：每页明细 JSON 从未被前端加载，停止生成并清理旧文件
    stale_monitors = site / "monitors"
    if stale_monitors.exists():
        shutil.rmtree(stale_monitors, ignore_errors=True)

    _write_atom(site / "atom.xml", data["new_deals"], now)

    # index.html：SSR + 内联数据（file:// 可用）
    env = Environment(
        loader=FileSystemLoader(str(cfg.templates_dir)),
        autoescape=select_autoescape(("html", "j2")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    inline_json = _compact_json(_inline_payload(payload)).replace("</", "<\\/")
    html = env.get_template("dashboard.html.j2").render(
        generated_at=iso(now),
        payload_json=inline_json,
        kpis=payload["kpis"],
        freshness=freshness,
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
