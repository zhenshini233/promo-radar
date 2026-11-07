# 厂商宇宙正式报告 v1

> 版本：v1（2026-11）｜依据：Day 3–11 的探索、映射、覆盖率与盲区数据
> 用途：作为 **Provider 实体落库**与后续数据模型的输入
> 配套文件：`PROVIDER_UNIVERSE_SPEC.md`（口径）、`SOURCE_CATALOG.md`（来源）、`aliases.json`（映射）、`universe_annotated_v0.json`（数据快照）

---

## 1. 执行摘要

### 当前数字

| 指标 | 数值 |
|---|---:|
| 宇宙条目（去重后） | **429** |
| 已监控 | **397** |
| 来源内覆盖率 | **92.5%** |
| 有官网、未监控（可执行盲区） | **0** |
| 无官网、待确认 | **32** |
| 监控有、宇宙无 | **6** |
| 别名映射 | 62 |
| 域名映射 | 72 |
| 排除项（有理由） | 24 |

### 三句话结论

1. **方向成立**：以“厂商宇宙”为分母，可以把“覆盖面”从口号变成可计算、可审计的指标。
2. **有官网盲区已清零**：从 Day 3 的 5 个降到 0；监控清单从 359 家增至 384 家。
3. **92.5% 仍是“来源内覆盖”，不是“市场覆盖”**：外圈只测了 HuggingFace 一个来源，且 303 个外圈组织里真实厂商只有 3 家。

---

## 2. 口径（落库的直接依据）

### 2.1 四个概念

| 概念 | 定义 | 是否进 Provider 表 |
|---|---|---|
| Provider | 提供 AI 模型/推理/算力/托管/自助服务的组织或平台 | ✅ |
| Product | 模型、端点、套餐 | ❌（挂在 Provider 下） |
| Offer | 促销、额度、免费层 | ❌（下一层） |
| Source | 目录、榜单、社区、搜索引擎 | ❌（但可同时是 Provider） |

### 2.2 纳入标准

- **MUST**：AI 相关 + 有公开入口 + 可独立识别。
- **NICE**：自助注册、免费层、公开 API、定价页。
- **EXCLUDE**：内容站、目录站、社区、纯本地工具、通用云产品、政府/学术、招聘咨询、死站、模型作者/量化工具。

### 2.3 主键与别名

- 主键：**canonical slug**。
- 域名：以注册域为准（`seed.bytedance.com` → `bytedance.com`）。
- 别名：品牌名、模型 ID 首段、旧域名、来源写法。
- 冲突：同域不同名合并；同名不同域不自动合并，进 `pending`。
- 子品牌：保留子品牌，`parent` 指向母公司。

### 2.4 状态机

```
candidate → in_universe → monitored → covered
                ├→ pending
                ├→ ignored（有理由）
                └→ retired
```

---

## 3. 来源与机制矩阵（现状）

| 机制 | 聚合目录 | 平台/榜单 | 厂商官网 | 社区 | 生态/搜索 |
|---|---|---|---|---|---|
| 人工审核 | aicredits、FreeToken、opentoken（候选） | — | 人工月查 | linux.do | — |
| 机器清单 | mnfst、aifree（候选） | models.dev、LiteLLM | pricing 页 | — | GitHub（候选） |
| 平台 API | — | OpenRouter、HuggingFace（信号） | — | — | Product Hunt（403） |
| 社区信号 | — | — | — | HN、Reddit（候选） | X/Discord（未做） |
| 搜索引擎 | — | — | — | — | Brave/SearXNG（未接） |
| 众包 | Issue/PR（未做） | — | 提交表单（未做） | 用户反馈 | — |

**当前实际参与宇宙计算的来源：**

| 来源 | 厂商数 | 独有 | 独有率 | 已监控 |
|---|---:|---:|---:|---:|
| models.dev | 205 | 135 | 66% | 205 |
| aicredits | 138 | 91 | 66% | 138 |
| OpenRouter | 120 | 59 | 49% | 106 |
| LiteLLM | 85 | 34 | 40% | 71 |

> 独有率偏高、Jaccard 偏低（10%–20%），主要因为来源键仍不统一；别名归一后已改善，但未完全消除。

---

## 4. 形成过程（Day 3–11）

