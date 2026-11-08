"""回归测试：本轮修复的正确性 bug 与健康度逻辑。"""

import hashlib
import sqlite3
from datetime import timedelta

import radar.pipeline.runner as runner_mod
from radar.delivery.site import _freshness, _monitor_rows
from radar.domain.dedup import make_key
from radar.domain.models import RawItem, RunReport, SourceResult, iso, utcnow
from radar.domain.scoring import score_item
from radar.infra.config import GeneralConfig, KeywordRule, RadarConfig
from radar.storage.repository import SqliteRepository


class FakeOKSource:
    name = "fake_ok"

    def fetch(self, ctx):
        return [
            RawItem(source="fake_ok", title="新用户注册送 $25 额度",
                    url="https://example.com/a", evidence="welcome credit"),
        ]


class FakeFailSource:
    name = "fake_fail"

    def fetch(self, ctx):
        raise RuntimeError("boom")


def _cfg(tmp_path) -> RadarConfig:
    return RadarConfig(
        root=tmp_path,
        general=GeneralConfig(data_dir=str(tmp_path / "data"), expire_days=45, promo_threshold=4.0),
        keywords=[KeywordRule(r"注册.{0,6}送", 3.0, "注册送")],
        sources={"fake_ok": {"enabled": True}, "fake_fail": {"enabled": True}},
    )


def test_make_key_keeps_key_override_without_url():
    item = RawItem(source="watchlist", title="", url="", key_override="watchlist:X:home")
    expected = hashlib.sha1(b"watchlist:X:home").hexdigest()
    assert make_key(item) == expected
    # 无 override 且无 url 时才回退到 source+标题
    plain = RawItem(source="x", title="Hello")
    assert make_key(plain) == make_key(RawItem(source="x", title="Hello"))
    assert make_key(plain) != expected


def test_monitor_band_splits_double_semicolon_keywords(tmp_path):
    providers = tmp_path / "providers.toml"
    providers.write_text(
        '[[provider]]\nname = "X"\nurls = [\n    { label = "home", url = "https://x.ai" },\n]\n',
        encoding="utf-8",
    )
    store = SqliteRepository(tmp_path / "test.db")
    now = utcnow()
    store.upsert_snapshot(
        url="https://x.ai", provider="X", label="home", content_hash="h",
        promo_keywords="free credits;;free tier", now=now, changed=False,
    )
    store.record_history(
        url="https://x.ai", checked_at=iso(now),
        promo_keywords="free credits;;free tier", changed=True,
    )

    rows = _monitor_rows(store, providers, days=3)
    store.close()
    assert len(rows) == 1
    assert rows[0]["band"] == "--1" or rows[0]["band"].endswith("1")
    assert rows[0]["checked_days"] == 1


def test_freshness_levels(tmp_path):
    now = utcnow()

    def level_at(hours_ago: float) -> str:
        store = SqliteRepository(tmp_path / f"fresh-{hours_ago}.db")
        finished = now - timedelta(hours=hours_ago)
        # 新鲜度只认全量轮次（>= full_run_min_sources），单源 --only 不算
        store.record_run(RunReport(started_at=finished, finished_at=finished,
                                   results=[SourceResult(name=f"a{i}") for i in range(5)]))
        result = _freshness(store, now, min_sources=5)["level"]
        store.close()
        return result

    fresh_store = SqliteRepository(tmp_path / "fresh-empty.db")
    assert _freshness(fresh_store, now, min_sources=5)["level"] == "critical"
    fresh_store.close()

    assert level_at(3) == "ok"
    assert level_at(10) == "warn"
    assert level_at(30) == "critical"


def test_last_success_requires_at_least_one_success(tmp_path):
    now = utcnow()
    store = SqliteRepository(tmp_path / "fresh-health.db")

    # 单源失败：不能算「基本健康」
    store.record_run(RunReport(started_at=now, finished_at=now,
                               results=[SourceResult(name="bad", status="error")]))
    assert store.last_success_at() is None

    # 5 源 1 失败（20%）：健康（容忍单个长期失效源）
    healthy_at = now + timedelta(minutes=2)
    store.record_run(RunReport(
        started_at=healthy_at, finished_at=healthy_at,
        results=[SourceResult(name=f"ok{i}") for i in range(4)]
        + [SourceResult(name="bad", status="error")],
    ))
    assert store.last_success_at() == iso(healthy_at)

    # 2 源 1 失败（50%）：不健康，不能把时间前移到本轮
    half_at = now + timedelta(minutes=3)
    store.record_run(RunReport(
        started_at=half_at, finished_at=half_at,
        results=[SourceResult(name="ok"), SourceResult(name="bad", status="error")],
    ))
    assert store.last_success_at() == iso(healthy_at)

    # 单源局部刷新（--only watchlist）成功：不更新全量新鲜度，避免掩盖全源故障
    single_at = now + timedelta(minutes=4)
    store.record_run(RunReport(
        started_at=single_at, finished_at=single_at,
        results=[SourceResult(name="watchlist")],
    ))
    assert store.last_success_at(min_sources=5) == iso(healthy_at)
    # 不传阈值时保留旧语义（任意健康轮次），供 CLI/调试用
    assert store.last_success_at() == iso(single_at)
    store.close()


