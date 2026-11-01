"""盲区收编计划的纯计算测试（URL 解析 / 去重 / 待收编）。"""

from radar.pipeline.enroll import compute_enroll_plan


def test_compute_enroll_plan_resolves_and_pends():
    registries = {
        "openrouter": ["deepinfra", "akashml", "v0"],
        "modelsdev": ["somevendor"],
    }
    tracked = {"deepinfra"}  # 已监控 → 不算盲区
    modelsdev = {"somevendor": {"label": "SomeVendor", "doc": "https://docs.somevendor.dev"}}
    brands = {"v0": ("v0（Vercel）", "https://v0.app")}
    entries, pending = compute_enroll_plan(registries, tracked, modelsdev, brands)
    # v0 走品牌表官网，somevendor 走 modelsdev doc，akashml 无 URL → 待收编
    assert {e["name"] for e in entries} == {"v0（Vercel）", "SomeVendor"}
    assert [p["key"] for p in pending] == ["akashml"]
    assert pending[0]["sources"] == ["openrouter"]


def test_compute_enroll_plan_dedupes_same_domain():
    entries, _ = compute_enroll_plan(
        {"modelsdev": ["dup1", "dup2"]}, set(),
        {"dup1": {"label": "D", "doc": "https://docs.d.com"},
         "dup2": {"label": "D2", "doc": "https://docs.d.com/guide"}},
        {},
    )
    # 同一注册域只收编一个监控条目
    assert len(entries) == 1
    assert entries[0]["label"] == "docs"


def test_compute_enroll_plan_skips_variant_of_tracked():
    # ai21labs 与已监控的 ai21 互为包含 → 不算盲区
    entries, pending = compute_enroll_plan({"openrouter": ["ai21labs"]}, {"ai21"}, {}, {})
    assert entries == [] and pending == []
