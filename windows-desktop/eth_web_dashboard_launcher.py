from __future__ import annotations

import sys
import traceback
from pathlib import Path


def get_runtime_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parents[1]


def get_log_path() -> Path:
    return Path.home() / "ETH_15M_Web_Dashboard.log"


def write_log(message: str) -> None:
    log_path = get_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")


ROOT = get_runtime_root()
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

WINDOW_TITLE = "ETH 15M 独立桌面看盘终端"


def ensure_runtime_assets() -> None:
    required_paths = [
        ROOT / "src",
        ROOT / "web-dashboard" / "index.html",
        ROOT / "presets" / "okx_15m_mtf_production_candidate.json",
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing bundled runtime assets: " + ", ".join(missing))


def launch_desktop_window() -> None:
    write_log("Desktop launcher bootstrap start")
    ensure_runtime_assets()

    import webview
    from eth_backtester.dashboard_server import build_dashboard_args, start_dashboard_server

    args = build_dashboard_args(["--no-browser", "--port", "0"])
    server, url, thread = start_dashboard_server(args)
    write_log(f"Dashboard window starting at {url}")
    try:
        webview.create_window(
            WINDOW_TITLE,
            url,
            width=1600,
            height=980,
            min_size=(1280, 760),
            background_color="#0a0f1a",
            text_select=True,
        )
        try:
            webview.start(gui="edgechromium", debug=False)
        except Exception as exc:
            write_log(f"EdgeChromium launch failed, fallback to default backend: {exc}")
            webview.start(debug=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        write_log("Dashboard window stopped")


if __name__ == "__main__":
    try:
        launch_desktop_window()
    except Exception:
        write_log(traceback.format_exc())
        raise
