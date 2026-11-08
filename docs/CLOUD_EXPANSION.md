# 云资源扩展设计（CLOUD_EXPANSION）

> 状态：**已实现 v1**（2026-11-08）｜schema v10｜120 项测试全绿
> 基线：`src/radar` 40 个 Python 文件 / 4,041 行（扩展前）
> 定位：本文档回答「为什么扩、扩成什么样、按什么顺序做」；具体进度与数字以 `STATE.md` 为准。

---

## 1. 背景与目标

### 1.1 现状

`promo-radar` 目前只覆盖 **AI API 厂商的促销信息**（注册送额度、绑卡送额度、free tier）。数据模型是
`RawItem → Deal → Offer`，判定逻辑是「AI 促销关键词加权」，站点是「活动卡片 + 表格 + 时间线」。

它能回答：*哪家 AI 厂商现在送多少额度？*

它不能回答：

- 哪家云厂商有**永久免费**的 VPS / 对象存储 / 数据库？
- 哪个 PaaS 能**免费部署**一个常驻项目（Vercel / Render / Fly / Koyeb / Cloudflare）？
- 免费额度**要不要绑卡、要不要实名、有没有时限**？
- 某个 VPS 特价**补货了没有、折合月价多少**？

### 1.2 目标

把项目从「AI 促销雷达」扩展为 **「开发者可白嫖云资源雷达」**：

> 系统性收集 **可免费获取、可用于部署项目** 的云资源信息，并给出结构化、可筛选、可追溯的证据。

「可部署」是核心判据。以下都属于目标范围：

| 品类 | 典型资源 |
|---|---|
| 计算（VM/VPS） | Oracle Always Free、AWS/GCP/Azure 免费层、低价 KVM 小鸡、RackNerd 特价 |
| PaaS / Serverless | Vercel、Netlify、Render、Fly.io、Koyeb、Railway、Cloudflare Workers、Deno Deploy |
| 存储 / 对象存储 | Cloudflare R2、Backblaze B2、Supabase Storage、各类免费网盘与图床 |
| 数据库 | Supabase、Neon、Turso、Upstash、MongoDB Atlas、Aiven 免费层 |
| CDN / 网络 | Cloudflare、jsDelivr、免费隧道与内网穿透 |
| 开发者配套 | 免费 CI 分钟数、免费监控、免费邮件额度、免费域名/证书 |

**本次收敛边界（已决策，不再摇摆）：**

| 决策 | 取值 | 含义 |
|---|---|---|
| 地域 | **国内外双线** | 海外目录 + 国内云厂商免费试用；国内条目带 `regions=["CN"]`，站点可按地区筛选 |
| 频率 | **每天一轮** | 与现有 `radar.yml` 一致，不新增每小时 workflow |
| 部署 | **GitHub + Pages 静态站** | 不引入常驻服务、数据库服务、Worker 运行时 |
| 后端 | **不做 Cloudflare D1** | 领取跟踪走浏览器本地存储 + JSON 导出（见 10.3） |
| 内容 | **先做 free 资源** | 不做全量比价、不做付费套餐库 |
| 产品视角 | **「我要部署一个网站」** | 站点按部署场景组织，而不只按厂商罗列（见 7.8） |

### 1.3 非目标（明确不做）

- ❌ 不做常规套餐的**全量比价**（AWS EC2 全机型价格、VPSBenchmarks 跑分对比）。仅当某套餐进入「免费/特价」语义时才收录。
- ❌ 不做**付费项目**：实习、奖学金、研究基金、投资计划、会议门票。只收「可免费获取的资源」。
- ❌ 不做「注册即送」之外的**灰色渠道**（共享账号、破解、代实名）。
- ❌ 不做自动注册/自动领取。工具只收集公开信息，领取动作由人完成。
- ❌ 不做多用户 SaaS、登录体系、付费墙。
- ⚠️ 国内云厂商**只收公开免费/试用页**，不绕过实名认证，不代注册；页面结构差异由配置化解析器兜底。
- ❌ **不做 Cloudflare D1 / Worker / 任何运行时后端**（见下方 D1 决策）。
- ❌ 不引入 Airflow / Celery / Postgres / 前端构建链（沿用 `ARCHITECTURE_REVIEW.md` 的 ADR-1/2/9/10）。

### 1.3.1 为什么现在不上 Cloudflare D1

**结论：能上，但当前不需要，收益 < 成本。**

D1 解决的是「运行时写入 + 多端同步」，而本项目的数据流是**构建时生成**：Actions 每天跑一轮，把结果写成静态 JSON，Pages 只读。整个链路上没有一个「用户写」的动作是必须落库的。

| 若引入 D1，需要新增 | 成本 |
|---|---|
| Cloudflare Worker（路由、CORS、鉴权） | 1 个新服务 + 部署流程 |
| D1 表结构与迁移 | 第二套 schema，与 SQLite 双份维护 |
| 身份识别（否则谁都能改数据） | 至少一个 token 或 GitHub OAuth |
| 前端从 `fetch(静态 json)` 改为 `fetch(Worker)` | 静态站降级路径要重写 |
| 本地开发要跑 `wrangler` | 破坏「双击 index.html 就能看」的零依赖体验 |

而它换来的只有一个功能：**领取状态跨设备同步**。这个功能用 `localStorage` + 导出/导入 JSON 就能覆盖 95% 的单人使用场景。

**触发条件（满足任意两条再考虑 D1）：**
1. 需要在手机、电脑、平板之间自动同步领取状态；
2. 需要多人共享同一份「已领/被拒」记录；
3. 需要在站点上收集公开反馈（点赞/纠错）并聚合统计；
4. 静态 JSON 体积超过 5MB，需要服务端分页/检索。

在此之前，D1 属于「为了架构先进而引入的运维负担」。

### 1.4 成功判据

| 维度 | 目标 |
|---|---|
| 覆盖面 | ≥ 120 家云/资源厂商，≥ 6 个品类 |
| 结构化率 | 收录条目中 ≥ 80% 带 `offer_type` + `eligibility`；≥ 60% 带 `resources` |
| 新鲜度 | 每条 offer 可查 `last_verified_at`；永久免费类 30 天内必复验 |
| 信噪比 | 站点首页「本周新增」中误报（非云资源/非免费）≤ 10% |
| 部署可用性 | 「部署一个静态站 / 带数据库的站 / 一个后端服务」三种场景，各能给出 ≥ 3 个当前可用的免费方案 |
| 成本 | 单轮全量 < 8 分钟；每天 1 轮，GitHub Actions < 400 分钟/月 |

---

## 2. 设计原则

1. **复用优先**：不新建第二套管线。所有云源仍走 `@register_source` + `RawItem` + 打分 + 去重 + SQLite + 静态站。
2. **免费语义优先于价格语义**：先答「能不能白嫖、有什么限制」，再答「多少钱」。因此不建 `Plan` 价格表，把规格与限制放进 `offers` 的结构化字段。
3. **配置驱动**：云厂商页面结构相似度高，用 `cloud_sources.toml` + 通用解析器覆盖，避免 50 个手写类。
4. **不猜**：解析不出的字段留空，原文进 `evidence`。宁可少一个字段，不可编一个数字。
5. **证据可追溯**：每个结构化字段都要能指回「哪个 URL、哪次抓取、哪段原文」。
6. **零 IO 的 domain**：新模型与归一化函数仍放 `domain/`，不碰网络与数据库。
7. **向后兼容**：v9 的 AI 数据不迁移、不重算；新增列全部带默认值。