| 阶段 | 动作 | 结果 |
|---|---|---|
| Day 3 | 4 来源只读聚合 | 宇宙 440，覆盖 76.6%，无域名 98 |
| Day 4 | 补官网 + 别名归一 | 宇宙 426，覆盖 86.6%，有官网盲区 17 |
| Day 5 | 补监控 15 家 A/B 级 | 监控 374，覆盖 90.1%，有官网盲区 2 |
| Day 6 | 首次建档强信号入库 | Featherless `$50 credits` 入库 |
| Day 7 | 核查 40 条无域名 | 补 8、排除 4、待查 28 |
| Day 8 | 补监控 7 家 + Seed 归一 | 监控 381，覆盖 92.9% |
| Day 9 | 排除 2 个 C 级 + Ionstream 恢复 | 覆盖 93.3%，有官网盲区 0 |
| Day 10 | HuggingFace 外圈扫描 | 外圈 303，真实厂商 3 |
| Day 11 | 补监控 3 家外圈厂商 | 监控 384，覆盖 93.4%，有官网盲区 0 |

---

## 5. 当前结构

### 5.1 按来源贡献

- 平台 API（OpenRouter/models.dev/LiteLLM）贡献了大部分结构化厂商；
- 人工目录（aicredits）贡献了“有活动但不在平台 API”的厂商；
- 官网监控补了 22 家（Day 5/8/11）；
- HuggingFace 只贡献 3 家真实厂商。

### 5.2 按状态

| 状态 | 数量 |
|---|---:|
| monitored | 397 |
| in_universe（未监控，无官网） | 32 |
| ignored | 24（另有若干未计入宇宙的来源键） |

### 5.3 尚未标注的维度

- `category`（inference / cloud / gpu / aggregator / relay / ai-infra）
- `regions`（global / cn / us / eu…）
- `relevance`（0–1）
- `last_verified`（最近一次确认）

这四项是落库前必须补的，否则 Provider 表会缺关键字段。

---

## 6. 覆盖率与盲区

### 6.1 指标

```
覆盖率       = monitored / (in_universe - ignored)
有官网盲区   = in_universe - monitored - 无官网
无官网盲区   = 有收录但无法确定官网
```

### 6.2 当前

- 覆盖率 92.5%（来源内）。
- 有官网盲区 0。
- 无官网 28（9 待人工、12 未知、7 跳过）。
- 监控有、宇宙无 6（OpenRouter/HF 来源自身、Google 研究资助、OpenBMB/ServiceNow/TII 已排除）。

### 6.3 为什么不是“市场覆盖率”

- 分母是 4 个来源的并集；
- 监控清单本身主要由这些来源自动收编；
- 只测了 HuggingFace 一个外圈来源；
- 搜索引擎、Product Hunt、中文平台、区域厂商尚未接入。

**结论：92.5% 应读作“现有来源内部覆盖”，不能对外宣称“覆盖了 92.5% 的市场”。**

---

## 7. 别名与域名归一

`aliases.json` 结构：

| 字段 | 数量 | 作用 |
|---|---:|---|
| aliases | 62 | 来源写法 → canonical slug |
| names | 28 | canonical → 展示名 |
| domains | 72 | canonical → 注册域 |
| ignored | 24 | 非厂商/占位/研究机构，附理由 |

已处理的典型冲突：

- `meta-llama` / `Meta` / `facebook` → `meta`
- `kimiforcoding` / `Kimi` → `moonshot`
- `stepfunglobal` / `StepFun` → `stepfun`
- `amazonnova` / `bedrock` / `amazon` → `aws`
- `googleaistudio` / `vertexai` → `google`
- `zai-org` → `zai`
- `ibm-granite` → `ibm`

---

## 8. 第五来源评估

| 来源 | 可达性 | 结论 |
|---|---|---|
| HuggingFace API | ✅（需 verify=False / 修证书） | 模型生态信号源，不是厂商目录 |
| Product Hunt | ❌ 403（Cloudflare） | 需 API key 或绕行 |
| GitHub Trending | ✅ | 可抓，但需过滤“非厂商” |
| YC Directory | ✅ | 可抓，但更新低频 |
| DuckDuckGo HTML | ❌ 超时 | 不可用 |

HuggingFace 样本：1000 热门模型 / 339 组织 / 36 已覆盖 / 303 外圈；外圈真实厂商 3 家（Qdrant、Lightricks、Red Hat AI），其余为模型作者、工具、研究机构。

---

## 9. Provider 实体落库依据

### 9.1 字段映射

