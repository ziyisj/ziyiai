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
    feed._last_ws_message_monotonic = 100.0
    feed._last_rest_refresh_monotonic = 0.0
    feed._stale_refresh_inflight = False
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


def test_snapshot_backfills_when_websocket_silently_stales(monkeypatch: pytest.MonkeyPatch, bare_feed: OKXPublicRealtimeFeed) -> None:
    calls: list[str] = []

    monkeypatch.setattr(bare_feed, "_trigger_stale_backfill", lambda: calls.append("backfill"))
    monkeypatch.setattr("eth_backtester.okx_ws_public.time.monotonic", lambda: 170.0)

    bare_feed.snapshot()

    assert calls == ["backfill"]


def test_snapshot_skips_redundant_backfill_when_recently_refreshed(monkeypatch: pytest.MonkeyPatch, bare_feed: OKXPublicRealtimeFeed) -> None:
    calls: list[str] = []

    def fake_backfill() -> None:
        calls.append("backfill")

    bare_feed._last_rest_refresh_monotonic = 168.0
    monkeypatch.setattr(bare_feed, "_backfill_recent_candles", fake_backfill)
    monkeypatch.setattr("eth_backtester.okx_ws_public.time.monotonic", lambda: 170.0)

    bare_feed.snapshot()

    assert calls == []


def test_snapshot_throttles_retries_after_recent_stale_backfill_attempt(monkeypatch: pytest.MonkeyPatch, bare_feed: OKXPublicRealtimeFeed) -> None:
    calls: list[str] = []

    bare_feed._last_rest_refresh_monotonic = 170.0
    monkeypatch.setattr(bare_feed, "_trigger_stale_backfill", lambda: calls.append("backfill"))
    monkeypatch.setattr("eth_backtester.okx_ws_public.time.monotonic", lambda: 171.0)

    bare_feed.snapshot()

    assert calls == []


def test_snapshot_only_triggers_one_stale_backfill_while_previous_attempt_is_inflight(monkeypatch: pytest.MonkeyPatch, bare_feed: OKXPublicRealtimeFeed) -> None:
    calls: list[str] = []

    monkeypatch.setattr(bare_feed, "_trigger_stale_backfill", lambda: calls.append("backfill"))
    monkeypatch.setattr("eth_backtester.okx_ws_public.time.monotonic", lambda: 170.0)

    bare_feed.snapshot()
    bare_feed.snapshot()

    assert calls == ["backfill"]


def test_run_stale_backfill_resets_inflight_flag_and_refreshes_latest_price(monkeypatch: pytest.MonkeyPatch, bare_feed: OKXPublicRealtimeFeed) -> None:
    bare_feed._stale_refresh_inflight = True
    refreshed = [
        Candle(datetime(2026, 4, 13, 0, 15), 100.5, 102.0, 100.0, 101.5, 12.0),
        Candle(datetime(2026, 4, 13, 0, 30), 101.5, 103.0, 101.0, 102.5, 11.0),
        Candle(datetime(2026, 4, 13, 0, 45), 102.5, 104.0, 102.0, 103.5, 13.0),
    ]

    monkeypatch.setattr(
        "eth_backtester.okx_ws_public.fetch_eth_ohlcv_from_okx",
        lambda inst_id, bar, candles_limit: refreshed,
    )
    monkeypatch.setattr("eth_backtester.okx_ws_public.time.monotonic", lambda: 170.0)

    bare_feed._run_stale_backfill()

    assert bare_feed._stale_refresh_inflight is False
    assert bare_feed._latest_price == 103.5
    assert bare_feed._latest_price_ts == datetime(2026, 4, 13, 0, 45).isoformat()


def test_trigger_stale_backfill_rolls_back_inflight_when_thread_start_fails(monkeypatch: pytest.MonkeyPatch, bare_feed: OKXPublicRealtimeFeed) -> None:
    class BrokenThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self) -> None:
            raise RuntimeError("thread start failed")

    bare_feed._stale_refresh_inflight = True
    monkeypatch.setattr("eth_backtester.okx_ws_public.threading.Thread", BrokenThread)

    with pytest.raises(RuntimeError, match="thread start failed"):
        bare_feed._trigger_stale_backfill()

    assert bare_feed._stale_refresh_inflight is False