---

## 3. 领域词汇（先统一语言）

| 词 | 含义 | 与现有概念的关系 |
|---|---|---|
| **Vertical** | 业务垂直领域：`ai_api` / `cloud` / `vps` / `paas` / `storage` / `database` / `cdn` / `devtool` | 新增，用于站点分栏与规则包选择 |
| **Category** | 资源品类（计算/存储/数据库/网络…），一个 Provider 可有多个 | 扩展 `providers.category` 单值为 `categories` 数组 |
| **Provider** | 服务提供方（Oracle、Vercel、RackNerd） | 复用现有 `providers` 四表 |
| **Offer** | 一个可获取的资源方案（「Oracle 永久免费 4 OCPU + 24G 内存」） | 复用 `offers`，扩展类型与结构化字段 |
| **OfferType** | 免费/优惠的类型（见 3.1） | 新增 |
| **Eligibility** | 获取门槛（绑卡、实名、学生、企业、地区） | 新增 JSON 字段 |
| **Resources** | 资源规格（vCPU/内存/磁盘/流量/时长） | 新增 JSON 字段 |
| **Terms** | 条款快照（规格 + 限制 + 门槛的指纹） | 新增 `terms_hash` |
| **Signal** | 供给或条款的变化事件（补货、售罄、新地区、条款变更、降价） | 新增表 |
| **Claim** | 我对某个 offer 的领取状态（想领/已领/被拒/过期） | 新增表，个人侧数据 |
| **Evidence** | 某条 offer 在某个来源被看到的记录 | 复用 `offer_evidence` |

### 3.1 OfferType 取值

| 值 | 含义 | 例子 | 默认有效期语义 |
|---|---|---|---|
| `always_free` | 永久免费，长期可用 | Oracle Always Free、Cloudflare 免费版 | 无截止，靠复验维持 |
| `free_tier` | 免费层（有额度上限，可长期用） | Vercel Hobby、Supabase Free | 无截止，额度按月重置 |
| `trial` | 限时试用（注册后 N 天） | GCP $300 / 90 天 | `expires_at` = 领取日 + N 天 |
| `credits` | 赠金/额度（用完即止） | AWS Activate、各类 $5–$200 credits | 有金额与有效期 |
| `student` | 学生/教育认证专属 | GitHub Student Pack、Azure for Students | 需认证 |
| `startup` | 创业/加速器计划 | AWS Activate、Google for Startups | 需企业资质 |
| `oss` | 开源项目赞助 | Cloudflare OSS、MongoDB OSS | 需仓库证明 |
| `promo_code` | 优惠码/活动 | 黑五、优惠码、限时折扣 | 有活动截止 |
| `lifetime` | 终身/买断 | 终身授权、Lifetime VPS | 一次性 |
| `restock` | 补货/放货信号 | RackNerd 补货、Hetzner 开新机房 | 瞬时事件 |

> `restock` 不是独立 offer，而是 `signals.kind`。此处列出仅为说明语义边界：**活动是 Offer，供给变化是 Signal。**

---

## 4. 数据模型（v9 → v10）

### 4.1 迁移总则

- 全部为 **`ALTER TABLE ... ADD COLUMN`** + `CREATE TABLE`，不重建、不改名、不回填业务数据。
- 新列一律 `NOT NULL DEFAULT`，旧代码读写不受影响。
- `PRAGMA user_version` 从 `9` 升到 `10`，沿用 `repository._migrate()` 的幂等迁移方式。
- 回滚方式：`data/backup/radar-pre-v10.db` 快照 + 代码回退；新列可被旧代码忽略。

### 4.2 `providers` 扩展

```sql
ALTER TABLE providers ADD COLUMN vertical   TEXT NOT NULL DEFAULT 'ai_api';
ALTER TABLE providers ADD COLUMN categories TEXT NOT NULL DEFAULT '[]'; -- JSON: ["compute","storage"]
ALTER TABLE providers ADD COLUMN deploy_modes TEXT NOT NULL DEFAULT '[]'; -- JSON: ["vm","docker","git","serverless"]
ALTER TABLE providers ADD COLUMN free_tier_url TEXT NOT NULL DEFAULT '';
ALTER TABLE providers ADD COLUMN pricing_url   TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_providers_vertical ON providers (vertical);
```

- `vertical` 是**单值主归属**（一家厂商只归一个垂直），`categories` 是多品类标签。
- `deploy_modes` 用于「我能怎么部署」筛选：`vm` / `docker` / `git` / `serverless` / `k8s` / `static`。
- 现有 370 家 AI 厂商默认 `vertical='ai_api'`，行为不变。

### 4.3 `offers` 扩展

```sql
ALTER TABLE offers ADD COLUMN vertical   TEXT NOT NULL DEFAULT 'ai_api';
ALTER TABLE offers ADD COLUMN offer_type TEXT NOT NULL DEFAULT 'credits';
ALTER TABLE offers ADD COLUMN category   TEXT NOT NULL DEFAULT '';
ALTER TABLE offers ADD COLUMN resources  TEXT NOT NULL DEFAULT '{}'; -- JSON
ALTER TABLE offers ADD COLUMN limits     TEXT NOT NULL DEFAULT '{}'; -- JSON
ALTER TABLE offers ADD COLUMN eligibility TEXT NOT NULL DEFAULT '{}'; -- JSON
ALTER TABLE offers ADD COLUMN regions    TEXT NOT NULL DEFAULT '[]'; -- JSON
ALTER TABLE offers ADD COLUMN claim_steps TEXT NOT NULL DEFAULT '';
ALTER TABLE offers ADD COLUMN difficulty  INTEGER NOT NULL DEFAULT 2; -- 1..5
ALTER TABLE offers ADD COLUMN expires_at       TEXT NOT NULL DEFAULT '';
ALTER TABLE offers ADD COLUMN terms_hash       TEXT NOT NULL DEFAULT '';
ALTER TABLE offers ADD COLUMN last_verified_at  TEXT NOT NULL DEFAULT '';
ALTER TABLE offers ADD COLUMN verified_by       TEXT NOT NULL DEFAULT 'rule';
ALTER TABLE offers ADD COLUMN status_reason     TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_offers_vertical ON offers (vertical);
CREATE INDEX IF NOT EXISTS idx_offers_type     ON offers (offer_type);
CREATE INDEX IF NOT EXISTS idx_offers_expires  ON offers (expires_at);
```

### 4.4 三个 JSON 字段的精确形状

**`resources`**（只放能比较的数字，单位固定）：

