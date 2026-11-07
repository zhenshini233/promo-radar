"""providers.toml 的唯一写入入口：跨进程文件锁 + 原子替换 + 幂等去重。

背景：自动收编（aicredits / 盲区收编）、CLI `add-provider`、`radar serve`
手动刷新可能并发写同一个文件。原实现直接 `open(..., "a")`，并发时会
产生重复 provider 块，进程被中断时还会留下半截文件。

约定：
- 读-改-写全程持锁；
- 先写同目录临时文件、fsync，再 os.replace 原子替换；
- 已存在的 name（大小写不敏感）或注册域相同的条目直接跳过；
- 只追加，不重排/不删除已有内容，避免破坏人工维护的注释与顺序。
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

from ..domain.domains import registrable_domain
from .config import load_providers

LOCK_SUFFIX = ".lock"
LOCK_TIMEOUT = 15.0


class ProviderStoreError(RuntimeError):
    """providers.toml 无法安全读取/写入。"""


@contextmanager
def file_lock(lock_path: Path, timeout: float = LOCK_TIMEOUT):
    """跨进程独占锁（POSIX flock / Windows msvcrt.locking）。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(b"\0")
                fh.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"lock timeout after {timeout}s: {lock_path}")
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def atomic_write_text(path: Path, text: str, attempts: int = 3) -> None:
    """同目录临时文件 + os.replace，避免写到一半留下损坏文件。"""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for i in range(attempts):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == attempts - 1:
                    raise
                time.sleep(0.1 * (i + 1))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', "'")


def _render_entry(entry: dict) -> str:
    name = entry["name"].strip()
    urls = entry.get("urls") or []
    notes = (entry.get("notes") or "").strip()
    tier = entry.get("tier")
    lines = ["[[provider]]", f'name = "{_escape(name)}"']
    if tier in (1, 2, 3):
        lines.append(f"tier = {int(tier)}")
    lines.append("urls = [")
    for u in urls:
        label = _escape(str(u.get("label") or "home"))
        url = _escape(str(u.get("url") or "").strip())
        lines.append(f'    {{ label = "{label}", url = "{url}" }},')
    lines.append("]")
    if notes:
        lines.append(f'notes = "{_escape(notes)}"')
    return "\n".join(lines) + "\n"


def _known(entries: list[dict]) -> tuple[set[str], set[str]]:
    names = {str(p["name"]).strip().lower() for p in entries if p.get("name")}
    domains = {
        registrable_domain(str(u.get("url") or ""))
        for p in entries
        for u in (p.get("urls") or [])
    }
    domains.discard(None)
    return names, domains


def append_provider_entries(path: Path, entries: list[dict]) -> list[str]:
    """追加 provider 条目；返回实际追加的 name 列表。

    条目格式：{"name": str, "urls": [{"label": str, "url": str}], "notes": str}
    """
    path = Path(path)
    candidates = [
        e for e in entries
        if (e.get("name") or "").strip() and (e.get("urls") or [])
    ]
    if not candidates:
        return []

    with file_lock(path.with_name(path.name + LOCK_SUFFIX)):
        if path.exists():
            raw = path.read_text(encoding="utf-8")
            try:
                existing = load_providers(path)
            except Exception as e:  # noqa: BLE001 - TOML 损坏时拒绝写入，避免覆盖
                raise ProviderStoreError(f"providers.toml 解析失败，拒绝写入: {e}") from e
        else:
            raw = "# watchlist：推理服务商官网监控清单\n"
            existing = []

        known_names, known_domains = _known(existing)
        blocks: list[str] = []
        added: list[str] = []
        for entry in sorted(candidates, key=lambda e: e["name"].strip().lower()):
            name = entry["name"].strip()
            urls = entry.get("urls") or []
            domains = {
                registrable_domain(str(u.get("url") or "")) for u in urls
            }
            domains.discard(None)
            # name 已存在，或任一 URL 的注册域已被监控 → 幂等跳过
            if name.lower() in known_names or (domains & known_domains):
                continue
            blocks.append(_render_entry(entry))
            added.append(name)
            known_names.add(name.lower())
            known_domains |= domains

        if blocks:
            text = raw.rstrip("\n") + "\n\n" + "\n".join(blocks) + "\n"
            atomic_write_text(path, text)
        return added