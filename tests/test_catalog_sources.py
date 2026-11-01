"""四个目录 diff 源的解析与事件测试（fixtures 为真实响应裁剪样本）。"""

import json
from pathlib import Path
from unittest.mock import MagicMock

from radar.collectors.litellm import LiteLLMSource, _extract_prices
from radar.collectors.mnfst import MnfstSource, _extract_providers as _mnfst_extract
from radar.collectors.modelsdev import ModelsDevSource, _extract_providers
from radar.collectors.freetoken import FreeTokenSource, _extract_providers as _ft_extract

FIXTURES = Path(__file__).parent / "fixtures"


def _ctx():
    return MagicMock()


# ---------- models.dev ----------

def test_modelsdev_extract_and_diff():
    data = json.loads((FIXTURES / "modelsdev_api.json").read_text(encoding="utf-8"))
    catalog = _extract_providers(data)
    assert len(catalog) == 3
    first = next(iter(catalog.values()))
    assert {"label", "models", "doc"} <= set(first)

    src = ModelsDevSource()
    items = src.diff_to_items({}, catalog)
    assert len(items) == 3
    assert all(i.force_keep and i.key_override.startswith("modelsdev:provider:") for i in items)


# ---------- mnfst ----------

def test_mnfst_extract_and_diff():
    data = json.loads((FIXTURES / "mnfst_data.json").read_text(encoding="utf-8"))
    catalog = _mnfst_extract(data)
    assert len(catalog) == 3

    src = MnfstSource()
    items = src.diff_to_items({}, catalog)
    assert len(items) == 3
    assert items[0].source == "mnfst"


# ---------- freetoken ----------

def test_freetoken_extract_handles_dict_wrapper():
    data = json.loads((FIXTURES / "freetoken_providers.json").read_text(encoding="utf-8"))
    catalog = _ft_extract(data)
    assert 0 < len(catalog) <= 16

    src = FreeTokenSource()
    items = src.diff_to_items({}, catalog)
    assert len(items) == len(catalog)
    assert all(i.force_keep for i in items)


# ---------- litellm ----------

def test_litellm_extract_prices():
    data = json.loads((FIXTURES / "litellm_prices.json").read_text(encoding="utf-8"))
    prices = _extract_prices(data)
    # 样本中按图计价的 image_generation 条目（无 token 价）被正确过滤
    assert 15 <= len(prices) <= 38
    assert all(info["i"] >= 0 for info in prices.values())  # 样本中部分条目（audio 等）会被过滤
    for info in prices.values():
        assert set(info) == {"i", "o", "p"}
        assert info["i"] >= 0
    # sample_spec 说明行（provider 是 "one of ..." 占位文本）不进价格库
    assert "sample_spec" not in prices


def test_litellm_provider_canonicalization():
    data = json.loads((FIXTURES / "litellm_prices.json").read_text(encoding="utf-8"))
    prices = _extract_prices(data)
    # 路由/变体子标签归并到主厂商（登记名单与事件标题可读）
    assert prices["us.writer.palmyra-x4-v1:0"]["p"] == "bedrock"      # bedrock_converse
    assert prices["azure_ai/cohere-rerank-v3-english"]["p"] == "azure"  # azure_ai
    from radar.collectors.litellm import _canonical_provider
    assert _canonical_provider("vertex_ai-anthropic_models") == "vertex_ai"
    assert _canonical_provider("text-completion-openai") == "openai"
    assert _canonical_provider("cohere_chat") == "cohere"
    assert _canonical_provider("v0") == "v0"  # 独立厂商不误伤


def test_litellm_free_model_and_price_drop_events():
    src = LiteLLMSource()
    src._drop_threshold = 0.5
    prev = {"paid-model": {"i": 1e-5, "o": 2e-5, "p": "openai"}}
    curr = {
        "paid-model": {"i": 2e-6, "o": 2e-5, "p": "openai"},   # 降 80% → 事件
        "new-free": {"i": 0.0, "o": 0.0, "p": "somelab"},      # 新增免费 → 事件
        "stable-model": {"i": 3e-5, "o": 3e-5, "p": "x"},      # 新增但收费 → 无事件
    }
    items = src.diff_to_items(prev, curr)
    titles = [i.title for i in items]
    assert any("价格大降" in t and "paid-model" in t for t in titles)
    assert any("新增免费模型" in t and "new-free" in t for t in titles)
    assert not any("stable-model" in t for t in titles)


def test_litellm_small_drop_no_event():
    src = LiteLLMSource()
    src._drop_threshold = 0.5
    prev = {"m": {"i": 1e-5, "o": 2e-5, "p": "x"}}
    curr = {"m": {"i": 0.8e-5, "o": 2e-5, "p": "x"}}  # 降 20%
    assert src.diff_to_items(prev, curr) == []