```json
{
  "vcpu": 4,
  "ram_gb": 24,
  "disk_gb": 200,
  "disk_type": "nvme",
  "storage_gb": 10,
  "bandwidth_gb": 1000,
  "runtime_hours_month": 750,
  "requests_month": 100000,
  "build_minutes_month": 600,
  "regions_count": 3,
  "ipv4": 1
}
```

**`limits`**（额度与周期）：

```json
{
  "credit_usd": 300,
  "valid_days": 90,
  "renew": "monthly",
  "concurrency": 1,
  "seats": 1,
  "sleep_after_minutes": 15,
  "egress_free_gb": 100
}
```

**`eligibility`**（获取门槛）：

```json
{
  "card_required": false,
  "card_hint": "需验证 $1 但退回",
  "real_name": false,
  "phone": true,
  "student": false,
  "company": false,
  "github_account": true,
  "region_block": ["CN"],
  "vpn_block": true
}
```

> 约定：**只有抓到了证据才写字段**。抓不到就省略该键，不写 `false`。`card_required: false` 必须来自明确的 "no credit card required" 文案，不能由「没提到」推断。

### 4.5 新增表

```sql
-- 条款快照历史：terms_hash 变化时留档，支撑「条款变更」事件与人工复核
CREATE TABLE IF NOT EXISTS offer_terms_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id       INTEGER NOT NULL,
    terms_hash     TEXT NOT NULL,
    snapshot       TEXT NOT NULL DEFAULT '{}', -- {resources, limits, eligibility}
    changed_fields TEXT NOT NULL DEFAULT '[]',
    changed_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_terms_offer ON offer_terms_history (offer_id, changed_at);

-- 信号事件：供给与条款变化，不等于新 offer
CREATE TABLE IF NOT EXISTS signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,   -- restock|sold_out|new_region|price_drop|terms_changed|appeared|disappeared
    vertical     TEXT NOT NULL DEFAULT 'ai_api',
    provider_id  INTEGER,
    offer_id     INTEGER,
    source       TEXT NOT NULL DEFAULT '',
    page_url     TEXT NOT NULL DEFAULT '',
    payload      TEXT NOT NULL DEFAULT '{}',
    observed_at  TEXT NOT NULL,
    notified_at  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_signals_time ON signals (observed_at);
CREATE INDEX IF NOT EXISTS idx_signals_kind ON signals (kind, observed_at);

-- 个人领取跟踪：白嫖场景的核心差异化功能
CREATE TABLE IF NOT EXISTS claims (
    offer_id    INTEGER PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT 'todo'
                CHECK (state IN ('todo', 'claimed', 'rejected', 'expired', 'skipped')),
    claimed_at  TEXT NOT NULL DEFAULT '',
    expires_at  TEXT NOT NULL DEFAULT '',
    account     TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);
```

### 4.6 不做 `plans` 表的理由

初版设计曾计划 `plans / price_points` 支撑全量比价。按本次范围（免费白嫖优先）砍掉，理由：

1. 免费资源的「规格」是**少数几个数字**，用 `offers.resources` 足够筛选；
2. 全量 SKU 需要处理计费维度（按秒/按小时/阶梯/出站流量），成本远高于收益；
3. 若未来确需比价，可在 `offers` 之上加 `plans(offer_id, plan_code, price)`，不需要改现有结构。

**唯一保留的价格能力**：`payg_price_usd` 可放进 `limits`，用于「免费额度用完后大概多少钱」。

---

## 5. 契约（对现有模型的增量）

### 5.1 `RawItem`（`domain/models.py`）

```python
@dataclass
class RawItem:
    source: str
    title: str
    url: str = ""
    provider: str | None = None
    amount_hint: str | None = None
    card_required_hint: bool | None = None
    evidence: str = ""
    published_at: datetime | None = None
    key_override: str | None = None
    force_keep: bool = False
    # v10 新增（全部有默认值，旧源不需要改）
    vertical: str = "ai_api"
    offer_type: str = "credits"
    category: str = ""
    resources: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    eligibility: dict = field(default_factory=dict)
    regions: list[str] = field(default_factory=list)
    expires_at: str = ""
    claim_steps: str = ""
    difficulty: int = 2
```

### 5.2 采集器契约（分两族，不破坏现有 `Source` 协议）

```python
class Source(Protocol):
    name: str
    def fetch(self, ctx: FetchContext) -> list[RawItem]: ...   # 现状，保留

class ConfigDrivenSource(Source, Protocol):
    """配置驱动源：解析逻辑共用，差异全在 cloud_sources.toml。"""
    spec: "SourceSpec"
```

```python
@dataclass
class SourceSpec:
    name: str
    vertical: str
    category: str
    mode: str                      # html | json | markdown | rss
    url: str
    interval_hours: int = 24
    force_keep: bool = True        # 免费资源目录条目跳过阈值过滤
    selectors: dict = field(default_factory=dict)
    fields: dict = field(default_factory=dict)
    spec_regex: dict = field(default_factory=dict)   # 从文本抽 vcpu/ram/disk/...
    defaults: dict = field(default_factory=dict)     # offer_type/eligibility 兜底
```

### 5.3 输出契约（payload）

`data.json` 增加三个顶层键，旧键不变：

```json
{
  "schema_version": "v10",
  "verticals": [
    {"id": "ai_api", "label": "AI 促销", "active": 213},
    {"id": "cloud",  "label": "云计算",  "active": 42},
    {"id": "paas",   "label": "部署平台", "active": 18}
  ],
  "offers": [ ... ],
  "signals": [ ... ],
  "claims":  [ ... ]
}
```

`deals` 保留，作为 AI 侧的兼容视图（前端可逐步切换）。

---

## 6. 架构与数据流

### 6.1 分层（在现有七层上做最小增量）

```
domain/      models(+vertical/offer_type/resources)  normalize_units()  rulesets/
collectors/  base.py（不变）
             cloud/
               ├─ free_for_dev.py        # Markdown 目录 diff
               ├─ vendor_free_page.py    # 配置驱动：官方免费层页
               ├─ paas_pricing.py        # 配置驱动：PaaS 定价页
               ├─ vps_specials.py        # 配置驱动：特价页
               └─ leb_rss.py             # 社区 RSS
infra/       cloud_config.py（cloud_sources.toml 加载 + 校验）
             ratelimit.py（per-host 令牌桶，M5）
pipeline/    runner.py（+ --vertical 过滤 + interval_hours 到期判断）
             resolve.py（新：provider 解析 + offer 指纹）
storage/     repository.py（+ offers/signals/claims 读写）
delivery/    site.py（+ vertical 分栏 + 云资源表格视图）
```

### 6.2 端到端数据流（输入 → 输出）

