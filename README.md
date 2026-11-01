# promo-radar

系统性收集国际 AI API 服务商"注册送额度 / 绑卡送额度 / 免费层"类促销活动的个人监控站。

多渠道抓取 → 关键词打分 → 三级去重 → SQLite 归档 → **交互式 Dashboard**（纯静态，双击可开）+ Atom 订阅 + 可选 Telegram 推送。

## 渠道全景（12 条线）

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

自动发现闭环：目录/平台冒出新面孔 → **自动收编**（aicredits 域名挖掘 + catalog diff 事件）→ 自动盯官网变化 → 报告呈现。

## 架构（v2 分层）

```
src/radar/
├─ domain/      纯逻辑：models / scoring（关键词打分）/ dedup（三级去重+别名）
├─ collectors/  源插件：@register_source 注册表 + CatalogDiffSource 基类 + 11 个源
├─ pipeline/    runner：collect → score → filter → dedup → repo → 事件流（逐源故障隔离）
├─ storage/     repository.py（Repository + StateStore 协议 + SQLite 实现）+ schema.sql
├─ delivery/    site.py（dashboard 站点生成）/ notify.py（Notifier 协议 + Telegram）
├─ infra/       config.toml 加载 / http（重试/代理/正文提取 trafilatura）
└─ cli.py       run / report / add-provider
```

解耦约定：collectors 只依赖 `StateStore` 协议；delivery 只读 domain 模型；加源 = 一个类 + `@register_source` + `__init__.py` 一行 import + config 开关。

## 快速开始

```bash
pip install -e .
radar run            # 抓取全部源 + 生成 data/site/（index.html + data.json + monitors/ + atom.xml）
radar report         # 仅用已有数据重建站点
radar add-provider <名> --url <页>   # 手动收编服务商
```

大陆网络抓 linux.do / raw.githubusercontent 需配代理（config.toml `[proxy]`；本机已配 v2rayN 10808）。GitHub Actions 海外直连。

打开 `data/site/index.html` 即是 dashboard：**双击本地可开**（数据内联，无 fetch 依赖），GitHub Pages 亦可托管。

## Dashboard 功能

- **三视图**：卡片（活跃活动）/ 表格（全量+排序）/ 时间线（按日聚簇）
- **筛选**：来源 / 类型（送额度、免绑卡、free tier…自动归纳）/ 金额档 / 状态，多选 chips 带计数 + 全文搜索
- **Watchlist 信号带**：每监控页 30 天逐日信号（金=有促销信号），有信号的排前面
- **KPI 条**：活跃数 / 本周新增 / 有信号页数 / 历史入库
- **亮暗双主题**：跟随系统 + 手动切换（记忆偏好）；无 JS 时 SSR 内容完整可读

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

完成。workflow 自动：每天一轮（海外网络直连 linux.do）→ 数据与
providers.toml commit 回仓库（持久化 + 去重历史 + 保活）→ dashboard 发布到
gh-pages 分支。到仓库 **Settings → Pages → Branch 选 gh-pages** 开启，
之后访问 `https://<你>.github.io/promo-radar/` 随时看盘。
用量：每轮约 4 分钟 × 4 轮/天 ≈ 500 分钟/月，免费额度（2000/月）四倍冗余。

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

源故障隔离 · 幂等（重复运行 0 新增）· 证据留存（每条 deal 带原文摘录与时间）· 只归档不删除 · 离线可测（真实响应 fixtures）· 配置驱动 · 零 npm

## 已知边界

- linux.do 大陆直连被 SNI 阻断，本地走代理（当前节点出口被 CF 挑战，换节点或交 Actions）
- Reddit 公开 JSON 封锁（v2 OAuth，桩已留）
- JS 渲染站（systalyze 等 Framer 站）探测不到 → 人工月查
- 多账号批量薅羊毛违反 ToS，本工具只收集公开信息
