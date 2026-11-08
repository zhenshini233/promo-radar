"""端到端并行验证：两个源各 sleep 0.4s，并行总耗时应显著低于串行。

用本地 ThreadingHTTPServer 模拟 RSS 与 JSON 源，不访问外网，秒级完成。
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from radar.infra.config import load_config
from radar.pipeline.runner import run
from radar.storage.repository import SqliteRepository

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>test</title><link>https://example.com</link>
<item>
  <title>新用户注册送 $25 额度</title>
  <link>https://example.com/deal</link>
  <description>注册送 25 额度，限时活动</description>
</item>
</channel></rss>"""

MODELS = '{"acme": {"name": "Acme AI", "models": {"m1": {}}, "doc": "https://acme.ai"}}'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(0.4)  # 模拟慢源：串行会叠加，并行不会
        if self.path.startswith("/feed"):
            body, ctype = RSS, "application/rss+xml; charset=utf-8"
        else:
            body, ctype = MODELS, "application/json; charset=utf-8"
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_two_sources_fetch_in_parallel(tmp_path, local_server):
    data_dir = (tmp_path / "data").as_posix()
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f"""
[general]
data_dir = "{data_dir}"
http_timeout = 5
page_timeout = 2
max_source_workers = 5

[sources.linuxdo]
enabled = true
feeds = ["{local_server}/feed"]

[sources.modelsdev]
enabled = true
url = "{local_server}/models.json"

[[keywords]]
pattern = '注册.{{0,6}}送'
weight = 3.0
label = "注册送"
""",
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)
    store = SqliteRepository(cfg.data_dir / "radar.db")
    t0 = time.perf_counter()
    report = run(cfg, store)
    elapsed = time.perf_counter() - t0
    store.close()

    statuses = {r.name: r.status for r in report.results}
    assert statuses == {"linuxdo": "ok", "modelsdev": "ok"}
    assert len(report.new_offers) == 1
    assert report.success_rate == 1.0
    # 两个请求各 0.4s：并行 ~0.4s，串行 >=0.8s
    assert elapsed < 0.78, f"并行未生效，耗时 {elapsed:.2f}s"