"""监控页 ↔ Provider 只读关联：注册域匹配与三类计数。"""

from radar.storage.repository import SqliteRepository


def _snapshot(repo, url, provider):
    repo.conn.execute(
        "INSERT INTO snapshots (url, provider, content_hash, last_checked_at, last_changed_at)"
        " VALUES (?, ?, 'h', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
        (url, provider),
    )


def test_link_three_buckets(tmp_path):
    repo = SqliteRepository(tmp_path / "radar.db")
    repo.conn.execute(
        "INSERT INTO providers (slug, name, category, status)"
        " VALUES ('openai', 'OpenAI', 'model_lab', 'monitored')"
    )
    pid = repo.conn.execute("SELECT id FROM providers WHERE slug = 'openai'").fetchone()[0]
    repo.conn.execute(
        "INSERT INTO provider_domains (domain, provider_id, is_primary) VALUES ('openai.com', ?, 1)",
        (pid,),
    )
    repo.conn.execute(
        "INSERT INTO providers (slug, name, category, status)"
        " VALUES ('foo', 'Foo', 'unknown', 'ignored')"
    )
    repo.conn.execute("INSERT INTO provider_domains (domain, provider_id) VALUES ('foo.dev', 2)")
    repo.conn.commit()

    _snapshot(repo, "https://openai.com/pricing", "OpenAI")
    _snapshot(repo, "https://notexample.com/x", "NotExample")
    _snapshot(repo, "https://foo.dev/x", "Foo")
    repo.conn.commit()

    s = repo.provider_page_stats()
    assert s["total_pages"] == 3
    assert s["linked_pages"] == 1
    assert s["unlinked_pages"] == 1
    assert s["ignored_pages"] == 1
    assert s["link_rate"] == 1 / 3
    assert s["by_category"]["model_lab"]["pages"] == 1
    assert s["providers_with_pages"] == 1
    assert s["providers_without_pages"] == 0


def test_empty_snapshots(tmp_path):
    repo = SqliteRepository(tmp_path / "radar.db")
    s = repo.provider_page_stats()
    assert s["total_pages"] == 0
    assert s["link_rate"] == 0.0