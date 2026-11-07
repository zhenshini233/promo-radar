"""首屏预算：内联载荷裁剪，全量拆分到 data.js / data.json。"""

import json
import re
import shutil
from pathlib import Path

from radar.delivery.site import INLINE_DEAL_LIMIT, INLINE_MONITOR_LIMIT, build_site
from radar.domain.models import RawItem, utcnow
from radar.domain.scoring import score_item
from radar.infra.config import GeneralConfig, RadarConfig
from radar.storage.repository import SqliteRepository

PROJECT = Path(__file__).resolve().parents[1]
INLINE_LIMIT_BYTES = 200_000


def _cfg(tmp_path) -> RadarConfig:
    shutil.copytree(PROJECT / "templates", tmp_path / "templates")
    blocks = []
    for i in range(100):
        blocks.append(
            f'[[provider]]\nname = "P{i}"\nurls = [\n'
            f'    {{ label = "home", url = "https://p{i}.example" }},\n]\n'
        )
    (tmp_path / "providers.toml").write_text("\n".join(blocks), encoding="utf-8")
    return RadarConfig(
        root=tmp_path,
        general=GeneralConfig(data_dir=str(tmp_path / "data")),
    )


def _seed(repo: SqliteRepository) -> None:
    now = utcnow()
    for i in range(120):
        repo.upsert_scored(
            score_item(RawItem(
                source="aicredits", title=f"注册送 ${i + 1} 额度",
                url=f"https://p{i}.example/promo", provider=f"P{i}",
                evidence="注册送额度，详情见官网活动页。" * 4,
            )),
            now,
        )
    for i in range(100):
        repo.upsert_snapshot(
            url=f"https://p{i}.example", provider=f"P{i}", label="home",
            content_hash="h", promo_keywords="", now=now, changed=False,
        )


def test_index_inline_payload_is_capped(tmp_path):
    cfg = _cfg(tmp_path)
    repo = SqliteRepository(cfg.data_dir / "radar.db")
    _seed(repo)
    out = build_site(cfg, repo)
    repo.close()

    html = out.read_text(encoding="utf-8")
    assert len(html.encode("utf-8")) < INLINE_LIMIT_BYTES

    match = re.search(
        r'<script type="application/json" id="radar-data">(.*?)</script>', html, re.S
    )
    assert match, "内联 payload 缺失"
    inline = json.loads(match.group(1))
    assert len(inline["deals"]) == INLINE_DEAL_LIMIT
    assert len(inline["monitors"]) == INLINE_MONITOR_LIMIT
    assert inline["source_vendors"] == {}
    assert inline["inline_meta"]["deals_total"] == 120
    assert inline["inline_meta"]["full_data"] == "data.js"


def test_data_js_carries_full_payload(tmp_path):
    cfg = _cfg(tmp_path)
    repo = SqliteRepository(cfg.data_dir / "radar.db")
    _seed(repo)
    out = build_site(cfg, repo)
    repo.close()

    text = (out.parent / "data.js").read_text(encoding="utf-8")
    assert text.startswith("window.__RADAR_FULL__=")
    full = json.loads(text[len("window.__RADAR_FULL__="):-1])
    assert len(full["deals"]) == 120
    assert len(full["monitors"]) == 100
    assert full["source_vendors"], "全量 data.js 应包含厂商清单"