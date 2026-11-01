"""CLI 入口：radar run / report / add-provider。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .delivery.notify import push_new_deals
from .delivery.site import build_site
from .infra.config import load_config, load_providers
from .pipeline.runner import run
from .storage.repository import SqliteRepository


def _print_report(report) -> None:
    print(f"运行时间: {report.finished_at:%Y-%m-%d %H:%M:%S} UTC")
    print(f"{'源':<14}{'状态':<8}{'抓取':>6}{'过线':>6}{'新增':>6}{'更新':>6}{'耗时':>9}  错误")
    for r in report.results:
        print(
            f"{r.name:<14}{r.status:<8}{r.fetched:>6}{r.kept:>6}{r.new:>6}{r.updated:>6}"
            f"{r.elapsed_ms:>7}ms  {r.error[:80]}"
        )
    print(
        f"\n合计: 新增 {len(report.new_deals)} 条，归档过期 {report.expired_count} 条"
    )
    for deal in report.new_deals[:10]:
        print(f"  + {deal.title[:70]} ({deal.source})")
    if len(report.new_deals) > 10:
        print(f"  ... 共 {len(report.new_deals)} 条，详见 digest.html")


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    store = SqliteRepository(cfg.data_dir / "radar.db")
    only = [s.strip() for s in (args.only or "").split(",") if s.strip()] or None
    try:
        report = run(cfg, store, only=only)
        _print_report(report)

        if not args.no_report:
            out = build_site(cfg, store)
            print(f"\n站点已生成: {out.parent}/")

        if not args.no_notify:
            ok, msg = push_new_deals(cfg, report.new_deals)
            print(f"推送: {msg}" if ok else f"推送跳过/失败: {msg}")
        return 0 if report.ok else 1
    finally:
        store.close()


def cmd_serve(args) -> int:
    from .server import serve

    cfg = load_config(args.config)
    serve(cfg, port=args.port)
    return 0


def cmd_report(args) -> int:
    cfg = load_config(args.config)
    store = SqliteRepository(cfg.data_dir / "radar.db")
    try:
        out = build_site(cfg, store)
        print(f"站点已生成: {out.parent}/")
        return 0
    finally:
        store.close()


def cmd_add_provider(args) -> int:
    cfg = load_config(args.config)
    existing = {p["name"].lower() for p in load_providers(cfg.providers_file)}
    if args.name.lower() in existing:
        print(f"错误: {args.name} 已存在于 providers.toml", file=sys.stderr)
        return 1

    urls = list(args.url)
    if not urls:
        print("错误: 至少提供一个 --url", file=sys.stderr)
        return 1

    lines = [f"\n[[provider]]", f'name = "{args.name}"', "urls = ["]
    for i, url in enumerate(urls):
        label = args.label[i] if i < len(args.label) else "home"
        lines.append(f'    {{ label = "{label}", url = "{url}" }},')
    lines.append("]")
    if args.note:
        lines.append(f'notes = "{args.note}"')

    with open(cfg.providers_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已添加 {args.name}（{len(urls)} 个页面）到 {cfg.providers_file}")
    print("下次 radar run 时会先建立内容基线，之后变化才会产生事件。")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="radar", description="AI API 促销活动聚合监控")
    parser.add_argument("--config", help="config.toml 路径（默认项目根/环境变量 RADAR_CONFIG）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="抓取所有源并生成报告/推送")
    p_run.add_argument("--no-report", action="store_true", help="跳过生成站点")
    p_run.add_argument("--no-notify", action="store_true", help="跳过 Telegram 推送")
    p_run.add_argument("--only", help="只跑指定源（逗号分隔，如 aicredits,watchlist）")

    p_serve = sub.add_parser("serve", help="本地服务：dashboard + 手动刷新（部分源）")
    p_serve.add_argument("--port", type=int, default=8790)
    p_serve.add_argument("--config")
    p_serve.set_defaults(func=cmd_serve)

    p_rep = sub.add_parser("report", help="仅根据已有数据重新渲染报告")
    p_rep.add_argument("--config")

    p_add = sub.add_parser("add-provider", help="添加服务商到 watchlist")
    p_add.add_argument("name", help="服务商名称")
    p_add.add_argument("--url", action="append", help="监控页面 URL（可多次）")
    p_add.add_argument("--label", action="append", default=[], help="页面标签（与 --url 顺序对应）")
    p_add.add_argument("--note", default="", help="备注")

    p_run.set_defaults(func=cmd_run)
    p_rep.set_defaults(func=cmd_report)
    p_add.set_defaults(func=cmd_add_provider)

    args = parser.parse_args(argv)
    return args.func(args)
