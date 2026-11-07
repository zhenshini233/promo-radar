"""P0-3：从 providers.toml 移除非厂商监控页。

按 `[[provider]]` 块删除，保留注释与其它条目；默认 dry-run，加 --apply 才写。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar.infra.providers_store import atomic_write_text  # noqa: E402

TARGETS = {
    "trelis.com",
    "stripe.com",
    "nairrpilot.org",
    "antler.co",
    "blog.google",
    "IndiaAI",
    "Pawsey 超算中心",
    "sovereignai.gov.uk",
    "disg.gov.sg",
    "中国移动",
    "TII（阿布扎比技术创新院）",
    "OpenBMB",
}

BLOCK = re.compile(r"(?m)^\[\[provider\]\]\s*$")


def main() -> None:
    path = ROOT / "providers.toml"
    text = path.read_text(encoding="utf-8")
    parts = BLOCK.split(text)
    header, blocks = parts[0], parts[1:]
    kept, removed = [], []
    for b in blocks:
        m = re.search(r'(?m)^name\s*=\s*"(.+?)"', b)
        name = m.group(1) if m else ""
        if name in TARGETS:
            removed.append(name)
        else:
            kept.append(b)
    print(f"blocks={len(blocks)} removed={len(removed)} kept={len(kept)}")
    print("removed:", ", ".join(removed))
    if "--apply" in sys.argv:
        new = header + "".join("[[provider]]\n" + b for b in kept)
        atomic_write_text(path, new)
        print("written", path)


if __name__ == "__main__":
    main()