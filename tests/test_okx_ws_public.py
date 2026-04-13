from __future__ import annotations

import threading
from datetime import datetime

import pytest

from eth_backtester.models import Candle
from eth_backtester.okx_ws_public import OKXPublicRealtimeFeed


@pytest.fixture()
def bare_feed() -> OKXPublicRealtimeFeed:
    feed = OKXPublicRealtimeFeed.__new__(OKXPublicRealtimeFeed)
    feed.inst_id = "ETH-USDT-SWAP"
    feed.bar = "15m"
    feed.candles_limit = 5
    feed._lock = threading.Lock()
    feed._stop_event = threading.Event()
    feed._candles = [
        Candle(datetime(2026, 4, 13, 0, 0), 100.0, 101.0, 99.0, 100.5, 10.0),
        Candle(datetime(2026, 4, 13, 0, 15), 100.5, 102.0, 100.0, 101.5, 12.0),
    ]
    feed._latest_price = None
    feed._latest_price_ts = None
    feed._status = "connected"
    feed._last_error = None
    return feed


def test_handle_candle_update_backfills_missing_gap(monkeypatch: pytest.MonkeyPatch, bare_feed: OKXPublicRealtimeFeed) -> None:
    def fake_backfill() -> None:
        bare_feed._candles = [
            Candle(datetime(2026, 4, 13, 0, 0), 100.0, 101.0, 99.0, 100.5, 10.0),
            Candle(datetime(2026, 4, 13, 0, 15), 100.5, 102.0, 100.0, 101.5, 12.0),
            Candle(datetime(2026, 4, 13, 0, 30), 101.5, 103.0, 101.0, 102.5, 11.0),
            Candle(datetime(2026, 4, 13, 0, 45), 102.5, 104.0, 102.0, 103.5, 13.0),
        ]

    monkeypatch.setattr(bare_feed, "_backfill_recent_candles", fake_backfill)

    bare_feed._handle_candle_update(
        [["1776042000000", "103.5", "105.0", "103.0", "104.5", "15.0", "0", "0", "1"]]
    )

    assert [candle.timestamp for candle in bare_feed._candles] == [
        datetime(2026, 4, 13, 0, 0),
        datetime(2026, 4, 13, 0, 15),
        datetime(2026, 4, 13, 0, 30),
        datetime(2026, 4, 13, 0, 45),
        datetime(2026, 4, 13, 1, 0),
    ]


def test_backfill_recent_candles_replaces_cache(monkeypatch: pytest.MonkeyPatch, bare_feed: OKXPublicRealtimeFeed) -> None:
    refreshed = [
        Candle(datetime(2026, 4, 13, 0, 15), 100.5, 102.0, 100.0, 101.5, 12.0),
        Candle(datetime(2026, 4, 13, 0, 30), 101.5, 103.0, 101.0, 102.5, 11.0),
        Candle(datetime(2026, 4, 13, 0, 45), 102.5, 104.0, 102.0, 103.5, 13.0),
    ]

    monkeypatch.setattr(
        "eth_backtester.okx_ws_public.fetch_eth_ohlcv_from_okx",
        lambda inst_id, bar, candles_limit: refreshed,
    )

    bare_feed._backfill_recent_candles()

    assert bare_feed._candles == refreshed
