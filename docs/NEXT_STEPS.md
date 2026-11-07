# 下一步（NEXT_STEPS）

> 更新于 Day 15。每完成一项，回到 `README.md` 第 3 节更新数字，并把本项移到“已完成”。

## 已完成（Day 1–15 摘要）

- P0 修复：去重 key、band 分隔符、孤儿快照、CI 分支、watchlist 熔断
- 可用性：代理 UI、无代理直连、并行抓取、硬超时
- 调度：T1/T2/T3 分层 + 错峰
- 架构：七层 / 三闭环 / 演进式方案（`ARCHITECTURE_REVIEW.md`）
- 宇宙：4+1 来源聚合、别名归一、补盲、外圈扫描（`UNIVERSE_REPORT_v1.md`）
- 标注：category / regions / relevance + 品牌归并（`ANNOTATION_RULES_v0.md`）
- 实体：v7 四表，379 Provider，覆盖率 91.4%（`PROVIDER_ENTITY_v0.md`）
- 关联：345 页，关联率 92.2%（`PROVIDER_PAGES_v0.md`）

---

## P0：数据正确性

### 1. 收敛 73 个无监控页的 Provider

- **现状**：297 个 Provider 有页；73 个没有（41 个 `monitored` 无有效页 + 32 个 `in_universe`）。
- **动作**：逐条判断——无官网 → 保持 `in_universe`；有官网 → 补页或降级 `ignored`。
- **验收**：`monitored` 全部有页；报告注明“有页覆盖率”。

### 2. 处理 19 个未关联监控页

- **现状**：345 页中 318 已关联，19 未关联，8 关联到已忽略厂商。
- **动作**：补 `aliases.json` 的域名，或把页面标 `ignored` 后移出 watchlist。
- **验收**：未关联页 < 5%，且每一条有理由。

### 3. 移除 9 个非厂商监控页

- **现状**：NAIRR Pilot、Antler Disrupt、Stripe Atlas、UK Sovereign AI Fund 等仍在 `providers.toml`。
- **动作**：从 watchlist 删除（DB 里已是 `ignored`）。
- **验收**：`providers.toml` 中不再有资助/活动/创业项目页。

---

## P1：可用性

### 4. dashboard 分类视图

- 按 `category` / `regions` 展示：Provider 数、页数、覆盖率、盲区。
- 数据已就绪（`provider_stats` / `provider_page_stats`），只差渲染。

### 5. snapshots ↔ provider_id

- 当前是只读关联；下一步可加 `snapshots.provider_id` 或建视图，让站点直接按 Provider 聚合。
- 建议先加视图，稳定两周再考虑加列。

### 6. 28 条无官网条目

- 9 条待人工（Avian、Cosine、Quiver、Switchpoint、Laya、Lemonade、NexAGI、PublicAI、Recursive），
  12 条未知，7 条已跳过。

### 7. W&B / CoreWeave 域名归属

- `wandb.ai` 同时被 CoreWeave 与 Wandb 占用（models.dev 数据源标注问题）。
- 动作：确认后合并或改 `aliases.json`。

---

## P2：覆盖深度

### 8. 第二外圈来源

- 候选：Hacker News、GitHub Trending（均可达）；Product Hunt 403。
- 目的：把“来源内覆盖”变成可讨论的“市场覆盖”。

### 9. Offer 层

- 促销条目（Startup Program / Credits / for Startups）现在是 Provider 的重复项，
  应拆成 `offers`，与 Provider 一对多。

### 10. 采集健壮性

- ETag / If-Modified-Since（Miniflux 模式）
- 限速与 robots.txt
- 失败告警（连续失败、覆盖率下降）

### 11. 契约与可观测

- Pydantic 模型 + JSON Schema + 契约测试
- structlog 结构化日志

---

## 不做（已评估）

- Airflow / Dagster / Celery / Redis / K8s：当前规模用不上
- Scrapy：10 个来源不需要框架
- LLM 逐条判定：成本高、不可复现
- 多用户 SaaS：先服务单用户

---

## 运行命令

```powershell
$env:PYTHONPATH='src'
python scripts/universe_report.py
python scripts/annotate_universe.py
python scripts/import_providers.py
python scripts/provider_page_report.py
python -m pytest -q
```

顺序不能颠倒：宇宙 → 标注 → 落库 → 关联。

---

## 完成定义

一项任务算完成，必须同时满足：

1. 有可复算的数字（SQL 或脚本输出）；
2. 有测试覆盖（新增逻辑至少 1 个用例）；
3. 文档更新到对应正式文件，不新建过程文档；
4. 旧数字被替换，而不是两处并存。