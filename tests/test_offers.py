"""Offer 层：按厂商+金额+标题归并，deals 作为证据。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_offers import build_offers  # noqa: E402
from radar.storage.repository import SqliteRepository  # noqa: E402


def _deal(repo, key, title, provider, amount, url, status, source="x"):
    repo.conn.execute(
        "INSERT INTO deals (dedup_key, source, title, url, provider, amount_hint,"
        " first_seen_at, last_seen_at, last_changed_at, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            key, source, title, url, provider, amount,
            "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00", status,
        ),
    )


def test_offer_grouping_and_evidence(tmp_path):
    repo = SqliteRepository(tmp_path / "radar.db")
    repo.conn.execute(
        "INSERT INTO providers (slug, name, category, status)"
        " VALUES ('openai', 'OpenAI', 'model_lab', 'monitored')"
    )
    repo.conn.execute(
        "INSERT INTO provider_aliases (alias, provider_id, kind) VALUES ('openai', 1, 'name')"
    )
    _deal(repo, "k1", "OpenAI $50 credits", "OpenAI", "$50", "https://openai.com/x", "new", "a")
    _deal(repo, "k2", "OpenAI $50 credits", "OpenAI", "$50", "https://openai.com/y", "active", "b")
    _deal(repo, "k3", "OpenAI free tier", "OpenAI", "", "https://openai.com/z", "expired", "c")
    repo.conn.commit()

    stats = build_offers(repo.conn)
    assert stats["offers"] == 2
    assert stats["evidence"] == 3
    assert stats["merged"] == 1
    assert stats["unmatched"] == 0

    by_status = repo.offer_stats()
    assert by_status["total"] == 2
    assert by_status["active"] == 1
    assert by_status["expired"] == 1


def test_offers_idempotent(tmp_path):
    repo = SqliteRepository(tmp_path / "radar.db")
    _deal(repo, "k1", "Foo $10", "", "$10", "https://foo.dev", "new")
    repo.conn.commit()

    build_offers(repo.conn)
    build_offers(repo.conn)
    assert repo.offer_stats()["total"] == 1
    assert repo.conn.execute("SELECT COUNT(*) FROM offer_evidence").fetchone()[0] == 1