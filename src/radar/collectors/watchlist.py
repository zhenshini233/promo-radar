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
from datetime import datetime, timezone
from urllib.parse import urlsplit

from ..infra.config import load_providers
from ..infra.http import extract_text, get_text, loose_text
from ..domain.models import RawItem, iso, utcnow
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

# 自动收编排除：内容/社区/基础设施域名（不提供模型 API 优惠，进监控只添噪）
_AUTO_BLOCKLIST = {
    "github.com", "youtube.com", "medium.com", "x.com", "twitter.com",
    "discord.gg", "discord.com", "reddit.com", "huggingface.co",
    "linkedin.com", "substack.com", "notion.site", "apple.com",
    "ycombinator.com", "news.ycombinator.com", "aicredits.dev",
    "aicredits.tech", "openrouter.ai", "artificialanalysis.ai",
    # 政府/学术/公共机构域（aicredits 活动页常见，非模型厂商）
    "gov.uk", "ac.uk", "org.uk", "gov.sg", "gov.in", "org.au",
    "europa.eu", "edu.cn", "gov.cn",
}


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


# 多段公共后缀（末两段不是注册域，需取末三段）：_registrable 防把
# turing.ac.uk 收编成 "ac.uk" 这类垃圾条目
_MULTI_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk",
    "com.au", "net.au", "org.au", "gov.au", "edu.au",
    "co.jp", "ne.jp", "or.jp", "go.jp", "ac.jp",
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn",
    "com.hk", "org.hk", "gov.hk", "edu.hk",
    "com.tw", "org.tw", "gov.tw", "edu.tw",
    "co.kr", "or.kr", "go.kr", "ne.kr", "re.kr",
    "com.sg", "org.sg", "gov.sg", "edu.sg",
    "co.in", "net.in", "org.in", "gov.in", "edu.in",
    "com.br", "com.mx", "com.ar", "com.tr", "co.za", "co.nz", "org.nz",
}


def _registrable(url: str) -> str | None:
    """URL → 注册域（去 www、取末两段；多段公共后缀取末三段）。非 http(s) 返回 None。"""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.split("@")[-1].split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) < 2 or not labels[-1].isalpha():
        return None
    take = 3 if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTI_SUFFIXES else 2
    return ".".join(labels[-take:])


def _known_domains(ctx) -> set[str]:
    domains = set()
    for p in load_providers(ctx.cfg.providers_file):
        domains.add(p["name"].lower())
        for u in p["urls"]:
            d = _registrable(u["url"])
            if d:
                domains.add(d)
    return domains


def auto_enroll_from_items(ctx, items: list[RawItem]) -> int:
    """把 items 里没见过的新域名追加进 providers.toml。返回收编数量。

    幂等：域名已在 watchlist（按 name 或任意 URL 的注册域判断）则跳过。
    """
    if not ctx.cfg.source("watchlist").get("auto_enroll", True):
        return 0
    known = _known_domains(ctx)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blocks: list[str] = []
    for item in items:
        dom = _registrable(item.url)
        if not dom or dom in known or dom in _AUTO_BLOCKLIST:
            continue
        known.add(dom)
        blocks.append(
            f'\n[[provider]]\nname = "{dom}"\n'
            f'urls = [\n    {{ label = "home", url = "https://{dom}" }},\n]\n'
            f'notes = "auto-enrolled from {item.source} {today}"\n'
        )
    if blocks:
        with open(ctx.cfg.providers_file, "a", encoding="utf-8") as f:
            f.write("\n".join(blocks))
        print(f"[auto-enroll] 新收编 {len(blocks)} 个域名进 watchlist")
    return len(blocks)


@register_source("watchlist")
class WatchlistSource:

    def fetch(self, ctx) -> list[RawItem]:
        providers = load_providers(ctx.cfg.providers_file)
        if not providers:
            return []
        patterns = ctx.cfg.watchlist_keywords or DEFAULT_WATCH_KEYWORDS
        regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
        max_workers = max(1, int(ctx.cfg.source("watchlist").get("max_workers", 8)))

        tasks = [(p, u) for p in providers if p["enabled"] for u in p["urls"]]

        def _fetch(task):
            p, u = task
            try:
                return (p, u, get_text(ctx.http, u["url"]), None)
            except Exception as e:  # noqa: BLE001 - 页级失败不拖垮整个源
                return (p, u, None, e)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fetched = list(pool.map(_fetch, tasks))

        items: list[RawItem] = []
        attempts = len(fetched)
        successes = 0
        last_err: Exception | None = None
        for p, u, text, err in fetched:
            if err is not None:
                last_err = err
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
            if event == "none":
                continue

            key = f"watchlist:{p['name']}:{u['label']}"
            if event == "new":
                items.append(
                    RawItem(
                        source="watchlist",
                        title=f"[{p['name']}] 页面出现促销信号: {', '.join(hits[:5])}",
                        url=u["url"],
                        provider=p["name"],
                        evidence=_make_evidence(text, visible, regexes),
                        key_override=key,
                        force_keep=True,
                    )
                )
            else:
                # 促销文案消失：把对应 deal 归档，事件留在 snapshot 里
                from ..domain.dedup import make_key
                from ..domain.models import RawItem as _RI

                ctx.state.mark_expired(make_key(_RI(source="watchlist", title="", key_override=key)))
                print(f"[watchlist] {p['name']}/{u['label']} 促销文案消失，已归档对应 deal")

        if attempts and successes == 0:
            raise RuntimeError(f"watchlist: all {attempts} pages failed (last: {last_err})")
        return items
