from __future__ import annotations

import gzip
import struct
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.analysis.signals import classify_signal_type
from src.config import Settings, reload_settings
from src.data.datasets import persist_history_book, score_setups
from src.data.forexsb import parse_lb, resample_ohlc, write_csv
from src.data.storage import (
    IndicatorRow,
    SetupMemory,
    SignalRow,
    init_db,
    reset_engine,
    session_scope,
)
from sqlalchemy import select


def _record(minutes: int, o: int, h: int, l: int, c: int, v: int = 10, spread: int = 12) -> bytes:
    return struct.pack("<iiiiiii", minutes, o, h, l, c, v, spread)


def test_parse_lb_scales_eurusd_prices() -> None:
    raw = _record(0, 108000, 108150, 107900, 108050) + _record(5, 108050, 108200, 108000, 108100)
    frame = parse_lb(raw, price_scale=100_000)
    assert list(frame.columns)[:5] == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 2
    assert abs(float(frame["open"].iloc[0]) - 1.08000) < 1e-9
    assert abs(float(frame["close"].iloc[-1]) - 1.08100) < 1e-9
    assert frame.index[0] == datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert frame.index[1].minute == 5
    assert "spread" in frame.columns


def test_resample_m30_to_h1(tmp_path: Path) -> None:
    idx = pd.date_range("2024-01-02 00:00", periods=4, freq="30min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [1.10, 1.11, 1.12, 1.13],
            "high": [1.12, 1.13, 1.14, 1.15],
            "low": [1.09, 1.10, 1.11, 1.12],
            "close": [1.11, 1.12, 1.13, 1.14],
            "volume": [1, 1, 1, 1],
        },
        index=idx,
    )
    hourly = resample_ohlc(frame, "1h")
    assert len(hourly) == 2
    assert float(hourly["open"].iloc[0]) == 1.10
    assert float(hourly["close"].iloc[0]) == 1.12
    assert float(hourly["high"].iloc[0]) == 1.13
    out = tmp_path / "EURUSD_H1_forexsb.csv"
    write_csv(hourly, out)
    loaded = pd.read_csv(out)
    assert "datetime" in loaded.columns
    assert "close" in loaded.columns


def test_classify_signal_type_buckets() -> None:
    assert classify_signal_type("HOLD", []) == "hold"
    assert classify_signal_type("BUY", ["H1-aligned trend continuation"]) == "continuation"
    assert (
        classify_signal_type(
            "SELL",
            ["Close at/over upper Bollinger band", "RSI overbought (72.0)"],
        )
        == "band_rsi"
    )
    assert classify_signal_type("BUY", ["EMA 9/21 bullish cross"]) == "ema_cross"
    assert classify_signal_type("SELL", ["MACD bearish cross"]) == "macd_cross"
    assert classify_signal_type("BUY", ["Stochastic oversold (20)"]) == "stoch"
    assert classify_signal_type("SELL", ["CCI overbought (120)"]) == "cci"
    assert classify_signal_type("BUY", ["Bullish RSI divergence: higher low"]) == "divergence"
    assert classify_signal_type("BUY", ["EMA 9 above EMA 21"]) == "mixed"


def test_score_setups_and_persist(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'memory.db'}")
    reset_engine()
    reload_settings()
    init_db()
    closed = [
        {"signal_type": "band_rsi", "side": "SELL", "session": "london", "pips": 8.0, "strength": 70},
        {"signal_type": "band_rsi", "side": "SELL", "session": "london", "pips": -5.0, "strength": 62},
        {"signal_type": "continuation", "side": "SELL", "session": "overlap", "pips": 3.0, "strength": 55},
    ]
    setups = score_setups(closed)
    assert setups[0]["signal_type"] == "continuation"
    idx = pd.date_range("2024-03-04 08:00", periods=120, freq="5min", tz="UTC")
    close = pd.Series(1.085 + (idx.hour * 0) + pd.Series(range(120)).values * -0.00002, index=idx)
    m5 = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.0003,
            "low": close - 0.0003,
            "close": close,
            "volume": 10,
        },
        index=idx,
    )
    persist_history_book(m5, None, None, setups, [])
    with session_scope() as session:
        memory = list(session.scalars(select(SetupMemory)))
        bars = session.scalar(select(IndicatorRow).limit(1))
        leftover = list(session.scalars(select(SignalRow).where(SignalRow.source == "history")))
    assert len(memory) == 2
    assert any(row.signal_type == "band_rsi" and row.side == "SELL" for row in memory)
    assert bars is not None
    assert leftover == []


def test_gzip_roundtrip_matches_parser(tmp_path: Path) -> None:
    raw = b"".join(_record(i * 5, 110000 + i, 110050 + i, 109950 + i, 110020 + i) for i in range(8))
    gz = tmp_path / "EURUSD5.lb.gz"
    gz.write_bytes(gzip.compress(raw))
    frame = parse_lb(gzip.decompress(gz.read_bytes()))
    assert len(frame) == 8
    assert float(frame["close"].iloc[0]) == 1.10020
