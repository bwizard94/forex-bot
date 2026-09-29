"""Market data adapters: OANDA, Twelve Data, and CurrencyFreaks.

Live candles and bid/ask come from OANDA. Twelve Data is the OHLCV backup
when OANDA is down (its basic plan is 8 credits/minute). CurrencyFreaks is
an independent FX mid source used to cross-check OANDA quotes and to fill
in prices if the broker pricing endpoint fails. CF latest is USD-based and
is cached so a free plan is not burned by the 15-second quote loop.
"""

from __future__ import annotations

import threading
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

import httpx
from requests.exceptions import RequestException
import oandapyV20
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.pricing as pricing
from loguru import logger
from oandapyV20.exceptions import V20Error
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import Settings, Timeframe, get_settings
from src.utils import (
    OANDA_GRANULARITY,
    TWELVE_INTERVAL,
    TokenBucket,
    parse_iso,
    price_to_pips,
    to_display_symbol,
    to_oanda_instrument,
    to_twelvedata_symbol,
    utcnow,
)


class FeedError(RuntimeError):
    """Raised when a market-data source cannot be reached after retries."""


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: Timeframe
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    complete: bool
    source: str

    def to_row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "ts": self.ts,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "complete": self.complete,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    mid: float
    spread: float
    tradeable: bool
    ts: datetime
    source: str = "oanda"


def mids_from_usd_rates(rates: dict[str, float], symbols: Sequence[str]) -> dict[str, float]:
    """Convert a USD-base rate map (EUR=0.86 means 1 USD = 0.86 EUR) into pair mids."""
    out: dict[str, float] = {}
    for raw in symbols:
        symbol = to_display_symbol(raw)
        if "/" not in symbol:
            continue
        base, quote = symbol.split("/", 1)
        try:
            if base == "USD" and quote in rates:
                out[symbol] = float(rates[quote])
            elif quote == "USD" and base in rates and rates[base]:
                out[symbol] = 1.0 / float(rates[base])
            elif base in rates and quote in rates and rates[base]:
                out[symbol] = float(rates[quote]) / float(rates[base])
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return out


def usd_base_legs(symbols: Sequence[str]) -> list[str]:
    legs: set[str] = set()
    for raw in symbols:
        symbol = to_display_symbol(raw)
        if "/" not in symbol:
            continue
        base, quote = symbol.split("/", 1)
        if base != "USD":
            legs.add(base)
        if quote != "USD":
            legs.add(quote)
    return sorted(legs)


def _new_oanda_client(settings: Settings) -> oandapyV20.API:
    token = settings.oanda_api_token.get_secret_value()
    if not token:
        raise FeedError("OANDA_API_TOKEN is not configured")
    return oandapyV20.API(access_token=token, environment=settings.oanda_environment)


