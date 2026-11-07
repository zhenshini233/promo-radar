# promo-radar 架构评审与技术选型

> 评审对象：`284a92d` 之后的当前实现（含本轮 P0 加固）  
> 规模：`src/radar` 39 个文件 / 4,304 行；模板 578 行；测试 15 个文件 / 1,466 行  
> 结论：**方向是对的，不需要推倒重来；但底层有 3 处结构性债务，应在继续加功能前解决。**

* * *

## 1\. 结论（TL;DR）

### 三句话

1.  **分层骨架优于大多数个人项目**：domain 零 IO、collectors 协议化、delivery 只读模型，这个方向要保留。
2.  **真正的问题不在抓取，而在数据模型**：provider 是字符串、offer 没有生命周期、目录字段被丢弃、`state` 表成了影子数据库——这导致"能不能领、何时截止、哪来的证据"答不出来。
3.  **第二问题是边界**：调度藏在 watchlist 内部、源在 fetch 里写状态、`runner` 里堆特判。应拆出 `scheduler` / `resolver` / `lifecycle` 三个独立层。

### 推荐路线

**方案 A：演进式重构（保留 Python 单体 + SQLite）**

-   不引入 Airflow / Dagster / Prefect / Celery / K8s。
-   引入 `Pydantic contracts`、`SQLAlchemy + Alembic`、独立 `scheduler`、`Offer/Evidence/Signal` 实体模型。
-   前端从"Jinja SSR + Vue 全局版"迁到 **Vite + Vue 3 + TS 单份组件**，静态数据分片。
-   预计 8–12 周，可分 5 个阶段独立交付、独立回滚。

### 不该做的事

-   不要为了"架构先进"上工作流编排平台（调研结论一致：几个 cron 任务用 Dagster 是 overkill）。
-   不要立刻迁 Postgres（SQLite 完全够，SQLAlchemy 保留切换能力）。
-   不要做多用户 SaaS / 登录体系。
-   不要让 LLM 参与每条数据的判定（成本、不可复现、隐私）。

* * *

## 2\. 现状工作流

### 2.1 端到端数据流

```
[触发]
  GitHub Actions cron (每天 02:37 UTC)
  / radar serve 手动刷新（可勾选源）
  / CLI radar run
        │
        ▼
[配置] load_config()
  config.local.toml 优先（不合并 config.toml）
  providers.toml（实体清单，自动收编会写它）
        │
        ▼
[采集] build_sources() → 并行 fetch（每源独立 http client + SQLite 连接）
  ├─ 发现型-全量：aicredits.llms-full.txt → 201 条 RawItem(force_keep)
  ├─ 发现型-diff：modelsdev / mnfst / freetoken / litellm / openrouter / aa
  │     └─ 上次基线存 state 表（JSON 字符串）→ 本轮 diff → 事件
  ├─ 社区型：linuxdo RSS ×2、Hacker News Algolia
  └─ 信号型：watchlist
        providers.toml → 到期页面 → HTML 正文 → snapshots/snapshot_history
        → 关键词集合变化 → 新活动 / 归档
        │
        ▼
[主线程处理]
  score_item()（关键词规则）→ 阈值过滤 → make_key()
  → upsert_scored()（精确 key → alias → 标题模糊 + 金额护栏）
        │
        ▼
[收尾]
  全量快照消失归档 → 盲区自动收编（写 providers.toml）
  → 源健康门控 → expire_old() → 连续失败统计
  → record_run() / prune_history() / prune_orphan_snapshots()
        │
        ▼
[发布]
  build_site(): Jinja SSR + 内联全量 JSON + Vue 模板 + data.json + atom.xml
  push_new_deals(): Telegram

```

### 2.2 控制流的关键特征

| 特征 | 现状 | 影响 |
| --- | --- | --- |
| 触发 | cron / 手动 / CLI 三种入口，共用 `run()` | 简单，但没有"任务/运行"抽象 |
| 并发 | 源级并行，落库串行 | 正确；但源在 fetch 内写状态，逼出"每 worker 独立 DB 连接" |
| 状态 | `state` 表 + `snapshots` 表 + `aliases` 表 | 职责重叠，`state` 是不可查询的 JSON 影子库 |
| 调度 | watchlist 内部算 `next_check_at`；目录源每轮全跑 | 调度逻辑分散，runner 不知道谁该跑 |
| 失败 | 源级隔离 + 熔断 + 新鲜度横幅 | 已止血，但没有告警通道与统一健康模型 |
| 发布 | 每次全量重建静态站 | 简单；但单页 467KB，无分页/分片 |

### 2.3 现有分层与依赖方向

