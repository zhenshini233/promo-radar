"""Day 15：snapshots ↔ Provider 只读关联报告。

不改表结构；用注册域把监控页关联到 provider_domains。
输出 docs/discovery/PROVIDER_PAGES_v0.md
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar.infra.config import load_config  # noqa: E402
from radar.storage.repository import SqliteRepository  # noqa: E402

OUT = ROOT / "docs/discovery/PROVIDER_PAGES_v0.md"


def main() -> None:
    cfg = load_config()
    repo = SqliteRepository(cfg.data_dir / "radar.db")
    s = repo.provider_page_stats(limit=30)
    repo.close()

    lines = [
        "# 监控页 ↔ Provider 关联 v0（Day 15）\n",
        "> 只读：用 `snapshots.url` 的注册域匹配 `provider_domains.domain`。",
        "> 不修改 snapshots，不新增列。\n",
        "## 摘要\n",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 监控页总数 | {s['total_pages']} |",
        f"| 已关联 | {s['linked_pages']} |",
        f"| 关联率 | {s['link_rate']:.1%} |",
        f"| 未关联 | {s['unlinked_pages']} |",
        f"| 关联到非厂商（ignored） | {s['ignored_pages']} |",
        f"| 有页的 Provider | {s['providers_with_pages']} |",
        f"| 无页的 Provider | {s['providers_without_pages']} |\n",
        "## 按分类\n",
        "| 分类 | 页数 | Provider 数 |",
        "|---|---:|---:|",
    ]
    for cat, v in s["by_category"].items():
        lines.append(f"| {cat} | {v['pages']} | {v['providers']} |")
    lines += ["", f"## 名称不一致（{s['mismatch_total']}，Top 30）\n",
              "| URL | snapshots.provider | 关联 Provider |", "|---|---|---|"]
    for m in s["mismatch"]:
        lines.append(f"| {m['url']} | {m['snapshot_provider']} | {m['provider']} |")
    lines += ["", f"## 未关联（{s['unlinked_total']}，Top 30）\n",
              "| URL | snapshots.provider |", "|---|---|"]
    for u in s["unlinked_samples"]:
        lines.append(f"| {u['url']} | {u['provider']} |")
    lines += ["", f"## 无监控页的 Provider（{s['providers_without_pages']}，Top 30）\n",
              "| 名称 | slug | 状态 |", "|---|---|---|"]
    for m in s["missing_samples"]:
        lines.append(f"| {m['name']} | {m['slug']} | {m['status']} |")
    lines += ["", "## 结论\n",
              f"- 关联率 **{s['link_rate']:.1%}**，说明 Provider 实体与监控页已可对账。",
              "- 未关联页通常是：无官网条目、促销/活动页、域名未进 provider_domains。",
              "- 名称不一致不代表错，多为来源写法差异（如 OpenAI / openai）。",
              "- 下一步可把关联结果做成 dashboard 分组，或迁移 snapshots.provider_id。\n"]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"pages={s['total_pages']} linked={s['linked_pages']} rate={s['link_rate']:.1%} "
        f"unlinked={s['unlinked_pages']} ignored={s['ignored_pages']} "
        f"providers_with_pages={s['providers_with_pages']} missing={s['providers_without_pages']}"
    )
    print("by_category", s["by_category"])


if __name__ == "__main__":
    main()