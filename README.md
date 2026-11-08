# promo-radar

系统性收集 **AI API 促销 + 可白嫖云资源**（免费额度 / 免费服务器 / 可部署网站）的个人监控站。

多渠道抓取 → 关键词打分 → 三级去重 → SQLite 归档 → **交互式 Dashboard**（纯静态，双击可开）+ Atom 订阅 + 可选 Telegram 推送。

三个领域共用一套管线：

- **AI 促销**：注册送额度、绑卡送额度、free tier。
- **云资源**（v10）：永久免费、免费层、试用赠金，重点回答「我想部署一个网站，能用什么」。
- **免费算力**（v10.7）：免费 GPU / Notebook / 免费 token 额度，回答「没有显卡怎么跑模型」。

两者**不是两个目录**：所有来源统一写入 `offers`，站点只有一个「全部资源」列表，用「领域」筛选切换。
`deals` 表只作为历史线索保留，不再产生新数据。

## 渠道全景（15 条线）

| # | 渠道 | 覆盖 | 层级 |
|---|---|---|---|
| 1 | aicredits.dev（llms-full.txt） | 200+ 条人工筛选目录，**新域名自动收编进 watchlist** | 目录 |
| 2 | linux.do RSS ×2（福利羊毛 + AI 标签） | 中文羊毛集散地 | 社区 |
| 3 | Hacker News Algolia | 英文一手发布（4 组关键词增量） | 社区 |
| 4 | OpenRouter models API | 供应商 `:free` 模型 0→N 事件 | 平台 |
| 5 | models.dev api.json | 供应商名录基线，新 provider 入库事件 | 平台 |
| 6 | mnfst/awesome-free-llm-apis data.json | 免费 API 清单 diff（11.9k star） | 目录 |
| 7 | FreeToken providers.json | 中文免费额度清单 diff | 目录 |
| 8 | litellm 价格库 diff | 新增免费模型 / 输入价降 ≥50% 事件 | 价格 |
| 9 | watchlist 官网探测 | **330+ 家服务商官网** promo 文案信号带（盲区自动收编，持续增长） | 官网 |
| 10 | Artificial Analysis API | 新模型厂商上榜（60 家基线已建，✅ 已启用） | 榜单 |
| 11 | 子代理批量排查 | OpenRouter 供应商逐家核查（已排查 35 家收编 32 家） | 人工 |
| 12 | SearXNG 关键词搜索 | 需自托管 | ⏸ 延后 |
| 13 | **free-for-dev 目录** | 800+ 条免费开发者资源，只收云/托管/数据库/存储/CI/监控分类 | 目录 |
| 14 | **官方免费页** | `cloud_sources.toml` 配置化 42 个页面：国内云厂商（阿里云/腾讯云/华为云/京东云/百度智能云/青云）、8 家模型平台（百炼/火山方舟/腾讯混元/智谱/MiniMax/硅基流动/千帆/星火）、3 家免费算力（阿里云/百度 AI Studio/腾讯 Cloud Studio），结构化出 `offer_type` / 规格 / 门槛 | 官网 |
| 15 | **国内社区 RSS** | 掘金 / 开源中国 / 博客园，只收「免费额度、试用、领取、0元」等组合信号 | 社区 |

自动发现闭环：目录/平台冒出新面孔 → **自动收编**（aicredits 域名挖掘 + catalog diff 事件）→ 自动盯官网变化 → 报告呈现。

## 架构（v2 分层）

```
src/radar/
├─ domain/      纯逻辑：models / scoring（按 vertical 选规则包）/ dedup / free_gate / normalize_units
├─ collectors/  源插件：@register_source 注册表 + CatalogDiffSource 基类 + 12 个 AI 源
│               └─ cloud/  free_for_dev（目录）+ pages（cloud_sources.toml 配置化）
├─ pipeline/    runner：collect → score/free-gate → filter → dedup → repo → 事件流（逐源故障隔离）
├─ storage/     repository.py（Deal + v10 Offer/信号/领取 + SQLite 实现）+ schema.sql
├─ delivery/    site.py（dashboard，含部署场景/云资源视图）/ notify.py
├─ infra/       config.toml + cloud_sources.toml / http（重试/代理/正文提取）
└─ cli.py       run / report / add-provider / (--vertical ai_api|cloud)
```

