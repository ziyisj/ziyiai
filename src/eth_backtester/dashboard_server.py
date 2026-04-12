from __future__ import annotations

import argparse
import json
import socket
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .cli import apply_preset_args, build_parser
from .indicators import exponential_moving_average, relative_strength_index, simple_moving_average
from .live import build_okx_live_dashboard_bundle


def get_runtime_root() -> Path:
    import sys

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parents[2]


ROOT = get_runtime_root()
STATIC_DIR = ROOT / "web-dashboard"
DEFAULT_PRESET = ROOT / "presets" / "okx_15m_mtf_production_candidate.json"


def _serialize_candles(candles):
    return [
        {
            "time": candle.timestamp.isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }
        for candle in candles
    ]


def _build_indicator_payload(candles):
    closes = [c.close for c in candles]
    ema12 = exponential_moving_average(closes, 12)
    ema26 = exponential_moving_average(closes, 26)
    macd = [None if a is None or b is None else a - b for a, b in zip(ema12, ema26)]
    macd_seed = [v if v is not None else 0.0 for v in macd]
    signal = exponential_moving_average(macd_seed, 9)
    histogram = [None if m is None or s is None else m - s for m, s in zip(macd, signal)]

    return {
        "ma5": simple_moving_average(closes, 5),
        "ma10": simple_moving_average(closes, 10),
        "ma20": simple_moving_average(closes, 20),
        "rsi14": relative_strength_index(closes, 14),
        "macd": macd,
        "macd_signal": signal,
        "macd_histogram": histogram,
    }


class DashboardState:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.lock = threading.Lock()

    def _resolve_args(self, bar: str | None = None) -> argparse.Namespace:
        if not bar or bar == self.args.okx_bar:
            return self.args
        merged = vars(self.args).copy()
        merged["okx_bar"] = bar
        return argparse.Namespace(**merged)

    def fetch_payload(self, bar: str | None = None) -> dict:
        resolved_args = self._resolve_args(bar)
        with self.lock:
            candles, snapshot, realtime = build_okx_live_dashboard_bundle(resolved_args)
        return {
            "snapshot": snapshot.to_dict(),
            "candles": _serialize_candles(candles),
            "indicators": _build_indicator_payload(candles),
            "realtime": realtime,
            "meta": {
                "refresh_seconds": max(1, int(getattr(resolved_args, "dashboard_refresh_seconds", 1))),
                "instrument": resolved_args.okx_inst_id,
                "bar": resolved_args.okx_bar,
                "strategy": resolved_args.strategy,
                "stream_url": f"/api/dashboard-stream?bar={resolved_args.okx_bar}",
            },
        }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, state: DashboardState, **kwargs):
        self.state = state
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        return

    def _serve_sse_stream(self, bar: str | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        previous_body = None
        while True:
            payload = self.state.fetch_payload(bar=bar)
            body = json.dumps(payload, ensure_ascii=False)
            if body != previous_body:
                self.wfile.write(f"event: dashboard\ndata: {body}\n\n".encode("utf-8"))
                self.wfile.flush()
                previous_body = body
            time.sleep(0.5)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard":
            try:
                params = parse_qs(parsed.query)
                bar = params.get("bar", [None])[0]
                payload = self.state.fetch_payload(bar=bar)
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        if parsed.path == "/api/dashboard-stream":
            try:
                params = parse_qs(parsed.query)
                bar = params.get("bar", [None])[0]
                self._serve_sse_stream(bar=bar)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        return super().do_GET()


class ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def build_dashboard_args(cli_args: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dashboard-refresh-seconds", type=int, default=1)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--browser-path", type=Path)

    default_args = [
        "--preset",
        str(DEFAULT_PRESET),
        "--live-okx-snapshot",
        "--okx-inst-id",
        "ETH-USDT-SWAP",
        "--okx-bar",
        "15m",
        "--okx-candles",
        "300",
    ]
    args = parser.parse_args(default_args + (cli_args or []))
    return apply_preset_args(args)


def create_dashboard_server(args: argparse.Namespace) -> tuple[ReusableHTTPServer, str]:
    state = DashboardState(args)

    def handler(*handler_args, **handler_kwargs):
        DashboardHandler(*handler_args, state=state, **handler_kwargs)

    server = ReusableHTTPServer((args.host, args.port), handler)
    actual_port = server.server_address[1]
    url = f"http://{args.host}:{actual_port}/"
    return server, url


def wait_for_server(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"Dashboard server did not become ready within {timeout} seconds: {url}")


def start_dashboard_server(args: argparse.Namespace) -> tuple[ReusableHTTPServer, str, threading.Thread]:
    server, url = create_dashboard_server(args)
    thread = threading.Thread(target=server.serve_forever, name="eth-dashboard-server", daemon=True)
    thread.start()
    try:
        wait_for_server(url)
    except Exception:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        raise
    return server, url, thread


def run_dashboard_server(args: argparse.Namespace) -> str:
    server, url = create_dashboard_server(args)
    if not args.no_browser:
        webbrowser.open(url)
    print(f"Dashboard running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return url


def main(cli_args: list[str] | None = None) -> None:
    args = build_dashboard_args(cli_args)
    run_dashboard_server(args)


if __name__ == "__main__":
    main()
