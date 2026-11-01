"""覆盖计算：数据源 ↔ 厂商 的归属关系（唯一实现，三处消费）。

模型：每个能提供厂商名单的数据源维护一份"覆盖清单"（registry），
厂商被哪些源覆盖 = 拿厂商名去各清单里查（归一化后精确匹配）。
实时计算，不存历史；清单本身来自各源的 catalog 基线（state 表）。

消费方：数据源页（覆盖厂商数 + 登记名单）、厂商页（覆盖来源筛选/列）。
"""

from __future__ import annotations

import json
import re

from .brands import BRANDS

SOURCE_IDS = [
    "aicredits", "linuxdo", "hackernews", "openrouter", "modelsdev",
    "mnfst", "freetoken", "litellm", "watchlist", "aa_providers", "reddit",
]

# 有厂商清单的源（覆盖筛选只列这些）；watchlist 是监控输出层，不作为覆盖来源
REGISTRY_SOURCES = ["aicredits", "openrouter", "modelsdev", "mnfst", "freetoken", "litellm", "aa_providers"]

SOURCE_NAMES = {
    "aicredits": "aicredits.dev", "linuxdo": "Linux.do", "hackernews": "Hacker News",
    "openrouter": "OpenRouter", "modelsdev": "models.dev", "mnfst": "free-llm-apis",
    "freetoken": "FreeToken", "litellm": "LiteLLM", "watchlist": "厂商官网",
    "aa_providers": "Artificial Analysis", "reddit": "Reddit",
}

SOURCE_TYPES = {
    "aicredits": "目录", "linuxdo": "社区", "hackernews": "社区",
    "openrouter": "榜单", "modelsdev": "榜单", "mnfst": "目录",
    "freetoken": "目录", "litellm": "价格监控", "watchlist": "官网监控",
    "aa_providers": "榜单", "reddit": "社区",
}

SOURCE_BLURBS = {
    "aicredits": "人工筛选的免费额度目录（存量档案）；新目录条目入库，新域名自动收编进厂商监控",
    "linuxdo": "中文社区羊毛首发（linux.do 对数据中心 IP 风控，直连/Actions 均 403；需自建网络环境）",
    "hackernews": "英文一手发布监控（Show HN 与 free credits 类帖）",
    "openrouter": "供应商在 OpenRouter 挂出 :free 免费模型时产生条目",
    "modelsdev": "models.dev 名录出现新供应商时产生条目",
    "mnfst": "free-llm-apis 清单 diff（11.9k star）",
    "freetoken": "中文免费额度清单 diff",
    "litellm": "出现新免费模型或输入价降 ≥50% 时产生条目",
    "watchlist": "已收录厂商官网的每日动静（促销内容出现/消失）",
    "aa_providers": "新 AI 实验室进入 Artificial Analysis 榜单时产生条目",
    "reddit": "预留 v2：公开 JSON 已封锁，需 OAuth 接入",
}


