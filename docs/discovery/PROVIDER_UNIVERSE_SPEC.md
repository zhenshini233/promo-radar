# 厂商宇宙口径（Provider Universe Spec）

> Day 1 产物｜版本 v0.1｜目的：为“覆盖面”提供唯一分母，为后续 Provider 实体落库提供判定标准。  
> 本文只定义“谁算、怎么认、怎么归、怎么算覆盖”，不涉及代码实现。

* * *

## 1\. 目的与范围

“厂商宇宙”是一份**可解释的厂商全集**，用来回答四个问题：

1.  世界上有多少个与本项目相关的 AI 厂商？
2.  我们监控了多少？漏了谁？
3.  哪些来源在贡献独有厂商，哪些只是重复？
4.  某个厂商为什么在宇宙里 / 为什么被排除？

**范围**：提供 AI 模型、推理 API、GPU 算力、模型托管或相关自助式服务的厂商与平台。

**不负责**：活动（Offer）本身的判定；那是下一层的事。本文只定义“厂商身份”。

* * *

## 2\. 三个概念必须先分开

| 概念 | 定义 | 例子 | 是否进宇宙 |
| --- | --- | --- | --- |
| **Provider（厂商/平台）** | 提供 AI 能力或算力的组织/平台，有独立官网与自助入口 | DeepInfra、Groq、Modal、Cloudflare Workers AI | ✅ 是主体 |
| **Product（产品/模型）** | 厂商下的模型、端点、套餐 | Llama 4、DeepSeek-V4、Workers AI | ❌ 挂在 Provider 下，不单独进宇宙 |
| **Offer（活动）** | 厂商提供的促销/额度/免费层 | “注册送 $25”“$1,000 credits” | ❌ 挂在 Provider 下，由下一层处理 |
| **Source（来源）** | 提供厂商/活动线索的目录、榜单、社区、搜索引擎 | aicredits、OpenRouter、HN | ❌ 不是厂商；但可同时具备 Provider 角色 |

**关键规则**：一个实体可以同时是 Source 和 Provider（例如 OpenRouter 既是我们发现厂商的来源，本身也提供 API）。宇宙中保留其 Provider 身份，同时标注 `roles = ["aggregator", "source"]`。

* * *

## 3\. 纳入标准

### 3.1 必须满足（MUST）

1.  **AI 相关**：提供模型推理、模型托管、GPU/算力、向量/语音/图像/视频等 AI API，或 AI 基础设施（推理网关、模型路由、评测/可观测）。
2.  **有公开入口**：有可访问的官网或文档站；不要求现在可注册，但要有公开信息页。
3.  **可独立识别**：有独立品牌或独立注册域；不是某个大厂内部未公开的项目代号。

### 3.2 加分项（NICE，用于分级，不作为纳入门槛）

-   有自助注册/控制台（self-serve）。
-   有免费层、试用额度或公开促销。
-   有公开 API 文档。
-   有定价页。

### 3.3 排除（EXCLUDE）

