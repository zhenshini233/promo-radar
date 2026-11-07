# 监控页 ↔ Provider 关联 v0（Day 15）

> 只读：用 `snapshots.url` 的注册域匹配 `provider_domains.domain`。
> 不修改 snapshots，不新增列。

## 摘要

| 指标 | 数值 |
|---|---:|
| 监控页总数 | 345 |
| 已关联 | 318 |
| 关联率 | 92.2% |
| 未关联 | 19 |
| 关联到非厂商（ignored） | 8 |
| 有页的 Provider | 297 |
| 无页的 Provider | 73 |

## 按分类

| 分类 | 页数 | Provider 数 |
|---|---:|---:|
| inference | 86 | 83 |
| model_lab | 49 | 39 |
| cloud | 46 | 42 |
| gpu | 39 | 37 |
| app | 32 | 31 |
| ai_infra | 25 | 24 |
| aggregator | 21 | 21 |
| unknown | 14 | 14 |
| relay | 6 | 6 |

## 名称不一致（91，Top 30）

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

## 未关联（19，Top 30）

| URL | snapshots.provider |
|---|---|
| https://cloud.siliconflow.cn/pricing | SiliconFlow |
| https://www.parasail.io/ | Parasail |
| https://mimo.mi.com/ | Xiaomi-MiMo |
| https://www.liquid.ai/pricing | Liquid |
| https://dev.writer.com/ | Writer |
| https://aionlabs.ai/pricing | Aion-Labs |
| https://moondream.ai/ | Moondream |
| https://scaledown.ai/ | Scaledown |
| https://elorian.ai/ | Elorian |
| https://typesafe.ai/ | Typesafe |
| https://relace.io/ | Relace |
| https://github.com | Vercel AI Gateway |
| https://openrouter.ai | OpenRouter |
| https://huggingface.co | Hugging Face |
| https://ovh.net | OVHcloud AI Endpoints |
| https://www.chinamobileltd.com | 中国移动 |
| https://neon.tech | Neon |
| https://www.openbmb.cn | OpenBMB |
| https://www.tii.ae | TII（阿布扎比技术创新院） |

## 无监控页的 Provider（73，Top 30）

| 名称 | slug | 状态 |
|---|---|---|
| OCI Generative AI | oracle | monitored |
| OpenAI | openai | monitored |
| Xiaomi | xiaomi | monitored |
| Genesis Cloud | genesiscloud-com | monitored |
| Infer by Flow7 | flow7 | monitored |
| kluster.ai | kluster | monitored |
| KT | kt | monitored |
| Lightricks | lightricks | monitored |
| Makora | makora | monitored |
| Phala | phala | monitored |
| Pioneer | pioneer | monitored |
| Prismml | prismml | monitored |
| routing.run | routingrun | monitored |
| scaledown | scaledown | monitored |
| SenseNova (China) | sensenova | monitored |
| Systalyze | systalyze | monitored |
| Tensormesh | tensormesh | monitored |
| Vultr | vultr | monitored |
| Clarifai | clarifai | monitored |
| aion-labs | aion | monitored |
| moondream | moondream | monitored |
| Parasail | parasail | monitored |
| relace | relace | monitored |
| writer | writer | monitored |
| aistudentpack.com | aistudentpack | monitored |
| AMD | amd | monitored |
| Fishaudio | fishaudio | monitored |
| Heygen | heygen | monitored |
| Leonardo AI | leonardo | monitored |
| lovable.dev | lovable | monitored |

## 结论

- 关联率 **92.2%**，说明 Provider 实体与监控页已可对账。
- 未关联页通常是：无官网条目、促销/活动页、域名未进 provider_domains。
- 名称不一致不代表错，多为来源写法差异（如 OpenAI / openai）。
- 下一步可把关联结果做成 dashboard 分组，或迁移 snapshots.provider_id。
