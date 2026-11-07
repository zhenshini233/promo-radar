# 阶段 1 收尾：发现与实体基础（Day 1–15）

> 阶段目标：把“能抓到促销”升级为“知道自己覆盖了谁、还差谁”，并落到可查询实体。
> 状态：**已完成**，进入阶段 2 前冻结以下内容。

---

## 1. 阶段目标与达成

| 目标 | 达成情况 |
|---|---|
| 抓得到、跑得稳 | 并行抓取、硬超时、代理自动降级、watchlist 熔断 |
| 判得准 | 强信号词表、首次建档、标题归一、去重 key 修复 |
| 存得下 | schema v7：4 张 Provider 实体表 + 原 deals/snapshots 不变 |
| 看得见 | 静态站点、freshness、feedback、分层调度 |
| 说得清覆盖 | 宇宙 429 条、Provider 379、覆盖率 91.4%、页关联 92.2% |

---

## 2. 交付物

### 代码

| 模块 | 内容 |
|---|---|
| `domain/domains.py` | 注册域归一 |
| `infra/proxy.py`、`local_config.py` | 代理探测、本地配置 |
| `infra/providers_store.py` | providers.toml 安全写入 |
| `storage/repository.py` | v7 迁移、`provider_stats`、`provider_page_stats` |
| `pipeline/runner.py`、`collectors/watchlist.py` | 并行抓取、分层调度 |
| `scripts/*.py`（4 个） | 宇宙 → 标注 → 落库 → 关联 |

### 数据

- `data/radar.db`：deals / snapshots / runs / providers 等
- `data/universe/universe_v0.json`：宇宙快照
- `data/universe/universe_annotated_v0.json`：标注结果
- `docs/discovery/aliases.json`：别名与域名映射（数据源）

### 文档（11 份，见 `docs/README.md`）

- 架构：`ARCHITECTURE_REVIEW.md`
- 口径：`PROVIDER_UNIVERSE_SPEC.md`、`SOURCE_CATALOG.md`
- 结果：`UNIVERSE_REPORT_v1.md`、`ANNOTATION_v0.md`
- 实体：`PROVIDER_ENTITY_v0.md`、`PROVIDER_PAGES_v0.md`

---

## 3. 验收数字（冻结）

| 指标 | 数值 |
|---|---:|
| 宇宙条目 | 429 |
| Provider 实体 | 379 |
| ├ monitored | 338 |
| ├ in_universe | 32 |
| └ ignored | 9 |
| Provider 覆盖率 | 91.4% |
| 监控页 | 345 |
| 页 ↔ Provider 关联率 | 92.2% |
| 测试 | 106 通过 |
| schema | v7 |

复现命令：

```powershell
$env:PYTHONPATH='src'
python scripts/universe_report.py
python scripts/annotate_universe.py
python scripts/import_providers.py
python scripts/provider_page_report.py
python -m pytest -q
```

---

## 4. 冻结项（阶段 2 前不再改）

1. **口径**：`PROVIDER_UNIVERSE_SPEC.md` 的纳入/排除标准。
2. **schema v7**：4 张 Provider 表字段与唯一键。
3. **标注规则 v0**：category / regions / relevance 公式。
4. **脚本顺序**：宇宙 → 标注 → 落库 → 关联。
5. **覆盖率表述**：只说“来源内覆盖 91.4%”，不外推市场覆盖率。

---

## 5. 已知限制

| 限制 | 影响 | 承接 |
|---|---|---|
| 73 个 Provider 无监控页 → **33**（32 未监控 + 1 例外） | 覆盖率有水分 | 阶段 2 P0-1，已完成 |
| 19 个页未关联 → **2** | 实体层漏配 | 阶段 2 P0-2，已完成 |
| 9 个非厂商页 → **0** | 数据纯度 | 阶段 2 P0-3，已完成 |
| 32 条无官网 | 宇宙完整性 | 阶段 2 P1 |
| 只有 1 个外圈来源 | 市场覆盖未知 | 阶段 2 P2 |
| Offer 未拆层 | 促销条目混入 Provider 语义 | 阶段 2 P2 |

---

## 6. 阶段 2：质量收敛与可视化

**目标**：把“来源内覆盖”做成“可信覆盖”，并让结果在 dashboard 可见。

**第一件事**：进入 P1，做 dashboard 分类视图。

**验收标准**：

- 未关联页 < 5%；
- 非厂商监控页清零；
- dashboard 能按 category 展示覆盖率与盲区；
- 覆盖率口径写进站点提示，不夸大。

**建议时间盒**：3–5 个工作日。

---

*阶段 1 结束。后续变更从 `NEXT_STEPS.md` 的 P0 开始。*