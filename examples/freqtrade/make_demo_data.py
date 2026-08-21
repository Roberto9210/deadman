"""Deterministic OHLCV candles for the demo backtest.

No download, no network, no randomness: the same candles every run, so two
runs of demo.py differ only in what deadman was configured to do. The file is
written through freqtrade's own data handler, so the on-disk format is
whatever the installed freqtrade reads - not a format guessed here.
"""
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from freqtrade.data.history import get_datahandler
from freqtrade.enums import CandleType

PAIR = "BTC/USDT"
TIMEFRAME = "5m"
EXCHANGE = "kraken"
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
CANDLES = 24 * 12 * 3  # three days of 5m candles


def build_frame(candles: int = CANDLES, start: datetime = START) -> pd.DataFrame:
    """A slow sine plus a faster one: enough movement for the demo's fixed
    entry/exit candles to produce both winners and losers, and reproducible to
    the last decimal because there is no random in it."""
    rows = []
    for i in range(candles):
        ts = start + timedelta(minutes=5 * i)
        base = 30_000.0 + 300.0 * math.sin(i / 15.0)
        close = base + 40.0 * math.cos(i / 7.0)
        rows.append([int(ts.timestamp() * 1000), base, max(base, close) + 15.0,
                     min(base, close) - 15.0, close, 100.0 + i])
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True)
    return df


def write(datadir: Path, exchange: str = EXCHANGE, pair: str = PAIR,
          timeframe: str = TIMEFRAME, data_format: str = "json") -> Path:
    """datadir is the freqtrade data directory (<userdir>/data); the candles
    go into <datadir>/<exchange>/."""
    target = Path(datadir) / exchange
    target.mkdir(parents=True, exist_ok=True)
    handler = get_datahandler(target, data_format)
    handler.ohlcv_store(pair, timeframe, build_frame(), CandleType.SPOT)
    written = sorted(target.glob(f"*-{timeframe}.*"))
    if not written:
        raise RuntimeError(f"the data handler wrote nothing under {target}")
    return written[0]


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "demo_out" / "user_data" / "data"
    path = write(out)
    print(f"wrote {CANDLES} candles -> {path}")