```
                 ┌──────────────┐
   cli.py ──────▶│  pipeline    │──────▶ collectors ──┐
   server.py ───▶│  runner      │                     │
                 │  enroll      │                     ▼
                 └──────┬───────┘              ┌──────────────┐
                        │                      │ infra/http   │
                        ▼                      │ infra/config │
                 ┌──────────────┐              │ infra/proxy  │
                 │   delivery   │              └──────────────┘
                 │ site/notify  │                     │
                 └──────┬───────┘                     │
                        │                             │
                        ▼                             ▼
                 ┌──────────────────────────────────────────┐
                 │  storage（SqliteRepository + StateStore） │
                 └──────────────────────────────────────────┘
                        ▲
                        │
                 ┌──────┴───────┐
                 │   domain     │  纯模型 / 打分 / 去重 / 覆盖
                 └──────────────┘

```

**做对了的依赖约束：**

-   `domain` 零 IO，可被所有层引用，也可以单独测试。
-   `collectors` 只依赖 `StateStore` 协议，不感知 SQLite 实现。
-   `delivery` 只读 domain 模型，不反向调用 collectors。
-   加源 = 一个类 + `@register_source` + 一行 import + config 开关（RSSHub 的 route registry 思路）。

**已经开始渗漏的地方：**

-   `watchlist` 在 `fetch()` 里做调度、熔断、关键词匹配、事件判定、归档、写快照——一个方法承担了 6 个职责。
-   `runner` 里出现 `getattr(src, "full_snapshot", False)` 这种按源特判。
-   `CatalogDiffSource` 把"抓取"和"读写基线"耦合在同一个 `fetch()` 中，导致并行时必须给每个 worker 一个独立 DB 连接。
-   `delivery/site.py` 直接解析 `state` 里 297KB 的 litellm JSON 来计算统计——展示层承担了领域计算。

* * *

## 3\. 逐层评审

| 层 | 现有实现 | 判定 | 问题 | 建议 |
| --- | --- | --- | --- | --- |
| **domain** | `models.py` / `scoring.py` / `dedup.py` / `coverage.py` / `brands.py` / `domains.py` | ✅ 方向正确 | 模型只有 `RawItem → Deal`，"厂商/活动/证据/信号"没有实体化；`Deal` 缺 `expires_at`/`kind`/`difficulty`/`confidence` | 保留纯函数；新增 `Provider`/`Offer`/`Evidence`/`Signal` 模型与 `lifecycle.py` |
| **contracts** | ❌ 不存在 | ⚠️ 缺失 | 源输出、JSON 载荷、配置都没有 schema；前端字段靠约定 | 新增 Pydantic v2 模型 + JSON Schema；源用 `CollectorResult` |
| **collectors** | 11 个源 + 注册表 + CatalogDiff + watchlist | ⚠️ 混合职责 | "发现"与"监控"共用 `RawItem`；fetch 内写状态；watchlist 300 行巨方法 | 拆 `DiscoverySource`（产出 Offer 候选）与 `SignalSource`（产出页面变化）；fetch 只做 IO，状态提交回主线程 |
| **scheduler** | ❌ 藏在 watchlist | ⚠️ 边界错误 | 目录源每轮全跑、页面源自己算 due；runner 不知道调度 | 独立 `scheduler/due.py`：`sources.next_run_at` + `pages.next_check_at` + tier + 熔断 |
| **pipeline** | `runner.py` / `enroll.py` | ✅ 编排清晰 | 特判多、过期与抓取耦合、收编写文件 | 拆 `resolve.py`（实体解析）、`lifecycle.py`（状态机）、`runner.py`（纯编排） |
| **storage** | 裸 `sqlite3` + `schema.sql` + 手工迁移 | ⚠️ 可用但脆 | `state` 是影子库；`snapshots` 同时承担内容/调度/健康；无外键；迁移靠手写 ALTER | SQLAlchemy 2.0 + Alembic；拆 `pages`/`page_state`/`signals`/`cursors` |
| **delivery** | Jinja SSR + Vue 模板 + 内联 JSON + Atom | ⚠️ 双份真相 | SSR 与 Vue 模板重复 ~350 行；467KB 单页；无分页；静态站反馈不可用 | 单份 Vite+Vue3+TS；JSON 分片；可选 FastAPI/Worker |
| **infra** | config/http/proxy/providers\_store | ✅ 本轮已加固 | config.local 不合并 config.toml；无 Pydantic 校验 | Pydantic Settings；配置合并语义明确 |
| **cli/server** | argparse + stdlib http | ✅ 零依赖 | API 能力弱、无 OpenAPI、无鉴权 | 保留 CLI；`serve` 可迁 FastAPI（可选） |
| **observability** | `print` + `runs` 表 | ⚠️ 不足 | 无结构化日志、无指标、无告警 | `structlog` + `metrics_daily` + Telegram/Issue 告警 |
| **tests** | 15 文件 / 1,466 行 | ⚠️ 偏解析器 | 缺源契约、端到端、渲染快照、性能基准 | contract + integration + snapshot + coverage gate |

