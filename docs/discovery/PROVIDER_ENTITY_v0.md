# Provider 实体落库 v0（Day 14）

> 目标：把厂商宇宙从“分析产物”变成“可查询实体”。
> 范围：schema v7 新增 4 张表 + 导入 370 条 + 覆盖率对账。**旧表未改动**。

---

## 1. 结果总览

| 指标 | 数值 |
|---|---:|
| `providers` | **370** |
| ├ `monitored` | 338 |
| ├ `in_universe` | 32 |
| └ `ignored`（非厂商） | 0 |
| `provider_domains` | 370 |
| `provider_aliases` | 737 |
| `provider_sources` | 550 |
| 覆盖率（SQL） | **91.4%** |
| 域名冲突 | 1（已知，`wandb.ai`） |
| 无来源 Provider | 0 |

来源分布：modelsdev 197、aicredits 135、openrouter 116、litellm 84、watchlist 14。

---

## 2. 表结构（v7）

### providers

| 字段 | 说明 |
|---|---|
| `id` | 自增主键 |
| `slug` | 唯一键；优先用品牌词，其次原 slug/名称 |
| `name` | 展示名 |
| `category` | model_lab / inference / cloud / gpu / aggregator / ai_infra / app / relay / unknown |
| `regions` | JSON 数组，主地区在前 |
| `relevance` | 0–1，监控优先级 |
| `confidence` | high / medium / low |
| `status` | in_universe / monitored / pending / ignored / retired（CHECK 约束） |
| `vendor_like` | 0/1；0 = 资助/活动/机构，不进覆盖率分母 |
| `brand_key` | 归并键 |
| `parent_id` | 预留：子品牌 → 母公司 |
| `first_seen_at` / `updated_at` | 时间戳 |

### provider_domains

`domain` 主键，一个注册域只属于一个 provider；`is_primary` 预留。

### provider_aliases

`alias` 主键，保存名称、slug、域名的归一写法；`kind` 为 name / domain。

### provider_sources

`(provider_id, source)` 主键，记录首次/最近收录时间。

---

## 3. 导入口径

1. 输入 `data/universe/universe_annotated_v0.json`（421 条）。
2. 只导入代表条目（`duplicate_of` 为空）：**370 条**；其余 50 条转为别名与来源。
3. 状态映射：
   - `vendor_like = false` → `ignored`
   - 已监控 → `monitored`
   - 其余 → `in_universe`
4. 来源：
   - 用 4 个发现来源；
   - 若为空且已监控 → 补 `watchlist`（HF 外圈/人工补录的 14 家）。
5. 幂等：全量重建 4 张表，重复运行结果一致。

---

## 4. 覆盖率三种口径

| 口径 | 分母 | 分子 | 覆盖率 |
|---|---:|---:|---:|
| 宇宙脚本（未去重、含非厂商） | 421 | 389 | 92.4% |
| 代表条目（真厂商） | 370 | 338 | 91.4% |
| SQL（排除 ignored） | 370 | 338 | 91.4% |

差异来自：

- 同品牌归并：421 → 370（51 条重复）；
- 非厂商排除：9 条不计入分母/分子。

**SQL 口径是正式口径**，后续对外只说 91.4%，并注明“来源内覆盖”。

---

## 5. 冲突处理

唯一域名冲突：`wandb.ai`。

原因：models.dev 把 W&B Inference 的 provider id `wandb` 标成了 `CoreWeave`，导致 CoreWeave 与 Wandb 共享同一官网域。

处理：不抢占（保留先入库 owner），详见本文 §5；后续人工确认 W&B Inference 归属后再合并。

---

## 6. 数据质量

| 检查 | 结果 |
|---|---|
| `slug` 重复 | 0 |
| 无来源 Provider | 0 |
| 无域名 Provider | 33（无官网 32 + 1 条长尾） |
| 状态非法 | 0（CHECK 约束） |
| 重复导入行数变化 | 0 |

---

## 7. 与旧结构的关系

- `deals`、`snapshots` 仍按 `provider` 文本关联，**未迁移**；
- `providers.toml` 仍是监控清单的写入端（384 家）；
- 新表是只读实体层，不参与抓取与判定；
- 下一步才做 `snapshots.provider_id` 关联。

这样保证：即使实体层有问题，抓取与发布链路不受影响。

---

## 8. 验收

- [x] 370 条 Provider 入库
- [x] SQL 覆盖率与脚本口径一致（91.4%）
- [x] 重复导入幂等
- [x] 域名/别名冲突不抢占
- [x] 全量测试通过（101 个）
- [x] 旧表 schema 未变（v4 → v7 迁移测试通过）

---

## 9. 下一步

1. **snapshots ↔ provider_id**：用 `provider_domains` 做关联视图，先只读；
2. **dashboard 分组**：按 category/regions 展示覆盖率与盲区；
3. **清理监控清单**：9 个非厂商促销页、28 条无官网；
4. **第二外圈来源**：HN / GitHub Trending，验证“市场覆盖”；
5. **Offer 层**：把促销条目（Startup Program/Credits）从 Provider 拆到 Offer。

---

*本文件记录 Day 14 的落库结果；表结构变更以 `src/radar/storage/schema.sql` 为准。*