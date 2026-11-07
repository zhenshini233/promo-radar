"""providers.toml 写入：幂等、域名去重、并发安全。"""

from concurrent.futures import ThreadPoolExecutor

from radar.infra.config import load_providers
from radar.infra.providers_store import append_provider_entries

HEADER = '# watchlist\n\n[[provider]]\nname = "Existing"\nurls = [\n    { label = "home", url = "https://existing.com" },\n]\n'


def _path(tmp_path):
    p = tmp_path / "providers.toml"
    p.write_text(HEADER, encoding="utf-8")
    return p


def test_append_is_idempotent(tmp_path):
    p = _path(tmp_path)
    entry = {"name": "NewCo", "urls": [{"label": "home", "url": "https://newco.ai"}], "notes": "x"}

    assert append_provider_entries(p, [entry]) == ["NewCo"]
    # 同名（大小写不敏感）再次追加应跳过
    assert append_provider_entries(p, [{**entry, "name": "newco"}]) == []

    providers = load_providers(p)
    assert {x["name"] for x in providers} == {"Existing", "NewCo"}
    assert p.read_text(encoding="utf-8").startswith("# watchlist")


def test_append_skips_same_registrable_domain(tmp_path):
    p = _path(tmp_path)
    first = append_provider_entries(
        p, [{"name": "Alpha", "urls": [{"label": "home", "url": "https://alpha.ai"}]}]
    )
    second = append_provider_entries(
        p, [{"name": "Alpha Alt", "urls": [{"label": "docs", "url": "https://docs.alpha.ai/x"}]}]
    )
    assert first == ["Alpha"]
    assert second == [], "同注册域不应重复收编"


def test_concurrent_appends_do_not_corrupt_or_duplicate(tmp_path):
    p = _path(tmp_path)
    names = [f"Co{i}" for i in range(10)]

    def add(i: int):
        return append_provider_entries(
            p,
            [{"name": names[i], "urls": [{"label": "home", "url": f"https://co{i}.example"}]}],
        )

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(add, range(10)))

    providers = load_providers(p)
    assert len(providers) == 11  # Existing + 10
    assert len({x["name"] for x in providers}) == 11
    text = p.read_text(encoding="utf-8")
    assert text.count('name = "Co') == 10, "不应出现重复块"


def test_broken_toml_is_not_overwritten(tmp_path):
    p = tmp_path / "providers.toml"
    p.write_text('[[provider]\nname = "broken"\n', encoding="utf-8")
    original = p.read_text(encoding="utf-8")

    try:
        append_provider_entries(
            p, [{"name": "X", "urls": [{"label": "home", "url": "https://x.ai"}]}]
        )
    except Exception:
        pass
    # 解析失败时拒绝写入，原文件保持不变
    assert p.read_text(encoding="utf-8") == original


def test_append_renders_tier(tmp_path):
    p = _path(tmp_path)
    added = append_provider_entries(p, [{
        "name": "TierCo",
        "tier": 1,
        "urls": [{"label": "home", "url": "https://tierco.ai"}],
    }])
    assert added == ["TierCo"]
    providers = load_providers(p)
    tierco = next(x for x in providers if x["name"] == "TierCo")
    assert tierco["tier"] == 1
    assert "tier = 1" in p.read_text(encoding="utf-8")