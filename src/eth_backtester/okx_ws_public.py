from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import Candle

try:
    import websockets
except Exception:  # pragma: no cover
    websockets = None


OKX_PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"


@dataclass
class RealtimeMarketSnapshot:
    inst_id: str
    bar: str
    latest_price: float | None = None
    latest_price_ts: str | None = None
    candles: list[Candle] | None = None
    status: str = "disconnected"
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "inst_id": self.inst_id,
            "bar": self.bar,
            "latest_price": self.latest_price,
            "latest_price_ts": self.latest_price_ts,
            "status": self.status,
            "last_error": self.last_error,
            "candles": [
                {
                    "time": candle.timestamp.isoformat(),
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
                for candle in (self.candles or [])
            ],
        }


class OKXPublicWebSocketClient:
    def __init__(self, inst_id: str, bar: str, max_candles: int = 300, url: str = OKX_PUBLIC_WS_URL) -> None:
        self.inst_id = inst_id
        self.bar = bar
        self.max_candles = max_candles
        self.url = url
        self.snapshot = RealtimeMarketSnapshot(inst_id=inst_id, bar=bar, candles=[])
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def set_seed_candles(self, candles: list[Candle]) -> None:
        with self._lock:
            self.snapshot.candles = list(candles)[-self.max_candles:]
            if self.snapshot.candles and self.snapshot.latest_price is None:
                self.snapshot.latest_price = self.snapshot.candles[-1].close
                self.snapshot.latest_price_ts = self.snapshot.candles[-1].timestamp.isoformat()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name=f"okx-ws-{self.inst_id}-{self.bar}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def get_snapshot(self) -> RealtimeMarketSnapshot:
        with self._lock:
            return RealtimeMarketSnapshot(
                inst_id=self.snapshot.inst_id,
                bar=self.snapshot.bar,
                latest_price=self.snapshot.latest_price,
                latest_price_ts=self.snapshot.latest_price_ts,
                candles=list(self.snapshot.candles or []),
                status=self.snapshot.status,
                last_error=self.snapshot.last_error,
            )

    def _run_loop(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        if websockets is None:
            with self._lock:
                self.snapshot.status = "error"
                self.snapshot.last_error = "websockets dependency is not installed"
            return

        while not self._stop.is_set():
            try:
                with self._lock:
                    self.snapshot.status = "connecting"
                    self.snapshot.last_error = None
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "args": [
                            {"channel": "tickers", "instId": self.inst_id},
                            {"channel": "candle" + self.bar, "instId": self.inst_id},
                        ],
                    }))
                    with self._lock:
                        self.snapshot.status = "connected"
                    while not self._stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        self._handle_message(json.loads(raw))
            except Exception as exc:  # pragma: no cover
                with self._lock:
                    self.snapshot.status = "error"
                    self.snapshot.last_error = str(exc)
                await asyncio.sleep(2)

    def _handle_message(self, message: dict[str, Any]) -> None:
        arg = message.get("arg") or {}
        channel = arg.get("channel", "")
        data = message.get("data") or []
        if not data:
            return

        with self._lock:
            if channel == "tickers":
                item = data[0]
                last = item.get("last")
                ts = item.get("ts")
                if last is not None:
                    self.snapshot.latest_price = float(last)
                if ts is not None:
                    self.snapshot.latest_price_ts = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat()
                return

            if channel.startswith("candle"):
                parsed: list[Candle] = []
                for row in reversed(data):
                    ts, open_price, high, low, close, *_rest = row
                    vol = row[5] if len(row) > 5 else 0.0
                    parsed.append(
                        Candle(
                            timestamp=datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).replace(tzinfo=None),
                            open=float(open_price),
                            high=float(high),
                            low=float(low),
                            close=float(close),
                            volume=float(vol),
                        )
                    )
                existing = self.snapshot.candles or []
                by_ts = {c.timestamp: c for c in existing}
                for candle in parsed:
                    by_ts[candle.timestamp] = candle
                self.snapshot.candles = sorted(by_ts.values(), key=lambda c: c.timestamp)[-self.max_candles:]
                if self.snapshot.candles:
                    self.snapshot.latest_price = self.snapshot.candles[-1].close
                    self.snapshot.latest_price_ts = self.snapshot.candles[-1].timestamp.isoformat()


def normalize_ws_channel_for_bar(bar: str) -> str:
    return "candle" + bar
