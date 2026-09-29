"""Shared helpers: symbol conversion, pip math, rate limiting, and retries."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Iterable

from src.config import Timeframe

OANDA_GRANULARITY: dict[Timeframe, str] = {
    "M1": "M1",
    "M5": "M5",
    "H1": "H1",
    "D1": "D",
}

TWELVE_INTERVAL: dict[Timeframe, str] = {
    "M1": "1min",
    "M5": "5min",
    "H1": "1h",
    "D1": "1day",
}

TIMEFRAME_MINUTES: dict[Timeframe, int] = {
    "M1": 1,
    "M5": 5,
    "H1": 60,
    "D1": 1440,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_display_symbol(symbol: str) -> str:
    """EUR_USD / EURUSD / EUR/USD → EUR/USD."""
    cleaned = symbol.strip().upper().replace("-", "/").replace("_", "/")
    if "/" in cleaned:
        base, quote = cleaned.split("/", 1)
        return f"{base}/{quote}"
    if len(cleaned) == 6:
        return f"{cleaned[:3]}/{cleaned[3:]}"
    return cleaned


def canonical_pair(symbol: str) -> str:
    """USD/EUR is the same market as EUR/USD — always trade the EUR/USD listing."""
    display = to_display_symbol(symbol)
    if display == "USD/EUR":
        return "EUR/USD"
    return display


def to_oanda_instrument(symbol: str) -> str:
    display = to_display_symbol(symbol)
    return display.replace("/", "_")


def to_twelvedata_symbol(symbol: str) -> str:
    return to_display_symbol(symbol)


def is_jpy_pair(symbol: str) -> bool:
    return "JPY" in to_display_symbol(symbol)


def pip_size(symbol: str) -> float:
    """Minimum pip increment used for SL/TP distance math."""
    return 0.01 if is_jpy_pair(symbol) else 0.0001


def pip_precision(symbol: str) -> int:
    """Broker display precision (OANDA default: 3 for JPY, 5 otherwise)."""
    return 3 if is_jpy_pair(symbol) else 5


def price_to_pips(symbol: str, price_distance: float) -> float:
    return abs(price_distance) / pip_size(symbol)


def pips_to_price(symbol: str, pips: float) -> float:
    return pips * pip_size(symbol)


def format_price(symbol: str, price: float, precision: int | None = None) -> str:
    digits = precision if precision is not None else pip_precision(symbol)
    return f"{price:.{digits}f}"


def parse_iso(ts: str) -> datetime:
    text = ts.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, rest = text.split(".", 1)
        sign_at = max(rest.rfind("+"), rest.rfind("-") if rest[:1] != "-" else rest.find("-", 1))
        if sign_at > 0:
            frac, tzbit = rest[:sign_at], rest[sign_at:]
        else:
            frac, tzbit = rest, "+00:00"
        frac = "".join(ch for ch in frac if ch.isdigit())[:6].ljust(6, "0")
        text = f"{head}.{frac}{tzbit}"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def chunked(items: Iterable, size: int) -> list[list]:
    bucket: list = []
    out: list[list] = []
    for item in items:
        bucket.append(item)
        if len(bucket) >= size:
            out.append(bucket)
            bucket = []
    if bucket:
        out.append(bucket)
    return out


class TokenBucket:
    """Simple thread-safe rate limiter (tokens per interval)."""

    def __init__(self, rate: int, per_seconds: float = 60.0) -> None:
        self.rate = max(1, rate)
        self.per_seconds = per_seconds
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - self.per_seconds
                while self._times and self._times[0] < cutoff:
                    self._times.popleft()
                if len(self._times) < self.rate:
                    self._times.append(now)
                    return
                wait = self.per_seconds - (now - self._times[0]) + 0.05
            if time.monotonic() + wait > deadline:
                raise TimeoutError("rate limiter timed out")
            time.sleep(max(wait, 0.05))