```
① 触发
   radar run --vertical cloud   或   radar.yml 的云源步骤（每日一轮）
        │
        ▼
② 到期判断（interval_hours）
   state["next_run_at:<source>"] <= now 才抓；未到期跳过并计入 skipped
        │
        ▼
③ 采集（并行，故障隔离）
   free_for_dev  : GET README.md  → 解析条目 → markdown diff → RawItem[]
   vendor_free   : GET 页面       → CSS 选择器 → 正则抽规格 → RawItem[]
   paas_pricing  : GET 页面/JSON  → 同上
   leb_rss       : GET feed       → 逐条 → RawItem[]
        │
        ▼
④ 归一化（纯函数，domain）
   单位换算（GB/TB/MB、$/年 → $/月、小时 → 月）
   offer_type 归一（free/免费/always free → always_free）
   eligibility 归一（no credit card required → card_required=false）
   provider 归一（域名/别名 → provider_slug）
        │
        ▼
⑤ 判定
   score_item(ruleset[vertical])
   强规则：免费额度 > 0 且（免绑卡 或 永久有效）→ 直接保留
   offer 指纹：sha1(provider_slug | offer_type | 归一化条款)
        │
        ▼
⑥ 去重与合并
   精确：offer_key（指纹）
   跨源：canonical_url → 标题相似度 0.80 + 金额/规格护栏
   证据：同一 offer 多来源写入 offer_evidence
        │
        ▼
⑦ 生命周期
   always_free/free_tier：last_seen 刷新；30 天未复验 → stale
   trial/credits：expires_at 到期 → expired
   promo_code：活动截止 → expired
   条款变化：terms_hash 变 → signals(terms_changed)
        │
        ▼
⑧ 落库（单事务/源）
   offers / offer_evidence / offer_terms_history / signals / provider_sources
        │
        ▼
⑨ 发布
   data.json（v10 契约）+ index.html（分栏）+ atom-cloud.xml
        │
        ▼
⑩ 通知
   只推：新增 always_free / credit ≥ $50 / 补货；不推：常规 trial
```

---

## 7. 源清单与接入优先级（国外 · 每日 · 可部署）

> 说明：URL 均为公开页面；标注「待验证」的表示路径需在实现时先做 200 探测。
> 「方式」对应解析器：`md` = Markdown 目录 diff，`cfg-html` = 配置化 HTML，`json` = JSON，`rss` = 订阅源。
> 排序原则：① 直接回答「能不能免费部署网站」 → ② 国外可访问 → ③ 解析成本低 → ④ 每日一轮内跑得完。

### 7.1 P0：目录型金矿（1 个源覆盖上百家）

| 源 | URL | 方式 | 产出 | 备注 |
|---|---|---|---|---|
| free-for-dev | `raw.githubusercontent.com/ripienaar/free-for-dev/master/README.md` | md | 800+ 条免费开发者资源，含 Hosting / DB / Storage / CI 分节 | 最大的单点覆盖；首轮只建基线，之后 diff |
| awesome-selfhosted | `raw.githubusercontent.com/awesome-selfhosted/awesome-selfhosted/master/README.md` | md | 可自托管项目清单 | 只收「有免费托管/一键部署」的条目，其余过滤 |

> free-for-dev 的 README 已按品类分节，解析时直接用二级标题作为 `category`，比逐家抓官网省 10 倍工作量。

### 7.2 P0：静态站托管（最贴合「部署网站」）

| 厂商 | 页面 | 免费要点（以页面为准） | 备注 |
|---|---|---|---|
| GitHub Pages | `pages.github.com` | 公开仓库站点免费；1GB 站点、100GB/月带宽 | 与现有发布链路天然一致 |
| Cloudflare Pages | `pages.cloudflare.com` | 静态资源不限带宽；每月构建次数有限 | 私有仓库也能用；可绑自定义域 |
| Netlify | `netlify.com/pricing/` | Free：100GB 带宽、300 构建分钟/月 | 表单/函数有独立额度 |
| Vercel | `vercel.com/pricing` | Hobby：个人非商用；带宽与函数额度 | 商用需 Pro，需在 `eligibility` 标注 |
| Surge | `surge.sh/` | 免费发布静态站，CLI 一条命令 | 无 CI，适合纯静态 |
| Firebase Hosting | `firebase.google.com/pricing` | Spark 计划免费额度 | 与 Firestore 免费层联动 |
| Render Static Site | `render.com/pricing` | 静态站免费，不限休眠 | 与 Render Web Service 同平台 |

### 7.3 P1：全栈与后端 PaaS（能跑 API / 常驻服务）

| 厂商 | 页面 | 免费要点（以页面为准） | 备注 |
|---|---|---|---|
| Render | `render.com/pricing` | Free Web Service（闲置休眠）、免费 Postgres 期限 | 冷启动 30–60s，需在 `limits` 标注 |
| Fly.io | `fly.io/docs/about/pricing/` | 免费 allowance（政策常变，**待复验**） | 需绑卡；有免费机器额度 |
| Koyeb | `koyeb.com/pricing` | 免费实例（**待复验**） | 支持 Docker / Git |
| Railway | `railway.com/pricing` | 试用额度（政策常变，**待复验**） | 不适合长期免费托管 |
| Deno Deploy | `deno.com/deploy/pricing` | 免费请求额度 | 边缘运行时，支持 TS |
| Cloudflare Workers | `developers.cloudflare.com/workers/platform/pricing/` | 每日请求数免费额度 | 与 Pages Functions 共用 |
| Google Cloud Run | `cloud.google.com/run/pricing` | 每月免费额度（请求/CPU/内存） | 需绑卡；scale-to-zero |
| Vercel Functions | `vercel.com/pricing` | Hobby 函数额度 | 与静态托管同平台 |

### 7.4 P1：数据库与存储（给网站配后端）

| 厂商 | 页面 | 免费要点（以页面为准） | 备注 |
|---|---|---|---|
| Supabase | `supabase.com/pricing` | Free：Postgres + Auth + Storage + 2 个项目 | 项目闲置会暂停，需标注 |
| Neon | `neon.tech/pricing` | 免费分支、自动扩缩容到零 | 冷启动连接延迟 |
| Turso | `turso.tech/pricing` | 免费库数/行数（**待复验**） | SQLite 兼容 |
| Upstash | `upstash.com/pricing` | Redis / Kafka 免费额度 | 适合缓存与队列 |
| MongoDB Atlas | `mongodb.com/pricing` | M0 免费集群 | 共享集群性能有限 |
| Aiven | `aiven.io/pricing` | 部分服务免费试用（**待复验**） | 需逐服务确认 |
| Cloudflare R2 | `developers.cloudflare.com/r2/pricing/` | 免费存储额度 + 零出站费 | 图片/静态资源首选 |
| Backblaze B2 | `backblaze.com/cloud-storage/pricing` | 免费存储额度 | 出站有免费额度 |

### 7.5 P1：大厂永久免费层（长期稳定，但门槛高）

| 厂商 | 页面 | 品类 | 关键信息 |
|---|---|---|---|
| Oracle Cloud | `oracle.com/cloud/free/` | compute/storage/db | Always Free：ARM 实例 + 块存储 + 自治数据库；需绑卡 |
| AWS | `aws.amazon.com/free/` | 全品类 | 12 个月免费 + 始终免费；需绑卡 |
| Google Cloud | `cloud.google.com/free` | 全品类 | 赠金 + always free；需绑卡 |
| Azure | `azure.microsoft.com/pricing/free-services/` | 全品类 | 赠金 + 12 个月免费 + 始终免费 |
| Cloudflare | `cloudflare.com/plans/` | cdn/serverless/storage | 免费版含 CDN、DNS、Workers/Pages 额度 |
| IBM Cloud | `ibm.com/cloud/free` | compute/db | Lite 计划（**待复验**） |

