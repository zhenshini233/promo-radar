# 宇宙标注规则 v0（Day 13）

> 目标：为 425 条宇宙条目补 `category` / `regions` / `relevance` 三个维度的**初值**，
> 作为 Provider 实体落库的字段依据。本版不写数据库、不改 `providers.toml`。
> 实现：`scripts/annotate_universe.py`；结果：`data/universe/universe_annotated_v0.json`。

---

## 1. 边界

- **只做初值**：规则命中即给值，允许后续人工覆盖。
- **可解释**：每条带 `confidence`（high / medium / low），低置信集中列出。
- **可复算**：输入是宇宙构建结果 + `aliases.json`，不依赖临时人工数据。
- **不改变宇宙规模**：标注不新增、不删除条目。

人工修正写入 `docs/discovery/annotations_overrides.json`：

```json
{
  "some-slug": {
    "category": "inference",
    "regions": ["cn", "global"],
    "relevance": 0.8,
    "confidence": "high",
    "vendor_like": true
  }
}
```

覆盖优先于所有规则。

---

## 2. category（单选）

| 值 | 含义 | 典型 |
|---|---|---|
| `model_lab` | 自研模型的组织/实验室 | OpenAI、Anthropic、DeepSeek、Mistral、Stability |
| `inference` | 推理托管、Serverless、模型 API | Together、Fireworks、Groq、Replicate、SiliconFlow |
| `cloud` | 综合云/大厂 AI 平台 | AWS、Azure、Google、阿里云、腾讯云、火山引擎 |
| `gpu` | GPU/算力租用与算力市场 | RunPod、Vast、Lambda、CoreWeave、PPIO |
| `aggregator` | 多模型聚合/路由/网关 | OpenRouter、LiteLLM、Portkey、AiHubMix |
| `ai_infra` | 向量库、可观测、评测、RAG、芯片 | Pinecone、Qdrant、LangChain、W&B、NVIDIA |
| `app` | 面向终端用户的 AI 应用/创作工具 | Cursor、Perplexity、ElevenLabs、Runway |
| `relay` | 中转/镜像/代理站（低置信，默认不监控） | 中文 API 中转站 |
| `unknown` | 信息不足，待人工 | 长尾小站、无官网条目 |

### 判定顺序

1. **品牌词命中**（名称、slug、注册域首段）→ `high`
2. **关键词兜底**（gpu / aggregator / relay / ai_infra / inference / app / cloud / model_lab）→ `medium`
3. 都没有 → `unknown` + `low`

品牌词按长度降序做前缀匹配；长度 ≤3 的词只做完全相等，避免 `kt`、`ai` 之类误配。

---

## 3. regions（多选，有序）

| 值 | 含义 |
|---|---|
| `global` | 面向全球开放（多数 API 平台） |
| `cn` | 中国大陆 |
| `us` | 美国 |
| `eu` | 欧洲 |
| `apac` | 亚太（日韩印新澳） |
| `unknown` | 无法判断 |

**第一个值是主地区**，后续是补充。例如 `["cn", "global"]` 表示中国团队、全球可用。

判定顺序：

1. 品牌表里的固定值；
2. 名称含中文 → `cn`；
3. 注册域 TLD：`.cn` → `cn`；`.de/.fr/.eu/.uk/...` → `eu`；`.jp/.kr/.in/.sg/.au` → `apac`；
4. 有域名但无信号 → `global`（low）；
5. 无域名 → `unknown`。

> `global` 是“默认开放”的近似，不代表已核实全球可用。

---

## 4. relevance（0–1）

含义：**进入监控的优先级**，不是厂商规模、不是市场份额。

```
0.50 基础
+0.15 类别属于 model_lab / inference / gpu / aggregator / cloud
+0.10 有官网（可监控）
+0.10 被 ≥2 个独立来源收录
+0.10 已监控
-0.20 非厂商（资助/活动/机构）
clamp [0.05, 0.95]
```

解读：

- `≥0.80`：核心厂商，应监控；
- `0.60–0.79`：值得监控，按 tier 排期；
- `0.40–0.59`：边缘，先观察；
- `<0.40`：非厂商或信息不足，不监控。

---

## 4.1 品牌归并与重复条目

宇宙的构建键是“名称/域名”，同一厂商常出现多条：

- 名称写法不同：`Mistral` 与 `mistralai`、`Moonshot` 与 `Moonshot AI (China)`；
- 促销项目：`RunPod Startup Program`、`Vultr Free Trial Credits`；
- 平台子产品：`Amazon Bedrock`、`Azure Cognitive Services`。

标注阶段为每条生成 `brand_key`（命中的品牌词），同组内选一个代表，其余标 `duplicate_of = 代表 slug`。

代表优先级：

1. 已监控；
2. 真厂商（`vendor_like`）；
3. 名称不含促销后缀；
4. 名称归一后恰好等于品牌词；
5. 名称更短；
6. 来源更多。

当前结果：**315 个品牌组、51 条重复、去重后 370 个厂商**（与监控清单 384 家接近）。

落库要求：

- `providers.slug` 用代表条目的 `brand_key` 或代表 slug；
- `duplicate_of` 非空的条目只作为别名/页面来源，不建独立 Provider；
- 促销项目（`Startup Program`、`Credits`、`for Startups`）是 Offer，不是 Provider。

---

## 5. confidence

| 值 | 含义 |
|---|---|
| `high` | 品牌词精确命中 |
| `medium` | 关键词或 TLD 推断 |
| `low` | 仅有默认值（无域名、无信号） |

低置信条目必须人工确认后才能用于自动决策（如自动加入监控）。

---

## 6. 非厂商判定（vendor_like）

名称或 slug 含以下词 → `vendor_like = false`，`relevance` 扣 0.20：

`internship`、`mission`、`pilot`、`accelerator`、`grants`、`student pack`、`atlas`、
`antler`、`disrupt`、`blog.google`、`sovereign ai fund`、`enterprise compute initiative`。

这类条目保留在宇宙中（有收录价值），但落库时应标 `ignored` 或 `program`，不进入监控。

---

## 7. 已知局限

1. **品牌前缀误配**：如 `meta` 会命中 `metax`，已用更长品牌词优先覆盖；仍可能有长尾误配。
2. **地区默认偏 US/global**：品牌表对海外厂商默认 `us, global`，未逐一核实总部。
3. **长尾 unknown**：32 条（7.5%）无足够信息，需人工或用官网补。
4. **类别单一化**：一个厂商只给一个主类；同时做模型和推理的（如 Together）按主要收入归 `inference`。
5. **relevance 不是质量分**：高 relevance 不代表厂商可靠，只代表“值得监控”。

---

## 8. 验收标准（本版已达成）

| 指标 | 目标 | 实测 |
|---|---|---|
| 分类未知率 | <10% | **7.5%**（32/425） |
| 地区未知 | <5% | **2.6%**（11/425） |
| 低置信 | <15% | **5.4%**（23/425） |
| 非厂商识别 | 有清单 | **12 条** |
| 核心厂商抽检 | 无错分 | AI21/Anthropic/DeepSeek/xAI/Stability 等均正确 |

---

*本规则是初版，允许在 Provider 落库阶段迭代；任何口径变更先改本文，再改脚本。*