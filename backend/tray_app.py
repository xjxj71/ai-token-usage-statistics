"""Windows tray entrypoint for the packaged desktop app.

Runs uvicorn in a background thread and hosts a pystray icon on the main
thread. Dev usage: ``python -m backend.tray_app``. Frozen usage: the
PyInstaller console-free executable.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend import paths

logger = logging.getLogger(__name__)

MUTEX_NAME = "Local\\AiTokenUsageStatistics"
# Inno Setup AppMutex matches the bare name without the namespace prefix.
APP_MUTEX_NAME = "AiTokenUsageStatistics"

_SERVER_REF: list[Any] = []
_SERVER_THREAD: list[threading.Thread] = []
_READY = threading.Event()
_SERVER_ERROR: list[str] = []


# ── Single instance ─────────────────────────────────────────────


def acquire_single_instance() -> int | None:
    """Return a mutex handle if we own the instance, else None (already running)."""
    if sys.platform != "win32":
        # Best-effort lock file on non-Windows (mainly for dev).
        lock = paths.data_dir() / "instance.lock"
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return 1  # sentinel non-None handle
        except FileExistsError:
            return None

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    ERROR_ALREADY_EXISTS = 183
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def release_single_instance(handle: int | None) -> None:
    if handle is None:
        return
    if sys.platform != "win32":
        try:
            (paths.data_dir() / "instance.lock").unlink(missing_ok=True)
        except OSError:
            pass
        return
    ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]


# ── Logging / stdio redirect ────────────────────────────────────


def redirect_stdio_and_logging() -> Path:
    """Send stdout/stderr and logging to a rotating app.log (noconsole safe)."""
    paths.init_user_dirs()
    log_path = paths.app_log_path()

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    class _Stream:
        def __init__(self) -> None:
            self._buf = ""

        def write(self, msg: str) -> int:
            self._buf += msg
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    logger.info("stdio: %s", line)
            return len(msg)

        def flush(self) -> None:
            if self._buf.strip():
                logger.info("stdio: %s", self._buf.strip())
            self._buf = ""

    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        stream = _Stream()
        sys.stdout = stream  # type: ignore[assignment]
        sys.stderr = stream  # type: ignore[assignment]

    return log_path


# ── Port / instance state ───────────────────────────────────────


def find_free_port(preferred: int, host: str = "127.0.0.1", attempts: int = 20) -> int:
    for port in range(preferred, preferred + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # No SO_REUSEADDR: we need a truthful "is this port free?" answer.
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"端口 {preferred}–{preferred + attempts - 1} 均被占用")


def write_instance_state(host: str, port: int, pid: int | None = None) -> dict[str, Any]:
    state = {
        "pid": pid if pid is not None else os.getpid(),
        "port": port,
        "host": host,
        "started_at": datetime.now(UTC).isoformat(),
        "base_url": f"http://{host}:{port}",
    }
    path = paths.instance_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def read_instance_state() -> dict[str, Any] | None:
    path = paths.instance_state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("base_url"):
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def clear_instance_state() -> None:
    try:
        paths.instance_state_path().unlink(missing_ok=True)
    except OSError:
        pass


def resolve_existing_base_url() -> str:
    state = read_instance_state()
    if state:
        return str(state.get("base_url") or f"http://127.0.0.1:{state.get('port', 8001)}")
    return "http://127.0.0.1:8001"


# ── Uvicorn in background thread ────────────────────────────────


def _serve(host: str, port: int) -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        import uvicorn

        from backend.main import app

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_config=None,
            lifespan="on",
            access_log=False,
        )
        server = uvicorn.Server(config)
        _SERVER_REF.append(server)
        loop.run_until_complete(server.serve())
    except Exception as exc:
        _SERVER_ERROR.append(f"{type(exc).__name__}: {exc}")
        logger.exception("uvicorn thread crashed")
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()
        _READY.set()


def start_server_thread(host: str, port: int) -> threading.Thread:
    t = threading.Thread(target=_serve, args=(host, port), name="uvicorn", daemon=True)
    _SERVER_THREAD.append(t)
    t.start()
    return t


def request_shutdown() -> None:
    for server in _SERVER_REF:
        server.should_exit = True
    for t in _SERVER_THREAD:
        t.join(timeout=5)


def wait_ready(base_url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"{base_url.rstrip('/')}/api/config"
    while time.monotonic() < deadline:
        if _SERVER_ERROR:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.2)
    return False


# ── Tray UI ─────────────────────────────────────────────────────


def _load_tray_image():
    from PIL import Image

    for cand in (
        paths.bundle_root() / "assets" / "tray-32.png",
        paths.app_root() / "assets" / "tray-32.png",
        paths.bundle_root() / "assets" / "icon-previews" / "variant-a.png",
        paths.app_root() / "assets" / "icon-previews" / "variant-a.png",
    ):
        if cand.is_file():
            return Image.open(cand)
    return Image.new("RGB", (32, 32), (79, 70, 229))


def show_tray(base_url: str) -> None:
    import pystray
    from pystray import Menu, MenuItem

    icon_image = _load_tray_image()
    state = {"url": base_url}

    def on_open(icon, _item):
        webbrowser.open(state["url"])

    def on_exit(icon, _item):
        request_shutdown()
        clear_instance_state()
        icon.stop()

    menu = Menu(
        MenuItem("打开面板", on_open, default=True),
        MenuItem("退出", on_exit),
    )
    icon = pystray.Icon(
        "ai-token-usage",
        icon_image,
        title=f"AI 用量统计 · 就绪 · {base_url}",
        menu=menu,
    )
    try:
        icon.run()
    except Exception:
        logger.exception("tray icon failed")
        request_shutdown()
        clear_instance_state()


def _notify(title: str, message: str) -> None:
    try:
        import pystray

        img = _load_tray_image()
        icon = pystray.Icon("ai-token-usage-notify", img, title=title)
        # Icon must be running for notify on some backends; best-effort only.
        threading.Thread(target=icon.run, daemon=True).start()
        time.sleep(0.3)
        icon.notify(message, title)
        time.sleep(0.5)
        icon.stop()
    except Exception:  # noqa: BLE001
        logger.info("notify fallback: %s — %s", title, message)


def main() -> int:
    paths.init_user_dirs()
    redirect_stdio_and_logging()

    handle = acquire_single_instance()
    if handle is None:
        url = resolve_existing_base_url()
        webbrowser.open(url)
        return 0

    from backend.config import settings

    host = settings.host or "127.0.0.1"
    preferred = int(settings.port or 8001)

    try:
        port = find_free_port(preferred, host=host if host != "0.0.0.0" else "127.0.0.1")
    except RuntimeError as exc:
        _notify("AI 用量统计", str(exc))
        release_single_instance(handle)
        return 1

    if host not in ("127.0.0.1", "::1", "localhost") and not settings.api_key:
        _notify(
            "AI 用量统计",
            "正在监听非本机地址且未设置 TOKEN_STAT_API_KEY，存在暴露风险",
        )

    base_url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    write_instance_state(host if host != "0.0.0.0" else "127.0.0.1", port)

    _notify("AI 用量统计", "正在启动…")
    start_server_thread(host, port)

    if not wait_ready(base_url):
        reason = _SERVER_ERROR[0] if _SERVER_ERROR else "启动超时"
        _notify("AI 用量统计", f"启动失败：{reason}")
        request_shutdown()
        clear_instance_state()
        release_single_instance(handle)
        return 1

    webbrowser.open(base_url)
    try:
        show_tray(base_url)
    finally:
        request_shutdown()
        clear_instance_state()
        release_single_instance(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
