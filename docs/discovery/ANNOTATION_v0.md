# 宇宙标注结果 v0（Day 13）

> 输入：425 条宇宙条目；规则见 `ANNOTATION_RULES_v0.md`。
> 本版只给初值，不改数据库、不改 providers.toml。

## 摘要

- 条目：**429**
- 分类未知：**35**
- 地区未知：**15**
- 低置信：**26**
- 非厂商（资助/活动/机构）：**11**
- 同品牌重复条目：**50**（去重后 **379** 个厂商）

## 分类分布

| 分类 | 数量 | 占比 |
|---|---:|---:|
| inference | 109 | 25.4% |
| model_lab | 76 | 17.7% |
| cloud | 58 | 13.5% |
| gpu | 46 | 10.7% |
| app | 41 | 9.6% |
| ai_infra | 35 | 8.2% |
| unknown | 35 | 8.2% |
| aggregator | 23 | 5.4% |
| relay | 6 | 1.4% |

## 主地区分布

| 地区 | 数量 |
|---|---:|
| us | 259 |
| cn | 49 |
| eu | 49 |
| global | 43 |
| unknown | 15 |
| apac | 14 |

## 相关性分桶

| 区间 | 数量 |
|---|---:|
| 0.80+ | 285 |
| 0.70-0.79 | 99 |
| 0.60-0.69 | 26 |
| 0.50-0.59 | 19 |

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
| blog.google | blog.google | unknown | global | aicredits |
| eu_jev | — | unknown | unknown | litellm |
| laya | — | unknown | unknown | litellm |
| lemonade | — | unknown | unknown | litellm |
| nace | — | unknown | unknown | litellm |
| Parallel | — | unknown | unknown | openrouter |
| pinstripes | — | unknown | unknown | litellm |
| ricursiveai | — | unknown | unknown | openrouter |
| Trelis AI Grants (up to | trelis.com | unknown | global | aicredits |

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
| Antler Disrupt | antler.co | global | aicredits |
| blog.google | blog.google | global | aicredits |
| eu_jev | — | unknown | litellm |
| IndiaAI Mission | indiaai.gov.in | apac | aicredits |
| laya | — | unknown | litellm |
| lemonade | — | unknown | litellm |
| nace | — | unknown | litellm |
| NAIRR Pilot | nairrpilot.org | us | aicredits |
| Parallel | — | unknown | openrouter |
| Pawsey Summer Internship | pawsey.org.au | apac | aicredits |
| pinstripes | — | unknown | litellm |
| ricursiveai | — | unknown | openrouter |
| Singapore Enterprise Compute Initiative | disg.gov.sg | apac | aicredits |
| Trelis AI Grants (up to | trelis.com | global | aicredits |
| UK Sovereign AI Fund | sovereignai.gov.uk | eu | aicredits |
