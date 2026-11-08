"""v10 云资源扩展：目录解析、单位归一、免费门槛、Offer 幂等。"""

from __future__ import annotations

import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.collectors.cloud.free_for_dev import parse_readme
from radar.domain.dedup import offer_key
from radar.domain.free_gate import is_free_resource, is_paid_program
from radar.domain.models import RawItem
from radar.domain.normalize_units import extract_limits, extract_specs
from radar.infra.cloud_config import load_cloud_pages
from radar.storage.repository import SqliteRepository


def _item(**kw) -> RawItem:
    base = dict(source="test", title="Test", vertical="paas", offer_type="free_tier")
    base.update(kw)
    return RawItem(**base)


def test_parse_readme_keeps_only_deployable_categories():
    md = """
## Web Hosting
  * [Cloudflare Pages](https://pages.cloudflare.com) - Static hosting with free tier.
  * [Netlify](https://netlify.com) - Free plan with 100 GB bandwidth.

## Design Tools
  * [Figma](https://figma.com) - Free plan for designers.

## Databases
  * [Supabase](https://supabase.com) - Free Postgres database.
"""
    items = parse_readme(md, limit=50)
    providers = {i.provider for i in items}
    assert {"Cloudflare Pages", "Netlify", "Supabase"} <= providers
    assert "Figma" not in providers
    assert all(i.vertical in {"paas", "database"} for i in items)


def test_extract_specs_and_credit_are_bounded():
    specs = extract_specs("2 vCPU, 4 GB RAM, 80 GB SSD, 100 GB bandwidth")
    assert specs["vcpu"] == 2
    assert specs["ram_gb"] == 4
    assert specs["disk_gb"] == 80
    assert specs["bandwidth_gb"] == 100

    # "$200 in credits" 才能识别为赠金；普通价格不能当额度
    assert extract_limits("Get $200 in credits, no credit card")["credit_usd"] == 200
    assert "credit_usd" not in extract_limits("Only $0.00325 per GB")

    # 异常大的数字被丢弃
    assert "vcpu" not in extract_specs("1000000 vCPU")


def test_free_gate_rejects_paid_programs():
    paid = _item(
        title="AI Research Internship - paid fellowship",
        evidence="A funded research program with a stipend.",
        offer_type="free_tier",
    )
    assert is_paid_program(paid)
    assert not is_free_resource(paid)

    free = _item(
        title="Oracle Always Free",
        evidence="4 OCPU and 24 GB memory, always free.",
        vertical="cloud",
        offer_type="always_free",
        resources={"ram_gb": 24},
    )
    assert is_free_resource(free)


def test_offer_key_is_stable_and_distinguishes_entries():
    a = _item(provider="Demo", title="Demo Free Tier", resources={"vcpu": 2, "ram_gb": 4})
    b = _item(provider="Demo", title="Demo Free Tier", resources={"vcpu": 4, "ram_gb": 8})
    c = _item(provider="Demo", title="Demo Worker Free Tier", resources={"vcpu": 2})
    # 规格变化不改变身份（由 terms_hash 记录变化）
    assert offer_key(a) == offer_key(b)
    assert offer_key(a) != offer_key(c)


def test_upsert_offer_idempotent_and_records_terms_change(tmp_path):
    repo = SqliteRepository(tmp_path / "radar.db")
    now = datetime(2026, 11, 8, tzinfo=timezone.utc)
    item = _item(provider="Demo Cloud", resources={"ram_gb": 4}, vertical="cloud")

    offer, action = repo.upsert_offer(item, now)
    assert action == "new"
    assert offer is not None and offer.provider == "Demo Cloud"

    _, action2 = repo.upsert_offer(item, now)
    assert action2 == "unchanged"
    assert repo.conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 1

    changed = _item(provider="Demo Cloud", resources={"ram_gb": 8}, vertical="cloud")
    _, action3 = repo.upsert_offer(changed, now)
    assert action3 == "updated"
    assert repo.conn.execute("SELECT COUNT(*) FROM offer_terms_history").fetchone()[0] == 1
    assert repo.conn.execute(
        "SELECT COUNT(*) FROM signals WHERE kind='terms_changed'"
    ).fetchone()[0] == 1
    repo.close()


def test_load_cloud_pages_skips_invalid_entries(tmp_path):
    p = tmp_path / "cloud_sources.toml"
    p.write_text(
        """
[[page]]
name = "ok"
provider = "OK"
url = "https://example.com/free"

[[page]]
name = ""
url = "https://example.com/bad"
""",
        encoding="utf-8",
    )
    specs = load_cloud_pages(p)
    assert len(specs) == 1
    assert specs[0].provider == "OK"
    assert specs[0].vertical == "cloud"

def test_expire_offers_by_date_and_stale(tmp_path):
    """两种过期：明确截止时间，以及长期未再见。"""
    repo = SqliteRepository(tmp_path / "radar.db")
    now = datetime(2026, 11, 8, tzinfo=timezone.utc)

    expired_by_date = _item(
        provider="DateCo", title="Date limited", expires_at="2026-11-01T00:00:00Z"
    )
    stale = _item(provider="StaleCo", title="Old observation")
    repo.upsert_offer(expired_by_date, now)
    repo.upsert_offer(stale, now - timedelta(days=60))

    count = repo.expire_offers(now=now, stale_days=45)
    assert count == 2
    assert repo.get_offer(offer_key(expired_by_date)).status == "expired"
    assert repo.get_offer(offer_key(expired_by_date)).status_reason == "expires_at"
    assert repo.get_offer(offer_key(stale)).status == "expired"
    assert repo.get_offer(offer_key(stale)).status_reason == "stale"
    repo.close()