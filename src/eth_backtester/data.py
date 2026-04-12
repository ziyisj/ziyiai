from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta
from pathlib import Path

from .models import Candle

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


def load_candles_from_csv(path: str | Path) -> list[Candle]:
    csv_path = Path(path)
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV is missing a header row")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

        candles: list[Candle] = []
        for row in reader:
            candles.append(
                Candle(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )

    if not candles:
        raise ValueError("CSV did not contain any candle rows")
    return candles


def generate_sample_eth_csv(path: str | Path, periods: int = 180) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    start = datetime(2024, 1, 1)
    base_price = 2200.0

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])

        previous_close = base_price
        for step in range(periods):
            trend = step * 4.5
            seasonal = math.sin(step / 8.0) * 55.0
            noise = math.cos(step / 3.3) * 12.0
            close = round(base_price + trend + seasonal + noise, 2)
            open_price = round(previous_close, 2)
            high = round(max(open_price, close) + 14.0 + (step % 5), 2)
            low = round(min(open_price, close) - 10.0 - (step % 3), 2)
            volume = round(950 + (step * 9) + abs(seasonal) * 3.2, 2)
            writer.writerow(
                [
                    (start + timedelta(hours=step)).isoformat(),
                    open_price,
                    high,
                    low,
                    close,
                    volume,
                ]
            )
            previous_close = close

    return output_path
