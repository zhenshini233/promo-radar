"""HTTP 硬性总时长：慢响应必须在 deadline 内返回失败，不能拖住整轮。"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from radar.infra.http import get_text


class SlowHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(5)
        body = b"slow"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def slow_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def test_get_text_respects_total_deadline(slow_server):
    client = httpx.Client(timeout=httpx.Timeout(30.0, connect=3.0))
    t0 = time.perf_counter()
    try:
        with pytest.raises(RuntimeError):
            get_text(client, slow_server, timeout=1.0, retries=0)
        elapsed = time.perf_counter() - t0
    finally:
        client.close()
    assert elapsed < 2.5, f"deadline 未生效，耗时 {elapsed:.1f}s"