"""watchlist 分层调度：分层推断、到期判断、错峰、下次检查时间。"""

from datetime import datetime, timedelta, timezone

import radar.collectors.watchlist as watchlist_mod
from radar.collectors.base import FetchContext
from radar.collectors.watchlist import (
    _is_due, _next_check_at, _resolve_tier, _slot, WatchlistSource,
)
from radar.domain.models import parse_iso, utcnow
from radar.infra.config import GeneralConfig, RadarConfig
from radar.storage.repository import SqliteRepository

INTERVALS = {1: 1, 2: 7, 3: 30}
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def test_resolve_tier_rules():
    assert _resolve_tier({"tier": 1}, None) == 1
    assert _resolve_tier({"tier": 3}, {"promo_keywords": "free tier"}) == 3
    assert _resolve_tier({}, {"promo_keywords": "free tier"}) == 1
    assert _resolve_tier({"notes": "auto-enrolled from aicredits 2026-11-01"}, None) == 3
    assert _resolve_tier({"notes": "auto-enrolled"}, {"promo_keywords": ""}) == 2
    assert _resolve_tier({}, None) == 2


def test_is_due_respects_next_check_at():
    assert _is_due({"next_check_at": "2026-11-08T10:00:00Z"}, 2, "https://x", NOW, INTERVALS)
    assert not _is_due({"next_check_at": "2026-11-09T10:00:00Z"}, 2, "https://x", NOW, INTERVALS)


def test_is_due_without_schedule_shards_by_url():
    due = [
        i for i in range(200)
        if _is_due(None, 2, f"https://site{i}.example", NOW, INTERVALS)
    ]
    assert 10 < len(due) < 60, f"一周分片比例异常: {len(due)}/200"


def test_is_due_signal_page_checked_immediately():
    snap = {"promo_keywords": "free tier", "next_check_at": ""}
    assert _is_due(snap, 2, "https://x", NOW, INTERVALS)


def test_next_check_at_intervals_and_failure():
    daily = parse_iso(_next_check_at(NOW, 1, "https://x", INTERVALS, ok=True)) - NOW
    weekly = parse_iso(_next_check_at(NOW, 2, "https://x", INTERVALS, ok=True)) - NOW
    failed = parse_iso(_next_check_at(NOW, 1, "https://x", INTERVALS, ok=False)) - NOW
    assert timedelta(days=1) <= daily < timedelta(days=1, hours=3)
    assert timedelta(days=7) <= weekly < timedelta(days=8)
    assert timedelta(days=1) <= failed < timedelta(days=1, hours=3)


def test_fetch_only_checks_due_pages(tmp_path, monkeypatch):
    """A（有信号）和 C（显式 T1）应抓；B（无信号且 slot 不匹配）应跳过。"""
    now = utcnow()
    target = now.timetuple().tm_yday % 7
    i = 0
    while _slot(f"https://skip{i}.example", 7) == target:
        i += 1
    skipped_url = f"https://skip{i}.example"

    providers = tmp_path / "providers.toml"
    providers.write_text(
        f'''
[[provider]]
name = "A"
urls = [{{ label = "home", url = "https://signal.example" }}]

[[provider]]
name = "B"
urls = [{{ label = "home", url = "{skipped_url}" }}]

[[provider]]
name = "C"
tier = 1
urls = [{{ label = "home", url = "https://tier1.example" }}]
''',
        encoding="utf-8",
    )

    cfg = RadarConfig(
        root=tmp_path,
        general=GeneralConfig(data_dir=str(tmp_path / "data")),
        sources={"watchlist": {"enabled": True, "max_workers": 1}},
    )
    store = SqliteRepository(tmp_path / "data" / "radar.db")
    # A 已有快照且带促销信号 → 立即复查
    store.upsert_snapshot(
        url="https://signal.example", provider="A", label="home",
        content_hash="old", promo_keywords="free credits", now=now, changed=False,
    )

    calls: list[str] = []

    def fake_get_text(client, url, **kwargs):
        calls.append(url)
        return "<html><body>free credits $100 credits free tier for new users</body></html>"

    monkeypatch.setattr(watchlist_mod, "get_text", fake_get_text)

    items = WatchlistSource().fetch(FetchContext(cfg=cfg, http=None, state=store))
    store.close()

    assert set(calls) == {"https://signal.example", "https://tier1.example"}
    assert skipped_url not in calls
    # A：旧信号 → 新信号（事件）；C：首次建档即命中强信号（也应入库）
    assert len(items) == 2


def test_baseline_with_strong_signal_creates_item(tmp_path, monkeypatch):
    providers = tmp_path / "providers.toml"
    providers.write_text(
        '[[provider]]\nname = "F"\ntier = 1\n'
        'urls = [\n    { label = "home", url = "https://f.ai" },\n]\n',
        encoding="utf-8",
    )
    cfg = RadarConfig(
        root=tmp_path,
        general=GeneralConfig(data_dir=str(tmp_path / "data")),
        sources={"watchlist": {"enabled": True, "max_workers": 1}},
    )
    store = SqliteRepository(tmp_path / "data" / "radar.db")
    monkeypatch.setattr(
        watchlist_mod, "get_text",
        lambda *a, **k: "<html><body>$50 credits for new users</body></html>",
    )

    items = WatchlistSource().fetch(FetchContext(cfg=cfg, http=None, state=store))
    assert len(items) == 1
    assert "$50" in items[0].title
    assert items[0].evidence.startswith("[首次建档]")

    # 强制到期再抓一次：同一关键词集合不应重复产生事件
    store.schedule_snapshot(url="https://f.ai", tier=1, next_check_at="2020-01-01T00:00:00Z")
    again = WatchlistSource().fetch(FetchContext(cfg=cfg, http=None, state=store))
    assert again == []
    store.close()


def test_baseline_with_weak_signal_does_not_create_item(tmp_path, monkeypatch):
    providers = tmp_path / "providers.toml"
    providers.write_text(
        '[[provider]]\nname = "W"\ntier = 1\n'
        'urls = [\n    { label = "home", url = "https://w.ai" },\n]\n',
        encoding="utf-8",
    )
    cfg = RadarConfig(
        root=tmp_path,
        general=GeneralConfig(data_dir=str(tmp_path / "data")),
        sources={"watchlist": {"enabled": True, "max_workers": 1}},
    )
    store = SqliteRepository(tmp_path / "data" / "radar.db")
    monkeypatch.setattr(
        watchlist_mod, "get_text",
        lambda *a, **k: "<html><body>free tier available</body></html>",
    )

    items = WatchlistSource().fetch(FetchContext(cfg=cfg, http=None, state=store))
    assert items == [], "free tier 属于宽泛词，首轮不应倒进库"
    store.close()