### 3.1 三个结构性债务（按优先级）

#### 债务 1：没有实体层（最严重）

```python
# 现状
Deal(provider="DeepInfra", amount_hint="$1,000 in credits", status="new")

```

-   `provider` 是字符串 → `DeepInfra` / `deepinfra` / `deepinfra.com` 三种写法无法归并。
-   `amount_hint` 是自由文本 → 无法按金额排序/筛选（前端只能正则猜）。
-   没有 `expires_at` → 无法回答"什么时候截止"。
-   没有 `evidence` 表 → 一个活动只有一个 `evidence` 字符串，多来源证据丢失（`also_seen_in` 只是来源名）。
-   aicredits 明明解析了 `Expires At` / `Difficulty` / `Category`，却没有字段可存。

**这不是"再加几个字段"，而是数据模型少了一层。** 所有下游（去重、筛选、通知、API）都被这一层卡住。

#### 债务 2：状态与调度边界错误

-   `state` 表：`litellm:prices`（297KB JSON）、`modelsdev:providers`（24KB）等，本质是**不可查询的基线库**。
-   `snapshots` 表：`content_hash`（内容）、`promo_keywords`（业务）、`fail_count`（健康）、`tier/next_check_at`（调度）四类状态挤在一行。
-   `watchlist.fetch()`：抓取 + 调度 + 判定 + 归档 + 写库。

结果是：任何一处逻辑变化都要改 `watchlist.py` 这个 300 行方法；并行抓取被迫给每个 worker 开独立 DB 连接；新增信号源只能复制这套逻辑。

#### 债务 3：发布层与数据层耦合

-   `build_site()` 读 SQLite → 直接内联全量 JSON → 生成 467KB 单页。
-   `monitors` 的逐日 band、`source_vendors` 的 88KB 名单、`deals` 的 185KB 证据，全部塞进首屏。
-   静态 Pages 没有后端，反馈按钮不可用；`localStorage` 只能存主题。
-   `data.json` 是事实上的 API，但没有版本、没有 schema、没有分页。

* * *

## 4\. 同类项目调研（GitHub）

