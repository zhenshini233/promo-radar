"""Day 13：为厂商宇宙补齐 category / regions / relevance 初值。

只读宇宙（复用 universe_report.build_universe 的口径），不写数据库、不改 providers.toml。
规则见 docs/discovery/ANNOTATION_RULES_v0.md；人工修正见 docs/discovery/annotations_overrides.json。

判定顺序：
1. 品牌词（名称 / 注册域首段 / slug）命中 BRANDS → high
2. 关键词兜底 → medium
3. 域名 TLD / 中文名推断地区
4. 仍未知 → unknown + low

输出：
- data/universe/universe_annotated_v0.json
- docs/discovery/ANNOTATION_v0.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from radar.infra.config import load_config  # noqa: E402
from universe_report import build_universe  # noqa: E402

OUT_JSON = ROOT / "data/universe/universe_annotated_v0.json"
OUT_MD = ROOT / "docs/discovery/ANNOTATION_v0.md"
ALIASES = ROOT / "docs/discovery/aliases.json"
OVERRIDES = ROOT / "docs/discovery/annotations_overrides.json"

CATEGORIES = (
    "model_lab", "inference", "cloud", "gpu", "aggregator", "ai_infra", "app", "relay", "unknown"
)
REGIONS = ("global", "cn", "us", "eu", "apac", "unknown")

# 品牌 → (category, regions)。键为小写去符号；按长度降序做前缀匹配。
# 注意：只放“名称以该词开头即成立”的品牌；短词（<=3）仅做完全相等匹配。
BRANDS: dict[str, tuple[str, tuple[str, ...]]] = {
    # 综合云 / 大厂 AI 平台
    "amazon": ("cloud", ("us", "global")),
    "aws": ("cloud", ("us", "global")),
    "bedrock": ("cloud", ("us", "global")),
    "azure": ("cloud", ("us", "global")),
    "microsoft": ("cloud", ("us", "global")),
    "google": ("cloud", ("us", "global")),
    "googlegemini": ("model_lab", ("us", "global")),
    "vertex": ("cloud", ("us", "global")),
    "alibaba": ("cloud", ("cn", "global")),
    "alibabacloud": ("cloud", ("cn", "global")),
    "aliyun": ("cloud", ("cn", "global")),
    "qwen": ("model_lab", ("cn", "global")),
    "tencent": ("cloud", ("cn", "global")),
    "tencentcloud": ("cloud", ("cn", "global")),
    "baidu": ("cloud", ("cn",)),
    "huawei": ("cloud", ("cn",)),
    "volcengine": ("cloud", ("cn", "global")),
    "volcano": ("cloud", ("cn", "global")),
    "bytedance": ("cloud", ("cn", "global")),
    "bytedanceseed": ("model_lab", ("cn", "global")),
    "seed": ("model_lab", ("cn", "global")),
    "ibm": ("cloud", ("us", "global")),
    "watsonx": ("cloud", ("us", "global")),
    "oracle": ("cloud", ("us", "global")),
    "oci": ("cloud", ("us", "global")),
    "sap": ("cloud", ("eu", "global")),
    "snowflake": ("cloud", ("us", "global")),
    "databricks": ("cloud", ("us", "global")),
    "cloudflare": ("ai_infra", ("us", "global")),
    "linode": ("cloud", ("us", "global")),
    "akamai": ("cloud", ("us", "global")),
    "ovhcloud": ("cloud", ("eu", "global")),
    "ovh": ("cloud", ("eu", "global")),
    "scaleway": ("cloud", ("eu", "global")),
    "hetzner": ("cloud", ("eu", "global")),
    "civo": ("cloud", ("eu", "global")),
    "exoscale": ("cloud", ("eu", "global")),
    "infomaniak": ("cloud", ("eu", "global")),
    "ionos": ("cloud", ("eu", "global")),
    "northflank": ("cloud", ("us", "global")),
    "railway": ("cloud", ("us", "global")),
    "render": ("cloud", ("us", "global")),
    "vercel": ("cloud", ("us", "global")),
    "zeabur": ("cloud", ("apac", "global")),
    "koyeb": ("cloud", ("eu", "global")),
    "codesphere": ("cloud", ("eu", "global")),
    "hostkey": ("cloud", ("eu", "global")),
    "evroc": ("cloud", ("eu",)),
    "cloudferro": ("cloud", ("eu",)),
    "qiniu": ("cloud", ("cn",)),
    "redhat": ("ai_infra", ("us", "global")),
    "kt": ("cloud", ("apac",)),
    "scnet": ("gpu", ("cn",)),
    "ppio": ("gpu", ("cn", "global")),

    # 模型实验室 / 模型作者
    "openai": ("model_lab", ("us", "global")),
    "anthropic": ("model_lab", ("us", "global")),
    "claude": ("model_lab", ("us", "global")),
    "meta": ("model_lab", ("us", "global")),
    "mistral": ("model_lab", ("eu", "global")),
    "mistralai": ("model_lab", ("eu", "global")),
    "cohere": ("model_lab", ("us", "global")),
    "deepseek": ("model_lab", ("cn", "global")),
    "moonshot": ("model_lab", ("cn", "global")),
    "kimi": ("model_lab", ("cn", "global")),
    "zhipu": ("model_lab", ("cn", "global")),
    "zai": ("model_lab", ("cn", "global")),
    "zaicoding": ("model_lab", ("cn", "global")),
    "bigmodel": ("model_lab", ("cn", "global")),
    "minimax": ("model_lab", ("cn", "global")),
    "minimaxi": ("model_lab", ("cn", "global")),
    "stepfun": ("model_lab", ("cn", "global")),
    "baichuan": ("model_lab", ("cn",)),
    "ai21": ("model_lab", ("us", "global")),
    "alephalpha": ("model_lab", ("eu",)),
    "sakana": ("model_lab", ("apac",)),
    "inflection": ("model_lab", ("us", "global")),
    "arcee": ("model_lab", ("us", "global")),
    "poolside": ("model_lab", ("us", "global")),
    "thinkingmachines": ("model_lab", ("us", "global")),
    "reka": ("model_lab", ("us", "global")),
    "upstage": ("model_lab", ("apac",)),
    "sarvam": ("model_lab", ("apac",)),
    "allenai": ("model_lab", ("us",)),
    "ai2": ("model_lab", ("us",)),
    "cognition": ("model_lab", ("us", "global")),
    "decart": ("model_lab", ("us", "global")),
    "lightricks": ("model_lab", ("eu", "global")),
    "recraft": ("model_lab", ("us", "global")),
    "blackforest": ("model_lab", ("eu", "global")),
    "nous": ("model_lab", ("us",)),
    "nousresearch": ("model_lab", ("us",)),
    "liquid": ("model_lab", ("us", "global")),
    "liquidai": ("model_lab", ("us", "global")),
    "moondream": ("model_lab", ("us",)),
    "writer": ("model_lab", ("us", "global")),
    "xiaomi": ("model_lab", ("cn", "global")),
    "xiaomimimo": ("model_lab", ("cn", "global")),
    "longcat": ("model_lab", ("cn", "global")),
    "meituan": ("model_lab", ("cn", "global")),
    "sensenova": ("model_lab", ("cn", "global")),
    "modelscope": ("ai_infra", ("cn", "global")),
    "inception": ("model_lab", ("us", "global")),
    "inceptionlabs": ("model_lab", ("us", "global")),
    "prismml": ("model_lab", ("us",)),
    "prism": ("model_lab", ("us",)),
    "refuseless": ("model_lab", ("us",)),
    "sail": ("model_lab", ("us",)),
    "publicai": ("model_lab", ("us",)),
    "cosine": ("model_lab", ("us",)),
    "crucible": ("model_lab", ("us",)),
    "dekallm": ("model_lab", ("us",)),
    "mara": ("model_lab", ("us",)),
    "modelrun": ("inference", ("us",)),
    "nextbit": ("inference", ("us",)),
    "quiver": ("inference", ("us",)),
    "recursive": ("model_lab", ("us",)),
    "switchpoint": ("inference", ("us",)),
    "avian": ("model_lab", ("us",)),
    "hyperspace": ("model_lab", ("us",)),

    # 推理 / 托管 / API
    "together": ("inference", ("us", "global")),
    "togetherai": ("inference", ("us", "global")),
    "fireworks": ("inference", ("us", "global")),
    "fireworksai": ("inference", ("us", "global")),
    "groq": ("inference", ("us", "global")),
    "replicate": ("inference", ("us", "global")),
    "deepinfra": ("inference", ("us", "global")),
    "novita": ("inference", ("us", "global")),
    "hyperbolic": ("inference", ("us", "global")),
    "cerebras": ("inference", ("us", "global")),
    "sambanova": ("inference", ("us", "global")),
    "fal": ("inference", ("us", "global")),
    "falai": ("inference", ("us", "global")),
    "baseten": ("inference", ("us", "global")),
    "modal": ("inference", ("us", "global")),
    "anyscale": ("inference", ("us", "global")),
    "lepton": ("inference", ("us", "global")),
    "kluster": ("inference", ("us", "global")),
    "friendli": ("inference", ("apac", "global")),
    "chutes": ("inference", ("us", "global")),
    "morph": ("inference", ("us", "global")),
    "reflection": ("inference", ("us", "global")),
    "venice": ("inference", ("us", "global")),
    "wafer": ("inference", ("us", "global")),
    "scx": ("inference", ("us", "global")),
    "siliconflow": ("inference", ("cn", "global")),
    "streamlake": ("inference", ("cn", "global")),
    "cortecs": ("inference", ("eu", "global")),
    "gradient": ("inference", ("us", "global")),
    "ollama": ("inference", ("us", "global")),
    "commandcode": ("inference", ("us", "global")),
    "inferx": ("inference", ("us", "global")),
    "a4f": ("inference", ("us", "global")),
    "parasail": ("inference", ("us", "global")),
    "targon": ("inference", ("us", "global")),
    "runinfra": ("inference", ("us", "global")),
    "meganova": ("inference", ("us", "global")),
    "melious": ("inference", ("us", "global")),
    "mancer": ("inference", ("us", "global")),
    "nanogpt": ("inference", ("us", "global")),
    "submodel": ("inference", ("us", "global")),
    "synthetic": ("inference", ("us", "global")),
    "tinfoil": ("inference", ("us", "global")),
    "openinfer": ("inference", ("us", "global")),
    "llamagate": ("inference", ("us", "global")),
    "xpersona": ("inference", ("us", "global")),
    "zeldoc": ("inference", ("us", "global")),
    "zenifra": ("inference", ("us", "global")),
    "vancine": ("inference", ("us", "global")),
    "vispark": ("inference", ("apac",)),
    "lucidquery": ("inference", ("us", "global")),
    "mixlayer": ("inference", ("us", "global")),
    "ofox": ("inference", ("us", "global")),
    "opper": ("inference", ("us", "global")),
    "particle": ("inference", ("us", "global")),
    "pendra": ("inference", ("us", "global")),
    "pioneer": ("inference", ("us", "global")),
    "privatemode": ("inference", ("eu", "global")),
    "regolo": ("inference", ("eu", "global")),
    "river": ("inference", ("us", "global")),
    "scaledown": ("inference", ("us", "global")),
    "systalyze": ("inference", ("us", "global")),
    "tokengo": ("inference", ("us", "global")),
    "umans": ("inference", ("us", "global")),
    "wally": ("inference", ("us", "global")),
    "wallaby": ("inference", ("us", "global")),
    "neosmith": ("inference", ("us", "global")),
    "impossibl": ("inference", ("us", "global")),
    "featherless": ("inference", ("us", "global")),
    "frogbot": ("inference", ("us", "global")),
    "makora": ("inference", ("us", "global")),
    "modeloracle": ("inference", ("us", "global")),
    "nan": ("inference", ("us", "global")),
    "relace": ("inference", ("us", "global")),
    "openreason": ("inference", ("us", "global")),
    "infermatic": ("inference", ("us", "global")),
    "inferencenet": ("inference", ("us", "global")),
    "moark": ("inference", ("cn", "global")),
    "qihang": ("app", ("cn",)),
    "qhaigc": ("app", ("cn",)),

    # 算力 / GPU 云
    "runpod": ("gpu", ("us", "global")),
    "vast": ("gpu", ("us", "global")),
    "lambda": ("gpu", ("us", "global")),
    "coreweave": ("gpu", ("us", "global")),
    "vultr": ("gpu", ("us", "global")),
    "digitalocean": ("gpu", ("us", "global")),
    "akash": ("gpu", ("us", "global")),
    "crusoe": ("gpu", ("us", "global")),
    "cirrascale": ("gpu", ("us", "global")),
    "ionet": ("gpu", ("us", "global")),
    "primeintellect": ("gpu", ("us", "global")),
    "primeinference": ("gpu", ("us", "global")),
    "beam": ("gpu", ("us", "global")),
    "cerebrium": ("gpu", ("us", "global")),
    "atlascloud": ("gpu", ("us", "global")),
    "ionstream": ("gpu", ("us", "global")),
    "shadeform": ("gpu", ("us", "global")),
    "paperspace": ("gpu", ("us", "global")),
    "phala": ("gpu", ("us", "global")),
    "tensormesh": ("gpu", ("us", "global")),
    "tensorwave": ("gpu", ("us", "global")),
    "tensortorrent": ("gpu", ("us", "global")),
    "tenstorrent": ("ai_infra", ("us", "global")),
    "tensorx": ("gpu", ("us", "global")),
    "verda": ("gpu", ("eu", "global")),
    "standardcompute": ("gpu", ("us", "global")),
    "thundercompute": ("gpu", ("us", "global")),
    "iteracompute": ("gpu", ("us", "global")),
    "koscompute": ("gpu", ("us", "global")),
    "kosmikcompute": ("gpu", ("us", "global")),
    "hpcai": ("gpu", ("us", "global")),
    "thegrid": ("gpu", ("us", "global")),
    "gmicloud": ("gpu", ("us", "global")),
    "nscale": ("gpu", ("eu", "global")),
    "nebius": ("gpu", ("eu", "global")),
    "neuralwatt": ("gpu", ("us", "global")),
    "metax": ("ai_infra", ("cn",)),

    # 聚合 / 路由 / 中转
    "openrouter": ("aggregator", ("us", "global")),
    "litellm": ("aggregator", ("us", "global")),
    "portkey": ("aggregator", ("us", "global")),
    "edenai": ("aggregator", ("eu", "global")),
    "aihubmix": ("aggregator", ("cn", "global")),
    "302ai": ("aggregator", ("cn", "global")),
    "aimlapi": ("aggregator", ("us", "global")),
    "agentrouter": ("aggregator", ("us", "global")),
    "airouter": ("aggregator", ("us", "global")),
    "llmgateway": ("aggregator", ("eu", "global")),
    "crossmodel": ("aggregator", ("us", "global")),
    "bothub": ("aggregator", ("eu", "global")),
    "requesty": ("aggregator", ("eu", "global")),
    "routingrun": ("aggregator", ("us", "global")),
    "zenmux": ("aggregator", ("us", "global")),
    "anyapi": ("aggregator", ("us", "global")),
    "jiekou": ("relay", ("cn", "global")),
    "aixy": ("relay", ("cn", "global")),
    "llm7": ("relay", ("us", "global")),
    "llmtr": ("relay", ("eu", "global")),
    "llmtech": ("relay", ("eu", "global")),
    "freemodel": ("relay", ("us", "global")),

    # AI 基础设施
    "pinecone": ("ai_infra", ("us", "global")),
    "weaviate": ("ai_infra", ("eu", "global")),
    "qdrant": ("ai_infra", ("eu", "global")),
    "chroma": ("ai_infra", ("us", "global")),
    "milvus": ("ai_infra", ("cn", "global")),
    "langchain": ("ai_infra", ("us", "global")),
    "llamaindex": ("ai_infra", ("us", "global")),
    "weightsbiases": ("ai_infra", ("us", "global")),
    "wandb": ("ai_infra", ("us", "global")),
    "langsmith": ("ai_infra", ("us", "global")),
    "helicone": ("ai_infra", ("us", "global")),
    "datadog": ("ai_infra", ("us", "global")),
    "posthog": ("ai_infra", ("us", "global")),
    "sentry": ("ai_infra", ("us", "global")),
    "grafana": ("ai_infra", ("eu", "global")),
    "clickhouse": ("ai_infra", ("us", "global")),
    "neon": ("ai_infra", ("us", "global")),
    "supabase": ("ai_infra", ("us", "global")),
    "mongodb": ("ai_infra", ("us", "global")),
    "convex": ("ai_infra", ("us", "global")),
    "voyage": ("ai_infra", ("us", "global")),
    "voyageai": ("ai_infra", ("us", "global")),
    "jina": ("ai_infra", ("us", "global")),
    "mixedbread": ("ai_infra", ("eu", "global")),
    "braintrust": ("ai_infra", ("us", "global")),
    "arize": ("ai_infra", ("us", "global")),
    "fiddler": ("ai_infra", ("us", "global")),
    "predibase": ("ai_infra", ("us", "global")),
    "datarobot": ("ai_infra", ("us", "global")),
    "scale": ("ai_infra", ("us", "global")),
    "labelbox": ("ai_infra", ("us", "global")),
    "modular": ("ai_infra", ("us", "global")),
    "nvidia": ("ai_infra", ("us", "global")),
    "amd": ("ai_infra", ("us", "global")),
    "cncf": ("ai_infra", ("us", "global")),
    "llmbenchmark": ("ai_infra", ("us", "global")),
    "respan": ("ai_infra", ("us", "global")),

    # 应用 / 创作工具
    "perplexity": ("app", ("us", "global")),
    "cursor": ("app", ("us", "global")),
    "windsurf": ("app", ("us", "global")),
    "v0": ("app", ("us", "global")),
    "bolt": ("app", ("eu", "global")),
    "lovable": ("app", ("eu", "global")),
    "coze": ("app", ("cn", "global")),
    "poe": ("app", ("us", "global")),
    "meshy": ("app", ("us", "global")),
    "tripo": ("app", ("cn", "global")),
    "heygen": ("app", ("us", "global")),
    "jasper": ("app", ("us", "global")),
    "notion": ("app", ("us", "global")),
    "linear": ("app", ("us", "global")),
    "gitlab": ("app", ("us", "global")),
    "jetbrains": ("app", ("eu", "global")),
    "hubspot": ("app", ("us", "global")),
    "stripe": ("app", ("us", "global")),
    "grok": ("app", ("us", "global")),
    "krea": ("app", ("eu", "global")),
    "leonardo": ("app", ("apac", "global")),
    "runway": ("app", ("us", "global")),
    "midjourney": ("app", ("us", "global")),
    "elevenlabs": ("app", ("us", "global")),
    "cartesia": ("app", ("us", "global")),
    "deepgram": ("app", ("us", "global")),
    "assemblyai": ("app", ("us", "global")),
    "gladia": ("app", ("eu", "global")),
    "fishaudio": ("app", ("cn", "global")),

    # 补充：剩余条目中可识别的品牌
    "xai": ("model_lab", ("us", "global")),
    "stability": ("model_lab", ("eu", "global")),
    "gigachat": ("model_lab", ("eu",)),
    "deepcogito": ("model_lab", ("us",)),
    "subconscious": ("model_lab", ("us",)),
    "aion": ("model_lab", ("us",)),
    "nexagi": ("model_lab", ("us",)),
    "xingchen": ("model_lab", ("cn",)),
    "empirio": ("model_lab", ("us",)),
    "bailing": ("model_lab", ("cn",)),
    "clarifai": ("ai_infra", ("us", "global")),
    "lilac": ("ai_infra", ("us",)),
    "qvac": ("ai_infra", ("us",)),
    "multiverse": ("ai_infra", ("eu",)),
    "echo": ("ai_infra", ("us",)),
    "tracerml": ("ai_infra", ("us",)),
    "kilo": ("app", ("us", "global")),
    "cline": ("app", ("us", "global")),
    "atomic": ("app", ("us",)),
    "creator": ("app", ("us",)),
    "abacus": ("app", ("us", "global")),
    "speechmatics": ("app", ("eu", "global")),
    "opencode": ("app", ("us", "global")),
    "lightning": ("cloud", ("us", "global")),
    "drun": ("cloud", ("cn",)),
    "inferact": ("inference", ("us",)),
    "ambient": ("inference", ("us",)),
    "coralbricks": ("inference", ("us",)),
    "agnes": ("inference", ("us",)),
    "ainetcafe": ("inference", ("us",)),
    "auriko": ("inference", ("us",)),
    "berget": ("inference", ("eu",)),
    "claudinio": ("inference", ("us",)),
    "greenpt": ("inference", ("us",)),
    "kenari": ("inference", ("apac",)),
    "libertai": ("inference", ("eu",)),
    "modelis": ("inference", ("us",)),
    "near": ("inference", ("us",)),
    "pollinations": ("inference", ("us",)),
    "primalabs": ("inference", ("us",)),
    "vivgrid": ("inference", ("us",)),
    "flow7": ("inference", ("us",)),
    "inceptron": ("gpu", ("us",)),
    "gonka": ("gpu", ("us",)),
    "inco": ("gpu", ("eu",)),
    "boostmyagents": ("app", ("us",)),
    "mthreads": ("ai_infra", ("cn",)),
    "kuae": ("ai_infra", ("cn",)),

    # 非厂商：资助 / 活动 / 教育 / 研究机构（vendor_like=False）
    "nairr": ("unknown", ("us",)),
    "antler": ("unknown", ("global",)),
    "pawsey": ("unknown", ("apac",)),
    "turing": ("unknown", ("eu",)),
    "sovereignai": ("unknown", ("eu",)),
    "indiaai": ("unknown", ("apac",)),
    "disg": ("unknown", ("apac",)),
    "aistudentpack": ("unknown", ("global",)),
}

# 关键词兜底：按优先级从具体到宽泛。
KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gpu", ("gpu", "h100", "a100", "算力", "显卡", "compute cloud", "gpu cloud")),
    ("aggregator", ("aggregator", "router", "gateway", "聚合", "路由", "one api", "new api")),
    ("relay", ("中转", "relay", "mirror", "镜像站", "api proxy", "代理站")),
    ("ai_infra", ("vector", "observability", "guardrail", "vectordb", "evaluation", "evals",
                  "prompt management", "向量", "可观测", "评测")),
    ("inference", ("inference", "serverless", "endpoint", "hosted", "推理", "模型服务",
                   "model api", "llm api")),
    ("app", ("studio", "generator", "video", "image", "photo", "music", "voice", "avatar",
             "writing", "视频", "图片", "绘画", "写作", "数字人")),
    ("cloud", ("cloud", "云", "bedrock", "vertex")),
    ("model_lab", (" labs", "research", "实验室", "人工智能")),
)

NON_VENDOR = (
    "internship", "sovereign ai fund", "enterprise compute initiative", "mission",
    "pilot", "accelerator", "grants", "student pack", "stripe atlas",
    "antler", "disrupt", "blog.google",
)

BRAND_ORDER = sorted(BRANDS, key=len, reverse=True)

# 同一厂商的不同品牌写法归到同一 brand_key（只影响归并，不影响分类）。
BRAND_MERGE = {
    "googlegemini": "google",
    "bytedanceseed": "bytedance",
    "tencentcloud": "tencent",
    "alibabacloud": "alibaba",
    "minimaxi": "minimax",
    "mistralai": "mistral",
    "nousresearch": "nous",
    "liquidai": "liquid",
    "voyageai": "voyage",
    "togetherai": "together",
    "fireworksai": "fireworks",
    "falai": "fal",
    "weightsbiases": "wandb",
    "xiaomimimo": "xiaomi",
    "watsonx": "ibm",
    "zaicoding": "zai",
    "kimi": "moonshot",
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def tokens(slug: str, name: str, domains: list[str]) -> set[str]:
    nk = norm(re.sub(r"\(.*?\)", " ", name))
    stripped = re.sub(
        r"(forstartups|freetrialcredits|startupprogram|freeplan|freetier|credits|"
        r"accelerator|grants|plan|china).*$",
        "",
        nk,
    )
    toks = {nk, stripped, norm(slug)}
    for d in domains:
        toks.add(norm(d.split(".")[0]))
    return {t for t in toks if len(t) >= 2}


def infer_region(name: str, domains: list[str]) -> tuple[tuple[str, ...], str]:
    if re.search(r"[\u4e00-\u9fff]", name):
        return ("cn",), "medium"
    if any(d.endswith(".cn") for d in domains):
        return ("cn",), "medium"
    if any(d.endswith((".de", ".fr", ".eu", ".uk", ".nl", ".se", ".fi")) for d in domains):
        return ("eu",), "medium"
    if any(d.endswith((".jp", ".kr", ".in", ".sg", ".au")) for d in domains):
        return ("apac",), "medium"
    if domains:
        return ("global",), "low"
    return ("unknown",), "low"


def classify(slug: str, name: str, domains: list[str]) -> tuple[str, tuple[str, ...], str]:
    """返回 (category, regions, confidence)。"""
    toks = tokens(slug, name, domains)
    for brand in BRAND_ORDER:
        for t in toks:
            if t == brand or (len(brand) >= 4 and t.startswith(brand)):
                return BRANDS[brand][0], BRANDS[brand][1], "high"

    text = f"{name} {slug} {' '.join(domains)}".lower()
    regions, confidence = infer_region(name, domains)
    for category, words in KEYWORDS:
        if any(w in text for w in words):
            return category, regions, "medium" if confidence == "low" else confidence
    return "unknown", regions, confidence


def is_vendor_like(name: str, slug: str) -> bool:
    text = f"{name} {slug}".lower()
    return not any(k in text for k in NON_VENDOR)


def brand_key(slug: str, name: str, domains: list[str]) -> str | None:
    """命中的品牌词；用于把同一厂商的多个条目归到一组。"""
    toks = tokens(slug, name, domains)
    for brand in BRAND_ORDER:
        for t in toks:
            if t == brand or (len(brand) >= 4 and t.startswith(brand)):
                return BRAND_MERGE.get(brand, brand)
    return None


PROMO = re.compile(
    r"(for startups?|startup program|free trial|free plan|free tier|credits?|accelerator|grants?)",
    re.I,
)


def representative_rank(rec: dict) -> tuple:
    """同组内选代表：已监控 > 真厂商 > 名称无促销后缀 > 名称即品牌 > 名称短 > 来源多。"""
    return (
        rec["monitored"],
        rec["vendor_like"],
        not bool(PROMO.search(rec["name"])),
        norm(rec["name"]) == (rec["brand_key"] or ""),
        -len(rec["name"]),
        len(rec["sources"]),
    )


def relevance(category: str, domains: list[str], n_sources: int, monitored: bool,
               vendor_like: bool) -> float:
    score = 0.50
    if category in {"model_lab", "inference", "gpu", "aggregator", "cloud"}:
        score += 0.15
    if domains:
        score += 0.10
    if n_sources >= 2:
        score += 0.10
    if monitored:
        score += 0.10
    if not vendor_like:
        score -= 0.20
    return round(max(0.05, min(0.95, score)), 2)


def main() -> None:
    cfg = load_config()
    built = build_universe(cfg)
    alias_data = json.loads(ALIASES.read_text(encoding="utf-8"))
    display = alias_data.get("names", {})

    overrides: dict[str, dict] = {}
    if OVERRIDES.exists():
        overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))

    records = []
    for slug, e in built.universe.items():
        name = e.get("name") or display.get(slug) or slug
        domains = sorted(e.get("domains") or [])
        category, regions, confidence = classify(slug, name, domains)
        vendor_like = is_vendor_like(name, slug)
        over = overrides.get(slug) or {}
        category = over.get("category", category)
        regions = tuple(over.get("regions", regions))
        confidence = over.get("confidence", confidence)
        vendor_like = over.get("vendor_like", vendor_like)
        records.append({
            "slug": slug,
            "name": name,
            "domains": domains,
            "sources": sorted(e.get("sources") or []),
            "monitored": bool(e.get("monitored")),
            "vendor_like": vendor_like,
            "category": category,
            "regions": list(regions),
            "relevance": over.get("relevance", relevance(
                category, domains, len(e.get("sources") or []),
                bool(e.get("monitored")), vendor_like,
            )),
            "confidence": confidence,
            "brand_key": brand_key(slug, name, domains),
            "duplicate_of": None,
        })

    groups: dict[str, list[dict]] = {}
    for r in records:
        if r["brand_key"]:
            groups.setdefault(r["brand_key"], []).append(r)
    for items in groups.values():
        rep = max(items, key=representative_rank)
        for r in items:
            if r is not rep:
                r["duplicate_of"] = rep["slug"]
    duplicate_extra = sum(len(v) - 1 for v in groups.values())

    records.sort(key=lambda r: (-r["relevance"], r["name"].lower()))

    cat = Counter(r["category"] for r in records)
    reg = Counter((r["regions"][0] if r["regions"] else "unknown") for r in records)
    conf = Counter(r["confidence"] for r in records)
    buckets = Counter(
        "0.80+" if r["relevance"] >= 0.8 else
        "0.70-0.79" if r["relevance"] >= 0.7 else
        "0.60-0.69" if r["relevance"] >= 0.6 else
        "0.50-0.59" if r["relevance"] >= 0.5 else
        "0.40-0.49" if r["relevance"] >= 0.4 else
        "<0.40"
        for r in records
    )
    non_vendor = sum(1 for r in records if not r["vendor_like"])

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "version": "v0",
        "summary": {
            "total": len(records),
            "categories": dict(cat.most_common()),
            "regions": dict(reg.most_common()),
            "confidence": dict(conf.most_common()),
            "relevance_buckets": dict(buckets.most_common()),
            "unknown_category": cat.get("unknown", 0),
            "unknown_region": reg.get("unknown", 0),
            "non_vendor_like": non_vendor,
            "brand_groups": len(groups),
            "duplicate_extra": duplicate_extra,
            "dedup_universe": len(records) - duplicate_extra,
        },
        "entries": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    low = [r for r in records if r["confidence"] == "low"]
    unk = [r for r in records if r["category"] == "unknown"]
    lines = [
        "# 宇宙标注结果 v0（Day 13）\n",
        "> 输入：425 条宇宙条目；规则见 `ANNOTATION_RULES_v0.md`。",
        "> 本版只给初值，不改数据库、不改 providers.toml。\n",
        "## 摘要\n",
        f"- 条目：**{len(records)}**",
        f"- 分类未知：**{cat.get('unknown', 0)}**",
        f"- 地区未知：**{reg.get('unknown', 0)}**",
        f"- 低置信：**{len(low)}**",
        f"- 非厂商（资助/活动/机构）：**{non_vendor}**",
        f"- 同品牌重复条目：**{duplicate_extra}**（去重后 **{len(records) - duplicate_extra}** 个厂商）\n",
        "## 分类分布\n",
        "| 分类 | 数量 | 占比 |",
        "|---|---:|---:|",
    ]
    for k, v in cat.most_common():
        lines.append(f"| {k} | {v} | {v / len(records):.1%} |")
    lines += ["", "## 主地区分布\n", "| 地区 | 数量 |", "|---|---:|"]
    for k, v in reg.most_common():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## 相关性分桶\n", "| 区间 | 数量 |", "|---|---:|"]
    for k, v in buckets.most_common():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## 低置信（需人工确认，Top 60）\n",
              "| 厂商 | 域名 | 分类 | 地区 | 来源 |", "|---|---|---|---|---|"]
    for r in low[:60]:
        lines.append(
            f"| {r['name']} | {', '.join(r['domains']) or '—'} | {r['category']} | "
            f"{','.join(r['regions'])} | {','.join(r['sources'])} |"
        )
    lines += ["", "## 未知分类（Top 60）\n",
              "| 厂商 | 域名 | 地区 | 来源 |", "|---|---|---|---|"]
    for r in unk[:60]:
        lines.append(
            f"| {r['name']} | {', '.join(r['domains']) or '—'} | "
            f"{','.join(r['regions'])} | {','.join(r['sources'])} |"
        )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        f"total={len(records)} unknown_cat={cat.get('unknown', 0)} "
        f"unknown_region={reg.get('unknown', 0)} low_conf={len(low)} non_vendor={non_vendor}"
    )
    print("categories", dict(cat.most_common()))
    print("regions", dict(reg.most_common()))


if __name__ == "__main__":
    main()