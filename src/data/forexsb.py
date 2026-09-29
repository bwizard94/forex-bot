"""Download EUR/USD bars from ForexSB's DukasCopy historical feed.

The public app at https://forexsb.com/historical-forex-data loads binary
``.lb.gz`` files from ``data.forexsb.com``. This module does the same thing
so the desk can study years of EUR/USD without a manual download.
"""

from __future__ import annotations

import gzip
import json
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from loguru import logger

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "extra datasets"
CACHE_DIR = DATA_DIR / "cache"
INFO_URL = "https://data.forexsb.com/datafeed/info/premium.json.gz"
FEED_URL = "https://data.forexsb.com/datafeed/data/dukascopy"
MILLENNIUM = datetime(2000, 1, 1, tzinfo=timezone.utc)
PERIODS = {"M5": 5, "M30": 30}
DEFAULT_PRICE_SCALE = 100_000
DEFAULT_VOLUME_SCALE = 1


def _session() -> httpx.Client:
    return httpx.Client(
        timeout=60.0,
        headers={"User-Agent": "ForexSentinel/2.6 (EURUSD specialist desk)"},
        follow_redirects=True,
    )


def fetch_symbol_info(symbol: str = "EURUSD") -> dict[str, Any]:
    try:
        with _session() as client:
            payload = client.get(INFO_URL)
            payload.raise_for_status()
            raw = payload.content
        try:
            data = json.loads(gzip.decompress(raw))
        except OSError:
            data = json.loads(raw.decode("utf-8", errors="ignore"))
        item = data.get(symbol) if isinstance(data, dict) else {}
        if not item and isinstance(data, dict):
            symbols = data.get("symbols") if isinstance(data.get("symbols"), dict) else data
            if isinstance(symbols, dict):
                item = symbols.get(symbol) or {}
            if isinstance(symbols, list):
                item = next((row for row in symbols if isinstance(row, dict) and row.get("symbol") == symbol), {})
        return item or {}
    except Exception as exc:
        logger.warning("ForexSB info fetch failed: {}", exc)
        return {}


def parse_lb(raw: bytes, *, price_scale: int = DEFAULT_PRICE_SCALE, volume_scale: int = DEFAULT_VOLUME_SCALE) -> pd.DataFrame:
    """Parse ForexSB little-endian bar records (24 or 28 bytes)."""
    rec = 28 if (raw and len(raw) % 28 == 0) else 24
    if not raw or len(raw) % rec != 0:
        raise ValueError(f"unexpected ForexSB payload size {len(raw)}")
    times: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    spreads: list[float] = []
    fmt = "<iiiiiii" if rec == 28 else "<iiiiii"
    for offset in range(0, len(raw), rec):
        parts = struct.unpack_from(fmt, raw, offset)
        minutes, o, h, l, c, v = parts[:6]
        times.append(MILLENNIUM + timedelta(minutes=int(minutes)))
        opens.append(o / price_scale)
        highs.append(h / price_scale)
        lows.append(l / price_scale)
        closes.append(c / price_scale)
        volumes.append(max(1.0, float(v) / max(1, volume_scale)))
        if rec == 28:
            spreads.append(float(parts[6]))
    frame = pd.DataFrame(
        {
            "datetime": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )
    if spreads:
        frame["spread"] = spreads
    return frame.set_index("datetime").sort_index()


def download_period(symbol: str, period: int, dest: Path, *, force: bool = False) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000 and not force:
        return dest
    url = f"{FEED_URL}/{symbol}{period}.lb.gz"
    logger.info("Downloading ForexSB {} period {} from {}", symbol, period, url)
    with _session() as client:
        response = client.get(url)
        response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def resample_ohlc(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    how: dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "spread" in frame.columns:
        how["spread"] = "last"
    out = frame.resample(rule).agg(how).dropna(subset=["open", "high", "low", "close"])
    return out


def write_csv(frame: pd.DataFrame, path: Path, *, tail: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    work = frame.tail(int(tail)) if tail else frame
    export = work.reset_index()
    export = export.rename(columns={export.columns[0]: "datetime"})
    export.to_csv(path, index=False)
    return path


def ensure_eurusd_history(*, force: bool = False) -> dict[str, Any]:
    """Fetch ForexSB EURUSD M5+M30, write CSVs the desk already knows how to study."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    info = fetch_symbol_info("EURUSD")
    price_scale = int(info.get("priceScale") or DEFAULT_PRICE_SCALE)
    volume_scale = int(info.get("volumeScale") or DEFAULT_VOLUME_SCALE)
    written: list[str] = []
    spans: dict[str, str] = {}
    m5_path = CACHE_DIR / "EURUSD5.lb.gz"
    m30_path = CACHE_DIR / "EURUSD30.lb.gz"
    download_period("EURUSD", 5, m5_path, force=force)
    download_period("EURUSD", 30, m30_path, force=force)

    m5 = parse_lb(gzip.decompress(m5_path.read_bytes()), price_scale=price_scale, volume_scale=volume_scale)
    m30 = parse_lb(gzip.decompress(m30_path.read_bytes()), price_scale=price_scale, volume_scale=volume_scale)
    h1 = resample_ohlc(m30, "1h")
    d1 = resample_ohlc(m30, "1D")

    files = {
        "M5": (m5, DATA_DIR / "EURUSD_M5_forexsb.csv", 80_000),
        "H1": (h1, DATA_DIR / "EURUSD_H1_forexsb.csv", 16_000),
        "D1": (d1, DATA_DIR / "EURUSD_D1_forexsb.csv", 4_000),
    }
    for tf, (frame, path, tail) in files.items():
        write_csv(frame, path, tail=tail)
        written.append(path.name)
        if not frame.empty:
            spans[tf] = f"{frame.index[0].date()} → {frame.index[-1].date()} ({len(frame)} bars)"
            logger.info("ForexSB EUR/USD {} {}", tf, spans[tf])
    return {
        "ok": True,
        "source": "https://forexsb.com/historical-forex-data",
        "files": written,
        "spans": spans,
        "price_scale": price_scale,
    }
