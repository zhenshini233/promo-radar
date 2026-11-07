"""Provider 实体导入：计数、覆盖率口径、幂等、域名不抢占。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_providers import import_records  # noqa: E402
from radar.storage.repository import SqliteRepository  # noqa: E402


def _entry(**kw):
    base = {
        "slug": "", "name": "", "domains": [], "sources": [],
        "monitored": False, "vendor_like": True, "category": "unknown",
        "regions": ["global"], "relevance": 0.5, "confidence": "low",
        "brand_key": None, "duplicate_of": None,
    }
    base.update(kw)
    return base


def _entries():
    return [
        _entry(slug="openai.com", name="OpenAI", domains=["openai.com"],
               sources=["modelsdev", "aicredits"], monitored=True,
               category="model_lab", regions=["us", "global"], relevance=0.95,
               confidence="high", brand_key="openai"),
        _entry(slug="openai", name="OpenAI (dup)", domains=["openai.com"],
               sources=["litellm"], monitored=True, category="model_lab",
               regions=["us", "global"], relevance=0.9, confidence="high",
               brand_key="openai", duplicate_of="openai.com"),
        _entry(slug="foo.dev", name="Foo", domains=["foo.dev"],
               sources=["modelsdev"]),
        _entry(slug="nairr", name="NAIRR Pilot", vendor_like=False,
               monitored=True, relevance=0.3),
    ]


def _repo(tmp_path) -> SqliteRepository:
    return SqliteRepository(tmp_path / "radar.db")


def test_import_counts_and_coverage(tmp_path):
    repo = _repo(tmp_path)
    result = import_records(repo.conn, _entries())
    stats = repo.provider_stats()

    assert stats["total"] == 3
    assert stats["monitored"] == 1
    assert stats["ignored"] == 1
    assert stats["universe"] == 2
    assert stats["coverage"] == 0.5
    assert result["stats"]["domains"] == 2
    assert result["conflicts"]["domain"] == []


def test_import_is_idempotent(tmp_path):
    repo = _repo(tmp_path)
    import_records(repo.conn, _entries())
    import_records(repo.conn, _entries())

    assert repo.provider_stats()["total"] == 3
    assert repo.conn.execute("SELECT COUNT(*) FROM provider_domains").fetchone()[0] == 2
    assert repo.conn.execute("SELECT COUNT(*) FROM provider_aliases").fetchone()[0] >= 3


def test_domain_conflict_does_not_steal(tmp_path):
    repo = _repo(tmp_path)
    entries = [
        _entry(slug="a.com", name="A", domains=["shared.com"]),
        _entry(slug="b.com", name="B", domains=["shared.com"]),
    ]
    result = import_records(repo.conn, entries)

    assert len(result["conflicts"]["domain"]) == 1
    assert repo.conn.execute("SELECT COUNT(*) FROM provider_domains").fetchone()[0] == 1


def test_empty_database_stats(tmp_path):
    repo = _repo(tmp_path)
    stats = repo.provider_stats()
    assert stats["total"] == 0
    assert stats["coverage"] == 0.0