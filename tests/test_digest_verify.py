"""首页摘要与人工核实。"""

from datetime import datetime, timedelta, timezone

from radar.storage.repository import SqliteRepository


def _now():
    return datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _deal(repo, key, first, last, status="active", provider="OpenAI"):
    repo.conn.execute(
        "INSERT INTO deals (dedup_key, source, title, url, provider, amount_hint,"
        " first_seen_at, last_seen_at, last_changed_at, status)"
        " VALUES (?, 'x', 't', 'https://x', ?, '$10', ?, ?, ?, ?)",
        (key, provider, first, last, last, status),
    )
    # v10：首页统计读 offers，同步写一条最小的 Offer
    repo.conn.execute(
        "INSERT INTO offers (dedup_key, source, title, url, provider_name,"
        " first_seen_at, last_seen_at, status, vertical, offer_type)"
        " VALUES (?, 'x', 't', 'https://x', ?, ?, ?, ?, 'ai_api', 'credits')",
        (key, provider, first, last, status),
    )


def test_today_digest_counts(tmp_path):
    repo = SqliteRepository(tmp_path / "radar.db")
    now = _now()
    today = now.date().isoformat()
    repo.conn.execute(
        "INSERT INTO providers (id, slug, name, category, status)"
        " VALUES (1, 'openai', 'OpenAI', 'model_lab', 'monitored')"
    )
    repo.conn.execute(
        "INSERT INTO providers (id, slug, name, category, status)"
        " VALUES (2, 'foo', 'Foo', 'unknown', 'monitored')"
    )
    repo.conn.execute("INSERT INTO provider_domains (domain, provider_id) VALUES ('openai.com', 1)")
    repo.conn.execute("INSERT INTO provider_domains (domain, provider_id) VALUES ('foo.dev', 2)")
    _deal(repo, "k1", f"{today}T09:00:00Z", f"{today}T09:00:00Z")
    _deal(repo, "k2", "2026-11-01T09:00:00Z", "2026-11-06T09:00:00Z")
    repo.conn.execute(
        "INSERT INTO snapshots (url, provider, content_hash, last_checked_at, last_changed_at, fail_count)"
        " VALUES ('https://openai.com/pricing', 'OpenAI', 'h', ?, ?, 0)",
        (iso(now), iso(now)),
    )
    repo.conn.execute(
        "INSERT INTO snapshots (url, provider, content_hash, last_checked_at, last_changed_at, fail_count)"
        " VALUES ('https://foo.dev/x', 'Foo', 'h', ?, ?, 1)",
        (iso(now), iso(now)),
    )
    repo.conn.commit()

    d = repo.today_digest(now=now)
    assert d["today_new"] == 1
    assert d["recent_active"] == 2
    assert d["missed_count"] == 1
    assert d["missed"][0]["name"] == "Foo"
    assert d["missed"][0]["reason"] == "从未成功抓取"


def test_verify_offer(tmp_path):
    repo = SqliteRepository(tmp_path / "radar.db")
    _deal(repo, "k1", "2026-11-07T09:00:00Z", "2026-11-07T09:00:00Z")
    repo.conn.commit()

    assert repo.verify_offer("k1", by="user", now=_now()) is True
    offer = repo.get_offer("k1")
    assert offer.verified_by == "user"
    assert offer.last_verified_at.startswith("2026-11-07")
    assert repo.verify_offer("missing") is False


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")