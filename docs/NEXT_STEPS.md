# 下一步（NEXT_STEPS）

> 更新于 Day 15。每完成一项，回到 `README.md` 第 3 节更新数字，并把本项移到“已完成”。

## 已完成（Day 1–15 摘要）

- P0 修复：去重 key、band 分隔符、孤儿快照、CI 分支、watchlist 熔断
- 可用性：代理 UI、无代理直连、并行抓取、硬超时
- 调度：T1/T2/T3 分层 + 错峰
- 架构：七层 / 三闭环 / 演进式方案（`ARCHITECTURE_REVIEW.md`）
- 宇宙：4+1 来源聚合、别名归一、补盲、外圈扫描（`UNIVERSE_REPORT_v1.md`）
- 标注：category / regions / relevance + 品牌归并（`ANNOTATION_RULES_v0.md`）
- 实体：v7 四表，370 Provider，覆盖率 91.4%（`PROVIDER_ENTITY_v0.md`）
- 关联：345 页，关联率 92.2%（`PROVIDER_PAGES_v0.md`）
- **云资源扩展 v1（2026-11-08）**：schema v10、`free-for-dev` + 15 家官方免费层页、部署场景页、云资源表格、localStorage 领取、121 项测试全绿
- **统一链路 v10.1（2026-11-08）**：AI 与云统一写 `offers`，`deals` 停止写入；站点合并为「全部资源」+「厂商」，四维筛选；反馈/核实/摘要/通知全部改按 `offer_key`

---

## P0：数据正确性

### 1. 收敛无监控页的 Provider ✅（41 → 1）

- **结果**：`monitored` 无页从 41 降到 1（Wandb，models.dev 域名冲突，待人工确认）；总无页 73 → 33（32 个 `in_universe` + 1 例外）。
- **做法**：
  1. 用 watchlist 的 URL 补 Provider 域名（解决 8 个“有快照但缺域名”）；
  2. 对 32 个被哈希错峰排到未来的页做调度引导（`next_check_at` 置为已到期）；
  3. 抓取一轮，成功页写内容，失败页也落快照（`fail_count`）。
- **验收**：`monitored` 有页率 **99.7%**（337/338），关联率 92.2% → **96.0%**。

### 2. 处理未关联监控页 ✅（7 → 2）

- **现状**：366 页中 364 已关联；2 个未关联是 OpenRouter / Hugging Face（来源自身，宇宙有意排除）；已忽略厂商关联 0。
- **动作**：补 `aliases.json` 的域名，或把页面标 `ignored` 后移出 watchlist。
- **验收**：未关联页 < 5%，且每一条有理由。

### 3. 移除非厂商监控页 ✅（9 → 0）

- **现状**：NAIRR Pilot、Antler Disrupt、Stripe Atlas、UK Sovereign AI Fund 等仍在 `providers.toml`。
- **动作**：从 watchlist 删除（DB 里已是 `ignored`）。
- **验收**：`providers.toml` 中不再有资助/活动/创业项目页。

---

## P1：可用性

### 4. dashboard 分类视图 ✅

- 总览页新增“分类覆盖”区块：category、监控数/Provider 数、页数、盲区、覆盖率。
- 数据来自 `repo.provider_category_stats()`，随 `data.json` 下发。
- 当前最低：unknown 67%、model_lab 78%、inference 92%。

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