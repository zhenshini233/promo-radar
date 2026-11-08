"""存储层测试：upsert 状态机、模糊合并、过期归档、快照与 state。"""

from datetime import timedelta

from radar.domain.dedup import make_key
from radar.domain.models import RawItem, ScoredItem, utcnow
from radar.storage.repository import SqliteRepository


def _item(title="注册送 $25 额度", url="https://example.com/deal", source="linuxdo", **kw):
    return RawItem(source=source, title=title, url=url, evidence="注册送 $25 额度，详情见帖", **kw)


def _scored(item=None):
    from radar.domain.scoring import score_item

    return score_item(item or _item())


def _store(tmp_path):
    return SqliteRepository(tmp_path / "test.db")


def test_snapshots(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    later = now + timedelta(hours=1)
    store.upsert_snapshot(
        url="https://p.com", provider="P", label="home",
        content_hash="aaa", promo_keywords="free tier", now=now, changed=False,
    )
    snap = store.get_snapshot("https://p.com")
    assert snap["content_hash"] == "aaa" and snap["provider"] == "P"
    assert snap["last_changed_at"] == snap["last_checked_at"]  # 首建基线

    store.upsert_snapshot(
        url="https://p.com", provider="P", label="home",
        content_hash="bbb", promo_keywords="", now=later, changed=True,
    )
    snap2 = store.get_snapshot("https://p.com")
    assert snap2["content_hash"] == "bbb"
    assert snap2["last_changed_at"] == snap2["last_checked_at"]  # 内容变化 → 变化时间刷新
    assert snap2["last_checked_at"] != snap["last_checked_at"]


def test_state_roundtrip(tmp_path):
    store = _store(tmp_path)
    assert store.get_state("k") is None
    store.set_state("k", "v1")
    store.set_state("k", "v2")
    assert store.get_state("k") == "v2"


def test_digest_data_sections(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    scored = _scored()
    store.upsert_offer(scored.item, now, score=scored.score, matched=scored.matched)
    data = store.digest_data(now)
    assert len(data["new_deals"]) == 1
    assert data["total_deals"] == 1 and data["active_deals"] == 1
    assert data["needs_review"] == []


def test_feedback_upsert_and_clear(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    scored = _scored()
    offer, _ = store.upsert_offer(scored.item, now, score=scored.score, matched=scored.matched)
    key = offer.dedup_key

    store.record_feedback(key, "up")
    assert store.feedback_map() == {key: "up"}

    # 改主意：覆盖
    store.record_feedback(key, "down")
    assert store.feedback_map() == {key: "down"}

    # 空 vote = 清除
    store.record_feedback(key, "")
    assert store.feedback_map() == {}


def test_feedback_rejects_bad_vote(tmp_path):
    store = _store(tmp_path)
    try:
        store.record_feedback("k", "banana")
    except ValueError:
        return
    raise AssertionError("bad vote should raise")


def test_feedback_stats_aggregates_by_source(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    s1 = _scored(_item(source="linuxdo"))
    s2 = _scored(_item(title="HN 同款", url="https://hn.com/x", source="hackernews"))
    d1, _ = store.upsert_offer(s1.item, now, score=s1.score, matched=s1.matched)
    d2, _ = store.upsert_offer(s2.item, now, score=s2.score, matched=s2.matched)
    store.record_feedback(d1.dedup_key, "up")
    store.record_feedback(d1.dedup_key, "down")  # 覆盖，不算两条
    store.record_feedback(d2.dedup_key, "up")

    stats = store.feedback_stats()
    assert stats["total"] == 2
    assert stats["up"] == 1
    assert stats["down"] == 1
    assert stats["by_source"]["linuxdo"]["down"] == 1
    assert stats["by_source"]["hackernews"]["up"] == 1