解耦约定：collectors 只依赖 `StateStore` 协议；delivery 只读 domain 模型；加源 = 一个类 + `@register_source` + `__init__.py` 一行 import + config 开关。

## 快速开始

```bash
pip install -e .
radar run                          # 抓取全部源（AI + 云）+ 生成 data/site/
radar run --vertical cloud         # 只抓云资源（free-for-dev + 云厂商免费层页）
radar run --vertical ai_api        # 只抓 AI 促销源
radar report                       # 仅用已有数据重建站点
radar add-provider <名> --url <页>  # 手动收编服务商
```

大陆网络抓 linux.do / raw.githubusercontent 需配代理（config.toml `[proxy]`；本机已配 v2rayN 10808）。GitHub Actions 海外直连。

打开 `data/site/index.html` 即是 dashboard：**双击本地可开**。首屏内联只带 60 条活跃活动与 80 个监控页（兜底可交互），全量数据在同目录 `data.js`（外部脚本，file:// 不受 CORS 限制），`data.json` 供外部消费。index 体积稳定在 200KB 以内。

## Dashboard 功能

- **三视图**：卡片（活跃活动）/ 表格（全量+排序）/ 时间线（按日聚簇）
'- **用途筛选**（v10）：静态站 / 全栈 + 数据库 / 后端容器 / 对象存储 / 自建 VPS，直接在资源列表里筛
- **统一厂商**（v10）：AI 与云一个列表，可按领域、是否有官网监控筛选
- **领取跟踪**：任何一条资源都能标记「已领」，状态存本机 localStorage，可导出/导入'
- **筛选**：来源 / 类型（送额度、免绑卡、free tier…自动归纳）/ 金额档 / 状态，多选 chips 带计数 + 全文搜索
- **Watchlist 信号带**：每监控页 30 天逐日信号（金=有促销信号），有信号的排前面
- **KPI 条**：活跃数 / 本周新增 / 有信号页数 / 历史入库
- **亮暗双主题**：跟随系统 + 手动切换（记忆偏好）；无 JS 时 SSR 内容完整可读

## 数据新鲜度与健康

- 站点顶部横幅以**最近一次全量健康轮次**为基准：该轮至少 `full_run_min_sources`（默认 5）个源、且成功率 ≥80%；>6 小时黄色、>24 小时红色；从未成功则直接提示"尚未成功抓取"。`--only` 单源刷新不会把横幅刷绿，避免局部成功掩盖全源故障。
- `source_runs` 记录每源每轮状态；CLI 会打印「连续失败的源」，站点"数据源"页可看成功率与失败原因。
- watchlist 单页连续失败 3 次后熔断 7 天；**成功率 < 50% 才判源级故障**，个别死链不再拖垮整源。
- 本轮源成功率 < 80% 时**跳过过期归档**，避免故障期把仍有效的活动批量标记过期。
- `providers.toml` 的自动收编/手动添加统一走跨进程文件锁 + 原子替换，重复执行不会产生重复条目或半截文件。
- 全量快照型源（aicredits）上游消失的条目会自动归档；解析出 0 条或条目数骤降 >50% 时拒绝归档，防止上游格式变更误伤。

## 代理与并行

- **代理自动探测**：`config.local.toml` 里配了代理但本机端口没开时，启动阶段会做一次 TCP 探测（默认 0.5s），不通就**自动直连**，不再让每个请求卡在超时上。探测结果会在 CLI 打印一次。
- **代理设置面板**：`radar serve` 模式下，左侧栏「代理」可填写地址并保存（写入 `config.local.toml`，保留其余配置），保存后下一轮刷新自动生效；静态 Pages 模式不显示该面板。
- **源级并行**：默认最多 5 个源同时抓取（`[general] max_source_workers`），每个源使用独立 HTTP client 与独立 SQLite 连接；打分/去重/落库仍在主线程串行，保证结果确定性。
- **硬性总超时**：httpx 的 read timeout 是「每次 socket read」，慢站单请求可能拖到 30s+；现在每个请求额外有总 deadline（默认取 `http_timeout`），超时立即失败且**不再重试**，避免单源拖住整轮。
- **watchlist 分层调度**：T1 每日（有促销信号或 `providers.toml` 显式 `tier = 1`）、T2 每周、T3 每月；首次/旧库按 URL hash 错峰到周/月的某一天，只抓到期的页面。实测首轮从 360 页降到 **91 页 / 40 秒**，次轮 44 页 / 22 秒。间隔可在 `[sources.watchlist] tier1_interval_days / tier2_interval_days / tier3_interval_days` 调整。

