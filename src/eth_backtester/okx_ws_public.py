from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone

import websockets

from .download import fetch_eth_ohlcv_from_okx
from .models import Candle

OKX_PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"


class OKXPublicRealtimeFeed:
    def __init__(self, inst_id: str, bar: str, candles_limit: int = 300) -> None:
        self.inst_id = inst_id
        self.bar = bar
        self.candles_limit = candles_limit
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._candles: list[Candle] = []
        self._latest_price: float | None = None
        self._latest_price_ts: str | None = None
        self._status = "connecting"
        self._last_error: str | None = None
        self._seed_candles()
        self._thread = threading.Thread(target=self._run_loop, name=f"okx-ws-{inst_id}-{bar}", daemon=True)
        self._thread.start()

    def _seed_candles(self) -> None:
        try:
            candles = fetch_eth_ohlcv_from_okx(inst_id=self.inst_id, bar=self.bar, candles_limit=self.candles_limit)
            with self._lock:
                self._candles = candles
                self._status = "connecting"
                self._last_error = None
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._last_error = f"REST seed failed: {exc}"

    def _run_loop(self) -> None:
        asyncio.run(self._runner())

    async def _runner(self) -> None:
        backoff_seconds = 1.0
        while not self._stop_event.is_set():
            try:
                await self._run_ws_session()
                backoff_seconds = 1.0
            except Exception as exc:
                with self._lock:
                    self._status = "error"
                    self._last_error = str(exc)
                if self._stop_event.is_set():
                    return
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2.0, 10.0)

    async def _run_ws_session(self) -> None:
        async with websockets.connect(OKX_PUBLIC_WS_URL, ping_interval=20, ping_timeout=20, max_size=2**20) as websocket:
            subscribe_payload = {
                "op": "subscribe",
                "args": [
                    {"channel": "tickers", "instId": self.inst_id},
                    {"channel": f"candle{self.bar}", "instId": self.inst_id},
                ],
            }
            await websocket.send(json.dumps(subscribe_payload))
            with self._lock:
                self._status = "connected"
                self._last_error = None
            async for raw_message in websocket:
                if self._stop_event.is_set():
                    return
                self._handle_message(raw_message)

    def _handle_message(self, raw_message: str) -> None:
        payload = json.loads(raw_message)
        if payload.get("event"):
            if payload.get("event") == "error":
                with self._lock:
                    self._status = "error"
                    self._last_error = payload.get("msg") or "unknown OKX websocket error"
            return

        channel = (payload.get("arg") or {}).get("channel", "")
        data = payload.get("data") or []
        if channel == "tickers":
            self._handle_ticker_update(data)
            return
        if channel.startswith("candle"):
            self._handle_candle_update(data)

    def _handle_ticker_update(self, rows: list[dict]) -> None:
        if not rows:
            return
        row = rows[0]
        last = row.get("last")
        if last in {None, ""}:
            return
        latest_price = float(last)
        latest_ts = self._format_timestamp(row.get("ts"))
        with self._lock:
            self._latest_price = latest_price
            self._latest_price_ts = latest_ts
            self._status = "connected"

    def _handle_candle_update(self, rows: list[list[str]]) -> None:
        parsed_rows: list[Candle] = []
        for row in rows:
            if len(row) < 6:
                continue
            timestamp_ms, open_price, high, low, close, volume, *_rest = row
            parsed_rows.append(
                Candle(
                    timestamp=self._parse_okx_timestamp(timestamp_ms),
                    open=float(open_price),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=float(volume),
                )
            )
        if not parsed_rows:
            return

        with self._lock:
            for candle in sorted(parsed_rows, key=lambda item: item.timestamp):
                if self._candles and self._candles[-1].timestamp == candle.timestamp:
                    self._candles[-1] = candle
                elif self._candles and any(existing.timestamp == candle.timestamp for existing in self._candles[-3:]):
                    self._candles = [candle if existing.timestamp == candle.timestamp else existing for existing in self._candles]
                elif not self._candles or candle.timestamp > self._candles[-1].timestamp:
                    self._candles.append(candle)
                    self._candles = self._candles[-self.candles_limit :]
            self._status = "connected"

    def snapshot(self) -> dict:
        with self._lock:
            candles = list(self._candles)
            latest_price = self._latest_price
            latest_price_ts = self._latest_price_ts
            status = self._status
            last_error = self._last_error
        return {
            "candles": candles,
            "latest_price": latest_price,
            "latest_price_ts": latest_price_ts,
            "status": status,
            "last_error": last_error,
            "transport": "okx_ws_public",
            "updated_at": time.time(),
        }

    def stop(self) -> None:
        self._stop_event.set()

    @staticmethod
    def _parse_okx_timestamp(timestamp_ms: str | int | None) -> datetime:
        if timestamp_ms in {None, ""}:
            return datetime.now(timezone.utc).replace(tzinfo=None)
        return datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _format_timestamp(timestamp_ms: str | int | None) -> str | None:
        if timestamp_ms in {None, ""}:
            return None
        return datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat()
