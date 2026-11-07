# 监控页 ↔ Provider 关联 v0（Day 15）

> 只读：用 `snapshots.url` 的注册域匹配 `provider_domains.domain`。
> 不修改 snapshots，不新增列。

## 摘要

| 指标 | 数值 |
|---|---:|
| 监控页总数 | 366 |
| 已关联 | 364 |
| 关联率 | 99.5% |
| 未关联 | 2 |
| 关联到非厂商（ignored） | 0 |
| 有页的 Provider | 337 |
| 无页的 Provider | 33 |

## 按分类

| 分类 | 页数 | Provider 数 |
|---|---:|---:|
| inference | 95 | 91 |
| model_lab | 59 | 47 |
| cloud | 51 | 45 |
| gpu | 42 | 40 |
| app | 38 | 37 |
| ai_infra | 33 | 31 |
| aggregator | 22 | 22 |
| unknown | 18 | 18 |
| relay | 6 | 6 |

## 名称不一致（99，Top 30）

| URL | snapshots.provider | 关联 Provider |
|---|---|---|
| https://www.runpod.io/pricing | RunPod | RunPod Startup Program |
| https://boostmyagents.com | boostmyagents.com | boostmyagents |
| https://trycreatorai.com | trycreatorai.com | Creator AI |
| https://google.com | google.com | Google |
| https://helyxai.space | helyxai.space | Helyx AI |
| https://zeabur.com | zeabur.com | Zeabur Free Plan + |
| https://yandex.cloud | yandex.cloud | Yandex Cloud Startup Credits ($5,000 / |
| https://voyageai.com | voyageai.com | Voyageai |
| https://tripo3d.ai | tripo3d.ai | Tripo AI |
| https://speechmatics.com | speechmatics.com | Speechmatics |
| https://sentry.io | sentry.io | Sentry for Startups |
| https://sarvam.ai | sarvam.ai | sarvam |
| https://render.com | render.com | Render Startup Program |
| https://recraft.ai | recraft.ai | Recraft |
| https://primeintellect.ai | primeintellect.ai | PrimeIntellect |
| https://posthog.com | posthog.com | PostHog for Startups |
| https://pinecone.io | pinecone.io | Pinecone for Startups |
| https://t-cloud.com | t-cloud.com | Open Telekom Cloud / T Cloud Public |
| https://notion.com | notion.com | Notion for Startups |
| https://neon.com | neon.com | Neon |
| https://nvidia.com | nvidia.com | Nvidia |
| https://mongodb.com | mongodb.com | MongoDB for Startups |
| https://mixedbread.com | mixedbread.com | Mixedbread |
| https://mistral.ai | mistral.ai | Mistral |
| https://minimax.io | minimax.io | minimax |
| https://meshy.ai | meshy.ai | Meshy |
| https://linear.app | linear.app | Linear for Startups |
| https://langchain.com | langchain.com | LangSmith for Startups |
| https://ionos.com | ionos.com | IONOS Cloud |
| https://hubspot.com | hubspot.com | HubSpot for Startups |

## 未关联（2，Top 30）

| URL | snapshots.provider |
|---|---|
| https://openrouter.ai | OpenRouter |
| https://huggingface.co | Hugging Face |

## 无监控页的 Provider（33，Top 30）

| 名称 | slug | 状态 |
|---|---|---|
| Wandb | wandb | monitored |
| Avian | avian | in_universe |
| clf_ai_gateway | clfaigateway | in_universe |
| Cosine | cosine | in_universe |
| Crucible | crucible | in_universe |
| DekaLLM | dekallm | in_universe |
| Inferact vLLM | inferact | in_universe |
| inferenceapis | inferenceapis | in_universe |
| llamagate | llamagate | in_universe |
| Mara | mara | in_universe |
| ModelRun | modelrun | in_universe |
| nex-agi | nexagi | in_universe |
| NextBit | nextbit | in_universe |
| openinfer | openinfer | in_universe |
| Pearl Research | pearlresearch | in_universe |
| prism | prism | in_universe |
| publicai | publicai | in_universe |
| Quiver | quiver | in_universe |
| recursive | recursive | in_universe |
| refuseless | refuseless | in_universe |
| sail | sail | in_universe |
| Switchpoint | switchpoint | in_universe |
| xingchen-agi | xingchen | in_universe |
| aiand | aiand | in_universe |
| Ant Digital | antdigital | in_universe |
| dots-studio | dotsstudio | in_universe |
| eu_jev | eujev | in_universe |
| laya | laya | in_universe |
| lemonade | lemonade | in_universe |
| nace | nace | in_universe |

## 结论

- 关联率 **99.5%**，说明 Provider 实体与监控页已可对账。
- 未关联页通常是：无官网条目、促销/活动页、域名未进 provider_domains。
- 名称不一致不代表错，多为来源写法差异（如 OpenAI / openai）。
- 下一步可把关联结果做成 dashboard 分组，或迁移 snapshots.provider_id。