def test_expire_skipped_when_sources_unhealthy(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    store = SqliteRepository(tmp_path / "test.db")
    item = RawItem(source="fake_ok", title="注册送 $25 额度", url="https://example.com/old",
                   evidence="注册送 25 额度")
    deal, _ = store.upsert_scored(score_item(item), utcnow())
    store.conn.execute(
        "UPDATE deals SET last_seen_at = '2020-01-01T00:00:00Z' WHERE dedup_key = ?",
        (deal.dedup_key,),
    )
    store.conn.commit()

    monkeypatch.setattr(runner_mod, "build_sources", lambda cfg: [FakeFailSource()])
    report = runner_mod.run(cfg, store)
    assert report.success_rate == 0.0
    assert report.expired_count == 0
    assert store.get_deal(deal.dedup_key).status != "expired"
    store.close()


def test_expire_runs_when_sources_healthy(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    store = SqliteRepository(tmp_path / "test.db")
    item = RawItem(source="fake_ok", title="注册送 $25 额度", url="https://example.com/old",
                   evidence="注册送 25 额度")
    deal, _ = store.upsert_scored(score_item(item), utcnow())
    store.conn.execute(
        "UPDATE deals SET last_seen_at = '2020-01-01T00:00:00Z' WHERE dedup_key = ?",
        (deal.dedup_key,),
    )
    store.conn.commit()

    monkeypatch.setattr(runner_mod, "build_sources", lambda cfg: [FakeOKSource()])
    report = runner_mod.run(cfg, store)
    assert report.success_rate == 1.0
    assert report.expired_count == 1
    assert store.get_deal(deal.dedup_key).status == "expired"
    store.close()


def test_expire_skipped_when_no_sources_ran(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    store = SqliteRepository(tmp_path / "test.db")
    item = RawItem(source="fake_ok", title="注册送 $25 额度", url="https://example.com/old",
                   evidence="注册送 25 额度")
    deal, _ = store.upsert_scored(score_item(item), utcnow())
    store.conn.execute(
        "UPDATE deals SET last_seen_at = '2020-01-01T00:00:00Z' WHERE dedup_key = ?",
        (deal.dedup_key,),
    )
    store.conn.commit()

    monkeypatch.setattr(runner_mod, "build_sources", lambda cfg: [])
    report = runner_mod.run(cfg, store, only=["no-such-source"])
    assert report.expired_count == 0
    assert store.get_deal(deal.dedup_key).status != "expired"
    store.close()


class FakeCatalogSource:
    name = "fake_cat"
    full_snapshot = True
    items: list[RawItem] = []

    def fetch(self, ctx):
        return list(self.items)


def _catalog_item(n: int) -> RawItem:
    return RawItem(
        source="fake_cat", title=f"活动 {n}", url=f"https://cat.example/{n}",
        evidence="signup bonus", key_override=f"cat:{n}", force_keep=True,
    )


def test_catalog_disappearance_archives_missing_item(tmp_path, monkeypatch):
    src = FakeCatalogSource()
    src.items = [_catalog_item(i) for i in range(1, 5)]
    monkeypatch.setattr(runner_mod, "build_sources", lambda cfg: [src])
    cfg = _cfg(tmp_path)
    store = SqliteRepository(tmp_path / "test.db")

    first = runner_mod.run(cfg, store)
    assert len(first.new_deals) == 4
    gone_key = make_key(_catalog_item(4))

    src.items = [_catalog_item(i) for i in range(1, 4)]  # 4 消失
    runner_mod.run(cfg, store)
    assert store.get_deal(gone_key).status == "expired"
    store.close()


def test_catalog_zero_items_does_not_archive(tmp_path, monkeypatch):
    src = FakeCatalogSource()
    src.items = [_catalog_item(i) for i in range(1, 4)]
    monkeypatch.setattr(runner_mod, "build_sources", lambda cfg: [src])
    cfg = _cfg(tmp_path)
    store = SqliteRepository(tmp_path / "test.db")

    runner_mod.run(cfg, store)
    keys = [make_key(_catalog_item(i)) for i in range(1, 4)]

    src.items = []  # 上游解析失败（0 条）
    runner_mod.run(cfg, store)
    assert all(store.get_deal(k).status != "expired" for k in keys), "0 条时必须拒绝归档"
    store.close()


def test_snapshot_failure_count_resets_on_success(tmp_path):
    store = SqliteRepository(tmp_path / "test.db")
    now = utcnow()
    for _ in range(2):
        store.record_snapshot_failure(
            url="https://x.ai", provider="X", label="home", error="timeout", now=now
        )
    snap = store.get_snapshot("https://x.ai")
    assert snap["fail_count"] == 2
    assert "timeout" in snap["last_error"]

    store.upsert_snapshot(
        url="https://x.ai", provider="X", label="home", content_hash="h",
        promo_keywords="", now=now, changed=False,
    )
    snap = store.get_snapshot("https://x.ai")
    assert snap["fail_count"] == 0
    assert snap["last_error"] == ""
    store.close()


def test_v4_schema_migrates_to_latest(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (
            url TEXT PRIMARY KEY, provider TEXT NOT NULL, label TEXT DEFAULT '',
            content_hash TEXT NOT NULL, promo_keywords TEXT DEFAULT '',
            last_checked_at TEXT NOT NULL, last_changed_at TEXT NOT NULL
        );
        PRAGMA user_version = 4;
        """
    )
    conn.commit()
    conn.close()

    store = SqliteRepository(db)
    cols = {r["name"] for r in store.conn.execute("PRAGMA table_info(snapshots)")}
    version = store.conn.execute("PRAGMA user_version").fetchone()[0]
    store.close()
    assert {"fail_count", "last_error", "tier", "next_check_at"} <= cols
    assert version == 9  # v7/v8/v9 只新增表或列，旧数据不重写