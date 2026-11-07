"""config.local.toml 代理设置写入：保留其他键、校验、拒绝损坏文件。"""

import pytest

from radar.infra.local_config import LocalConfigError, read_proxy, update_proxy


def test_update_proxy_preserves_other_keys(tmp_path):
    p = tmp_path / "config.local.toml"
    p.write_text(
        '# 本地配置\n[proxy]\nurl = ""\nbypass = ["artificialanalysis.ai"]\n\n'
        '[notify.telegram]\nbot_token = "secret"\n',
        encoding="utf-8",
    )

    saved = update_proxy(p, "127.0.0.1:10808")
    text = p.read_text(encoding="utf-8")

    assert saved["url"] == "http://127.0.0.1:10808"
    assert read_proxy(p)["url"] == "http://127.0.0.1:10808"
    assert 'bypass = ["artificialanalysis.ai"]' in text
    assert 'bot_token = "secret"' in text
    assert text.startswith("# 本地配置")


def test_update_proxy_creates_file_and_can_clear(tmp_path):
    p = tmp_path / "config.local.toml"
    update_proxy(p, "")
    assert p.exists()
    assert read_proxy(p)["url"] == ""

    update_proxy(p, "socks5://127.0.0.1:1080")
    assert read_proxy(p)["url"] == "socks5://127.0.0.1:1080"


def test_invalid_proxy_rejected(tmp_path):
    p = tmp_path / "config.local.toml"
    with pytest.raises(LocalConfigError):
        update_proxy(p, "ftp://127.0.0.1:21")
    with pytest.raises(LocalConfigError):
        update_proxy(p, 'http://127.0.0.1:1080"')
    assert not p.exists()


def test_broken_toml_is_not_overwritten(tmp_path):
    p = tmp_path / "config.local.toml"
    p.write_text("[proxy\nurl = 1\n", encoding="utf-8")
    original = p.read_text(encoding="utf-8")

    with pytest.raises(LocalConfigError):
        update_proxy(p, "http://127.0.0.1:10808")
    assert p.read_text(encoding="utf-8") == original