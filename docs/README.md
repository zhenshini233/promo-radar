# promo-radar 文档索引

> 文档已精简：Day 3–11 的过程记录（补域名、补监控、外圈扫描等）已合并进
> `discovery/UNIVERSE_REPORT_v1.md`，原文删除。这里只保留长期有效的口径、结论与操作入口。

## 1. 先读这四份

| 文档 | 回答什么 |
|---|---|
| [`STAGE_CLOSURE.md`](STAGE_CLOSURE.md) | 阶段 1 做到哪、验收数字、下一阶段第一件事 |
| [`ARCHITECTURE_REVIEW.md`](ARCHITECTURE_REVIEW.md) | 为什么这样设计：七层、三闭环、选型取舍、迁移阶段 |
| [`discovery/PROVIDER_UNIVERSE_SPEC.md`](discovery/PROVIDER_UNIVERSE_SPEC.md) | 厂商宇宙口径：谁算厂商、怎么去重、状态机 |
| [`discovery/UNIVERSE_REPORT_v1.md`](discovery/UNIVERSE_REPORT_v1.md) | 当前宇宙状态：规模、覆盖率、盲区、落库依据 |

## 2. 目录结构

```
docs/
├── README.md                      # 本文件
├── ARCHITECTURE_REVIEW.md         # 架构评审与选型
├── NEXT_STEPS.md                  # 未决项与下一步
└── discovery/
    ├── PROVIDER_UNIVERSE_SPEC.md  # 口径（长期）
    ├── SOURCE_CATALOG.md          # 来源清单与机制矩阵（长期）
    ├── UNIVERSE_REPORT_v1.md      # 宇宙正式报告
    ├── aliases.json               # 别名 / 域名 / 排除项（数据源）
    ├── ANNOTATION_RULES_v0.md     # 分类 / 地区 / 相关性规则
    ├── ANNOTATION_v0.md           # 标注结果与低置信清单
    ├── PROVIDER_ENTITY_v0.md      # Provider 实体表与导入口径
    └── PROVIDER_PAGES_v0.md       # 监控页 ↔ Provider 关联
```

## 3. 当前状态（Day 15）

| 项 | 数值 |
|---|---:|
| 宇宙条目（去重前） | 429 |
| Provider 实体（去重后） | 379 |
| ├ monitored | 338 |
| ├ in_universe | 32 |
| └ ignored | 9 |
| Provider 覆盖率 | 91.4% |
| 监控页 | 377 |
| 页 ↔ Provider 关联率 | 96.0% |
| 数据库 schema | v7 |
| 测试 | 106 通过 |

> 覆盖率是“来源内覆盖”，不是市场覆盖。

## 4. 代码入口

| 脚本 | 作用 | 产物 |
|---|---|---|
| `scripts/universe_report.py` | 只读构建宇宙，算规模/重叠/盲区 | `data/universe/universe_v0.json`、`universe_snapshot.md` |
| `scripts/annotate_universe.py` | 补 category / regions / relevance，品牌归并 | `data/universe/universe_annotated_v0.json` |
| `scripts/import_providers.py` | 全量重建 Provider 实体 | `data/radar.db` 的 4 张 v7 表 |
| `scripts/provider_page_report.py` | 监控页 ↔ Provider 关联 | `docs/discovery/PROVIDER_PAGES_v0.md` |

运行顺序固定为：`universe_report → annotate_universe → import_providers → provider_page_report`。

## 5. 维护约定

1. **过程记录不进 `docs/`**：一次性的补录、探测结论写进对应正式文档的“形成过程”一节。
2. **正式报告只保留最新版**：`UNIVERSE_REPORT_v1.md` 更新时覆盖本文，不新增 v2 文件。
3. **口径先改 SPEC**：`PROVIDER_UNIVERSE_SPEC.md` 是唯一口径来源，代码与报告跟随。
4. **`aliases.json` 是数据源**：改完必须重跑 annotate + import，并核对覆盖率。
5. **Provider 实体只读**：`providers` 四张表由导入脚本重建，不手工 UPDATE。

## 6. 下次从哪继续

先看 [`NEXT_STEPS.md`](NEXT_STEPS.md)，按优先级选一项；每完成一项更新第 3 节数字与本文件状态表。