from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Candle

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
OKX_BASE_URL = "https://www.okx.com/api/v5"
OKX_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (eth-strategy-system)",
}


def fetch_eth_ohlc_from_coingecko(days: int = 30, vs_currency: str = "usd") -> list[Candle]:
    if days not in {1, 7, 14, 30, 90, 180, 365}:
        raise ValueError("CoinGecko OHLC days must be one of: 1, 7, 14, 30, 90, 180, 365")

    query = urlencode({"vs_currency": vs_currency, "days": days})
    url = f"{COINGECKO_BASE_URL}/coins/ethereum/ohlc?{query}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "eth-strategy-system/0.1"})

    with urlopen(request, timeout=30) as response:
        payload = json.load(response)

    candles: list[Candle] = []
    for item in payload:
        timestamp_ms, open_price, high, low, close = item
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).replace(tzinfo=None),
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=0.0,
            )
        )

    if not candles:
        raise ValueError("CoinGecko returned no OHLC data for Ethereum")
    return candles


def fetch_eth_ohlcv_from_okx(
    inst_id: str = "ETH-USDT",
    bar: str = "4H",
    candles_limit: int = 300,
    request_limit: int = 100,
) -> list[Candle]:
    if candles_limit <= 0:
        raise ValueError("candles_limit must be positive")
    if request_limit <= 0 or request_limit > 100:
        raise ValueError("request_limit must be between 1 and 100")

    collected: list[list[str]] = []
    after: str | None = None

    while len(collected) < candles_limit:
        params = {
            "instId": inst_id,
            "bar": bar,
            "limit": min(request_limit, candles_limit - len(collected)),
        }
        if after is not None:
            params["after"] = after
        query = urlencode(params)
        url = f"{OKX_BASE_URL}/market/history-candles?{query}"
        request = Request(url, headers=OKX_HEADERS)
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)

        if payload.get("code") != "0":
            raise ValueError(f"OKX API error: code={payload.get('code')} msg={payload.get('msg')}")

        rows = payload.get("data", [])
        if not rows:
            break
        collected.extend(rows)
        after = rows[-1][0]
        if len(rows) < params["limit"]:
            break

    if not collected:
        raise ValueError("OKX returned no candle data")

    candles: list[Candle] = []
    for row in reversed(collected[:candles_limit]):
        timestamp_ms, open_price, high, low, close, volume, *_rest = row
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc).replace(tzinfo=None),
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
        )
    return candles


def write_candles_to_csv(candles: list[Candle], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for candle in candles:
            writer.writerow(
                [
                    candle.timestamp.isoformat(),
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                ]
            )

    return output_path


def download_eth_csv_from_coingecko(
    path: str | Path,
    days: int = 30,
    vs_currency: str = "usd",
) -> Path:
    candles = fetch_eth_ohlc_from_coingecko(days=days, vs_currency=vs_currency)
    return write_candles_to_csv(candles, path)


def download_eth_csv_from_okx(
    path: str | Path,
    inst_id: str = "ETH-USDT",
    bar: str = "4H",
    candles_limit: int = 300,
) -> Path:
    candles = fetch_eth_ohlcv_from_okx(inst_id=inst_id, bar=bar, candles_limit=candles_limit)
    return write_candles_to_csv(candles, path)