> 大厂页面的价值不在「多」，而在「稳」：条目少但复验成本低，适合做站点的「永久免费」基线。

### 7.6 P2（可选）：VPS 特价（不在首期范围）

> 本项不阻塞主线：每天一轮即可，不需要每小时 workflow。若首期资源够用，可整体推迟。

| 源 | URL | 方式 | 备注 |
|---|---|---|---|
| LowEndBox | `lowendbox.com/feed/` | rss | 特价帖主力来源 |
| RackNerd Specials | `racknerd.com/specials/` | cfg-html | 年付低价档，库存波动大 |
| CloudCone | `cloudcone.com/vps/` | cfg-html | 闪购，需抓库存状态 |
| Hetzner Cloud | `hetzner.com/cloud` | cfg-html | 欧洲性价比，价格稳定 |
| Contabo | `contabo.com/en/vps/` | cfg-html | 大内存低價 |
| BandwagonHost | `bandwagonhost.com/` | cfg-html | 需代理，谨慎；仅作可选 |

### 7.7 复用现有源（零成本扩量）

| 现有源 | 改动 | 收益 | 优先级 |
|---|---|---|---|
| `hackernews` | `queries` 追加 `"free tier"`、`"free hosting"`、`"free postgres"`、`"self-hosted"` | 即时获得云资源讨论帖，零代码 | P1 |
| `watchlist` | `providers.toml` 增补云厂商 `/pricing`、`/free` 页，`tier=2` | 页面变化信号，无需新代码 | P1 |
| `linuxdo` | 追加云计算/服务器相关 RSS（标签待验证） | 中文补充，但非「国外为主」主线 | P3（可选） |

### 7.8 按「我要部署什么」选型矩阵

这是本站的核心产品视图。用户不需要知道 100 家厂商，只需要知道「我想做这件事，用什么」。

| 我想部署 | 免费方案组合 | 关键限制（需在 `limits` 标注） |
|---|---|---|
| 静态博客 / 文档站 | GitHub Pages / Cloudflare Pages / Netlify / Surge | 构建分钟数、商用限制（Vercel Hobby 非商用） |
| 前端 + Serverless API | Cloudflare Pages + Workers / Vercel / Netlify Functions | 每日请求数、函数执行时长 |
| 带数据库的全栈站 | Cloudflare Pages（前端）+ Supabase / Neon（DB） | 项目闲置暂停、连接数、存储上限 |
| 常驻后端 / 定时任务 | Render Free / Koyeb / Cloud Run / Fly.io | 闲置休眠与冷启动、每月运行小时 |
| 图片 / 文件存储 | Cloudflare R2 / Backblaze B2 / Supabase Storage | 出站流量、请求数、单文件大小 |
| 缓存 / 队列 | Upstash Redis / Cloudflare KV | 命令数、存储量 |
| 自建小 VPS（Docker） | Oracle Always Free / 低价 VPS（P2） | 绑卡、区域库存、ARM 架构兼容 |
| 免费域名 + HTTPS | Cloudflare DNS + Let's Encrypt | 域名本身通常不免费，需标注 |

> 站点应提供「场景 → 方案」的入口，而不只是「厂商 → 免费额度」的列表。数据模型上，这对应
> `offers.category` + `providers.deploy_modes` 两个字段的组合筛选。

### 7.9 优先级结论

```
P0  free-for-dev 目录（1 天见效，先把站点填满）
 ↓
P0  静态站托管 + PaaS（回答「怎么部署网站」，7 家）
 ↓
P1  数据库 / 存储（补齐「带后端的站」，8 家）
 ↓
P1  大厂永久免费层（6 家，做「永久免费」基线）
 ↓
P2  VPS 特价（可选，首期不做）
```

理由：目录源一次接入就能验证「值不值得做」；静态托管 + PaaS 直接回答你的核心诉求；数据库/存储让方案能落地成完整站点；大厂页决定可信度；VPS 特价解析最脏且时效性要求最高，放最后。

---

## 8. 配置化解析器（关键设计）

### 8.1 为什么必须配置化

「一网打尽」意味着源会到 50–100 个。若每家园商一个 Python 类，维护成本会压垮项目。观察到的规律：

- 官方免费层页 80% 是「标题 + 段落 + 列表」结构；
- PaaS 定价页 70% 有结构化表格（Free / Hobby / Pro 三列）；
- 规格信息（vCPU/内存/磁盘）几乎都以 `\d+\s*(vCPU|GB|TB)` 形式出现。

因此：**一个通用解析器 + 每源一段 TOML**，特殊站点才写代码。

### 8.2 `cloud_sources.toml` 形状

```toml
[[source]]
name = "oracle_always_free"
vertical = "cloud"
category = "compute"
mode = "html"
url = "https://www.oracle.com/cloud/free/"
provider = "Oracle Cloud"
interval_hours = 168
force_keep = true

[source.defaults]
offer_type = "always_free"
difficulty = 3
eligibility = { card_required = true, phone = false }

[source.selectors]
item = "section#free-tier article"      # 一个条目
title = "h3"
description = "p"
link = "a@href"
free_column = "td:nth-child(2)"         # 表格型页面才需要

[source.spec_regex]
vcpu = '(\\d+(?:\\.\\d+)?)\\s*(?:vCPU|OCPU|cores?)'
ram_gb = '(\\d+(?:\\.\\d+)?)\\s*GB\\s*(?:RAM|memory)'
disk_gb = '(\\d+(?:\\.\\d+)?)\\s*GB\\s*(?:block|storage|disk)'
```

### 8.3 解析器的降级策略

```
选择器命中 0 条  → 记 error，保留上一版基线，不产生删除事件（防误判）
标题命中、规格未命中 → 条目保留，resources 为空，evidence 存原文
整页 404/403       → 源级失败，计入 fail_count，熔断 7 天
页面结构大变（条目数骤降 >50%）→ 跳过归档，只更新基线（复用现有防御）
```

### 8.4 单位归一（`domain/normalize_units.py`）

| 输入 | 输出 |
|---|---|
| `1 TB` / `1000 GB` | `bandwidth_gb = 1000` |
| `$11/yr` / `$11 per year` | `credit_usd`? 否 → `limits.price_usd_year = 11` + `price_usd_month = 0.92` |
| `750 hours/month` | `runtime_hours_month = 750` |
| `100k requests/day` | `requests_month = 3_000_000`（×30，标注推算） |
| `30 days` | `valid_days = 30` |

> 所有「推算」必须在 `evidence` 里保留原值，避免二次失真。

---

## 9. 评分、去重与生命周期

### 9.1 规则包（`domain/rulesets/`）