| 类型 | 例子 | 原因 |
| --- | --- | --- |
| 内容/资讯站 | 博客、教程站、AI 新闻 | 不提供 API/算力 |
| 目录/导航站 | aicredits、awesome lists、AI 工具导航 | 是来源，不是厂商 |
| 社区/论坛 | [linux.do](http://linux.do)、Reddit、Discord | 是来源 |
| 纯本地工具 | LM Studio、Ollama 开源本地版 | 不提供托管 API（其云服务另算） |
| 通用云产品 | AWS EC2、Azure VM、GCP Compute | 只收其 AI 子品牌/产品线 |
| 政府/学术/公共机构 | [gov.sg](http://gov.sg)、[turing.ac.uk](http://turing.ac.uk) | 不提供商业化 AI API |
| 招聘/咨询/外包 | 招聘站、AI 咨询公司 | 不提供自助 API |
| 已停运/无官网 | 死站、纯 landing page 无实体 | 无法监控 |
| 纯模型下载站 | 只提供权重下载、无 API | 除非同时提供推理服务 |

### 3.4 需要人工判断的灰区

| 情况 | 建议 |
| --- | --- |
| 中转站/白标（relay） | 有独立域名 + API + 自助注册 → 纳入，标注 `relay`，置信度低，**不自动进监控** |
| 模型聚合器（OpenRouter、Vercel AI Gateway、[302.AI](http://302.AI)） | 纳入，标注 `aggregator` |
| 云厂商的 AI 子品牌 | 纳入子品牌（Bedrock/Vertex/Azure AI Foundry），不纳入整个云 |
| 被收购的品牌 | 保留现名，旧名进别名；标注 `parent` |
| 只做企业销售、无自助入口 | 纳入宇宙但标 `enterprise_only`，不自动进监控 |
| 开源项目 + 托管服务 | 托管服务算厂商；纯开源仓库不算 |

* * *

## 4\. 主键与别名

### 4.1 主键

**注册域优先**：

```
deepinfra.com → slug: deepinfra
console.anthropic.com → registrable: anthropic.com → slug: anthropic
www.cerebras.ai → registrable: cerebras.ai → slug: cerebras

```

-   一个厂商一个主注册域。
-   多产品线共用主域时，用 slug 区分（`cloudflare-workers-ai` vs `cloudflare`）。
-   无独立域名的（极少）用 `slug = 名称归一化`。

### 4.2 别名

以下都进 `aliases`：

-   品牌名与大小写变体（DeepInfra / deepinfra / Deep Infra）
-   模型 ID 首段（`deepseek` / `deepseek-ai`）
-   旧域名（收购/改名）
-   产品名（仅当产品名被独立引用时）
-   目录里的写法（`Aion Labs` / `aion-labs` / `aionlabs`）

### 4.3 归并规则

| 情况 | 规则 |
| --- | --- |
| 同注册域、不同名称 | 合并，保留最常用名，其余进别名 |
| 同名、不同注册域 | **不自动合并**，标 `pending`，人工确认 |
| 子品牌与母公司 | 保留子品牌，`parent` 指向母公司；母公司不重复收录子品牌 |
| 多段后缀 | 按注册域规则处理（`co.uk`、`com.cn` 等） |
| 重定向域名 | 以最终落地域为主域，旧域进别名 |

* * *

## 5\. 分类与地区

### 5.1 主分类（单选）

| 分类 | 说明 | 例子 |
| --- | --- | --- |
| `model-lab` | 自研模型 + API | OpenAI、Anthropic、Mistral、DeepSeek |
| `inference-api` | 托管第三方模型的推理服务 | DeepInfra、Groq、Together、Fireworks |
| `aggregator` | 多厂商路由/聚合 | OpenRouter、Vercel AI Gateway、[302.AI](http://302.AI) |
| `relay` | 中转/白标/合租 | 各类中转站 |
| `cloud-ai` | 云厂商的 AI 子品牌/产品线 | Bedrock、Vertex AI、Azure AI Foundry、Workers AI |
| `gpu-compute` | GPU/算力租赁 | Modal、RunPod、Lambda、CoreWeave |
| `ai-infra` | 向量、语音、图像、评测、可观测等 | Pinecone、ElevenLabs、LangSmith |
| `other` | 相关但难归类 | 待人工细化 |

### 5.2 标签（可多选）

`free-tier` / `trial-credit` / `startup-program` / `student` / `self-serve` / `enterprise-only` / `open-weights` / `regional`

### 5.3 地区与语言

-   `regions`：`global` / `cn` / `us` / `eu` / `jp` / `kr` / `sg` / `in` / `other`
-   `languages`：`en` / `zh` / `ja` / `ko` / `multi`
-   用于回答“中文/区域厂商覆盖了多少”。

* * *

## 6\. 状态机

```
candidate ──▶ in_universe ──▶ monitored ──▶ covered
                  │                │
                  ├──▶ pending     ├──▶ degraded（抓取失败/长期无信号）
                  └──▶ ignored     └──▶ retired（停运/被收购）

```

| 状态 | 含义 | 判定 |
| --- | --- | --- |
| `candidate` | 刚被某个来源提到，尚未归一 | 自动 |
| `in_universe` | 通过相关性检查，确认是 AI 厂商 | 规则 + 抽样 |
| `pending` | 灰区/冲突，需人工确认 | 人工 |
| `ignored` | 明确排除（内容站、云产品、招聘等） | 规则 + 人工 |
| `monitored` | 已进入监控清单，有至少一个页面 | 配置 |
| `covered` | 已监控且最近 14 天成功抓取 ≥1 次 | 运行数据 |
| `degraded` | 已监控但连续失败/长期无信号 | 运行数据 |
| `retired` | 停运、被收购、官网消失 | 人工 |

**注意**：`in_universe` 不等于 `monitored`。宇宙回答“是谁”，监控回答“在盯谁”。

* * *

## 7\. 覆盖的定义与指标

### 7.1 四个覆盖概念

| 概念 | 定义 |
| --- | --- |
| **已收录**（in universe） | 通过相关性检查，进入宇宙 |
| **已监控**（monitored） | 监控清单中有至少一个 `enabled` 页面 |
| **有效覆盖**（covered） | 已监控且最近 14 天成功抓取 ≥1 次 |
| **可监控盲区**（eligible blind） | 已收录、未监控、且有官网/自助入口 |

### 7.2 指标

```
厂商覆盖率   = monitored / (in_universe − ignored)
有效覆盖率   = covered / (in_universe − ignored)
盲区率       = eligible_blind / (in_universe − ignored)
来源边际覆盖 = 该来源独有的宇宙厂商数 / 该来源厂商数
来源重叠率   = |A ∩ B| / |A ∪ B|
发现延迟     = 活动中首次出现 → 首次入库的时间

```

### 7.3 分维度

覆盖率必须能按以下维度切开，否则只是数字：

-   按分类（inference / cloud / gpu / aggregator…）
-   按地区（global / cn / eu…）
-   按来源（谁贡献了独有厂商）
-   按语言（en / zh）

* * *

## 8\. 字段清单（概念级）

| 字段 | 说明 | 必填 |
| --- | --- | --- |
| `slug` | 稳定标识 | ✅ |
| `name` | 展示名 | ✅ |
| `domains` | 主域 + 别名域 | ✅ |
| `aliases` | 名称/模型前缀/旧名 | ✅ |
| `category` | 主分类 | ✅ |
| `tags` | free-tier / relay / enterprise-only… | ✅ |
| `regions` / `languages` | 地区与语言 | ✅ |
| `homepage` / `docs` | 官网与文档 | 建议 |
| `has_api` / `self_serve` | 是否提供 API / 可自助注册 | 建议 |
| `status` | universe / pending / ignored / monitored / retired | ✅ |
| `roles` | provider / source / aggregator | ✅ |
| `parent` | 母公司/子品牌关系 | 可选 |
| `sources` | 哪些来源提到它（含首次/最近时间） | ✅ |
| `relevance` | 相关性 0–1 | ✅ |
| `last_verified` | 最近一次确认它仍存在/仍相关 | ✅ |
| `notes` | 判定理由、边界情况 | 可选 |

* * *

## 9\. 判定流程（5 步）

```
① 候选归一
   域名 → 注册域；名称 → 归一化；保留原始写法
        ↓
② 去重
   同域合并；同名不同域 → pending；子品牌 → parent
        ↓
③ 相关性检查
   是否 AI 相关？是否提供 API/算力？是否内容/目录/社区？
   → 是 → in_universe；否 → ignored（记录理由）
        ↓
④ 可监控性检查
   有官网/文档？可访问？有自助入口？
   → eligible / enterprise_only / no_entry
        ↓
⑤ 状态判定 + 抽样
   in_universe + 可监控 → eligible blind → 进入补盲队列
   灰区 → pending（人工）

```

* * *

## 10\. 20 个抽样案例（口径自测）

| # | 实体 | 分类 | 进宇宙 | 理由 |
| --- | --- | --- | --- | --- |
| 1 | DeepInfra | inference-api | ✅ | 托管模型推理 + 自助注册 |
| 2 | Groq | inference-api | ✅ | 自研芯片推理 + API |
| 3 | OpenRouter | aggregator | ✅ | 多厂商路由；同时是来源 |
| 4 | aicredits.dev | — | ❌ | 人工目录，是来源不是厂商 |
| 5 | AWS Bedrock | cloud-ai | ✅ | 云厂商的 AI 子品牌 |
| 6 | AWS EC2 | — | ❌ | 通用云产品，非 AI API |
| 7 | Google Vertex AI | cloud-ai | ✅ | AI 平台产品线 |
| 8 | Azure AI Foundry | cloud-ai | ✅ | AI 平台产品线 |
| 9 | Cloudflare Workers AI | cloud-ai | ✅ | 边缘推理 API |
| 10 | Hugging Face | cloud-ai / ai-infra | ✅ | 模型托管 + Inference API |
| 11 | Ollama（开源本地） | — | ❌ | 本地工具；其云服务另算 |
| 12 | Ollama Cloud | inference-api | ✅ | 托管推理服务 |
| 13 | LM Studio | — | ❌ | 本地客户端，无托管 API |
| 14 | PostHog | — | ❌ | 产品分析，非 AI API（曾被误收编） |
| 15 | Neon | — | ❌ | 数据库，非 AI API |
| 16 | Sentry | — | ❌ | 可观测性，非 AI API |
| 17 | [302.AI](http://302.AI) | aggregator | ✅ | 多模型中转/聚合，自助注册 |
| 18 | 某中转站（有域名+API+注册） | relay | ✅ | 纳入但标 relay、置信度低 |
| 19 | [turing.ac.uk](http://turing.ac.uk) | — | ❌ | 学术机构，非商业 API |
| 20 | 某 AI 教程博客 | — | ❌ | 内容站，无 API |

**自测标准**：这 20 条判断中，至少 18 条与人工复核一致；否则先修口径，不进入 Day 3。

* * *

## 11\. 验收清单（Day 1）

-   \[ \] 能对任意一个现有厂商，按本口径给出“算/不算、分类、主键、状态、理由”。
-   \[ \] 20 个抽样案例判断一致率 ≥90%。
-   \[ \] 明确“来源”与“厂商”的双重身份规则（OpenRouter 类）。
-   \[ \] 明确云厂商只收 AI 子品牌。
-   \[ \] 明确 relay/aggregator/enterprise-only 的处理方式。
-   \[ \] 覆盖指标与分母定义无歧义。

* * *

*下一步（Day 2）：按“机制 × 层级”建立来源清单，找出矩阵空格与第一批接入来源。*