# 项目现状（唯一事实源）

> 任何数字、状态、下一步，以本文件为准。其它文档只解释“为什么”，不再各自定义“做到哪”。
> 最后更新：2026-11-08｜schema **v10**｜云资源扩展已落地（M0–M6）

---

## 0. 线上

- URL：https://zhenshini233.github.io/promo-radar/
- 最近部署：2026-11-08T00:16Z（run 42428937304，success）
- 自动更新：每天 02:37 UTC
- data 分支存 DB 快照；gh-pages 分支存站点

## 1. 现在有什么（可运行）

| 块 | 状态 | 证据 |
|---|---|---|
| 采集 | 可用 | `radar run` 跑通，10 个 AI 源 + watchlist + 2 个云源 |
| 理解 | 可用 | 解析器、注册域、别名归一、云规格/单位归一 |
| 判定 | 可用 | 评分、强信号、状态机、Offer 层、免费门槛 |
| 记忆 | 可用 | SQLite v10，核心表 + offers + signals + claims |
| 分发 | 可用 | 统一「资源」+ 统一「厂商」+ 用途筛选 + Telegram + 反馈 |
| 治理 | 半可用 | 覆盖率、分类视图、熔断；缺收编闸门 |

## 2. 数据（2026-11-08 本地实测）

| 表 | 行数 |
|---|---:|
| deals | 220 |
| snapshots | 333 |
| providers | 370（线上 v9 口径；本地开发库未跑 import_providers） |
| offers | 881（AI 212 + 云 669；统一目录的唯一展示实体） |
| offer_evidence | 882（一个 Offer 可有多条来源证据） |
| signals | 26 |
| vendors（聚合视图） | 805（AI + 云，不依赖 providers 表） |
| claims | 0 |

云资源分布：devtool 184 / cloud 84 / paas 72 / cdn 60 / storage 52 / database 48。

覆盖率 91.4%（338/370）；页关联 99.5%（364/366）；有官网盲区 0；无官网 32。

## 3. 代码入口（8 个脚本，职责唯一）

| 脚本 | 输入 → 输出 |
|---|---|
| `universe_report.py` | DB/state → `universe_v0.json` |
| `annotate_universe.py` | 宇宙 → `universe_annotated_v0.json` |
| `import_providers.py` | 标注 → `providers` 四表 |
| `provider_page_report.py` | 快照 → 关联报告 |
| `build_offers.py` | 历史 deals → `offers`（一次性迁移，不再每日执行） |
| `diagnose_pages.py` | 只读诊断无页 Provider |
| `queue_missing_pages.py` | 调度引导缺失页 |
| `prune_watchlist.py` | 移除非厂商条目 |

运行顺序：`universe → annotate → import → offers → page_report`。

## 4. 文档（14 份，定位固定）

| 文档 | 只回答 |
|---|---|
| `README.md` | 入口与状态摘要 |
| `STATE.md` | **本文件：唯一事实源** |
| `ARCHITECTURE_REVIEW.md` | 为什么这样分层 |
| `CLOUD_EXPANSION.md` | 云资源（免费额度/云服务器/云存储）扩展的设计与实现（v1 已落地） |
| `NEXT_STEPS.md` | 待办清单（按优先级） |
| `STAGE_CLOSURE.md` | 阶段 1 边界（历史） |
| `RELEASE_SCOPE.md` | 上线范围（待合并进 NEXT_STEPS） |
| `discovery/*`（7 份 + aliases.json） | 口径、来源、宇宙、标注、实体、关联 |

## 5. 已知债（按严重度，不新增）

| 级别 | 债 | 影响 |
|---|---|---|
| P0 | 收编闸门缺失 | 非 AI 条目仍可能进 watchlist |
| P0 | 步骤文档三份重叠（NEXT/RELEASE/STAGE） | 路线反复的根源 |
| P1 | 32 条无官网 | 覆盖率缺口 |
| P1 | 16 个 Offer 未匹配 Provider | 语义不完整 |
| P1 | 云页面 4/15 抓取失败（Oracle 403 / GCP 超时 / Render 超时 / Netlify 未命中） | 云覆盖率缺口 |
| P1 | 云资源结构化率约 40%（规格/额度字段） | 筛选能力有限 |
| P1 | watchlist 内混合调度/抓取/判定 | 层边界不清 |
| P2 | 无契约测试 | 重构易破 |
| P2 | 无回滚手册 | 线上故障恢复慢 |

## 6. 固定路线（不再改）

### R1 一致性收口（现在做）

1. **契约冻结**：Deal / Offer / Provider 各一组快照测试；
2. **文档合一**：把 `NEXT_STEPS`、`RELEASE_SCOPE` 合并成一份，`STAGE_CLOSURE` 只留历史；
3. **基线**：打 tag `v1.0.0-rc1`；
4. 验收：任何人按 `STATE.md` 能在 10 分钟内复现全部数字。

### R2 单链重构（R1 完成后）

按依赖顺序收口，不跨层改：

1. 采集→理解：解析器只产候选，不写库；
2. 理解→判定：评分/状态/Offer 只消费候选；
3. 判定→记忆：只写已判定实体；
4. 治理：入口闸门 + 出口覆盖率检查；
5. 计划：目标/预算/优先级（最后）。

### R3 上线（R2 完成后）

- 推 `main` + `data` 种子库；
- Actions 手动跑通一次；
- Pages 可访问；
- 回滚手册 + 基础告警。

### R4 云资源扩展（v1 已完成）

- M0 契约与 v10 模型：`vertical` / `offer_type` / `resources` / `eligibility` / `signals` / `claims`；
- M1 垂直化贯通：规则包、免费门槛、CLI `--vertical`；
- M2/M3 采集：`free-for-dev` 目录 + `cloud_sources.toml` 配置化官方页；
- M4/M5 数据：数据库/存储/大厂免费层；
- M6 站点：部署场景页、云资源表格、localStorage 领取跟踪；
- 待办：4 家抓取失败修复、结构化率提升、云侧 Telegram 日报、VPS 特价（P2 可选）。

---

## 7. 规则

1. 数字只在本文件更新，其它文档引用；
2. 新功能不做，直到 R1 完成；
3. 每完成一项，更新本文件第 1/2/5 节，并提交；
4. 不再新增“下一步”类文档。