class OandaClient:
    """Thin, reconnecting wrapper around oandapyV20."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._api: oandapyV20.API | None = None
        self._account_id = self.settings.oanda_account_id
        self._lock_failures = 0

    @property
    def api(self) -> oandapyV20.API:
        if self._api is None:
            self._api = _new_oanda_client(self.settings)
        return self._api

    def reconnect(self, reason: str = "") -> None:
        logger.warning("Reconnecting OANDA client {}", f"({reason})" if reason else "")
        self._api = _new_oanda_client(self.settings)

    def pause_writes(self, reason: str) -> None:
        latch = self._write_latch()
        latch.parent.mkdir(parents=True, exist_ok=True)
        latch.write_text(f"{utcnow().isoformat()} {reason}; reconcile OANDA before removing this file.\n")

    def _write_latch(self) -> Path:
        identity = self._account_id or self.settings.oanda_api_token.get_secret_value()
        key = hashlib.sha256(str(identity).encode()).hexdigest()[:16]
        return Path("data") / f"oanda-uncertain-{key}.lock"

    def assert_writes_allowed(self) -> None:
        if self.settings.oanda_environment != "practice":
            raise FeedError("This execution adapter permits practice-account writes only")
        if self._write_latch().exists():
            raise FeedError(f"OANDA writes paused: reconcile uncertain request recorded in {self._write_latch()}")

    def request(self, endpoint: Any) -> dict[str, Any]:
        # A timed-out POST/PUT may have executed at the broker. Never replay it.
        read_only = str(getattr(endpoint, "method", "")).upper() == "GET"
        latch = self._write_latch()
        if not read_only:
            self.assert_writes_allowed()
        try:
            return self.api.request(endpoint)
        except V20Error:
            raise  # Rejections are definitive; repeating them cannot fix the order.
        except (RequestException, ConnectionError, TimeoutError, OSError) as exc:
            if not read_only:
                self.pause_writes(f"{type(endpoint).__name__}: outcome unknown")
                raise FeedError(f"OANDA outcome unknown; writes paused in {latch}") from exc
            self._lock_failures += 1
            self.reconnect(type(exc).__name__)
            return self.api.request(endpoint)

    def ensure_account_id(self) -> str:
        if self._account_id:
            return self._account_id
        payload = self.request(accounts.AccountList())
        accounts_list = payload.get("accounts") or []
        if not accounts_list:
            raise FeedError("OANDA token is valid but no practice accounts were returned")
        self._account_id = str(accounts_list[0]["id"])
        logger.info("Auto-discovered OANDA account {}", self._account_id)
        return self._account_id

    @property
    def account_id(self) -> str:
        return self.ensure_account_id()


class MarketDataFetcher:
    """Pulls M1/M5/H1/D1 OHLCV and live bid/ask quotes from multiple feeds."""

    def __init__(self, settings: Settings | None = None, oanda: OandaClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.oanda = oanda or OandaClient(self.settings)
        self._twelve_bucket = TokenBucket(rate=7, per_seconds=60.0)
        self._http = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        self._instrument_cache: dict[str, dict[str, Any]] = {}
        self._cf_lock = threading.Lock()
        self._cf_mids: dict[str, float] = {}
        self._cf_fetched_at: float = 0.0
        self._cf_as_of: datetime | None = None

    def close(self) -> None:
        self._http.close()

    @property
    def reference_mids(self) -> dict[str, float]:
        return dict(self._cf_mids)

    @property
    def reference_as_of(self) -> datetime | None:
        return self._cf_as_of

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.6, min=0.6, max=8),
        retry=retry_if_exception_type((FeedError, V20Error, ConnectionError, TimeoutError, OSError)),
    )
    def fetch_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = 300,
        *,
        complete_only: bool = True,
    ) -> list[Candle]:
        display = to_display_symbol(symbol)
        try:
            candles = self._fetch_oanda_candles(display, timeframe, count)
            if candles:
                return [c for c in candles if c.complete] if complete_only else candles
        except Exception as exc:
            logger.warning("OANDA candles failed for {} {}: {}", display, timeframe, exc)
        try:
            candles = self._fetch_twelvedata_candles(display, timeframe, count)
            return candles
        except Exception as exc:
            raise FeedError(
                f"OANDA and Twelve Data both failed for {display} {timeframe}: {exc}"
            ) from exc

    def fetch_many(
        self,
        symbols: Sequence[str],
        timeframes: Sequence[Timeframe],
        count: int = 300,
    ) -> list[Candle]:
        out: list[Candle] = []
        for symbol in symbols:
            for tf in timeframes:
                try:
                    out.extend(self.fetch_candles(symbol, tf, count=count))
                except Exception as exc:
                    logger.exception("Failed fetching {} {}: {}", symbol, tf, exc)
        return out

    def fetch_quotes(self, symbols: Sequence[str]) -> list[Quote]:
        self.ensure_reference_mids(symbols)
        try:
            quotes = self._fetch_oanda_quotes(symbols)
            self._log_feed_divergence(quotes)
            return quotes
        except Exception as exc:
            logger.warning("OANDA pricing failed, falling back to CurrencyFreaks: {}", exc)
            fallback = self._quotes_from_reference(symbols)
            if not fallback:
                raise FeedError(f"OANDA pricing failed and CurrencyFreaks has no cache: {exc}") from exc
            return fallback

    def ensure_reference_mids(self, symbols: Sequence[str], *, force: bool = False) -> dict[str, float]:
        """Refresh CurrencyFreaks mids at most once per TTL window."""
        ttl = max(30, int(self.settings.reference_quote_ttl_seconds))
        with self._cf_lock:
            stale = (time.monotonic() - self._cf_fetched_at) >= ttl
            if not force and self._cf_mids and not stale:
                return dict(self._cf_mids)
        try:
            mids, as_of = self._fetch_currencyfreaks_mids(symbols)
        except Exception as exc:
            logger.warning("CurrencyFreaks refresh failed: {}", exc)
            return dict(self._cf_mids)
        with self._cf_lock:
            self._cf_mids = mids
            self._cf_fetched_at = time.monotonic()
            self._cf_as_of = as_of
        logger.info(
            "CurrencyFreaks mids refreshed ({}) {}",
            as_of.isoformat() if as_of else "now",
            {k: round(v, 5) for k, v in mids.items()},
        )
        return dict(mids)

    def _fetch_oanda_quotes(self, symbols: Sequence[str]) -> list[Quote]:
        instruments_csv = ",".join(to_oanda_instrument(s) for s in symbols)
        endpoint = pricing.PricingInfo(
            accountID=self.oanda.account_id,
            params={"instruments": instruments_csv},
        )
        payload = self.oanda.request(endpoint)
        quotes: list[Quote] = []
        for raw in payload.get("prices", []):
            bids = raw.get("bids") or []
            asks = raw.get("asks") or []
            if not bids or not asks:
                continue
            bid = float(bids[0]["price"])
            ask = float(asks[0]["price"])
            quotes.append(
                Quote(
                    symbol=to_display_symbol(raw["instrument"]),
                    bid=bid,
                    ask=ask,
                    mid=(bid + ask) / 2.0,
                    spread=ask - bid,
                    tradeable=bool(raw.get("tradeable", True)),
                    ts=parse_iso(raw.get("time") or payload.get("time")),
                    source="oanda",
                )
            )
        return quotes

    def _fetch_currencyfreaks_mids(
        self, symbols: Sequence[str]
    ) -> tuple[dict[str, float], datetime | None]:
        key = self.settings.currencyfreaks_api_key.get_secret_value()
        if not key:
            raise FeedError("CURRENCYFREAKS_API_KEY is not configured")
        legs = usd_base_legs(symbols)
        url = f"{self.settings.currencyfreaks_base_url.rstrip('/')}/v2.0/rates/latest"
        try:
            response = self._http.get(
                url,
                params={"apikey": key, "symbols": ",".join(legs)},
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise FeedError(f"CurrencyFreaks HTTP error: {exc}") from exc
        payload = response.json()
        if payload.get("status") in {401, 402, 403, 404} or payload.get("error"):
            raise FeedError(f"CurrencyFreaks error: {payload}")
        raw_rates = payload.get("rates") or {}
        rates = {str(k).upper(): float(v) for k, v in raw_rates.items()}
        mids = mids_from_usd_rates(rates, symbols)
        as_of = None
        if payload.get("date"):
            try:
                as_of = parse_iso(str(payload["date"]))
            except Exception:
                as_of = utcnow()
        else:
            as_of = utcnow()
        if not mids:
            raise FeedError(f"CurrencyFreaks returned no mids for {list(symbols)}: {payload}")
        return mids, as_of

    def _quotes_from_reference(self, symbols: Sequence[str]) -> list[Quote]:
        mids = self.ensure_reference_mids(symbols, force=True)
        ts = self._cf_as_of or utcnow()
        quotes: list[Quote] = []
        for raw in symbols:
            symbol = to_display_symbol(raw)
            mid = mids.get(symbol)
            if mid is None:
                continue
            quotes.append(
                Quote(
                    symbol=symbol,
                    bid=mid,
                    ask=mid,
                    mid=mid,
                    spread=0.0,
                    tradeable=True,
                    ts=ts,
                    source="currencyfreaks",
                )
            )
        return quotes

    def _log_feed_divergence(self, quotes: Sequence[Quote]) -> None:
        warn_at = float(self.settings.quote_warn_pips)
        as_of = self._cf_as_of
        stale_daily = False
        if as_of is not None:
            ts = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
            age_h = (utcnow() - ts).total_seconds() / 3600.0
            stale_daily = age_h >= 6 or (as_of.hour == 0 and as_of.minute == 0 and age_h >= 1)
        emit = logger.debug if stale_daily else logger.warning
        for quote in quotes:
            ref = self._cf_mids.get(quote.symbol)
            if ref is None:
                continue
            delta = price_to_pips(quote.symbol, quote.mid - ref)
            if abs(delta) >= warn_at:
                emit(
                    "Feed disagreement {} OANDA {} vs CurrencyFreaks {} ({:+.1f} pips){}",
                    quote.symbol,
                    quote.mid,
                    ref,
                    delta,
                    " — stale daily CF print, not a live veto" if stale_daily else "",
                )

    def quote_enrichment(self, quotes: Sequence[Quote] | dict[str, Quote]) -> list[dict[str, Any]]:
        """Serialize quotes with the independent CurrencyFreaks mid attached."""
        items = quotes.values() if isinstance(quotes, dict) else quotes
        rows: list[dict[str, Any]] = []
        for quote in items:
            ref = self._cf_mids.get(quote.symbol)
            delta = None
            if ref is not None:
                delta = round(price_to_pips(quote.symbol, quote.mid - ref), 2)
            rows.append(
                {
                    "symbol": quote.symbol,
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "mid": quote.mid,
                    "spread": quote.spread,
                    "tradeable": quote.tradeable,
                    "ts": quote.ts.isoformat(),
                    "source": quote.source,
                    "reference_mid": ref,
                    "reference_source": "currencyfreaks" if ref is not None else None,
                    "divergence_pips": delta,
                }
            )
        return rows

    def instrument_specs(self, symbol: str) -> dict[str, Any]:
        display = to_display_symbol(symbol)
        if display in self._instrument_cache:
            return self._instrument_cache[display]
        endpoint = accounts.AccountInstruments(
            accountID=self.oanda.account_id,
            params={"instruments": to_oanda_instrument(display)},
        )
        payload = self.oanda.request(endpoint)
        specs = (payload.get("instruments") or [{}])[0]
        self._instrument_cache[display] = specs
        return specs

    def display_precision(self, symbol: str) -> int:
        specs = self.instrument_specs(symbol)
        try:
            return int(specs.get("displayPrecision", 5))
        except (TypeError, ValueError):
            from src.utils import pip_precision

            return pip_precision(symbol)

    def _fetch_oanda_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        instrument = to_oanda_instrument(symbol)
        endpoint = instruments.InstrumentsCandles(
            instrument=instrument,
            params={
                "price": "M",
                "granularity": OANDA_GRANULARITY[timeframe],
                "count": min(count, 5000),
            },
        )
        payload = self.oanda.request(endpoint)
        candles: list[Candle] = []
        for raw in payload.get("candles", []):
            mid = raw.get("mid") or {}
            if not mid:
                continue
            candles.append(
                Candle(
                    symbol=to_display_symbol(symbol),
                    timeframe=timeframe,
                    ts=parse_iso(raw["time"]),
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=float(raw.get("volume") or 0),
                    complete=bool(raw.get("complete", True)),
                    source="oanda",
                )
            )
        return candles

    def _fetch_twelvedata_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        key = self.settings.twelvedata_api_key.get_secret_value()
        if not key:
            raise FeedError("TWELVEDATA_API_KEY is not configured")
        self._twelve_bucket.acquire()
        params = {
            "symbol": to_twelvedata_symbol(symbol),
            "interval": TWELVE_INTERVAL[timeframe],
            "outputsize": min(count, 5000),
            "apikey": key,
            "timezone": "UTC",
        }
        url = f"{self.settings.twelvedata_base_url.rstrip('/')}/time_series"
        try:
            response = self._http.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise FeedError(f"Twelve Data HTTP error: {exc}") from exc
        payload = response.json()
        if payload.get("status") == "error" or "values" not in payload:
            raise FeedError(f"Twelve Data error: {payload}")
        candles: list[Candle] = []
        for raw in reversed(payload.get("values") or []):
            candles.append(
                Candle(
                    symbol=to_display_symbol(symbol),
                    timeframe=timeframe,
                    ts=parse_iso(raw["datetime"]),
                    open=float(raw["open"]),
                    high=float(raw["high"]),
                    low=float(raw["low"]),
                    close=float(raw["close"]),
                    volume=float(raw.get("volume") or 0),
                    complete=True,
                    source="twelvedata",
                )
            )
        return candles


def sleep_backoff(attempt: int, base: float = 0.5, cap: float = 8.0) -> None:
    time.sleep(min(cap, base * (2**attempt)))
