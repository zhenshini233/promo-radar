# 宇宙标注结果 v0（Day 13）

> 输入：425 条宇宙条目；规则见 `ANNOTATION_RULES_v0.md`。
> 本版只给初值，不改数据库、不改 providers.toml。

## 摘要

- 条目：**421**
- 分类未知：**27**
- 地区未知：**15**
- 低置信：**24**
- 非厂商（资助/活动/机构）：**2**
- 同品牌重复条目：**51**（去重后 **370** 个厂商）

## 分类分布

| 分类 | 数量 | 占比 |
|---|---:|---:|
| inference | 109 | 25.9% |
| model_lab | 77 | 18.3% |
| cloud | 58 | 13.8% |
| gpu | 46 | 10.9% |
| app | 40 | 9.5% |
| ai_infra | 35 | 8.3% |
| unknown | 27 | 6.4% |
| aggregator | 23 | 5.5% |
| relay | 6 | 1.4% |

## 主地区分布

| 地区 | 数量 |
|---|---:|
| us | 257 |
| cn | 50 |
| eu | 48 |
| global | 40 |
| unknown | 15 |
| apac | 11 |

## 相关性分桶

| 区间 | 数量 |
|---|---:|
| 0.80+ | 286 |
| 0.70-0.79 | 99 |
| 0.60-0.69 | 26 |
| 0.50-0.59 | 10 |

## 低置信（需人工确认，Top 60）

| 厂商 | 域名 | 分类 | 地区 | 来源 |
|---|---|---|---|---|
| abliteration.ai | abliteration.ai | unknown | global | modelsdev |
| above.dev | above.dev | unknown | global | modelsdev |
| ai& | aiand.com | unknown | global | modelsdev |
| AKI.IO | aki.io | unknown | global | modelsdev |
| Bee by HEOSSI | heossi.com | unknown | global | modelsdev |
| Blue Claw | blueclaw.network | unknown | global | modelsdev |
| Boundless | boundless.network | unknown | global | modelsdev |
| Charm Hyper | charm.land | unknown | global | modelsdev |
| DaoXE | daoxe.com | unknown | global | modelsdev |
| engy | engy.ai | unknown | global | modelsdev |
| Helyx AI | helyxai.space | unknown | global | aicredits |
| Hopper | withhopper.com | unknown | global | modelsdev |
| Munito AI | munito.ai | unknown | global | modelsdev |
| typesafe | — | unknown | unknown | litellm,openrouter |
| elorian | — | unknown | unknown | openrouter |
| aiand | — | unknown | unknown | litellm |
| Ant Digital | — | unknown | unknown | openrouter |
| eu_jev | — | unknown | unknown | litellm |
| laya | — | unknown | unknown | litellm |
| lemonade | — | unknown | unknown | litellm |
| nace | — | unknown | unknown | litellm |
| Parallel | — | unknown | unknown | openrouter |
| pinstripes | — | unknown | unknown | litellm |
| ricursiveai | — | unknown | unknown | openrouter |

## 未知分类（Top 60）

| 厂商 | 域名 | 地区 | 来源 |
|---|---|---|---|
| abliteration.ai | abliteration.ai | global | modelsdev |
| above.dev | above.dev | global | modelsdev |
| ai& | aiand.com | global | modelsdev |
| aistudentpack.com | aistudentpack.com | global | aicredits |
| AKI.IO | aki.io | global | modelsdev |
| Bee by HEOSSI | heossi.com | global | modelsdev |
| Blue Claw | blueclaw.network | global | modelsdev |
| Boundless | boundless.network | global | modelsdev |
| Charm Hyper | charm.land | global | modelsdev |
| DaoXE | daoxe.com | global | modelsdev |
| engy | engy.ai | global | modelsdev |
| Helyx AI | helyxai.space | global | aicredits |
| Hopper | withhopper.com | global | modelsdev |
| klokintegration.se | klokintegration.se | eu | modelsdev |
| Munito AI | munito.ai | global | modelsdev |
| turing.ac.uk | turing.ac.uk | eu | aicredits |
| typesafe | — | unknown | litellm,openrouter |
| elorian | — | unknown | openrouter |
| aiand | — | unknown | litellm |
| Ant Digital | — | unknown | openrouter |
| eu_jev | — | unknown | litellm |
| laya | — | unknown | litellm |
| lemonade | — | unknown | litellm |
| nace | — | unknown | litellm |
| Parallel | — | unknown | openrouter |
| pinstripes | — | unknown | litellm |
| ricursiveai | — | unknown | openrouter |
