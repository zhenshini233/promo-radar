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


def test_upsert_new_then_unchanged(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    deal, action = store.upsert_scored(_scored(), now)
    assert action == "new" and deal.status == "new"

    # 同一内容重复见到：last_seen 刷新、状态不变
    deal2, action2 = store.upsert_scored(_scored(), now + timedelta(hours=1))
    assert action2 == "unchanged"
    assert deal2.status == "new"
    assert deal2.last_seen_at > deal.first_seen_at
    assert deal2.first_seen_at == deal.first_seen_at


def test_upsert_updated_on_content_change(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    store.upsert_scored(_scored(), now)
    changed = _scored(_item("注册送 $25 额度（加码）"))
    deal, action = store.upsert_scored(changed, now + timedelta(hours=2))
    assert action == "updated" and deal.status == "updated"
    assert "加码" in deal.title


def test_expired_deal_revives(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    store.upsert_scored(_scored(), now)
    assert store.expire_old(days=0, now=now + timedelta(seconds=1)) >= 1
    assert store.get_deal(make_key(_item())).status == "expired"

    deal, action = store.upsert_scored(_scored(), now + timedelta(hours=3))
    assert action == "updated"
    assert deal.status == "updated"


def test_fuzzy_merge_records_also_seen_in(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    deal1, _ = store.upsert_scored(_scored(), now)
    candidates = [deal1]

    # 同标题（差一个标点）不同 URL、不同源 → 模糊合并
    repost = _scored(_item(title="注册送 $25 额度！", url="https://other.com/x", source="hackernews"))
    deal2, action = store.upsert_scored(repost, now + timedelta(minutes=5), fuzzy_candidates=candidates)
    assert action == "unchanged"  # 内容没变，只是被转发
    assert deal2.dedup_key == deal1.dedup_key
    assert "hackernews" in deal2.also_seen_in


def test_fuzzy_merge_keeps_master_title_and_is_stable(tmp_path):
    """模糊合并不覆盖主条目标题，且转发帖重复出现不产生 updated（幂等回归）。"""
    store = _store(tmp_path)
    now = utcnow()
    master, _ = store.upsert_scored(_scored(_item(title="注册送 $25 额度")), now)
    candidates = [master]

    repost = _scored(_item(title="注册送 $25 额度（转发版标题不同）", url="https://other.com/x"))
    deal2, action = store.upsert_scored(repost, now + timedelta(minutes=1), fuzzy_candidates=candidates)
    assert deal2.title == "注册送 $25 额度", "主条目标题必须锁定"
    assert deal2.dedup_key == master.dedup_key

    # 转发帖再次出现：走别名 sighting，不产生 updated
    store2 = store
    _, action3 = store2.upsert_scored(repost, now + timedelta(minutes=2))
    assert action3 == "unchanged"
    # 主条目再次出现：精确命中，也不产生 updated
    _, action4 = store2.upsert_scored(_scored(), now + timedelta(minutes=3))
    assert action4 == "unchanged"


def test_fuzzy_not_merged_when_expired(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    deal1, _ = store.upsert_scored(_scored(), now)
    store.expire_old(days=0, now=now + timedelta(seconds=1))
    candidates = [store.get_deal(deal1.dedup_key)]
    repost = _scored(_item(title="注册送 $25 额度！", url="https://other.com/x"))
    deal2, action = store.upsert_scored(repost, now, fuzzy_candidates=candidates)
    # 已过期候选不参与合并 → 作为新 deal 入库
    assert action == "new" and deal2.dedup_key != deal1.dedup_key


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
    store.upsert_scored(_scored(), now)
    data = store.digest_data(now)
    assert len(data["new_deals"]) == 1
    assert data["total_deals"] == 1 and data["active_deals"] == 1
    assert data["needs_review"] == []


def test_feedback_upsert_and_clear(tmp_path):
    store = _store(tmp_path)
    now = utcnow()
    deal, _ = store.upsert_scored(_scored(), now)
    key = deal.dedup_key

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
    d1, _ = store.upsert_scored(_scored(_item(source="linuxdo")), now)
    d2, _ = store.upsert_scored(
        _scored(_item(title="HN 同款", url="https://hn.com/x", source="hackernews")), now
    )
    store.record_feedback(d1.dedup_key, "up")
    store.record_feedback(d1.dedup_key, "down")  # 覆盖，不算两条
    store.record_feedback(d2.dedup_key, "up")

    stats = store.feedback_stats()
    assert stats["total"] == 2
    assert stats["up"] == 1
    assert stats["down"] == 1
    assert stats["by_source"]["linuxdo"]["down"] == 1
    assert stats["by_source"]["hackernews"]["up"] == 1