def norm(s: str) -> str:
    """厂商名归一化：小写、去符号。"""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _state_names(raw: str, mode: str) -> list[str]:
    """从 state 的目录基线 JSON 提取厂商名。mode: keys/labels/sub_name/providers"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    if mode == "keys":
        return list(data.keys())
    if mode == "labels":
        return [str(info.get("label") or k) for k, info in data.items() if isinstance(info, dict)]
    if mode == "sub_name":
        return [str(info.get("name") or k) for k, info in data.items() if isinstance(info, dict)]
    if mode == "providers":
        return list({str(info.get("p")) for info in data.values()
                     if isinstance(info, dict) and info.get("p")})
    return []


def domain_norm(url: str) -> str:
    """URL → 注册域的 norm 形式（civo.com → civocom）。"""
    h = re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower())
    h = h.split("/")[0].split(":")[0].split("@")[-1]
    return norm(h)


def build_registries(repo, deals, monitors) -> dict[str, list[str]]:
    """source_id → 覆盖的厂商名键列表（norm）。watchlist = 监控中的厂商本身。

    aicredits 同时登记品牌名与来源域名：自动收编的厂商名是域名形式
    （civo.com），而目录条目的厂商是品牌名（Civo），两边都要能对上。
    """
    registries: dict[str, list[str]] = {}
    aicredits = set()
    for d in deals:
        if d.source != "aicredits":
            continue
        if d.provider:
            aicredits.add(norm(d.provider))
        if d.url:
            aicredits.add(domain_norm(d.url))
    registries["aicredits"] = sorted(aicredits)
    # OpenRouter 全量覆盖 = 模型 ID 首段实验室 slug + 上游托管商（/providers）
    registries["openrouter"] = sorted(
        {norm(x) for x in _state_names(repo.get_state("openrouter:vendors"), "keys")}
        | {norm(x) for x in _state_names(repo.get_state("openrouter:providers"), "keys")}
    )
    registries["modelsdev"] = sorted({norm(x) for x in _state_names(repo.get_state("modelsdev:providers"), "labels")})
    registries["mnfst"] = sorted({norm(x) for x in _state_names(repo.get_state("mnfst:providers"), "keys")})
    registries["freetoken"] = sorted({norm(x) for x in _state_names(repo.get_state("freetoken:providers"), "keys")})
    registries["litellm"] = sorted({norm(x) for x in _state_names(repo.get_state("litellm:prices"), "providers")})
    registries["aa_providers"] = sorted({norm(x) for x in _state_names(repo.get_state("aa:creators"), "sub_name")})
    registries["watchlist"] = sorted({norm(m["provider"]) for m in monitors})
    return registries


def _keys_match(vendor_keys: set[str], registry_keys: list[str]) -> bool:
    """厂商键与清单键的匹配：精确相等，或双向包含且短边 ≥4 字符。

    包含匹配解决同厂商的命名变体（mistralai↔Mistral、moonshotai↔Moonshot、
    aion-labs↔Aion Labs）；≥4 下限防止 "zai"/"ai" 这类短词误伤。
    """
    for rk in registry_keys:
        if rk in vendor_keys:
            return True
        if len(rk) < 4:
            continue
        for k in vendor_keys:
            if len(k) >= 4 and (k in rk or rk in k):
                return True
    return False


def covered_by(name: str, registries: dict[str, list[str]],
               only: list[str] | None = None, extra_keys: set[str] | None = None) -> list[str]:
    """厂商名 → 覆盖它的源 id 列表（按 SOURCE_IDS 顺序）。

    extra_keys：厂商的别名键（如官网域名的 norm 形式），一并参与匹配。
    """
    keys = {norm(name)} | (extra_keys or set())
    keys.discard("")
    ids = only if only is not None else REGISTRY_SOURCES
    return [sid for sid in ids if _keys_match(keys, registries.get(sid, []))]


def registry_sizes(registries: dict[str, list[str]]) -> dict[str, int]:
    return {sid: len(registries.get(sid, [])) for sid in REGISTRY_SOURCES}


def vendor_links(registries: dict[str, list[str]], monitors: list[dict]) -> dict[str, dict[str, tuple[str, str]]]:
    """登记名单键反向匹配监控厂商：source_id → {登记键: (显示名, 站点 URL)}。

    解析顺序：监控匹配（精确 → 双向包含 ≥4 字符）→ 静态品牌表 → 键本身。
    品牌兜底命中后，若其官网域名恰好已被监控，显示与链接以监控为准
    （同一厂商全站只认一套名字，品牌表只补监控没有的）。
    """
    sorted_mons = sorted(monitors, key=lambda w: (w["provider"], w["label"]))
    mon_keys = [({norm(m["provider"]), domain_norm(m["url"])}, m["provider"], m["url"])
                for m in sorted_mons if m.get("url")]
    mon_by_dom = {domain_norm(m["url"]): (m["provider"], m["url"]) for m in sorted_mons if m.get("url")}
    out: dict[str, dict[str, tuple[str, str]]] = {}
    for sid, keys in registries.items():
        links: dict[str, tuple[str, str]] = {}
        for k in keys:
            hit = next(((p, u) for vk, p, u in mon_keys if k in vk), None)
            if hit is None and len(k) >= 4:
                hit = next(
                    ((p, u) for vk, p, u in mon_keys
                     if any(len(x) >= 4 and (x in k or k in x) for x in vk)),
                    None,
                )
            if hit is None:
                brand = BRANDS.get(k)
                if brand:
                    hit = mon_by_dom.get(domain_norm(brand[1]), brand)
            if hit:
                links[k] = hit
        out[sid] = links
    return out