| 宇宙字段 | 目标字段 | 说明 |
|---|---|---|
| `slug` | `providers.slug` | 唯一键 |
| `name` | `providers.name` | 展示名 |
| `domains` | `provider_domains` 表 / JSON | 注册域，唯一 |
| `aliases` | `provider_aliases` 表 / JSON | 来源写法 |
| `category` | `providers.category` | **待标注** |
| `regions` | `providers.regions` | **待标注** |
| `status` | `providers.status` | universe/monitored/pending/ignored/retired |
| `roles` | `providers.roles` | provider/source/aggregator |
| `sources` | `provider_sources` 表 | 来源、首次/最近时间 |
| `relevance` | `providers.relevance` | 0–1，**待补规则** |
| `last_verified` | `providers.last_verified_at` | 初值可为空 |
| `parent` | `providers.parent_id` | 子品牌 |

### 9.2 唯一键与约束

1. `slug` 全局唯一；导入前按 `brand_key` 归并（见 `ANNOTATION_RULES_v0.md` §4.1），宇宙 429 条去重后为 379。
2. 一个注册域只能有一个 primary provider；子品牌通过 `parent_id` 关联，不重复占用域名。
3. 别名全局唯一；冲突进 `pending`，人工确认。
4. `ignored` 必须有理由，不物理删除。
5. `status = monitored` 必须至少关联一个 `page`。

### 9.3 数据质量门槛（落库前）

- [ ] 每条有 `slug`、`name`、`status`。
- [ ] 有域名，或至少被 2 个独立来源收录。
- [ ] 别名无冲突；同域不同名已合并。
- [ ] `ignored` 全部有理由。
- [ ] 覆盖率可从库中复算（不依赖脚本内存）。
- [ ] `category` / `regions` 有初值（可先 `unknown`）。

### 9.4 迁移步骤

1. 以 `aliases.json` + `universe_annotated_v0.json` 为输入，按 `brand_key` 去重后生成 `providers` 初始数据（429 → 379）。
2. 建 `provider_domains` / `provider_aliases` / `provider_sources`。
3. 把 `providers.toml` 的 384 家映射为 `providers` + `pages`。
4. 校验：slug 唯一、域名唯一、别名无冲突、monitored 都有 page。
5. 用 SQL 复算覆盖率，与脚本结果对账（目标差异 <1%）。
6. 双写/视图过渡 2 周，再切换。

---

## 10. 未决项

| # | 未决项 | 影响 | 建议 |
|---|---|---|---|
| 1 | 28 条无官网 | 宇宙完整性 | 搜索引擎/人工核查 |
| 2 | `category` / `regions` 未标注 | Provider 表缺字段 | 落库前补初值 |
| 3 | `relevance` 未定义 | 无法自动决定是否监控 | 规则：AI 相关 + API + 自助 + 来源数 |
| 4 | 市场覆盖未知 | 不能对外宣称覆盖率 | 抽样验证 + 第二外圈来源 |
| 5 | HF 信号源未实现 | 模型生态变化未利用 | 改造成“新 org/新模型”信号 |
| 6 | Product Hunt 403 | 新面孔来源缺失 | API key 或绕行 |
| 7 | Jaccard 仍偏低 | 来源独立性判断不稳 | 继续消除键不一致 |
| 8 | 宇宙含 40 条同品牌重复 | 直接落库会虚增厂商数 | 按 `brand_key` 归并，促销条目转 Offer |

---

## 11. 结论与下一步

### 结论

- 厂商宇宙已经可以作为 **Provider 实体的唯一输入**；
- 但它目前是“来源内宇宙”，不是“市场宇宙”；
- 落库前需要补 `category` / `regions` / `relevance` 三项，否则表结构会反复改；
- 有官网盲区为 0，意味着“再补监控”的边际收益已很低，下一阶段的重点应转向：
  1. **Provider 实体落库**；
  2. **分类与地区标注**；
  3. **第二外圈来源**（搜索/Product Hunt）；
  4. **HF 信号源改造**。

### 下一步（建议顺序）

1. 补 `category` / `regions` / `relevance` 的规则与初值（1–2 天）。
2. 设计 `providers` 表（阶段 2 的一部分），用本报告第 9 节作为验收标准。
3. 导入并复算覆盖率，与脚本对账。
4. 再接第二外圈来源，测“市场覆盖”。

---

*本报告是 Day 3–11 的收口，不替代 `PROVIDER_UNIVERSE_SPEC.md` 的口径定义；后续变更以 spec 为准，本报告记录当前状态。*