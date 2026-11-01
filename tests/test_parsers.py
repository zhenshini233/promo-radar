"""解析器测试：全部基于真实响应 fixture，离线运行。"""

import json
import re
from pathlib import Path

from radar.infra.http import loose_text, strip_html
from radar.collectors.aicredits import parse_llms_full
from radar.collectors.hackernews import _parse_hits
from radar.collectors.linuxdo import parse_feed
from radar.collectors.watchlist import DEFAULT_WATCH_KEYWORDS, decide_event

FIXTURES = Path(__file__).parent / "fixtures"


def test_watchlist_event_anchored_on_keyword_set_change():
    # 关键词集合没变：整页 hash 变了也不该发事件（动态内容噪音）
    assert decide_event({"free tier"}, {"free tier"}) == "none"
    assert decide_event(set(), set()) == "none"
    # 新增促销词 → new；全部消失 → gone
    assert decide_event(set(), {"$1,000 in credits"}) == "new"
    assert decide_event({"free tier"}, {"free tier", "$1,000 in credits"}) == "new"
    assert decide_event({"free tier"}, set()) == "gone"


def _hits(visible: str) -> set[str]:
    return {
        m.group(0).lower()
        for p in DEFAULT_WATCH_KEYWORDS
        for m in re.finditer(p, visible, re.IGNORECASE)
    }


# ---------- aicredits ----------

def test_aicredits_parses_real_dump():
    text = (FIXTURES / "aicredits_llms_full.txt").read_text(encoding="utf-8")
    items = parse_llms_full(text)
    assert len(items) >= 100, f"llms-full.txt 应解析出大量条目，实际 {len(items)}"

    by_key = {i.key_override: i for i in items}
    entry = by_key.get("aicredits:208")
    assert entry is not None and entry.title == "LLM Benchmark"
    assert entry.force_keep

    boost = next((i for i in items if "boostmyagents" in i.title.lower()), None)
    assert boost is not None
    assert boost.url == "https://boostmyagents.com"
    assert boost.amount_hint and boost.amount_hint.startswith("$5")
    assert boost.provider == "boostmyagents"
    assert boost.evidence  # 描述非空


# ---------- linux.do ----------

def test_linuxdo_parses_feed():
    xml_text = (FIXTURES / "linuxdo_welfare.rss").read_text(encoding="utf-8")
    items = parse_feed(xml_text)
    assert len(items) == 14

    moyu = next((i for i in items if "魔芋AI" in i.title), None)
    assert moyu is not None
    assert moyu.url == "https://linux.do/t/topic/2493126"
    assert "个帖子" not in moyu.evidence, "Discourse 尾部样板文字应被剔除"
    assert "邀请链接" in moyu.evidence or "注册" in moyu.evidence
    assert moyu.published_at is not None and moyu.published_at.year == 2026


# ---------- hackernews ----------

def test_hn_parses_algolia_response():
    data = json.loads((FIXTURES / "hn_free_credits.json").read_text(encoding="utf-8"))
    items = _parse_hits(data)
    assert items, "fixture 里应有命中"
    for it in items:
        assert it.title
        assert it.key_override.startswith("hn:")
        assert it.url  # 文章 URL 或 HN 讨论 fallback


# ---------- openrouter 供应商目录 ----------

def test_openrouter_extracts_vendors():
    from radar.collectors.openrouter import _extract_vendors

    data = {
        "data": [
            {"id": "deepseek/deepseek-chat", "pricing": {"prompt": "0.000001"}},
            {"id": "deepseek/deepseek-r1:free", "pricing": {"prompt": "0"}},
            {"id": "qwen/qwen-3:free", "pricing": {"prompt": "0"}},
            {"id": "meta/llama-4", "pricing": {"prompt": "0.0001"}},
            {"id": "newvendor/tiny:free", "pricing": {"prompt": "0"}},
            {"id": "no-slash", "pricing": {"prompt": "0"}},
        ]
    }
    vendors = _extract_vendors(data)
    assert vendors == {
        "deepseek": {"models": 2, "free": 1},
        "qwen": {"models": 1, "free": 1},
        "meta": {"models": 1, "free": 0},
        "newvendor": {"models": 1, "free": 1},
    }


# ---------- 自动收编纯函数 ----------

def test_registrable_domain():
    from radar.collectors.watchlist import _registrable

    assert _registrable("https://console.anthropic.com/x?utm=1") == "anthropic.com"
    assert _registrable("https://www.deepinfra.com/deepstart") == "deepinfra.com"
    assert _registrable("http://boostmyagents.com") == "boostmyagents.com"
    assert _registrable("ftp://x.com") is None
    assert _registrable("not-a-url") is None
    assert _registrable("https://192.168.1.1/") is None  # 纯数字末段


def test_auto_blocklist_covers_noise_domains():
    from radar.collectors.watchlist import _AUTO_BLOCKLIST

    for dom in ("github.com", "youtube.com", "huggingface.co", "aicredits.dev", "openrouter.ai"):
        assert dom in _AUTO_BLOCKLIST


# ---------- watchlist 关键词 ----------

def test_watchlist_keywords_hit_deepinfra():
    # deepinfra 的 promo 文案在 <script> 数据载荷里，须用 loose_text 检测
    visible = loose_text((FIXTURES / "deepinfra_home.html").read_text(encoding="utf-8"))
    hits = _hits(visible)
    assert any("credits" in h for h in hits), f"deepinfra 应命中 credits 类信号，实际: {hits}"


def test_watchlist_keywords_hit_chutes():
    visible = loose_text((FIXTURES / "chutes_pricing.html").read_text(encoding="utf-8"))
    assert _hits(visible), "chutes pricing 应命中 free tier"


def test_watchlist_no_hits_on_river():
    visible = loose_text((FIXTURES / "river_home.html").read_text(encoding="utf-8"))
    hits = _hits(visible)
    assert not hits, f"river.ai 当前无 promo 文案，不应命中: {hits}"


def test_strip_html_removes_script_but_loose_text_keeps_it():
    raw = "<div>DeepStart program</div><script>var grant = '$1,000 in credits';</script>"
    assert "credits" not in strip_html(raw)
    assert "credits" in loose_text(raw)
