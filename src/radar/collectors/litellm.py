"""BerriAI/litellm 的 model_prices_and_context_window.json（业界事实标准价格库）。

diff 事件：
- 新模型且输入价为 0 → "新增免费模型"；
- 已有模型输入价降幅 ≥ 阈值（默认 50%）→ "价格大降"。
纯涨价/常规波动不产生事件（噪音）。
"""

from __future__ import annotations

from ..domain.models import RawItem
from ..infra.http import get_json
from .base import FetchContext, register_source
from .catalog import CatalogDiffSource

DEFAULT_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)


def _canonical_provider(p: str) -> str:
    """归并同一厂商的路由/变体子标签（vertex_ai-anthropic_models → vertex_ai 等）。"""
    if p.startswith("vertex_ai"):  # vertex_ai-*-models 子标签都是 vertex 路由
        return "vertex_ai"
    if p.startswith("bedrock"):  # bedrock_converse / bedrock_mantle
        return "bedrock"
    if p.startswith("text-completion-"):  # text-completion-openai → openai
        return p[len("text-completion-"):]
    if p in ("azure_ai", "azure_text"):  # Azure 系路由归并
        return "azure"
    if p == "cohere_chat":
        return "cohere"
    if p == "fireworks_ai-embedding-models":
        return "fireworks_ai"
    if p == "meta_llama":
        return "meta"
    if p == "amazon_nova":  # Nova 只经 Bedrock 提供
        return "bedrock"
    return p


def _extract_prices(data) -> dict[str, dict]:
    """{model: {"i": 输入价, "o": 输出价, "p": provider}}；取每 token 美元价，8 位舍入。"""
    if not isinstance(data, dict):
        raise RuntimeError("litellm: unexpected schema (not a dict)")
    out: dict[str, dict] = {}
    for model, info in data.items():
        if not isinstance(info, dict) or str(info.get("mode", "")) in ("", "audio_transcription"):
            continue
        raw_p = str(info.get("litellm_provider") or "")
        if raw_p.startswith("one of"):  # sample_spec 等说明行的占位文本
            continue
        try:
            i_cost = round(float(info.get("input_cost_per_token", -1)), 8)
            o_cost = round(float(info.get("output_cost_per_token", -1)), 8)
        except (TypeError, ValueError):
            continue
        if i_cost < 0:
            continue
        out[str(model)] = {"i": i_cost, "o": o_cost, "p": _canonical_provider(raw_p)}
    return out


@register_source("litellm")
class LiteLLMSource(CatalogDiffSource):
    state_key = "litellm:prices"

    def _drop_threshold(self, ctx: FetchContext) -> float:
        return float(ctx.cfg.source("litellm").get("drop_threshold", 0.5))

    def fetch_catalog(self, ctx: FetchContext) -> dict:
        self._drop_threshold = float(ctx.cfg.source("litellm").get("drop_threshold", 0.5))
        url = ctx.cfg.source("litellm").get("url", DEFAULT_URL)
        return _extract_prices(get_json(ctx.http, url))

    def diff_to_items(self, prev: dict, curr: dict) -> list[RawItem]:
        items: list[RawItem] = []
        threshold = self._drop_threshold
        for model, info in sorted(curr.items()):
            old = prev.get(model)
            if old is None:
                if info["i"] == 0:
                    items.append(
                        RawItem(
                            source="litellm",
                            title=f"[litellm] 新增免费模型: {model}（{info['p']}）",
                            url="https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json",
                            provider=info["p"] or None,
                            evidence=f"litellm 价格库出现 {model}（{info['p']}），输入价 0。免费档上线通常是拉新信号。",
                            key_override=f"litellm:free:{model}",
                            force_keep=True,
                        )
                    )
                continue
            if old["i"] > 0 and info["i"] < old["i"]:
                drop = 1 - info["i"] / old["i"]
                if drop >= threshold:
                    items.append(
                        RawItem(
                            source="litellm",
                            title=f"[litellm] 价格大降 {drop:.0%}: {model}（{info['p']}）",
                            url="https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json",
                            provider=info["p"] or None,
                            evidence=(
                                f"{model} 输入价 {old['i']:.2e} → {info['i']:.2e} $/token"
                                f"（降 {drop:.0%}）。大幅降价常伴随官方促销或竞争拉新。"
                            ),
                            key_override=f"litellm:drop:{model}:{old['i']}:{info['i']}",
                            force_keep=True,
                        )
                    )
        return items
