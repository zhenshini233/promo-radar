"""宇宙标注规则：品牌匹配、地区推断、相关性边界。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from annotate_universe import classify, is_vendor_like, relevance  # noqa: E402


def test_brand_exact_and_prefix():
    assert classify("openai", "OpenAI", ["openai.com"])[0] == "model_lab"
    assert classify("together", "Together AI", ["together.ai"])[0] == "inference"
    assert classify("alibabacloud.com", "Alibaba Coding Plan (China)", ["aliyun.com"])[0] == "cloud"
    assert classify("x.ai", "xAI", ["x.ai"])[0] == "model_lab"
    assert classify("stability", "Stability AI", ["stability.ai"])[0] == "model_lab"


def test_region_by_brand_name_and_tld():
    assert classify("zhipu", "Zhipu AI", ["bigmodel.cn"])[1] == ("cn", "global")
    assert classify("sakana", "Sakana AI", ["sakana.ai"])[1] == ("apac",)
    assert classify("weaviate", "Weaviate", ["weaviate.io"])[1] == ("eu", "global")
    assert classify("foo", "Foo Bar", [])[1] == ("unknown",)


def test_unknown_stays_unknown():
    cat, regions, conf = classify("foo", "Foo Bar", ["foo.dev"])
    assert cat == "unknown"
    assert regions == ("global",)
    assert conf == "low"


def test_relevance_bounds_and_monotonic():
    assert relevance("model_lab", ["x.com"], 2, True, True) == 0.95
    assert relevance("unknown", [], 1, False, True) == 0.5
    assert relevance("unknown", [], 1, False, False) == 0.3
    assert relevance("relay", [], 0, False, True) == 0.5


def test_non_vendor_detection():
    assert is_vendor_like("NAIRR Pilot", "nairrpilot.org") is False
    assert is_vendor_like("Antler Disrupt", "antler.co") is False
    assert is_vendor_like("OpenAI", "openai.com") is True