"""watchlist：服务商官网 promo 探测（providers.toml 驱动）。

机制（借鉴 changedetection.io 的"锚定证据"思路）：
- 每个页面抓正文 → 归一化空白 → sha256 内容指纹，与 snapshots 表比对；
- 事件锚定"促销关键词集合的变化"而非整页 hash（首页价格计数器等动态
  内容会让整页 hash 频繁变化）；
- 关键词新增 → deal 事件；关键词全部消失 → 对应 deal 归档；
- 首次见到的页面只建基线，不产生事件（避免首轮噪音）；
- 页面并发抓取（max_workers），单页失败只记日志。

自动收编（auto_enroll）：aicredits 等目录源的新域名可经 auto_enroll_from_items
追加进 providers.toml，实现"发现新对象 → 自动纳入监控"。
"""

from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from ..infra.config import load_providers
from ..infra.http import extract_text, get_text, loose_text
from ..infra.providers_store import ProviderStoreError, append_provider_entries
from ..domain.domains import registrable_domain
from ..domain.enroll_rules import AUTO_BLOCKLIST as _AUTO_BLOCKLIST, enroll_allowed
from ..domain.models import RawItem, iso, parse_iso, utcnow
from .base import register_source

DEFAULT_WATCH_KEYWORDS = [
    r"free\s+credits?",
    r"\$\s?\d[\d,.]*\s*(in\s+)?(free\s+)?(trial\s+)?credits?",
    r"sign[- ]?up\s+bonus",
    r"welcome\s+(credit|bonus)",
    r"free\s+tier",
    r"绑卡",
    r"送\s*额度",
    r"注册\s*送",
    r"免费额度",
    r"体验(卡|金|额度)",
]

# 自动收编排除清单已迁到 domain/enroll_rules（与盲区收编共用）；
# _AUTO_BLOCKLIST 保留别名，避免外部引用失效。


def _context_snippet(visible: str, regexes: list[re.Pattern], window: int = 120) -> str:
    for rx in regexes:
        m = rx.search(visible)
        if m:
            s = max(0, m.start() - window)
            e = min(len(visible), m.end() + window)
            return ("…" if s > 0 else "") + visible[s:e].strip() + ("…" if e < len(visible) else "")
    return visible[:240]


def decide_event(old_hits: set[str], new_hits: set[str]) -> str:
    """锚定促销关键词集合的变化而非整页 hash——首页价格计数器等动态内容
    会让整页 hash 频繁变化，若据此发事件会产生噪音（changedetection.io
    的"锚定随优惠死掉的证据"原则）。返回 none | new | gone。"""
    if new_hits == old_hits:
        return "none"
    return "new" if new_hits else "gone"


# 证据清洗：loose_text 会带进脚本载荷，去掉常见 JS/JSON 碎片，别让用户看到 gtag
_NOISE_PATTERNS = [
    re.compile(r"function\s*\([^)]*\)\s*\{[^{}]*\}"),
    re.compile(r"dataLayer\.push\([^)]*\)"),
    re.compile(r"gtag\([^)]*\)"),
    re.compile(r'["\']?\s*:\s*["\']'),   # JSON 的 ":"
    re.compile(r'["\']\s*,\s*["\']'),    # JSON 的 ","
    re.compile(r"[{}[\];*]"),
    re.compile(r"\bfunction\b[^A-Za-z0-9$]*"),  # 截窗切残的 JS 尾巴
    re.compile(r"\.{3,}"),
]