```python
RULESETS = {
    "ai_api": AI_RULES,       # 现有 DEFAULT_RULES 原样迁入
    "cloud":  CLOUD_RULES,
    "vps":    VPS_RULES,
    "paas":   PAAS_RULES,
    "storage": STORAGE_RULES,
    "database": DB_RULES,
}
```

**CLOUD/VPS 规则示例（权重）**：

| 信号 | 权重 |
|---|---|
| `always free` / `永久免费` / `永久额度` | 5.0 |
| `free tier` / `免费层` / `免费套餐` | 3.5 |
| `no credit card` / `无需信用卡` / `免绑卡` | 3.0 |
| `$X credits` / `赠金` / `试用金` | 3.0 |
| `student` / `学生认证` / `.edu` | 2.5 |
| `docker` / `git push` / `一键部署` | 2.0 |
| `NVMe` / `KVM` / `独立IP` | 1.5 |
| `lifetime` / `终身` / `买断` | 2.0 |
| `补货` / `restock` / `back in stock` | 3.0 |
| `售罄` / `out of stock` / `sold out` | -2.0 |

**硬门槛（不靠分数）**：

```python
def is_free_resource(item) -> bool:
    # 必须至少满足一项，否则丢弃
    return (
        item.offer_type in {"always_free", "free_tier", "student", "oss", "startup"}
        or item.limits.get("credit_usd", 0) >= 5
        or item.resources.get("ram_gb", 0) >= 1
        or "free" in item.title.lower() and "trial" not in item.title.lower()
    )
```

> 这条硬门槛比分数更重要：云资源的标题经常不含「免费」，但页面正文含「Free tier」。因此**判定要看 `evidence`，不能只看标题**——沿用现有 `score_item` 的 `title + evidence` 拼接方式即可。

**该门槛对所有 vertical 生效，包括现有 AI 侧。** 用当前库（220 条）核对后，有三类需要收紧：

| 类型 | 现状 | 处理 |
|---|---|---|
| litellm「价格大降 60–100%」 | 6 条；降价 ≠ 免费 | 改写成 `signal.price_drop`；只有降到 0 才生成 `always_free` offer |
| aicredits 的实习/奖学金/投资计划/会议 | 8 条；不是可领资源 | 硬门槛直接丢弃（不满足 credit / resources / free_tier 任一） |
| AA 榜单、models.dev 新 provider | 只有厂商，没有 offer | 保持为发现层：只写 `provider_sources`，不生成 offer |

实测：220 条中 205 条（93%）含免费语义；其余 15 条里 6 条是降价事件、8 条是付费项目、1 条是榜单/会议类。
按新门槛实测：**5 条**会被过滤（Pawsey 实习、Antler 投资、Cohere 学者、NVIDIA Fellowship、Anthropic Fellows），
其余含 `$ credit` 的创业计划（AWS Activate 等）保留。AI 侧免费占比因此达到 **97.7%**。

### 9.2 Offer 指纹

```python
def offer_key(item: RawItem) -> str:
    basis = item.key_basis or "|".join([
        item.vertical,
        normalize_provider(item.provider or ""),
        item.offer_type,
        item.category,
        norm_title(item.title),
    ])
    return sha1(basis)
```

- **不含 `resources` / `limits`**：规格与额度会随政策变化，放进身份键会把「额度调整」误判成新 offer。
  它们由 `terms_hash = sha1(canonical_terms(...))` 单独记录，变化时产生 `terms_changed` 事件。
- 不含 URL：同一方案会被多个目录/帖子引用。
- `key_basis` 优先：配置化源给出 `page_name:url` 的精确指纹，目录源给出 `ffd:url`。

### 9.3 生命周期状态机

```
         首次发现
             │
             ▼
        ┌─────────┐   last_seen 刷新（每轮）   ┌─────────┐
        │ active  │◀──────────────────────────│ active  │
        └────┬────┘                            └─────────┘
             │
   ┌─────────┼──────────────┬──────────────────┐
   ▼         ▼              ▼                  ▼
expires_at 条款变化    上游删除/页面消失   30 天未复验
   │         │              │                  │
   ▼         ▼              ▼                  ▼
expired  terms_changed   removed           stale
         （仍 active）   （归档，不删）      （降权展示）
```

- `stale` 不写入 `offers.status`（CHECK 只有 active/expired/unknown），而是由 `last_verified_at` 计算展示态。
- `removed` 复用现有 `mark_expired_resolved`，并写 `status_reason='upstream_removed'`。

### 9.4 变更事件

| 事件 | 触发 | 通知 |
|---|---|---|
| `offer.created` | 新 offer_key | ✅ 仅 always_free / credits ≥ $50 |
| `offer.terms_changed` | `terms_hash` 变化 | ⚠️ 每日汇总 |
| `offer.expiring` | `expires_at` ≤ 7 天 | ✅ |
| `offer.expired` | 到期/消失 | ❌ |
| `signal.restock` | 特价页从售罄→有货 | ✅ |
| `signal.new_region` | 地区列表增加 | ⚠️ 汇总 |
| `signal.price_drop` | 同 plan 价差 ≥ 5% | ✅ 仅新低 |

---

## 10. 站点与通知

### 10.1 信息架构

```
顶部一级导航
├─ 场景         （默认首页：我要部署什么 → 免费方案组合，见 7.8）
├─ 全部资源      （完整表格 + 筛选）
├─ AI 促销       （现有视图，保持不变）
├─ 云计算 / VPS
├─ 部署平台 PaaS
├─ 存储 / 数据库
└─ 我的领取      （localStorage，可导出/导入）
```

「场景」页是本次扩展的产品核心：先用一句话回答「静态站用 GitHub Pages / Cloudflare Pages」，
再展开对应厂商的免费额度与限制。厂商列表是下钻，不是入口。

### 10.2 云资源视图（表格优先）

卡片不适合表达规格。云视图默认表格：

| 商家 | 类型 | 规格 | 存储/流量 | 门槛 | 有效期 | 最近验证 | 操作 |
|---|---|---|---|---|---|---|---|
| Oracle | 永久免费 | 4 OCPU / 24G（ARM 合计） | 200G 块存储 | 需绑卡 | 永久 | 3 天前 | 去领取 / 标记已领 |
| Supabase | 免费层 | 共享 | 500MB DB | 免绑卡 | 月重置 | 1 天前 | 去领取 |

筛选维度：

- 类型：`always_free` / `free_tier` / `trial` / `credits` / `student` / `promo`
- 门槛：免绑卡 / 免实名 / 免手机 / 需学生 / 需企业
- 品类：计算 / 存储 / 数据库 / CDN / PaaS / 其他
- 规格：内存 ≥ N GB、磁盘 ≥ N GB、额度 ≥ $N
- 地区：排除 CN 受限
- 状态：有货 / 售罄 / 即将到期 / 待复验

### 10.3 领取跟踪（不做后端）

**默认方案：纯前端 `localStorage`。不引入 Cloudflare D1。**

