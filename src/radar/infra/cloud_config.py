"""cloud_sources.toml 加载：把「每家园商一段配置」变成可执行的页面规格。

配置校验在加载时完成：缺 name/url 的条目直接跳过并打印，避免整轮失败。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CloudPageSpec:
    name: str
    provider: str
    url: str
    vertical: str = "cloud"
    category: str = "compute"
    offer_type: str = "free_tier"
    difficulty: int = 2
    claim_steps: str = ""
    expect: str = "free"
    interval_hours: int = 24
    regions: list[str] = field(default_factory=list)
    title_hint: str = ""
    selectors: dict = field(default_factory=dict)


def load_cloud_pages(path: Path) -> list[CloudPageSpec]:
    if not path.exists():
        return []
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    out: list[CloudPageSpec] = []
    for p in raw.get("page", []):
        name = str(p.get("name", "")).strip()
        url = str(p.get("url", "")).strip()
        if not name or not url:
            print(f"[cloud] 跳过无效配置：{p!r}")
            continue
        out.append(
            CloudPageSpec(
                name=name,
                provider=str(p.get("provider", name)).strip(),
                url=url,
                vertical=str(p.get("vertical", "cloud")).strip(),
                category=str(p.get("category", "compute")).strip(),
                offer_type=str(p.get("offer_type", "free_tier")).strip(),
                difficulty=int(p.get("difficulty", 2)),
                claim_steps=str(p.get("claim_steps", "")),
                expect=str(p.get("expect", "free")),
                interval_hours=int(p.get("interval_hours", 24)),
                regions=[str(x) for x in p.get("regions", [])],
                title_hint=str(p.get("title", "")).strip(),
                selectors=dict(p.get("selectors", {})),
            )
        )
    return out