| 项目 | 定位 | 架构要点 | 对本项目的借鉴 |
| --- | --- | --- | --- |
| [changedetection.io](https://github.com/dgtlmoon/changedetection.io) | 通用网页变更监控 | Flask + 队列 worker + 每个 watch 独立 JSON（2026 重构为 `uuid/watch.json`）+ 可选 Playwright + 多通知渠道 + 插件 | watch 级配置、队列、可插拔 datastore、通知矩阵；**不要**学它的 JSON 存储（我们已有 SQLite） |
| [RSSHub](https://github.com/DIYgod/RSSHub) | 通用 RSS 生成 | Hono + 路由注册表（namespace/route 元数据）+ 中间件（缓存/参数/反盗链）+ 无状态 | 源注册表的元数据化（maintainers/example/categories）；请求级缓存；**不要**学它的无状态（我们需要历史） |
| [Miniflux](https://github.com/miniflux/v2) | RSS 阅读器 | Go + Postgres + 内部 scheduler + ETag/If-Modified-Since + entry hash + tombstone + 多格式 adapter | **最值得借鉴**：条件请求、hash 去重、tombstone 防重导入、feed 级健康、极简依赖 |
| [ai-resource-radar](https://github.com/ai-resource-radar/ai-resource-radar) | 免费 AI 资源/价格雷达 | 确定性采集（无 AI/无 key）+ 23 源 adapter + 每日/每周 + 证据/验证时间 + 变更检测 + 双语站点/RSS | **最接近的竞品**：结构化字段（配额/重置/国家/绑卡/领取步骤）、`last_verified`、变更类型（新增/变化/移除/即将到期）、开源数据 |
| [opentoken](https://github.com/lfxiui/opentoken) | AI credits 目录 | YAML 数据 + PR 贡献 + 最后验证时间 | 数据即代码、社区贡献、时效标注 |
| [agentdeals](https://github.com/robhunter/agentdeals) | 开发者 free tier 目录 | 1,400+ 厂商 + 新鲜度 API + MCP server | 新鲜度可度量、MCP/API 作为分发渠道 |
| [grandet](https://github.com/hanzohanzhe/Grandet) | API 价格比较 | 价格/免费额度 + MCP + 来源与观察时间 | "免费额度 + 价格 + 来源日期"的产品化表达 |

### 4.1 调研结论

1.  **"目录 + 官网监控 + 证据 + 时效"这个组合是成立且有竞品的**，本项目并不偏离方向。
2.  竞品普遍比本项目多三样东西：
    -   **结构化字段**（配额、重置周期、国家、绑卡、领取步骤、难度）；
    -   **验证时间/证据链**（每条数据可追溯到最后一次确认）；
    -   **变更语义**（新增、条款变化、移除、即将到期），而不只是"出现/消失"。
3.  它们普遍**不**使用重量级编排框架：[changedetection.io](http://changedetection.io) 用队列 + 每 watch 配置；Miniflux 用内部 scheduler；ai-resource-radar 用确定性 adapter + 每日/每周 cron。**这印证了方案 A 的选择。**
4.  分发层正在从"网页"扩展到 **RSS + JSON API + MCP**（agentdeals / grandet）。这是本项目的差异化机会，但应在数据模型稳定之后做。

### 4.2 调度器选型调研

| 方案 | 适用 | 结论 |
| --- | --- | --- |
| 自研 `next_check_at` + cron | 单机、任务数量中等、需要精细控制 | ✅ 当前已实现，继续保留 |
| APScheduler | 常驻进程内的 cron/interval + 持久化 job store | ⚠️ 仅当 `radar serve` 变成 24h 常驻才考虑 |
| Prefect | Python 函数式流程、重试/缓存/UI | ❌ 个人项目过重；需要额外 runtime |
| Dagster | 资产化数据平台、血缘/分区 | ❌ 概念成本高，适合多团队 |
| Airflow | 大规模批处理 DAG | ❌ 明确过重 |
| Celery / Redis | 分布式任务队列 | ❌ 没有高并发/长任务需求 |

调研来源一致指出：**"几个 cron 任务"用 Dagster/Prefect 是 overkill**；单机静态站 + SQLite 的正确形态是"自研轻调度 + 明确的运行记录"。

* * *

## 5\. 现有设计的合理性评分

| 维度 | 分数 | 判断 |
| --- | --- | --- |
| 分层与依赖方向 | 8/10 | 优于同类个人项目；domain 零 IO 是亮点 |
| 源适配器模式 | 8/10 | `@register_source` + 协议 + fixture 测试，扩展成本低 |
| 数据模型 | 3/10 | 缺 provider/offer/evidence/lifecycle，是最大短板 |
| 状态与调度边界 | 4/10 | 调度藏在源里，state 是影子库 |
| 存储与迁移 | 5/10 | SQLite 选型合理，但缺 ORM/迁移框架/表职责拆分 |
| 发布与前端 | 4/10 | 双份 UI、全量内联、静态站无反馈 |
| 可观测性 | 3/10 | print + 表，无告警/指标 |
| 工程化 | 5/10 | 有测试，缺 lint/type/lock/覆盖率和契约测试 |
| 合规与安全 | 7/10 | 无 XSS、密钥走 env；缺 robots/ETag/限速（部分已补） |

**综合：5.2/10。方向正确，底座需要一次结构性升级。**

* * *

## 6\. 候选架构

### 方案 A：演进式重构（推荐）

保留 Python 单体、SQLite、静态发布；重做领域模型、调度边界、发布契约。

```
Trigger → Scheduler → Collectors → Normalize → Resolve → Lifecycle
        → Repository → Publisher → Notifier → Observability

```

-   优点：风险最低、可逐阶段回滚、复用现有 4,300 行与 89 个测试。
-   缺点：仍然是单机单体，扩展性有限（但对个人工具足够）。
-   工期：8–12 周。

### 方案 B：数据资产化（Dagster / Prefect + Postgres）

把每个源、每个页面、每个 Offer 建模为 asset，用编排平台管理调度、重试、血缘。

-   优点：血缘/分区/重试/UI 完整，适合多人与复杂依赖。
-   缺点：概念与运维成本高；需要常驻 runtime；与 GitHub Actions 的"一次性运行"模型冲突。
-   调研结论：**几个 cron 任务用 Dagster 是 overkill**。
-   工期：12–16 周，且长期维护成本更高。

### 方案 C：服务化（FastAPI + Worker + Postgres + SPA）

拆成 API、采集 worker、通知 worker、前端 SPA，支持多用户/多租户。

-   优点：可产品化、可做 SaaS。
-   缺点：需要服务器/数据库/队列/鉴权/备份；个人项目定位不需要。
-   工期：16 周+。

### 对比

| 维度 | A 演进式 | B 数据资产化 | C 服务化 |
| --- | --- | --- | --- |
| 迁移风险 | 低 | 中高 | 高 |
| 运维成本 | 低 | 中 | 高 |
| 扩展性 | 中 | 高 | 高 |
| 与 Actions 兼容 | ✅ | ⚠️ | ❌ |
| 适合当前团队 | ✅ | ❌ | ❌ |
| 保留现有代码 | 80% | 40% | 30% |

**选 A。**

* * *

## 7\. 推荐架构 A

### 7.1 目标分层

```
┌────────────────────────────────────────────────────────────────────┐
│ contracts/   Pydantic 模型：RawItem / CollectorResult / Offer /     │
│              Signal / Evidence / SourceSpec / Payload（JSON Schema）│
├────────────────────────────────────────────────────────────────────┤
│ scheduler/   due(sources, pages, now) → jobs[]                      │
│              tier + next_check_at + 熔断 + 错峰                     │
├────────────────────────────────────────────────────────────────────┤
│ collectors/  DiscoverySource（目录/社区/价格）                      │
│              SignalSource（页面监控）                               │
│              只做 IO，返回 CollectorResult；不写业务库               │
├────────────────────────────────────────────────────────────────────┤
│ pipeline/    normalize → resolve → lifecycle → orchestrate          │
│              （纯函数为主，可在主线程串行执行）                       │
├────────────────────────────────────────────────────────────────────┤
│ storage/     SQLAlchemy 2 + Alembic                                 │
│              providers / offers / evidence / pages / page_state /   │
│              signals / cursors / runs / feedback / rules            │
├────────────────────────────────────────────────────────────────────┤
│ delivery/    site（静态分片）/ feed / notify / api（可选）           │
├────────────────────────────────────────────────────────────────────┤
│ infra/       config(Pydantic Settings) / http(ETag+限速+robots) /   │
│              proxy / logging / atomic                               │
└────────────────────────────────────────────────────────────────────┘

```

### 7.2 目标工作流

```
① Trigger
   cron / serve / CLI
        │
② Scheduler.due(now)
   sources.next_run_at <= now  → 目录/社区/价格任务
   pages.next_check_at <= now  → 页面监控任务（tier 1/2/3）
   排除：熔断中、fail_count>=3、disabled
        │
③ Collectors（并行，纯 IO）
   DiscoverySource.fetch() → CollectorResult(items, metrics, cache_headers)
   SignalSource.fetch()    → CollectorResult(signals, metrics, cache_headers)
   不写业务库；只返回数据与建议的 cache header
        │
④ Normalize
   URL 规范化 / 金额币种 / 日期 / 厂商 slug / 类型 / 地区
        │
⑤ Resolve
   provider 实体匹配（slug → 别名 → 域名）
   offer 匹配（精确 key → alias → 结构化指纹 → simhash）
   多来源证据合并
        │
⑥ Lifecycle
   active / expiring（<=7d）/ expired / unknown
   依据：expires_at、信号消失、目录删除、last_confirmed_at、源健康
        │
⑦ Repository（单事务/源）
   upsert offers + evidence + signals + page_state + cursors
   记录 run/source_runs/metrics
        │
⑧ Publisher
   data/meta.json + data/offers-*.json + data/pages-*.json
   feed.xml（全量 active + 即将截止）
        │
⑨ Notifier
   新增 / 即将截止 / 源故障（去重 + 静默时段）
        │
⑩ Observability
   structlog JSON + metrics_daily + 健康页 + 告警

```

### 7.3 两类源契约

```python
class CollectorResult(BaseModel):
    items: list[RawItem] = []
    signals: list[RawSignal] = []
    fetched: int = 0
    not_modified: bool = False
    cache: CacheHints = CacheHints()      # etag / last_modified
    metrics: dict[str, float] = {}
    errors: list[str] = []

class DiscoverySource(Protocol):
    spec: SourceSpec
    def fetch(self, ctx) -> CollectorResult: ...   # 只读网络/文件

class SignalSource(Protocol):
    spec: SourceSpec
    def fetch(self, ctx) -> CollectorResult: ...   # 只读网络/文件

```

**关键变化**：`fetch()` 不再写 `state`/`snapshots`。基线读写由 pipeline 在提交阶段完成，因此：

-   并行 fetch 不需要每个 worker 开数据库连接；
-   源可以独立测试（输入 fixture，输出 `CollectorResult`）；
-   新增源不会碰到调度/状态代码。

### 7.4 调度独立

```python
@dataclass
class Job:
    kind: Literal["source", "page"]
    id: int
    tier: int
    due_at: str
    priority: float

def due(now, sources, pages, rules) -> list[Job]:
    ...

```

-   目录/社区/价格源：`sources.next_run_at`（每日/每周）。
-   页面：`pages.next_check_at` + tier（1/7/30 天）。
-   熔断：`fail_count >= 3` → 7 天后。
-   首轮无 schedule：URL hash 错峰（已在 P0 实现，迁到 scheduler 层）。
-   排序：tier → 有信号 → next\_check\_at。

### 7.5 前端与发布

-   **单份** Vite + Vue 3 + TS；删除 Jinja SSR 重复段（保留 noscript 精简列表）。
-   构建产物：`index.html`（骨架 < 30KB）+ `assets/app.[hash].js` + `data/meta.json` + `data/offers-*.json` + `data/pages-*.json`。
-   前端按需加载：首屏只拉 `meta.json` + `offers-1.json`。
-   数据契约：`payload.schema.json`，版本号 `v1`；前端类型由 schema 生成。
-   `file://` 场景：生成 `standalone.html`（内联前 100 条 + KPI），作为降级。
-   可选：FastAPI 只读 API + MCP（参考 agentdeals），但排在数据模型稳定之后。

* * *

## 8\. 数据模型 v7（在 UPGRADE\_PLAN v5 草案上的增量）

`providers / pages / offers / offer_evidence / signals` 是早期草案；v7 已先落地其中 4 张实体表（`providers / provider_domains / provider_aliases / provider_sources`），字段定义见 `discovery/PROVIDER_ENTITY_v0.md`。后续增量：

| 增量 | 原因 |
| --- | --- |
| `offers.regions`（JSON） | 竞品普遍标注国家可用性；中国区用户尤其需要 |
| `offers.terms_hash` | 条款指纹：配额/限制变化但标题不变时也能识别"条款变更" |
| `offer_evidence.verified_at` | 区分"观察到"与"人工/规则确认"，支撑 `last_verified` |
| `page_state` 从 `pages` 拆出 | ETag/Last-Modified/hash/fail\_count 是调度状态，不是页面身份 |
| `cursors(source, key, value, version)` | 替代 `state` 表里的基线 JSON；可查询、可版本化、可回滚 |

### 8.1 表职责

| 表 | 职责 | 不做什么 |
| --- | --- | --- |
| `providers` | 厂商身份、别名、官网、相关性、状态 | 不存抓取状态 |
| `pages` | 页面身份：URL、label、provider、tier、enabled | 不存 ETag/hash |
| `page_state` | 抓取状态：etag、last\_modified、hash、fail\_count、last\_success、next\_check\_at | 不存业务信号 |
| `offers` | 活动身份与生命周期 | 不存抓取细节 |
| `offer_evidence` | 多来源证据、观察时间、验证时间 | 不重复 offer 字段 |
| `signals` | 页面变化事件（appeared/changed/disappeared） | 不直接生成 offer |
| `cursors` | 源基线/游标（目录 JSON、HN 时间戳） | 不混业务数据 |
| `runs/source_runs` | 运行与源健康 | — |
| `feedback` | 用户反馈（up/down/snooze） | — |
| `rules` | 关键词规则版本 | — |

### 8.2 事件语义（参考 ai-resource-radar）

```
offer.created      首次发现
offer.terms_changed 标题未变，但配额/绑卡/限制/截止变化（terms_hash）
offer.expiring      <= 7 天
offer.expired       截止/信号消失/目录删除
offer.removed       上游明确删除
signal.appeared / signal.disappeared / signal.changed
source.degraded / source.recovered

```

通知与前端都基于事件类型，而不是"new/updated"两个模糊状态。

* * *

## 9\. 关键设计决策（ADR）

| # | 决策 | 理由 | 放弃的方案 |
| --- | --- | --- | --- |
| ADR-1 | 保留 SQLite，SQLAlchemy 抽象 | 单用户、<100MB、零运维；ORM 保留切 PG 能力 | 立即迁 Postgres |
| ADR-2 | 不上 Airflow/Dagster/Prefect/Celery | 任务数量与团队规模不匹配；Actions 是一次性运行 | 编排平台 |
| ADR-3 | 源契约二分：Discovery / Signal | "发现活动"与"监控变化"语义不同，混用导致特判 | 单一 RawItem 契约 |
| ADR-4 | fetch 只做 IO，状态提交回主线程 | 并行不需要每 worker 独立 DB；源可独立测试 | fetch 内写 state/snapshot |
| ADR-5 | 调度独立 scheduler 层 | runner 不应知道 tier/熔断/错峰 | 调度藏在 watchlist |
| ADR-6 | `state` JSON → `cursors` 表 | 可查询、可版本化、可回滚 | 继续用 state 字符串 |
| ADR-7 | Offer/Evidence/Signal 实体化 | 支撑生命周期、证据链、变更语义、API | 继续用 Deal 扁平表 |
| ADR-8 | 条件请求 + per-host 限速 + robots | 参考 Miniflux/changedetection；降低被封风险与带宽 | 全量重抓 |
| ADR-9 | 前端单份 Vite + Vue 3 + TS | 消除双份 UI；类型由 schema 生成 | 继续 Jinja+Vue 双份 |
| ADR-10 | 静态分片 + 可选 API | 首屏 <100KB；Pages 零成本；API 后置 | 全量内联单页 |
| ADR-11 | 反馈走 Cloudflare Worker + D1（Issue 降级） | Pages 无后端；反馈是高价值信号 | 只支持 serve 模式反馈 |
| ADR-12 | 不做 LLM 判定/摘要 | 成本、不可复现、隐私；规则+结构化足够 | 每条数据 LLM 摘要 |
| ADR-13 | 配置分层：运行参数 TOML / 实体入库 / secrets env | 避免 providers.toml 既是配置又是数据 | 继续用 TOML 存实体 |
| ADR-14 | API/MCP 延后到数据模型稳定后 | 分发层依赖稳定契约 | 先做 API 再做模型 |

* * *

## 10\. 迁移路线（5 阶段 / 约 9–12 周）

> 每阶段独立可交付、可回滚；不要求一次性切完。

### 阶段 1：契约冻结（1 周）

-   新增 `contracts/`：`RawItem`、`CollectorResult`、`Offer`、`Evidence`、`Signal`、`SourceSpec`、`Payload`。
-   每个现有源加一个 schema 断言测试（用现有 fixtures）。
-   `radar schema export` 输出 JSON Schema。
-   **验收**：`pytest tests/contract` 全绿；payload schema 可被前端生成类型。

### 阶段 2：存储重构（2 周）

-   SQLAlchemy 2.0 + Alembic；v7 表；`cursors` 替代 `state`。
-   `scripts/migrate_v6_to_v7.py`：幂等、对账、备份。
-   双写/视图过渡 2 周。
-   **验收**：offers/evidence/pages/signals 对账通过；回滚演练成功；查询 P95 <50ms。

### 阶段 3：调度与采集边界（2 周）

-   `scheduler/due.py`：sources/pages/tier/熔断/错峰。
-   `DiscoverySource` / `SignalSource` 拆分；`fetch` 只 IO。
-   HTTP：ETag/If-Modified-Since、per-host 令牌桶、robots 缓存、429 退避。
-   **验收**：新增源 ≤1 文件 + 1 行注册 + 1 fixture；304 命中 >60%；全量 <8min。

### 阶段 4：发布与前端（2 周）

-   Vite + Vue 3 + TS；删除 Jinja SSR 重复段。
-   分片 JSON + payload schema 版本；`standalone.html` 降级。
-   首屏预算：HTML <100KB、JS <150KB gzip。
-   **验收**：Lighthouse LCP <2s；模板单份；无全量内联。

### 阶段 5：可观测、反馈、API（2 周）

-   structlog JSON + `metrics_daily` + 健康页 + Telegram/Issue 告警。
-   Cloudflare Worker + D1 反馈（或 GitHub Issue 表单降级）。
-   可选：FastAPI 只读 API + MCP。
-   **验收**：源连续失败 2 次告警；Pages 可反馈；API 契约测试通过。

### 10.1 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 迁移数据丢失 | 备份 + 对账 + 双写 + 回滚脚本 |
| 契约变更影响前端 | schema 版本号 + 生成类型 + 快照测试 |
| 源适配器重写引入回归 | 现有 fixtures 作为契约基线，逐源切换 |
| 前端重构视觉回归 | 截图快照 + 灰度发布 |
| 工期超支 | 阶段 5 可延后；阶段 1–3 是核心 |

* * *

## 11\. 技术选型清单

| 领域 | 选择 | 理由 | GitHub |
| --- | --- | --- | --- |
| 数据契约 | Pydantic v2 | 类型/校验/JSON Schema 一体 | [pydantic/pydantic](https://github.com/pydantic/pydantic) |
| ORM/迁移 | SQLAlchemy 2.0 + Alembic | 成熟、可切 PG、迁移可回滚 | [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) · [sqlalchemy/alembic](https://github.com/sqlalchemy/alembic) |
| HTTP | httpx（AsyncClient） | 超时/代理/HTTP2/异步 | [encode/httpx](https://github.com/encode/httpx) |
| HTML 解析 | trafilatura + selectolax | 正文提取与快速选择器 | [adbar/trafilatura](https://github.com/adbar/trafilatura) · [lexbor/selectolax](https://github.com/lexbor/selectolax) |
| RSS | feedparser | 兼容性好 | [kurtmckee/feedparser](https://github.com/kurtmckee/feedparser) |
| 金额/日期 | 标准库 + 自研 normalize | 规则可解释，不引重依赖 | — |
| 去重 | simhash + 现有金额护栏 | 零依赖、可解释 | 自研 |
| 调度 | 自研 `next_check_at` | 与 Actions 一次性运行匹配 | — |
| 常驻调度（可选） | APScheduler | 仅当 serve 变 24h 常驻 | [agronholm/apscheduler](https://github.com/agronholm/apscheduler) |
| 日志 | structlog | 结构化 JSON、上下文 | [hynek/structlog](https://github.com/hynek/structlog) |
| 测试 | pytest + pytest-cov + respx | 单测/覆盖/HTTP mock | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) · [lundberg/respx](https://github.com/lundberg/respx) |
| Lint/Type | ruff + mypy | 快、统一 | [astral-sh/ruff](https://github.com/astral-sh/ruff) · [python/mypy](https://github.com/python/mypy) |
| 依赖管理 | uv | 锁文件、速度快 | [astral-sh/uv](https://github.com/astral-sh/uv) |
| 前端 | Vite + Vue 3 + TS | 现有 Vue 知识可复用；交互复杂 | [vitejs/vite](https://github.com/vitejs/vite) · [vuejs/core](https://github.com/vuejs/core) |
| 前端测试 | Vitest + Playwright | 单测 + E2E | [vitest-dev/vitest](https://github.com/vitest-dev/vitest) · [microsoft/playwright](https://github.com/microsoft/playwright) |
| 静态发布 | Cloudflare Pages | 免费、CDN、可回滚 | [cloudflare/workers-sdk](https://github.com/cloudflare/workers-sdk) |
| 反馈/数据 | Cloudflare D1 / R2 | Pages 原生、零运维 | 同上 |
| 可选 API | FastAPI | OpenAPI、类型、测试 | [fastapi/fastapi](https://github.com/fastapi/fastapi) |
| 可选内容站 | Astro | 只读内容型页面；不适合复杂筛选 | [withastro/astro](https://github.com/withastro/astro) |

### 11.1 明确不引入

-   ❌ Airflow / Dagster / Prefect / Temporal
-   ❌ Celery / Redis / RabbitMQ
-   ❌ Kubernetes / 微服务
-   ❌ Scrapy（同步、重；httpx + 简单并发足够）
-   ❌ 直接二次开发 [changedetection.io](http://changedetection.io)（Flask + JSON 存储 + 通用 watch 模型，与本项目数据模型耦合成本高）
-   ❌ LLM 逐条判定
-   ❌ 多用户/登录/SaaS

* * *

## 12\. 验收指标（架构级）

| 指标 | 目标 |
| --- | --- |
| 新增源成本 | ≤ 1 个文件 + 1 行注册 + 1 个 fixture，≤ 30 分钟 |
| 源契约覆盖 | 每个源都有 schema 断言 + 真实 fixture |
| 数据契约版本 | payload/schema 带版本号，前端类型由 schema 生成 |
| 单轮全量 | < 8 分钟（11 源 + 到期页面） |
| 304 命中率 | \> 60% |
| 首屏体积 | HTML <100KB，JS <150KB gzip |
| 数据新鲜度 | 每个源可查询 `last_success_at`；页面横幅可解释 |
| 证据链 | 每个 offer ≥1 条 evidence，含 observed\_at/verified\_at/source |
| 迁移 | 每次 schema 变更可回滚，迁移有对账 |
| 测试 | domain/pipeline 覆盖率 ≥80%；contract + snapshot + e2e 存在 |
| 告警 | 源连续失败 2 次 / 数据 24h 未更新 → 可送达 |

* * *

## 13\. 最终建议

1.  **不要重写。** 现有分层与源适配器模式是资产；问题集中在数据模型和边界。
2.  **先做契约与模型（阶段 1–2），再做调度（阶段 3），最后做前端（阶段 4）。** 前端重构如果先做，会在数据模型变化时返工两次。
3.  **把"证据 + 验证时间 + 变更类型"作为产品核心**，这是与 ai-resource-radar / agentdeals 竞争的关键，而不是"多接几个源"。
4.  **保持零运维**：SQLite + 静态站 + Actions + 可选 Cloudflare，不引入需要常驻的组件。
5.  **把 API/MCP 留到最后**：数据契约稳定后，它是低成本的分发放大器；在此之前做只会固化错误模型。

* * *

*本文档基于 2026-11 的代码与 GitHub 调研。实施顺序以 `docs/NEXT_STEPS.md` 为准，本文档负责解释“为什么这样改”。*