## Telegram 推送（可选）

@BotFather 建 bot → config.toml 填 token/chat_id（或环境变量 `RADAR_TG_TOKEN`/`RADAR_TG_CHAT_ID`）。只推新增，失败不影响抓取。

## 部署

### 方式 A：GitHub Actions + Pages（推荐，零成本零运维）

```bash
cd promo-radar
git init && git add -A && git commit -m "promo-radar v2"
gh repo create promo-radar --source . --push   # 公开仓库可免费开 Pages
gh secret set RADAR_TG_TOKEN     # 可选：Telegram 推送
gh secret set RADAR_TG_CHAT_ID
```

完成。workflow 自动：每天一轮（海外网络直连 linux.do）→ `providers.toml`
commit 回主分支（纯文本、可 review）→ SQLite 快照强制推送到独立 `data`
分支（只保留最新，主分支不再膨胀）→ dashboard 发布到 `gh-pages` 分支。
站点产物与每页明细 JSON 不再提交主分支。到仓库
**Settings → Pages → Branch 选 gh-pages** 开启，之后访问
`https://<你>.github.io/promo-radar/` 随时看盘。
用量：每天 1 轮 × 3–8 分钟 ≈ 90–250 分钟/月，免费额度（2000/月）充裕。

私有仓库免费版没有 Pages：要么"本地双击 data/site/index.html + Telegram 推送"，
要么用 Cloudflare Pages（免费）连私有仓库、发布目录填 `data/site`。

### 手动刷新与细分更新（serve 模式）

```bash
radar serve          # http://127.0.0.1:8790/ → 页面左侧"手动刷新"
radar serve --port 8800
```

- 页面右上侧出现"手动刷新"：**开始刷新**（全部源）或"选择部分源"勾选后刷新
- 刷新在后台执行（1~5 分钟），完成后页面自动载入新数据
- CLI 同样支持：`radar run --only aicredits,watchlist`
- 自动频率：Actions 每天一次（`37 2 * * *`），要改频率直接编辑 workflow cron

### 方式 B：本地 Windows 计划任务

```bat
schtasks /create /tn "promo-radar" /tr "python -m radar run" /sc hourly /mo 6
```

### 方式 C：海外 VPS（要 24h 常驻或顺带跑别的）

任意海外小鸡（RackNerd 年付 $11 级别足够）：clone → `pip install -e .` →
crontab 加 `23 */6 * * * cd ~/promo-radar && python -m radar run >> radar.log 2>&1`；
dashboard 用 `caddy file-server --listen :80 --root data/site` 一行起。
**国内 VPS 不可用**（linux.do 直连被 SNI 阻断）。

## 日常使用

| 频率 | 动作 |
|---|---|
| 自动 | 每轮 run 更新 dashboard / 推送新增 |
| 每周 | 打开 dashboard 扫"本周新增"和"待复核" |
| 每月 | 反向挖掘：AA 榜单 + OpenRouter 供应商清单扫新面孔 → `radar add-provider`（或用并行子代理批量核查，方法见 git 历史） |

## 设计原则

源故障隔离 · 失败可见（新鲜度横幅 + 连续失败计数）· 幂等（重复运行 0 新增）· 证据留存（每条 deal 带原文摘录与时间）· 只归档不删除 · 离线可测（真实响应 fixtures）· 配置驱动 · 零 npm

## 已知边界

- linux.do 大陆直连被 SNI 阻断，本地走代理（当前节点出口被 CF 挑战，换节点或交 Actions）
- Artificial Analysis 旧端点 `/api/v2/data/llms/models` 已返回 410，需按官方文档更新 URL 或暂时关闭 `aa_providers`
- Reddit 公开 JSON 封锁（v2 OAuth，桩已留）
- JS 渲染站（systalyze 等 Framer 站）探测不到 → 人工月查
- 多账号批量薅羊毛违反 ToS，本工具只收集公开信息