- 存储键：`radar.claims.v1`，值为 `{offer_key: {state, claimed_at, note}}`。
- 页面顶部显示「已领 N / 待领 M / 30 天内到期 K」。
- 提供「导出 JSON / 导入 JSON」两个按钮，换设备时手动迁移。
- `trial` 类 offer 标记「已领」后，前端按 `valid_days` 计算到期日，浏览器内提醒。
- `radar serve` 本地模式可选写 SQLite（单人、本机）；静态 Pages 模式不写任何后端。

> D1 的取舍与触发条件见 1.3.1。结论：单人使用、每天一次构建、静态站优先，D1 是纯负担。

`claims` 表仍然保留在 schema 中：它服务于 `serve` 模式与未来的 CLI 导出，不参与静态站构建。

### 10.4 通知

- 复用 `delivery/notify.py`，新增 `push_cloud_events()`。
- **每天一轮，合并成一条日报**：新增永久免费 / 大额赠金 / 即将到期 / 补货。
- 不推送常规 `free_tier` 的轻微条款变化，避免噪音。
- 静默规则：同一 `offer_key` 7 天内只推一次；`restock` 24 小时内只推一次。
- 未配置 Telegram 时只更新站点，不报错。

### 10.5 体积预算

- `data.json` 允许增长到 1.5MB（外部脚本，不影响首屏）。
- `index.html` 仍需 < 200KB：云条目首屏只内联 40 条，其余走 `data.js`。
- `atom-cloud.xml` 单列，避免 AI 订阅者被云条目淹没。

---

## 11. 部署与调度

### 11.1 单一 workflow，每天一轮

**不新增 `cloud.yml` / `vps.yml`。**在现有 `radar.yml` 内加一个云源步骤即可：

| 步骤 | 命令 | 失败影响 |
|---|---|---|
| 1. AI 源 | `python -m radar run --vertical ai_api` | 不影响云步骤 |
| 2. 云源 | `python -m radar run --vertical cloud --no-report` | `continue-on-error`，不阻塞发布 |
| 3. 发布 | `python -m radar report` | 用两份结果一起构建站点 |
| 4. 提交 | `providers.toml` + DB 快照 + `data/site` | 与现有流程一致 |

- 触发：`schedule: 37 2 * * *`（保持不变）+ `workflow_dispatch`（可手动只跑云）。
- 预算：AI 约 3–8 分钟，云约 2–4 分钟，合计 **< 400 分钟/月**，仍在免费额度内。
- 健康横幅按 vertical 分开统计：云源全挂不会把 AI 横幅刷红，反之亦然。

### 11.2 CLI 增量

```bash
radar run --vertical cloud          # 只跑云源
radar run --vertical ai_api         # 只跑现有 AI 源
radar run --only free_for_dev,cloudflare_pages
radar report --vertical cloud       # 只重建云视图（可选）
radar claim <offer_key> --state claimed   # 仅 serve 模式，写本地 SQLite
radar verify <offer_key>                  # 人工复验，写 last_verified_at
```

### 11.3 频率与限速

- **统一 24 小时一轮**，不做小时级调度。
- 源级 `interval_hours` 仍然保留：大厂免费层页设 `168`（每周），PaaS 定价页设 `72`（每 3 天），
  每日运行时未到期就跳过，减少请求。
- per-host 令牌桶：默认 1 req/s；`robots.txt` 缓存 24h。
- 单轮全量硬预算：**8 分钟**；超时源按故障处理，不影响其他源。

---

## 12. 迁移与兼容

### 12.1 迁移步骤

实现落点（与现有代码对齐）：

- `storage/schema.sql`：新增三张表的 `CREATE TABLE IF NOT EXISTS`，文件头注释改为 `PRAGMA user_version = 10`；
- `storage/repository.py`：`SCHEMA_VERSION = 10`，`_migrate()` 末尾增加 `if version < 10:` 分支，逐列调用
  `_add_column()`（该方法已用 `PRAGMA table_info` 做幂等判断，重复执行安全）；
- 新列不写回填 SQL 也不会为 NULL：`ALTER TABLE ... NOT NULL DEFAULT` 会让旧行自动取默认值。

```
1. 备份：data/radar.db → data/backup/radar-pre-v10.db
2. 执行 DDL（幂等）：repository._migrate(10)
3. 回填最小集：
   UPDATE offers SET vertical='ai_api', offer_type='credits' WHERE vertical IS NULL;
   UPDATE providers SET vertical='ai_api' WHERE vertical IS NULL;
4. 对账：
   SELECT COUNT(*) FROM offers;                    -- 必须仍为 213
   SELECT COUNT(*) FROM providers;                 -- 必须仍为 370
   SELECT COUNT(*) FROM deals;                     -- 必须仍为 213
5. 跑 pytest 全量（119 项）+ 现有 AI 源一轮，确认新增/更新数与迁移前一致
```

### 12.2 兼容策略

- 旧代码读新库：多出的列被忽略，`SELECT *` 的调用点需检查（现有代码均为显式列，安全）。
- 新代码读旧库：`_migrate` 自动补列。
- 站点：`schema_version` 字段让前端可判断；旧 `data.json` 仍可被新前端读取（字段可选）。

### 12.3 回滚

```
代码回退到 v9 tag → 用 radar-pre-v10.db 覆盖 → 确认 user_version=9
```

---

## 13. 验收口径（可复算）

| 指标 | SQL / 方法 | 目标 |
|---|---|---|
| 云厂商数 | `SELECT COUNT(DISTINCT provider_id) FROM offers WHERE vertical != 'ai_api'` | ≥ 120 |
| 结构化率 | `SELECT AVG(resources != '{}') FROM offers WHERE vertical != 'ai_api'` | ≥ 60% |
| 门槛标注率 | `SELECT AVG(eligibility != '{}') ...` | ≥ 80% |
| 免绑卡占比 | `SELECT AVG(json_extract(eligibility,'$.card_required') = 0) ...` | 仅统计，不设目标 |
| 复验新鲜度 | `SELECT COUNT(*) FROM offers WHERE last_verified_at < date('now','-30 day')` | = 0（always_free） |
| 误报率 | 人工抽 50 条，统计非免费/非云资源 | ≤ 10% |
| 解析成功率 | `source_runs.kept / fetched` | ≥ 70% |
| 单轮耗时 | `source_runs.elapsed_ms` 汇总 | < 4 分钟 |
| 幂等 | 连续两轮 `new_deals` | 第二轮 = 0 |

---

## 14. 里程碑