def _clean_snippet(s: str) -> str:
    for pat in _NOISE_PATTERNS:
        s = pat.sub(" ", s)
    s = re.sub(r"\\+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"^[^\w$￥¥]+", "", s)  # 去掉开头的省略号/标点


def _make_evidence(text: str, visible: str, regexes: list[re.Pattern], window: int = 130) -> str:
    """证据优先取正文（trafilatura），关键词不在正文时回退宽松文本并清洗代码碎片。"""
    candidates = []
    main = extract_text(text)
    if main:
        candidates.append(main)
    candidates.append(visible)
    for src in candidates:
        m = next((rx.search(src) for rx in regexes if rx.search(src)), None)
        if m:
            s = max(0, m.start() - window)
            e = min(len(src), m.end() + window)
            return _clean_snippet(("…" if s > 0 else "") + src[s:e] + ("…" if e < len(src) else ""))
    return _clean_snippet(visible[:240])


# 多段公共后缀逻辑已移到 domain.domains，供 providers_store 复用；
# 保留 _registrable 名称兼容旧测试与 enroll.py 的 import。
def _registrable(url: str) -> str | None:
    """URL → 注册域（去 www、取末两段；多段公共后缀取末三段）。非 http(s) 返回 None。"""
    return registrable_domain(url)


def auto_enroll_from_items(ctx, items: list[RawItem]) -> int:
    """把 items 里没见过的新域名追加进 providers.toml。返回收编数量。

    幂等：name 或注册域已存在则跳过；写入走 providers_store 的锁 + 原子替换。
    """
    if not ctx.cfg.source("watchlist").get("auto_enroll", True):
        return 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries: list[dict] = []
    for item in items:
        dom = _registrable(item.url)
        if not enroll_allowed(item.provider or dom or "", dom or "")[0]:
            continue
        entries.append(
            {
                "name": dom,
                "urls": [{"label": "home", "url": f"https://{dom}"}],
                "notes": f"auto-enrolled from {item.source} {today}",
            }
        )
    try:
        added = append_provider_entries(ctx.cfg.providers_file, entries)
    except ProviderStoreError as e:
        print(f"[auto-enroll] 写入失败，跳过：{e}")
        return 0
    if added:
        print(f"[auto-enroll] 新收编 {len(added)} 个域名进 watchlist")
    return len(added)


COOLDOWN_FAILS = 3
COOLDOWN_DAYS = 7


def _cooling_down(snapshot, url: str, now: datetime) -> bool:
    """连续失败 >=3 次且 7 天内没有成功 → 熔断跳过本轮。"""
    if not snapshot or int(snapshot.get("fail_count") or 0) < COOLDOWN_FAILS:
        return False
    try:
        last = parse_iso(snapshot["last_checked_at"])
    except (KeyError, ValueError, TypeError):
        return False
    if now - last >= timedelta(days=COOLDOWN_DAYS):
        return False
    print(f"[watchlist] 熔断跳过 {url}（连续失败 {snapshot['fail_count']} 次）")
    return True


def _resolve_tier(provider: dict, snapshot: dict | None) -> int:
    """厂商分层：显式 tier 优先；有促销信号的每日；自动收编且从未建档的每月。"""
    explicit = provider.get("tier")
    if explicit in (1, 2, 3):
        return int(explicit)
    if snapshot and snapshot.get("promo_keywords"):
        return 1
    notes = (provider.get("notes") or "").lower()
    if notes.startswith("auto-enrolled") and snapshot is None:
        return 3
    return 2


def _slot(url: str, days: int) -> int:
    """稳定分片：同一 URL 永远落在同一个 0..days-1 槽位。"""
    return int(hashlib.sha1(url.encode("utf-8")).hexdigest(), 16) % max(1, days)


def _is_due(snapshot, tier: int, url: str, now: datetime, intervals: dict[int, int]) -> bool:
    """是否到本轮检查时间。

    - 有 next_check_at：严格按时间；
    - 无 schedule（旧库/首次）且有促销信号：立即复查；
    - 其余：按 URL hash 错峰到周/月的某一天，避免首轮 400 页全量。
    """
    if snapshot and snapshot.get("next_check_at"):
        try:
            return parse_iso(snapshot["next_check_at"]) <= now
        except (TypeError, ValueError):
            return True
    days = max(1, int(intervals[tier]))
    if days <= 1:
        return True
    if snapshot and snapshot.get("promo_keywords"):
        return True
    return now.timetuple().tm_yday % days == _slot(url, days)


def _next_check_at(
    now: datetime, tier: int, url: str, intervals: dict[int, int], *, ok: bool
) -> str:
    days = max(1, int(intervals[tier])) if ok else 1
    # 每日层只做 0..2h 抖动；周/月层分散到 0..23h，避免同一时刻洪峰
    jitter_hours = _slot(url, 24) if days > 1 else _slot(url, 3)
    return iso(now + timedelta(days=days, hours=jitter_hours))


def _best_promo_phrase(hits: list[str]) -> str:
    """从命中的关键词里挑最有信息量的一个当标题：优先带 $ 金额的（最长），否则最长。"""
    if not hits:
        return "出现促销信号"
    money = [h for h in hits if h.startswith("$") or "$" in h]
    pool = money or hits
    return max(pool, key=len)


def _has_strong_signal(hits: list[str]) -> bool:
    """首次建档是否值得直接入库。

    只认强信号（金额/credits/额度/注册/欢迎/赠送），不认 free tier / free trial
    这类宽泛词，避免首轮把 400 个页面的“免费层”全部倒进库。
    """
    text = " ".join(hits).lower()
    return any(
        token in text
        for token in ("$", "credit", "额度", "注册", "welcome", "signup", "bonus", "赠送", "免费领取")
    )


@register_source("watchlist")
class WatchlistSource:

    def fetch(self, ctx) -> list[RawItem]:
        providers = load_providers(ctx.cfg.providers_file)
        if not providers:
            return []
        patterns = ctx.cfg.watchlist_keywords or DEFAULT_WATCH_KEYWORDS
        regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
        conf = ctx.cfg.source("watchlist")
        max_workers = max(1, int(conf.get("max_workers", 8)))
        max_pages = max(1, int(conf.get("max_pages", 400)))
        page_timeout = float(ctx.cfg.general.page_timeout)
        intervals = {
            1: max(1, int(conf.get("tier1_interval_days", 1))),
            2: max(1, int(conf.get("tier2_interval_days", 7))),
            3: max(1, int(conf.get("tier3_interval_days", 30))),
        }

        # 分层调度：只抓「到期」的页面。首轮/旧库按 URL hash 错峰到周/月，
        # 有促销信号的页面优先立即复查，因此不再一次性打满 400 页。
        now = utcnow()
        candidates = []
        cooling = 0
        for p in providers:
            if not p["enabled"]:
                continue
            for u in p["urls"]:
                snap = ctx.state.get_snapshot(u["url"])
                tier = _resolve_tier(p, snap)
                if _cooling_down(snap, u["url"], now):
                    cooling += 1
                    continue
                if not _is_due(snap, tier, u["url"], now, intervals):
                    continue
                candidates.append((p, u, tier, snap))

        candidates.sort(key=lambda t: (
            t[2],
            0 if (t[3] or {}).get("promo_keywords") else 1,
            t[0]["name"],
            t[1]["label"],
        ))
        if len(candidates) > max_pages:
            print(f"[watchlist] 到期页面 {len(candidates)} 超过上限 {max_pages}，本轮截断")
            candidates = candidates[:max_pages]

        if candidates:
            t1 = sum(1 for c in candidates if c[2] == 1)
            t2 = sum(1 for c in candidates if c[2] == 2)
            t3 = len(candidates) - t1 - t2
            print(
                f"[watchlist] 到期 {len(candidates)} 页（T1 {t1} / T2 {t2} / T3 {t3}），"
                f"熔断跳过 {cooling} 页"
            )

        tasks = [(p, u, tier) for p, u, tier, _ in candidates]

        def _fetch(task):
            p, u, tier = task
            try:
                return (
                    p, u, tier,
                    get_text(ctx.http, u["url"], timeout=page_timeout, retries=1),
                    None,
                )
            except Exception as e:  # noqa: BLE001 - 页级失败不拖垮整个源
                return (p, u, tier, None, e)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fetched = list(pool.map(_fetch, tasks))

        items: list[RawItem] = []
        attempts = len(fetched)
        successes = 0
        last_err: Exception | None = None
        for p, u, tier, text, err in fetched:
            if err is not None:
                last_err = err
                failed_at = utcnow()
                ctx.state.record_snapshot_failure(
                    url=u["url"], provider=p["name"], label=u["label"],
                    error=f"{type(err).__name__}: {err}", now=failed_at,
                )
                ctx.state.schedule_snapshot(
                    url=u["url"], tier=tier,
                    next_check_at=_next_check_at(
                        failed_at, tier, u["url"], intervals, ok=False
                    ),
                )
                print(f"[watchlist] {p['name']}/{u['label']} 抓取失败: {err}")
                continue
            successes += 1

            visible = loose_text(text)
            digest = hashlib.sha256(" ".join(visible.split()).encode("utf-8")).hexdigest()
            hits = sorted({m.group(0).lower() for rx in regexes for m in rx.finditer(visible)})
            old = ctx.state.get_snapshot(u["url"])
            now = utcnow()

            if old is None:  # 首次建基线，不产生事件
                ctx.state.upsert_snapshot(
                    url=u["url"], provider=p["name"], label=u["label"],
                    content_hash=digest, promo_keywords=";;".join(hits),
                    now=now, changed=False,
                )
                ctx.state.record_history(
                    url=u["url"], checked_at=iso(now), promo_keywords=";;".join(hits), changed=False,
                )
                ctx.state.schedule_snapshot(
                    url=u["url"], tier=tier,
                    next_check_at=_next_check_at(now, tier, u["url"], intervals, ok=True),
                )
                # 首次建档就命中强促销信号：直接产生事件，而不是等下次变化。
                # 没有这一步，Featherless 这类“首页一直写着 $50 credits”的页面
                # 永远不会入库（old is None 分支只建基线）。
                if tier <= 2 and _has_strong_signal(hits):
                    items.append(
                        RawItem(
                            source="watchlist",
                            title=f"{p['name']} — {_best_promo_phrase(hits)}",
                            url=u["url"],
                            provider=p["name"],
                            evidence="[首次建档] " + _make_evidence(text, visible, regexes),
                            key_override=f"watchlist:{p['name']}:{u['label']}",
                            force_keep=True,
                        )
                    )
                continue

            changed = old["content_hash"] != digest
            ctx.state.upsert_snapshot(
                url=u["url"], provider=p["name"], label=u["label"],
                content_hash=digest, promo_keywords=";;".join(hits),
                now=now, changed=changed,
            )
            ctx.state.record_history(
                url=u["url"], checked_at=iso(now), promo_keywords=";;".join(hits), changed=changed,
            )

            old_hits = {k for k in old["promo_keywords"].split(";;") if k}
            event = decide_event(old_hits, set(hits))
            ctx.state.schedule_snapshot(
                url=u["url"], tier=tier,
                next_check_at=_next_check_at(now, tier, u["url"], intervals, ok=True),
            )
            if event == "none":
                continue

            key = f"watchlist:{p['name']}:{u['label']}"
            if event == "new":
                items.append(
                    RawItem(
                        source="watchlist",
                        title=f"{p['name']} — {_best_promo_phrase(hits)}",
                        url=u["url"],
                        provider=p["name"],
                        evidence=_make_evidence(text, visible, regexes),
                        key_override=key,
                        force_keep=True,
                    )
                )
            else:
                # 促销文案消失：把对应 Offer 归档，事件留在 snapshot 里
                from ..domain.dedup import offer_key
                from ..domain.models import RawItem as _RI
                from ..domain.offer_infer import apply_ai_offer

                gone = _RI(source="watchlist", title="", key_override=key)
                ctx.state.mark_expired_offer(offer_key(apply_ai_offer(gone)))
                print(f"[watchlist] {p['name']}/{u['label']} 促销文案消失，已归档对应 Offer")

        # 单页失败不再判整源死亡（360 页里少数站点超时是常态）；
        # 成功率低于 50% 才视为源级故障，交给 runner 的故障隔离与告警。
        if attempts and successes / attempts < 0.5:
            raise RuntimeError(
                f"watchlist: only {successes}/{attempts} pages succeeded (last: {last_err})"
            )
        if attempts == 0:
            print("[watchlist] 本轮没有到期页面（或全部处于熔断期）")
        return items
