"""本地服务模式：`radar serve` —— 静态 dashboard + 手动刷新 API。

- GET  /            及静态文件：site/ 目录
- GET  /api/status  {"running": bool, "last": {...}}
- POST /api/refresh {"sources": ["aicredits", ...]}  省略 = 全部源
  后台线程执行一轮抓取；进行中重复请求返回 running。

仅绑定 127.0.0.1，供本机使用；零第三方依赖（标准库实现）。
"""

from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .infra.config import load_config, load_providers
from .infra.local_config import LocalConfigError, read_proxy, update_proxy
from .infra.proxy import is_proxy_available
from .pipeline.runner import run
from .storage.repository import SqliteRepository

_lock = threading.Lock()
_state = {"running": False, "started_at": None, "finished_at": None, "error": ""}


def _build_site(cfg) -> None:
    """独立构建站点（避免 delivery↔pipeline 循环导入，延迟导入）。"""
    from .delivery.site import build_site

    repo = SqliteRepository(cfg.data_dir / "radar.db")
    try:
        build_site(cfg, repo)
    finally:
        repo.close()


def _refresh_worker(cfg, sources: list[str] | None) -> None:
    try:
        # 重新加载配置：代理面板保存后无需重启 serve 即可生效
        if getattr(cfg, "config_path", None):
            cfg = load_config(cfg.config_path)
        repo = SqliteRepository(cfg.data_dir / "radar.db")
        try:
            run(cfg, repo, only=sources or None)
        finally:
            repo.close()
        _build_site(cfg)
        _state["error"] = ""
    except Exception as e:  # noqa: BLE001 - 后台刷新失败回传给页面
        _state["error"] = f"{type(e).__name__}: {e}"
    finally:
        import datetime as _dt

        _state["finished_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _state["running"] = False


class RadarHandler(SimpleHTTPRequestHandler):
    cfg = None  # 由 make_server 注入
    registry_names: list[str] = []

    def log_message(self, fmt, *args):  # 静默默认访问日志
        pass

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/status":
            last = None
            repo = SqliteRepository(self.cfg.data_dir / "radar.db")
            try:
                last = repo.last_run()
            finally:
                repo.close()
            self._json({"running": _state["running"], "error": _state["error"],
                        "finished_at": _state["finished_at"], "last": last})
            return
        if path == "/api/proxy":
            self._handle_proxy_get()
            return
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/refresh":
            self._handle_refresh()
            return
        if path == "/api/feedback":
            self._handle_feedback()
            return
        if path == "/api/proxy":
            self._handle_proxy_save()
            return
        self._json({"error": "not found"}, 404)

    def _local_proxy_path(self):
        return self.cfg.root / "config.local.toml"

    def _proxy_payload(self) -> dict:
        info = read_proxy(self._local_proxy_path())
        if not info.get("url") and self.cfg.proxy_url:
            info["url"] = self.cfg.proxy_url
            info["source"] = "config.toml / 环境变量"
        else:
            info["source"] = "config.local.toml"
        info["available"] = (
            is_proxy_available(info["url"], timeout=self.cfg.proxy_detect_timeout)
            if info.get("url") else True
        )
        info["auto_detect"] = bool(info.get("auto_detect", True))
        return info

    def _handle_proxy_get(self):
        self._json(self._proxy_payload())

    def _handle_proxy_save(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        url = str(body.get("url") or "").strip()
        auto_detect = bool(body.get("auto_detect", True))
        try:
            saved = update_proxy(self._local_proxy_path(), url, auto_detect)
        except LocalConfigError as e:
            self._json({"error": str(e)}, 400)
            return

        available = (
            is_proxy_available(saved["url"], timeout=self.cfg.proxy_detect_timeout)
            if saved["url"] else True
        )
        if not saved["url"]:
            message = "已清空代理，后续运行使用直连。"
        elif available:
            message = "已保存，代理端口可达；下一轮刷新生效。"
        else:
            message = "已保存，但代理端口当前不可达；运行时会自动改为直连。"
        self._json({"ok": True, "url": saved["url"], "auto_detect": saved["auto_detect"],
                    "available": available, "message": message})

    def _handle_refresh(self):
        if _state["running"]:
            self._json({"running": True, "message": "上一轮刷新仍在进行"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        sources = body.get("sources") or None
        if sources:
            valid = set(self.registry_names)
            sources = [s for s in sources if s in valid] or None

        _state["running"] = True
        _state["error"] = ""
        import datetime as _dt

        _state["started_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        threading.Thread(target=_refresh_worker, args=(self.cfg, sources), daemon=True).start()
        self._json({"started": True, "sources": sources or "all"})

    def _handle_feedback(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        key = (body.get("key") or "").strip()
        vote = (body.get("vote") or "").strip()
        note = (body.get("note") or "").strip()
        if not key:
            self._json({"error": "missing key"}, 400)
            return
        if vote not in ("up", "down", "snooze", ""):
            self._json({"error": f"bad vote: {vote}"}, 400)
            return
        repo = SqliteRepository(self.cfg.data_dir / "radar.db")
        try:
            repo.record_feedback(key, vote, note=note)
        finally:
            repo.close()
        self._json({"ok": True, "key": key, "vote": vote})


def make_server(cfg, host: str = "127.0.0.1", port: int = 8790) -> ThreadingHTTPServer:
    site_dir = cfg.data_dir / "site"
    site_dir.mkdir(parents=True, exist_ok=True)

    class BoundHandler(RadarHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(site_dir), **kw)

    BoundHandler.cfg = cfg
    BoundHandler.registry_names = _source_names()
    return ThreadingHTTPServer((host, port), BoundHandler)


def _source_names() -> list[str]:
    from .collectors.base import registered_names

    return registered_names()


def serve(cfg, port: int) -> None:
    # 启动前先保证站点存在
    _build_site(cfg)
    httpd = make_server(cfg, port=port)
    names = ", ".join(_source_names())
    print(f"promo-radar 本地服务已启动: http://127.0.0.1:{port}/")
    print(f"  页面: 浏览器打开上面地址；刷新: 页面右上角按钮（可勾选部分源）")
    print(f"  可用源: {names}")
    print("  Ctrl+C 退出")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