| 阶段 | 内容 | 交付 | 验收 | 预估 |
|---|---|---|---|---|
| **M0** 契约与模型 | v10 DDL、`RawItem` 扩展、`SourceSpec`、`schema_version` | 迁移脚本 + 契约测试 | 119 项全绿；旧数据计数不变 | 2 天 |
| **M1** 垂直化贯通 | vertical 从源到站点；规则包拆分；一级导航 | 站点可切到「云」空视图 | AI 侧数字与迁移前完全一致 | 3 天 |
| **M2** 目录源 | `free_for_dev`（md diff） | 首批 300+ 条免费资源 | 首轮建基线、次轮 0 新增 | 2 天 |
| **M3** 静态托管 + PaaS | Cloudflare Pages / GitHub Pages / Netlify / Vercel / Render / Koyeb / Surge（7 家，配置化） | 7 个 fixture + 结构化字段 | 「部署静态站」场景能出 ≥ 3 个可用方案 | 3 天 |
| **M4** 数据库 / 存储 | Supabase / Neon / Turso / Upstash / R2 / B2 / Atlas（8 家） | 表格视图 + 筛选 | 筛选「免绑卡 + 永久」能出结果 | 3 天 |
| **M5** 大厂永久免费层 | Oracle / AWS / GCP / Azure / Cloudflare / IBM（6 家） | 永久免费基线 | 每条有 `offer_type` + `eligibility` | 2 天 |
| **M6** 场景视图与领取 | 「我要部署什么」矩阵页、localStorage 领取跟踪、导出/导入 | 场景页可用 | 三种场景各出 ≥ 3 个方案；刷新后状态不丢 | 3 天 |
| **M7** 上线与治理 | `radar.yml` 加云步骤、告警、回滚手册、README/STATE 更新 | 线上云视图 | 连续失败 2 次告警；单轮 < 8 分钟 | 2 天 |

合计 **20 个工作日 ≈ 4 周**（业余时间约 5–6 周）。

- **M0–M2 是验证点**：做完若目录源质量不达标，可只保留 M2 并停止后续投入。
- **M3–M6 是价值兑现点**：直接回答「我想部署一个网站，用什么」。
- **VPS 特价不在里程碑内**（P2 可选），避免首期被最脏的解析拖住。

---

## 15. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| free-for-dev 条目质量参差 | 误报多、噪音大 | 硬门槛 + `force_keep=false` 走评分；人工抽检 50 条校准 |
| 官方页 JS 渲染（Vercel / Cloudflare 新版页面） | 抓不到 | 优先找 JSON/API；失败降级为 watchlist 信号 |
| 定价政策频繁变化（Railway/Fly） | 数据过期 | `interval_hours=72` + `last_verified_at` 展示 + 页面标「待复验」 |
| 规格单位混乱（GB vs GiB、年付 vs 月付） | 筛选错误 | `normalize_units` 单一入口 + fixture 单测 |
| 配置化解析器过度抽象 | 反而难维护 | 先支持 3 种 mode（md/html-table/html-list），特殊站点才写类 |
| 源数量增长导致 Actions 超时 | 抓不全 | `interval_hours` 分层 + 单轮 `max_pages` + 并行 |
| 与 `STATE.md`「R1 前不做新功能」冲突 | 路线反复 | 把 M0 并入 R1「契约冻结」；M1 起作为 R4 路线正式立项 |
| 合规 | 被封/争议 | 只抓公开页、遵守 robots、限速、不自动注册/不代领 |

---

## 16. 与现有文档的关系

| 文档 | 关系 |
|---|---|
| `STATE.md` | 唯一事实源；本方案落地后，数字与进度写回该文件 |
| `ARCHITECTURE_REVIEW.md` | 提供分层依据与 ADR；本文档是其「垂直扩展」的具体化 |
| `NEXT_STEPS.md` | 待办清单；M0–M7 完成后合并进去，不另立过程文档 |
| `discovery/*` | Provider 宇宙与标注口径；云厂商沿用同一套实体表，新增 `vertical` 维度 |
| `README.md` | 对外入口；上线后更新「渠道全景」与「快速开始」 |

---

## 17. 决策记录与剩余问题

### 17.1 已决策（2026-11-08）

| # | 问题 | 决定 | 依据 |
|---|---|---|---|
| D1 | 覆盖地域 | **国外为主**，不接国内云 | 用户选择；避免实名/备案/页面差异 |
| D2 | 更新频率 | **每天一轮**，沿用 `radar.yml` | 用户选择；当前信息变化不需要小时级 |
| D3 | 部署形态 | **GitHub + Pages 静态站** | 零成本、零运维，与现有链路一致 |
| D4 | 是否上 Cloudflare D1 | **不上** | 构建时生成、单人使用；成本 > 收益（见 1.3.1） |
| D5 | 内容范围 | **先做 free 资源**，不做全量比价 | 用户选择；`offers.resources` 足够表达 |
| D6 | 产品视角 | **按「我要部署什么」组织** | 用户核心诉求是「帮我找到能部署网站的资源」 |
| D7 | VPS 特价 | **P2 可选**，不进首期里程碑 | 解析最脏、时效要求最高，避免拖慢主线 |

### 17.2 仍待确认（不阻塞 M0–M2）

1. **付费价是否收录**：免费额度用完后（如 Render/Supabase 超限）的月费，是否写进 `limits.payg_price_usd`？
   收录会增加解析字段，但对「选型」有帮助。
2. **免费域名/邮箱品类**：是否纳入？这类资源常需要绑卡或仅首年免费，容易产生误报。
3. **AI 促销是否并入场景页**：默认保留独立入口；若你希望「一个页面看全部」，可在 M6 合并。

> 这三项在 M3 前给出即可，不影响当前设计。

---

## 18. 统一链路（v10.1，已完成）

初版 v10 让 AI 继续写 deals、云写 offers，导致站点出现两个目录。这是技术债，已收敛。

### 18.1 最终数据流

```
所有来源 → RawItem → normalize → gate → upsert_offer → offer_evidence
                                                        → offer_terms_history
                                                        → lifecycle
                                                        → offers（唯一展示实体）
```

- deals 停止写入，只读保留（历史线索）；
- 转发帖不再生成新行，而是作为同一 Offer 的第二条 offer_evidence；
- AI 的 offer_type 由 matched 推断，limits.credit_usd 从金额文本解析。

### 18.2 四维划分

| 维度 | 取值 | 作用 |
|---|---|---|
| ertical | ai_api / cloud / paas / storage / database / cdn / devtool / vps | 频道与规则包 |
| category | ai / compute / hosting / serverless / database / storage / cdn ... | 能力标签 |
| offer_type | always_free / free_tier / trial / credits / student / startup / oss / promo_code | 免费语义 |
| granularity | activity（厂商级活动）/ plan（规格级方案） | 去重粒度 |

### 18.3 站点

导航收敛为：**资源**（默认）/ **厂商** / 总览 / 已过期 / 数据源。
「用途」（静态站 / 全栈 / 后端 / 存储 / VPS）不再占独立页面，而是资源页的筛选维度。

厂商页也改为从 offers 聚合（`vendor_summary()`），不再只读 watchlist：AI 与云共 805 家，
每行显示领域、可用/资源数、品类、最近更新、是否有官网监控页。
「全部资源」同时包含 AI 与云，筛选维度为状态、领域、免费类型、金额/规格；表格含证据数、门槛、领取按钮。

### 18.4 验收（本地实测）

| 指标 | 结果 |
|---|---|
| AI 迁移 | 220 deals → 212 offers（转发合并），证据 882 |
| 云资源 | 669 条（free-for-dev 658 + 官方页 11） |
| 站点 | index 180KB；首屏同时出现 AI 促销与云计算 |
| 测试 | 125 项全绿 |