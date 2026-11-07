"""自动收编相关性闸门：硬排除 / 实体字段 / 名称启发式。"""

from radar.domain.enroll_rules import enroll_allowed


def _provider(**kw):
    base = {"status": "in_universe", "vendor_like": 1, "relevance": 0.6, "category": "inference"}
    base.update(kw)
    return base


def test_blocklist_domain_rejected():
    assert enroll_allowed("GitHub", "github.com") == (False, "blocklist")


def test_no_domain_rejected():
    assert enroll_allowed("X", "") == (False, "no-domain")


def test_entity_ignored_rejected():
    ok, reason = enroll_allowed("X", "x.example", _provider(status="ignored"))
    assert not ok and reason == "status:ignored"


def test_entity_not_vendor_rejected():
    ok, reason = enroll_allowed("X", "x.example", _provider(vendor_like=0))
    assert not ok and reason == "not-vendor"


def test_entity_low_relevance_rejected():
    ok, reason = enroll_allowed("X", "x.example", _provider(relevance=0.2))
    assert not ok and reason.startswith("low-relevance")


def test_entity_relay_rejected_unless_high_relevance():
    assert enroll_allowed("X", "x.example", _provider(category="relay", relevance=0.5))[1] == "relay"
    assert enroll_allowed("Y", "y.example", _provider(category="relay", relevance=0.8))[0]


def test_entity_ok_allowed():
    ok, reason = enroll_allowed("X", "x.example", _provider())
    assert ok and reason == "provider-entity"


def test_heuristic_rejects_directory_like_names():
    for name in ("Awesome LLM List", "AI Directory", "Some Newsletter"):
        ok, reason = enroll_allowed(name, "some.example")
        assert not ok, name
        assert reason.startswith("name:")


def test_heuristic_allows_plain_vendor_name():
    assert enroll_allowed("DeepInfra", "deepinfra.com") == (True, "heuristic")