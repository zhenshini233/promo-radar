"""runner 测试：源故障隔离、幂等、阈值过滤协同。"""

import radar.pipeline.runner as runner_mod
from radar.infra.config import GeneralConfig, KeywordRule, RadarConfig
from radar.domain.models import RawItem, RunReport
from radar.storage.repository import SqliteRepository


class FakeOKSource:
    name = "fake_ok"

    def fetch(self, ctx):
        return [
            RawItem(source="fake_ok", title="新用户注册送 $25 额度",
                    url="https://example.com/a", evidence="welcome credit"),
            RawItem(source="fake_ok", title="瑞幸抽免单", url="https://example.com/noise"),
        ]


class FakeFailSource:
    name = "fake_fail"

    def fetch(self, ctx):
        raise RuntimeError("boom")


def _cfg(tmp_path) -> RadarConfig:
    return RadarConfig(
        root=tmp_path,
        general=GeneralConfig(data_dir=str(tmp_path / "data"), expire_days=45, promo_threshold=4.0),
        keywords=[KeywordRule(r"注册.{0,6}送", 3.0, "注册送")],
        sources={"fake_ok": {"enabled": True}, "fake_fail": {"enabled": True}},
    )


def test_runner_isolates_source_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "build_sources", lambda cfg: [FakeOKSource(), FakeFailSource()])
    cfg = _cfg(tmp_path)
    store = SqliteRepository(tmp_path / "test.db")
    report = runner_mod.run(cfg, store)
    store.close()

    by_name = {r.name: r for r in report.results}
    assert by_name["fake_fail"].status == "error" and "boom" in by_name["fake_fail"].error
    assert by_name["fake_ok"].status == "ok"
    assert by_name["fake_ok"].fetched == 2
    assert by_name["fake_ok"].kept == 1, "噪音应在阈值过滤阶段被丢弃"
    assert len(report.new_deals) == 1
    assert report.ok  # 有源成功即视为运行成功


def test_runner_idempotent_second_run(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "build_sources", lambda cfg: [FakeOKSource()])
    cfg = _cfg(tmp_path)
    store = SqliteRepository(tmp_path / "test.db")

    first = runner_mod.run(cfg, store)
    second = runner_mod.run(cfg, store)
    store.close()

    assert len(first.new_deals) == 1
    assert len(second.new_deals) == 0, "第二次运行不应产生新增（去重幂等）"
    by_name = {r.name: r for r in second.results}
    assert by_name["fake_ok"].updated == 0
