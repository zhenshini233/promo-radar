"""去重测试：URL 规范化、标题相似度、key 稳定性、模糊合并与金额护栏。"""

from radar.domain.dedup import (
    amounts_compatible,
    canonical_url,
    find_fuzzy_match,
    make_key,
    norm_title,
    title_similarity,
)
from radar.domain.models import Deal, RawItem


def test_canonical_url_strips_tracking():
    assert (
        canonical_url("https://www.Example.com/path/?utm_source=x&aff=abc&id=2#frag")
        == "https://example.com/path?id=2"
    )


def test_canonical_url_trailing_slash():
    assert canonical_url("https://example.com/path/") == canonical_url("https://example.com/path")


def test_make_key_stable_across_tracking_params():
    a = RawItem(source="s", title="t", url="https://example.com/p?aff=1")
    b = RawItem(source="s", title="t", url="https://example.com/p?aff=2")
    assert make_key(a) == make_key(b)


def test_make_key_prefers_key_override():
    a = RawItem(source="s", title="t", url="https://example.com/p", key_override="aicredits:1")
    b = RawItem(source="s", title="t", url="https://example.com/p", key_override="aicredits:2")
    assert make_key(a) != make_key(b)


def test_title_similarity():
    assert title_similarity("新用户送额度", "新用户送额度") == 1.0
    assert title_similarity("【魔芋AI】新用户送额度", "【魔芋AI】新用户送额度！") >= 0.9
    assert title_similarity("瑞幸抽免单", "券商万一免五开户") < 0.5


def test_amounts_compatible():
    assert amounts_compatible(set(), {25.0})
    assert amounts_compatible({25.0}, {25.0})
    assert amounts_compatible({25.0}, {27.0})
    assert not amounts_compatible({25.0}, {100.0})


def _deal(title: str, amount: str | None, key: str = "k1") -> Deal:
    return Deal(
        dedup_key=key, source="linuxdo", title=title, url="https://x.com/1",
        provider=None, amount_hint=amount, card_required_hint=None,
        score=5.0, evidence="", first_seen_at="2026-06-29T00:00:00Z",
        last_seen_at="2026-06-29T00:00:00Z", last_changed_at="2026-06-29T00:00:00Z",
        status="new", also_seen_in=[],
    )


def test_fuzzy_match_merges_repost():
    candidates = [_deal("【魔芋AI】新用户送额度", "$10")]
    item = RawItem(source="hackernews", title="【魔芋AI】新用户送额度！", url="https://y.com/2")
    match = find_fuzzy_match(item, candidates)
    assert match is not None and match.dedup_key == "k1"


def test_fuzzy_match_amount_guard():
    # 标题几乎相同但金额 $25 vs $100 → 不同活动，不合并
    candidates = [_deal("平台注册送额度", "$25")]
    item = RawItem(source="hackernews", title="平台注册送额度", url="https://y.com/2", amount_hint="$100")
    assert find_fuzzy_match(item, candidates) is None


def test_fuzzy_blocked_by_title_amounts():
    # 同服务商不同档位（Google for Startups Scale vs AI Track）：hint 金额相同，
    # 但标题内金额不同 → 必须判为不同活动（真实误合并案例的回归测试）
    candidates = [
        _deal("Google for Startups Cloud Program - AI Track ($350,000)", None, key="k2")
    ]
    item = RawItem(
        source="aicredits",
        title="Google for Startups Cloud Program - Scale Tier ($200,000)",
        url="https://x.com/scale",
    )
    assert find_fuzzy_match(item, candidates) is None


def test_fuzzy_match_provider_guard():
    candidates = [_deal("平台注册送额度", None)]
    item = RawItem(source="hackernews", title="平台注册送额度", url="https://y.com/2", provider="River")
    match = find_fuzzy_match(item, candidates)
    # 一方 provider 为空不否决
    assert match is not None


def test_norm_title_strips_punctuation():
    assert norm_title("【魔芋AI】送额度！") == "魔芋ai送额度"
