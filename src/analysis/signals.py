"""Deterministic BUY / SELL / HOLD evaluation with SL / TP geometry.

Signal construction is directional when enough independent factors agree
(EMA structure, RSI regime or divergence, Bollinger location, MACD,
Stochastic, ADX, CCI, Supertrend, VWAP/Reaction Path, TTM squeeze,
Donchian liquidity sweep, Ichimoku, WaveTrend, EWMAC, Ox scalp triad,
higher-timeframe bias). Stops and targets are ATR-based so they expand
and contract with volatility. The live book is an **EUR/USD scalp**:
short SL/TP, Ox LWMA + envelope + DSS trigger, H1 still the map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd

from src.analysis.indicators import Divergence, compute_indicators, detect_rsi_divergence
from src.analysis.mistakes import calendar_hold_reason, session_is_open
from src.config import Settings, get_settings
from src.utils import format_price, pip_size, price_to_pips, utcnow

Action = Literal["BUY", "SELL", "HOLD"]


def classify_signal_type(action: str, confluence: list[str] | None) -> str:
    """Stable label for a setup so history and the live book can share a bucket."""
    if action not in {"BUY", "SELL"}:
        return "hold"
    text = " | ".join(confluence or []).lower()
    tags: list[str] = []
    if "continuation" in text:
        tags.append("continuation")
    if "fade" in text:
        tags.append("fade")
    if "lwma" in text or "trend envelope" in text or "dss of momentum" in text or "ox scalp" in text:
        tags.append("scalp")
    if "bollinger" in text:
        tags.append("band")
    if "rsi oversold" in text or "rsi overbought" in text:
        tags.append("rsi")
    elif "rsi pullback" in text:
        tags.append("rsi_pullback")
    if "ema 9/21" in text and "cross" in text:
        tags.append("ema_cross")
    if "macd" in text and "cross" in text:
        tags.append("macd_cross")
    elif "macd" in text:
        tags.append("macd")
    if "stochastic" in text:
        tags.append("stoch")
    if "cci " in text:
        tags.append("cci")
    if "supertrend" in text:
        tags.append("supertrend")
    if "squeeze" in text:
        tags.append("squeeze")
    if "vwap" in text or "fair price" in text:
        tags.append("vwap")
    if "liquidity sweep" in text or "donchian" in text:
        tags.append("sweep")
    if "ichimoku" in text or "kumo" in text:
        tags.append("ichimoku")
    if "wavetrend" in text:
        tags.append("wavetrend")
    if "ewmac" in text:
        tags.append("ewmac")
    if "divergence" in text:
        tags.append("divergence")
    if "fade" in tags:
        rest = [t for t in tags if t != "fade"]
        return "+".join(["fade"] + rest[:2]) if rest else "fade"
    if not tags:
        return "mixed"
    if tags == ["continuation"]:
        return "continuation"
    if "band" in tags and "rsi" in tags:
        return "band_rsi"
    return "+".join(tags[:3])


def classify_regime(row: pd.Series, h1_bias: str, d1_bias: str) -> str:
    """Name the tape so journals and growth can bucket squeeze vs trend vs chop.

    Not a second strategy. H1 is still the map. This is the Biz4Group idea we
    already compute (squeeze, ADX, RSI extremes) without stamping a label.
    """
    if _flag(row, "squeeze_on"):
        return "squeeze"
    rsi_value = _num(row, "rsi")
    wt = _num(row, "wt1")
    if (rsi_value is not None and rsi_value <= 40) or (wt is not None and wt <= -53):
        return "washout"
    if (rsi_value is not None and rsi_value >= 60) or (wt is not None and wt >= 53):
        return "rip"
    adx_value = _num(row, "adx")
    trending = adx_value is not None and adx_value >= 22
    if trending and h1_bias == "bullish":
        return "trend_bull"
    if trending and h1_bias == "bearish":
        return "trend_bear"
    if trending and d1_bias == "bullish" and h1_bias != "bearish":
        return "trend_bull"
    if trending and d1_bias == "bearish" and h1_bias != "bullish":
        return "trend_bear"
    return "chop"


def candle_body_atr(row: pd.Series) -> float | None:
    """Close-to-open body in ATRs. A doji is not an Ox envelope break."""
    atr_value = _num(row, "atr")
    open_px = _num(row, "open")
    close_px = _num(row, "close")
    if atr_value is None or atr_value <= 0 or open_px is None or close_px is None:
        return None
    return abs(close_px - open_px) / atr_value


@dataclass(slots=True)
class TradeSignal:
    symbol: str
    timeframe: str
    action: Action
    timestamp: datetime
    price: float
    entry: float | None
    stop_loss: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    risk_reward: float | None
    atr: float | None
    rsi: float | None
    ema_fast: float | None
    ema_slow: float | None
    bb_upper: float | None
    bb_mid: float | None
    bb_lower: float | None
    htf_bias: str
    confluence: list[str] = field(default_factory=list)
    reason: str = ""
    strength: int = 0
    divergence: str | None = None
    d1_bias: str = "neutral"
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    stoch_k: float | None = None
    stoch_d: float | None = None
    adx: float | None = None
    plus_di: float | None = None
    minus_di: float | None = None
    cci: float | None = None
    vwap: float | None = None
    supertrend: float | None = None
    squeeze: str | None = None
    wt: float | None = None
    signal_type: str = "hold"
    source: str = "live"
    decision_context: dict[str, Any] | None = None

    def to_row(self, *, skipped: bool = False, skip_reason: str | None = None) -> dict[str, Any]:
        fingerprint = ""
        try:
            from src.analysis.reflection import fingerprint_from_signal

            if self.action in {"BUY", "SELL"}:
                fingerprint = fingerprint_from_signal(self)
        except Exception:
            fingerprint = ""
        return {
            "ts": self.timestamp,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "action": self.action,
            "price": self.price,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "risk_reward": self.risk_reward,
            "strength": self.strength,
            "confluence": self.confluence,
            "reason": self.reason,
            "skipped": skipped,
            "skip_reason": skip_reason,
            "signal_type": self.signal_type or classify_signal_type(self.action, self.confluence),
            "fingerprint": fingerprint,
            "htf_bias": self.htf_bias,
            "d1_bias": self.d1_bias,
            "rsi": self.rsi,
            "atr": self.atr,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "macd": self.macd,
            "stoch_k": self.stoch_k,
            "adx": self.adx,
            "cci": self.cci,
            "vwap": self.vwap,
            "supertrend": self.supertrend,
            "squeeze": self.squeeze,
            "wt": self.wt,
            "source": self.source,
            "decision_context": self.decision_context,
        }

    def summary(self) -> str:
        return (
            f"{self.action} {self.symbol} @{format_price(self.symbol, self.price)} "
            f"str={self.strength} {self.reason}"
        )


def _flag(row: pd.Series, key: str) -> bool:
    if key not in row.index:
        return False
    value = row[key]
    try:
        if value != value:
            return False
    except Exception:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _num(row: pd.Series, key: str) -> float | None:
    if key not in row.index:
        return None
    try:
        value = float(row[key])
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return value


def _last_valid(df: pd.DataFrame) -> pd.Series | None:
    needed = ["ema_fast", "ema_slow", "rsi", "atr", "bb_upper", "bb_mid", "bb_lower", "close"]
    ready = df.dropna(subset=needed)
    if ready.empty:
        return None
    return ready.iloc[-1]


def _in_session(now: datetime, start_hour: int, end_hour: int) -> bool:
    """Weekday hours only. Friday close, Sunday reopen, and Monday open live on Settings."""
    settings = get_settings()
    probe = Settings(
        trade_session_start_hour=start_hour,
        trade_session_end_hour=end_hour,
        friday_flat_hour=int(getattr(settings, "friday_flat_hour", 20) or 20),
        monday_open_skip_minutes=int(getattr(settings, "monday_open_skip_minutes", 45) or 45),
        session_filter=True,
    )
    return session_is_open(now, probe)


def _session_hold_reason(now: datetime, settings: Settings) -> str:
    return calendar_hold_reason(now, settings) or (
        f"Outside weekday EUR/USD hours "
        f"({settings.trade_session_start_hour:02d}:00–{settings.trade_session_end_hour:02d}:00 UTC, "
        "Tokyo through New York)"
    )


def _htf_bias(htf: pd.DataFrame | None) -> str:
    if htf is None or htf.empty:
        return "neutral"
    row = _last_valid(htf)
    if row is None:
        return "neutral"
    fast = float(row["ema_fast"])
    slow = float(row["ema_slow"])
    gap = abs(fast - slow) / float(row["close"])
    if gap < 0.0001:
        return "neutral"
    return "bullish" if fast > slow else "bearish"


def _levels(
    action: Action,
    entry: float,
    atr_value: float,
    settings: Settings,
    symbol: str = "EUR/USD",
) -> tuple[float, float, float, float]:
    sl_dist = settings.atr_sl_multiplier * atr_value
    tp1_dist = settings.atr_tp1_multiplier * atr_value
    tp2_dist = settings.atr_tp2_multiplier * atr_value
    min_stop = pip_size(symbol) * float(getattr(settings, "min_stop_pips", 2.0) or 2.0) * 1.02
    if sl_dist < min_stop and sl_dist > 0:
        scale = min_stop / sl_dist
        sl_dist = min_stop
        tp1_dist *= scale
        tp2_dist *= scale
    if action == "BUY":
        sl = entry - sl_dist
        tp1 = entry + tp1_dist
        tp2 = entry + tp2_dist
    else:
        sl = entry + sl_dist
        tp1 = entry - tp1_dist
        tp2 = entry - tp2_dist
    rr = tp1_dist / sl_dist if sl_dist else 0.0
    return sl, tp1, tp2, rr


def _is_spike(price: float, rsi: float, bb_upper: float, wt1: float | None) -> bool:
    at_upper = bb_upper > 0 and price >= bb_upper * 0.9996
    return rsi >= 60 or at_upper or (wt1 is not None and wt1 >= 53)


def _is_washout(price: float, rsi: float, bb_lower: float, wt1: float | None) -> bool:
    at_lower = bb_lower > 0 and price <= bb_lower * 1.0004
    return rsi <= 40 or at_lower or (wt1 is not None and wt1 <= -53)


def evaluate_signal(
    symbol: str,
    timeframe: str,
    bars: pd.DataFrame,
    htf_bars: pd.DataFrame | None = None,
    d1_bars: pd.DataFrame | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
    *,
    heavy: bool = True,
) -> TradeSignal:
    settings = settings or get_settings()
    from src.utils import canonical_pair

    symbol = canonical_pair(symbol)
    now = now or utcnow()
    frame = compute_indicators(
        bars,
        ema_fast=settings.ema_fast,
        ema_slow=settings.ema_slow,
        rsi_period=settings.rsi_period,
        atr_period=settings.atr_period,
        bb_period=settings.bb_period,
        bb_std=settings.bb_std,
        heavy=heavy,
    )
    htf = None
    if htf_bars is not None and not htf_bars.empty:
        htf = compute_indicators(
            htf_bars,
            ema_fast=settings.ema_fast,
            ema_slow=settings.ema_slow,
            rsi_period=settings.rsi_period,
            atr_period=settings.atr_period,
            bb_period=settings.bb_period,
            bb_std=settings.bb_std,
            heavy=heavy,
        )
    d1 = None
    if d1_bars is not None and not d1_bars.empty:
        d1 = compute_indicators(
            d1_bars,
            ema_fast=settings.ema_fast,
            ema_slow=settings.ema_slow,
            rsi_period=settings.rsi_period,
            atr_period=settings.atr_period,
            bb_period=settings.bb_period,
            bb_std=settings.bb_std,
            heavy=heavy,
        )
    bias = _htf_bias(htf)
    d1_bias = _htf_bias(d1)
    row = _last_valid(frame)
    ts = utcnow()
    if row is None:
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            action="HOLD",
            timestamp=ts,
            price=float(bars["close"].iloc[-1]) if not bars.empty else 0.0,
            entry=None,
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            risk_reward=None,
            atr=None,
            rsi=None,
            ema_fast=None,
            ema_slow=None,
            bb_upper=None,
            bb_mid=None,
            bb_lower=None,
            htf_bias=bias,
            reason="Insufficient bars to compute indicators",
            strength=0,
        )

    price = float(row["close"])
    atr_value = float(row["atr"])
    rsi_value = float(row["rsi"])
    ema_fast = float(row["ema_fast"])
    ema_slow = float(row["ema_slow"])
    bb_upper = float(row["bb_upper"])
    bb_mid = float(row["bb_mid"])
    bb_lower = float(row["bb_lower"])
    ts = row.name.to_pydatetime() if hasattr(row.name, "to_pydatetime") else ts
    if getattr(ts, "tzinfo", None) is None:
        from datetime import timezone

        ts = ts.replace(tzinfo=timezone.utc) if isinstance(ts, datetime) else utcnow()

    divergence = detect_rsi_divergence(frame["close"], frame["rsi"])
    bull_factors: list[str] = []
    bear_factors: list[str] = []

    if bool(row.get("ema_cross_up")):
        bull_factors.append("EMA 9/21 bullish cross")
    elif ema_fast > ema_slow:
        bull_factors.append("EMA 9 above EMA 21")

    if bool(row.get("ema_cross_down")):
        bear_factors.append("EMA 9/21 bearish cross")
    elif ema_fast < ema_slow:
        bear_factors.append("EMA 9 below EMA 21")

    if rsi_value <= 38:
        bull_factors.append(f"RSI oversold ({rsi_value:.1f})")
    elif rsi_value <= 52 and ema_fast > ema_slow:
        bull_factors.append(f"RSI pullback for longs ({rsi_value:.1f})")
    if rsi_value >= 62:
        bear_factors.append(f"RSI overbought ({rsi_value:.1f})")
    elif rsi_value >= 48 and ema_fast < ema_slow:
        bear_factors.append(f"RSI pullback for shorts ({rsi_value:.1f})")

    if divergence and divergence.kind == "bullish":
        bull_factors.append(f"Bullish RSI divergence: {divergence.note}")
    if divergence and divergence.kind == "bearish":
        bear_factors.append(f"Bearish RSI divergence: {divergence.note}")

    if price <= bb_lower * 1.0004:
        bull_factors.append("Close at/under lower Bollinger band")
    if price >= bb_upper * 0.9996:
        bear_factors.append("Close at/over upper Bollinger band")

    macd_line = _num(row, "macd")
    macd_sig = _num(row, "macd_signal")
    macd_hist = _num(row, "macd_hist")
    if bool(row.get("macd_cross_up")):
        bull_factors.append("MACD bullish cross")
    elif macd_hist is not None and macd_hist > 0 and macd_line is not None and macd_sig is not None and macd_line > macd_sig:
        bull_factors.append("MACD histogram positive")
    if bool(row.get("macd_cross_down")):
        bear_factors.append("MACD bearish cross")
    elif macd_hist is not None and macd_hist < 0 and macd_line is not None and macd_sig is not None and macd_line < macd_sig:
        bear_factors.append("MACD histogram negative")

    stoch_k = _num(row, "stoch_k")
    stoch_d = _num(row, "stoch_d")
    if bool(row.get("stoch_cross_up")):
        bull_factors.append("Stochastic %K crossed above %D")
    elif stoch_k is not None and stoch_k <= 30:
        bull_factors.append(f"Stochastic oversold ({stoch_k:.0f})")
    if bool(row.get("stoch_cross_down")):
        bear_factors.append("Stochastic %K crossed below %D")
    elif stoch_k is not None and stoch_k >= 70:
        bear_factors.append(f"Stochastic overbought ({stoch_k:.0f})")

    adx_value = _num(row, "adx")
    plus_di = _num(row, "plus_di")
    minus_di = _num(row, "minus_di")
    if adx_value is not None and adx_value >= 18 and plus_di is not None and minus_di is not None:
        if plus_di > minus_di:
            bull_factors.append(f"ADX {adx_value:.0f} with +DI")
        elif minus_di > plus_di:
            bear_factors.append(f"ADX {adx_value:.0f} with −DI")

    cci_value = _num(row, "cci")
    if cci_value is not None and cci_value <= -100:
        bull_factors.append(f"CCI oversold ({cci_value:.0f})")
    if cci_value is not None and cci_value >= 100:
        bear_factors.append(f"CCI overbought ({cci_value:.0f})")

    st_dir = _num(row, "st_dir")
    if _flag(row, "st_flip_up"):
        bull_factors.append("Supertrend flip to bullish")
    elif st_dir is not None and st_dir > 0:
        bull_factors.append("Supertrend bullish")
    if _flag(row, "st_flip_down"):
        bear_factors.append("Supertrend flip to bearish")
    elif st_dir is not None and st_dir < 0:
        bear_factors.append("Supertrend bearish")

    squeeze_on = _flag(row, "squeeze_on")
    squeeze_fire = _flag(row, "squeeze_fire")
    squeeze_label = "fire" if squeeze_fire else ("on" if squeeze_on else "off")
    if squeeze_fire:
        if macd_hist is not None and macd_hist > 0:
            bull_factors.append("TTM squeeze fire with positive momentum")
        elif macd_hist is not None and macd_hist < 0:
            bear_factors.append("TTM squeeze fire with negative momentum")
        else:
            if ema_fast > ema_slow:
                bull_factors.append("TTM squeeze fire")
            elif ema_fast < ema_slow:
                bear_factors.append("TTM squeeze fire")

    vwap = _num(row, "vwap")
    vwap_disp = _num(row, "vwap_disp")
    if vwap_disp is not None and vwap is not None:
        if vwap_disp > 0.4 and ema_fast > ema_slow:
            bull_factors.append("Continuation beyond session VWAP (fair price)")
        elif vwap_disp < -0.4 and ema_fast < ema_slow:
            bear_factors.append("Continuation beyond session VWAP (fair price)")

    if _flag(row, "sweep_low"):
        bull_factors.append("Liquidity sweep of prior lows (close back inside Donchian)")
    if _flag(row, "sweep_high"):
        bear_factors.append("Liquidity sweep of prior highs (close back inside Donchian)")

    if _flag(row, "ichi_above"):
        bull_factors.append("Price above Ichimoku Kumo")
    elif _flag(row, "ichi_below"):
        bear_factors.append("Price below Ichimoku Kumo")

    wt1 = _num(row, "wt1")
    if _flag(row, "wt_cross_up"):
        bull_factors.append("WaveTrend bullish cross")
    elif wt1 is not None and wt1 <= -53:
        bull_factors.append(f"WaveTrend oversold ({wt1:.0f})")
    if _flag(row, "wt_cross_down"):
        bear_factors.append("WaveTrend bearish cross")
    elif wt1 is not None and wt1 >= 53:
        bear_factors.append(f"WaveTrend overbought ({wt1:.0f})")

    ewmac_v = _num(row, "ewmac")
    if ewmac_v is not None and ewmac_v >= 0.5:
        bull_factors.append(f"EWMAC trend strength {ewmac_v:.1f}")
    elif ewmac_v is not None and ewmac_v <= -0.5:
        bear_factors.append(f"EWMAC trend strength {ewmac_v:.1f}")

    wma48 = _num(row, "wma48")
    dss_v = _num(row, "dss")
    dss_sig = _num(row, "dss_signal")
    ox_long = False
    ox_short = False
    if wma48 is not None and price > wma48:
        bull_factors.append("Close above LWMA 48")
    elif wma48 is not None and price < wma48:
        bear_factors.append("Close below LWMA 48")
    if _flag(row, "te_break_up"):
        bull_factors.append("Trend Envelopes break up (Ox orange line)")
    elif _num(row, "te_up") is not None and price > float(row["te_up"]):
        bull_factors.append("Price above Trend Envelopes orange line")
    if _flag(row, "te_break_down"):
        bear_factors.append("Trend Envelopes break down (Ox blue line)")
    elif _num(row, "te_down") is not None and price < float(row["te_down"]):
        bear_factors.append("Price below Trend Envelopes blue line")
    if _flag(row, "dss_bull") or (
        dss_v is not None and dss_sig is not None and dss_v > dss_sig
    ):
        bull_factors.append("DSS of momentum green / above signal")
    if _flag(row, "dss_bear") or (
        dss_v is not None and dss_sig is not None and dss_v < dss_sig
    ):
        bear_factors.append("DSS of momentum orange / below signal")
    if htf is not None:
        htf_row = _last_valid(htf)
        if htf_row is not None:
            htf_wma = _num(htf_row, "wma48")
            htf_close = float(htf_row["close"])
            if htf_wma is not None and htf_close > htf_wma:
                bull_factors.append("H1 above LWMA 48")
            elif htf_wma is not None and htf_close < htf_wma:
                bear_factors.append("H1 below LWMA 48")
    ox_long = (
        wma48 is not None
        and price > wma48
        and (_flag(row, "te_break_up") or (_num(row, "te_up") is not None and price > float(row["te_up"])))
        and (dss_v is not None and dss_sig is not None and dss_v > dss_sig)
    )
    ox_short = (
        wma48 is not None
        and price < wma48
        and (_flag(row, "te_break_down") or (_num(row, "te_down") is not None and price < float(row["te_down"])))
        and (dss_v is not None and dss_sig is not None and dss_v < dss_sig)
    )
    if ox_long:
        bull_factors.append("Ox scalp triad (LWMA + envelope + DSS)")
    if ox_short:
        bear_factors.append("Ox scalp triad (LWMA + envelope + DSS)")

    if _flag(row, "vol_expansion"):
        bar_open = _num(row, "open")
        if bar_open is not None and price >= bar_open:
            bull_factors.append("Volume expansion on an up-bar")
        elif bar_open is not None and price < bar_open:
            bear_factors.append("Volume expansion on a down-bar")

    if bias == "bullish":
        bull_factors.append(f"{settings.htf_bias_timeframe} trend bullish")
    elif bias == "bearish":
        bear_factors.append(f"{settings.htf_bias_timeframe} trend bearish")
    if d1_bias == "bullish":
        bull_factors.append("D1 trend bullish")
    elif d1_bias == "bearish":
        bear_factors.append("D1 trend bearish")

    atr_pips = price_to_pips(symbol, atr_value)
    vol_note = f"ATR {atr_pips:.1f} pips" if atr_pips >= 3 else None
    # ATR is a filter, not a directional vote — counting it on both sides
    # used to manufacture confluence in dead, two-sided tape.

    min_atr = float(getattr(settings, "min_atr_pips", 0.8) or 0.8)
    if atr_pips < min_atr:
        bull_factors = []
        bear_factors = []
    action: Action = "HOLD"
    confluence: list[str] = []
    if len(bull_factors) >= settings.min_confluence and len(bull_factors) > len(bear_factors):
        if bias != "bearish":
            action = "BUY"
            confluence = [f for f in bull_factors if f != vol_note] + ([vol_note] if vol_note else [])
    if len(bear_factors) >= settings.min_confluence and len(bear_factors) > len(bull_factors):
        if bias != "bullish":
            action = "SELL"
            confluence = [f for f in bear_factors if f != vol_note] + ([vol_note] if vol_note else [])
    # H1 is the map. Mixed M5 (bull votes ≥ bear) used to HOLD forever while
    # H1 was bearish — the long was blocked and the short never fired.
    if action == "HOLD":
        if bias == "bearish" and len(bear_factors) >= settings.min_confluence:
            action = "SELL"
            confluence = [f for f in bear_factors if f != vol_note] + ([vol_note] if vol_note else [])
        elif bias == "bullish" and len(bull_factors) >= settings.min_confluence:
            action = "BUY"
            confluence = [f for f in bull_factors if f != vol_note] + ([vol_note] if vol_note else [])

    # H1 flat + a one-vote M5 split used to HOLD forever. Fade the extreme, or
    # use D1 as the map. A mid-range coin-flip still sits out.
    if (
        action == "HOLD"
        and bias == "neutral"
        and len(bull_factors) >= settings.min_confluence
        and len(bear_factors) >= settings.min_confluence
    ):
        if _is_spike(price, rsi_value, bb_upper, wt1) and d1_bias != "bullish":
            action = "SELL"
            confluence = [f for f in bear_factors if f != vol_note] + ([vol_note] if vol_note else [])
            confluence.append("Fade of the M5 spike")
        elif _is_washout(price, rsi_value, bb_lower, wt1) and d1_bias != "bearish":
            action = "BUY"
            confluence = [f for f in bull_factors if f != vol_note] + ([vol_note] if vol_note else [])
            confluence.append("Bounce off the M5 washout")
        elif d1_bias == "bearish":
            action = "SELL"
            confluence = [f for f in bear_factors if f != vol_note] + ([vol_note] if vol_note else [])
            confluence.append("D1-aligned short while H1 is flat")
        elif d1_bias == "bullish":
            action = "BUY"
            confluence = [f for f in bull_factors if f != vol_note] + ([vol_note] if vol_note else [])
            confluence.append("D1-aligned long while H1 is flat")

    reason: str
    sl = tp1 = tp2 = rr = None
    if action in ("BUY", "SELL"):
        sl, tp1, tp2, rr = _levels(action, price, atr_value, settings, symbol)
        if rr < settings.min_rr_ratio:
            action = "HOLD"
            reason = f"R:R {rr:.2f} below minimum {settings.min_rr_ratio}"
            confluence = []
        else:
            reason = "; ".join(confluence)
    else:
        why_hold = []
        if bias == "bearish" and len(bull_factors) >= settings.min_confluence:
            why_hold.append("Long blocked by H1 bearish bias")
        if bias == "bullish" and len(bear_factors) >= settings.min_confluence:
            why_hold.append("Short blocked by H1 bullish bias")
        if not why_hold:
            why_hold.append(
                f"No confluence (bull={len(bull_factors)} bear={len(bear_factors)} "
                f"need>={settings.min_confluence})"
            )
        reason = "; ".join(why_hold)

    if action in ("BUY", "SELL") and settings.require_htf_trend and bias == "neutral":
        is_fade = any("fade" in f.lower() or "washout" in f.lower() or "d1-aligned" in f.lower() for f in confluence)
        d1_aligned = (action == "SELL" and d1_bias == "bearish") or (action == "BUY" and d1_bias == "bullish")
        if not is_fade and not d1_aligned and len(confluence) < settings.min_confluence + 1:
            action = "HOLD"
            sl = tp1 = tp2 = rr = None
            confluence = []
            reason = "EUR/USD specialist waits for an H1 trend — no edge in a flat higher timeframe"

    if action == "BUY" and d1_bias == "bearish" and len(confluence) < settings.min_confluence + 1:
        action = "HOLD"
        sl = tp1 = tp2 = rr = None
        confluence = []
        reason = "Long against D1 needs extra confluence — waiting for a cleaner snapshot"
    elif action == "SELL" and d1_bias == "bullish" and len(confluence) < settings.min_confluence + 1:
        action = "HOLD"
        sl = tp1 = tp2 = rr = None
        confluence = []
        reason = "Short against D1 needs extra confluence — waiting for a cleaner snapshot"

    triggers = {
        "band": any("Bollinger" in f for f in confluence),
        "rsi_extreme": any("rsi oversold" in f.lower() or "rsi overbought" in f.lower() for f in confluence),
        "rsi_pullback": any("rsi pullback" in f.lower() for f in confluence),
        "stoch": any("stochastic" in f.lower() for f in confluence),
        "cci": any("cci " in f.lower() for f in confluence),
        "cross": any("cross" in f.lower() for f in confluence),
        "div": any("divergence" in f.lower() for f in confluence),
        "macd": any("macd" in f.lower() for f in confluence),
        "adx": any("adx " in f.lower() for f in confluence),
        "squeeze": any("squeeze" in f.lower() for f in confluence),
        "sweep": any("liquidity sweep" in f.lower() for f in confluence),
        "supertrend": any("supertrend flip" in f.lower() for f in confluence),
        "wavetrend": any("wavetrend" in f.lower() for f in confluence),
        "scalp": any("ox scalp" in f.lower() or "trend envelope" in f.lower() or "dss of momentum" in f.lower() for f in confluence),
        "fade": any("fade" in f.lower() or "washout" in f.lower() or "d1-aligned" in f.lower() for f in confluence),
    }
    continuation = False
    if action == "BUY":
        continuation = bias != "bearish" and (
            (macd_hist is not None and macd_hist > 0)
            or (adx_value is not None and plus_di is not None and minus_di is not None and adx_value >= 18 and plus_di > minus_di)
            or ema_fast > ema_slow
            or (st_dir is not None and st_dir > 0)
        )
    elif action == "SELL":
        continuation = bias != "bullish" and (
            (macd_hist is not None and macd_hist < 0)
            or (adx_value is not None and plus_di is not None and minus_di is not None and adx_value >= 18 and minus_di > plus_di)
            or ema_fast < ema_slow
            or (st_dir is not None and st_dir < 0)
        )
    # Reaction Path / TMA: do not chase when price is already stretched from fair price.
    tma_stretch = _num(row, "tma_stretch")
    stretched = (tma_stretch is not None and tma_stretch >= 1.8) or (
        vwap_disp is not None and abs(vwap_disp) >= 1.8
    )
    if action in ("BUY", "SELL") and squeeze_on and continuation and not any(triggers.values()):
        action = "HOLD"
        sl = tp1 = tp2 = rr = None
        confluence = []
        reason = "TTM squeeze is on — wait for the fire rather than fading compression."
    elif action in ("BUY", "SELL") and stretched and continuation and not any(triggers.values()):
        action = "HOLD"
        sl = tp1 = tp2 = rr = None
        confluence = []
        reason = (
            "Stretched from TMA/VWAP fair price — Reaction Path says wait for a "
            "reaction, not a chase."
        )
    elif action in ("BUY", "SELL") and not any(triggers.values()) and not continuation:
        action = "HOLD"
        sl = tp1 = tp2 = rr = None
        confluence = []
        reason = (
            "No trigger — need a band/RSI/stoch/CCI/WaveTrend extreme, a squeeze fire, "
            "a liquidity sweep, a cross, divergence, an Ox scalp triad, or H1-aligned continuation "
            "(EMA / MACD / ADX / Supertrend)."
        )
    elif action in ("BUY", "SELL") and continuation and not any(triggers.values()):
        tag = "H1-aligned trend continuation"
        if tag not in confluence:
            confluence.append(tag)
        reason = "; ".join(confluence)
    # Do not sell a washout or buy a spike. Those were the -$81 lower-band short
    # and the chase-into-overbought tickets — the tape is already extended.
    # Contrarian Zones + WaveTrend: stacked oscillator extremes are exhaustion.
    wt_washout = wt1 is not None and wt1 <= -53
    wt_spike = wt1 is not None and wt1 >= 53
    if action == "SELL":
        at_lower = price <= bb_lower * 1.0004
        if rsi_value <= 40 or at_lower or wt_washout:
            if bias != "bearish" and d1_bias != "bearish" and len(bull_factors) >= settings.min_confluence:
                fade_sl, fade_tp1, fade_tp2, fade_rr = _levels("BUY", price, atr_value, settings, symbol)
                if fade_rr < settings.min_rr_ratio:
                    action = "HOLD"
                    sl = tp1 = tp2 = rr = None
                    confluence = []
                    reason = f"R:R {fade_rr:.2f} below minimum {settings.min_rr_ratio}"
                else:
                    action = "BUY"
                    confluence = [f for f in bull_factors if f != vol_note] + ([vol_note] if vol_note else [])
                    confluence.append("Bounce off the M5 washout")
                    sl, tp1, tp2, rr = fade_sl, fade_tp1, fade_tp2, fade_rr
                    reason = "; ".join(confluence)
            else:
                action = "HOLD"
                sl = tp1 = tp2 = rr = None
                confluence = []
                reason = (
                    f"Will not short a bounce (RSI {rsi_value:.1f}"
                    f"{', WaveTrend oversold' if wt_washout else ''}"
                    f"{', sitting on the lower band' if at_lower else ''}). "
                    "Wait for RSI to reset or a lower high."
                )
    elif action == "BUY":
        at_upper = price >= bb_upper * 0.9996
        if rsi_value >= 60 or at_upper or wt_spike:
            if bias != "bullish" and d1_bias != "bullish" and len(bear_factors) >= settings.min_confluence:
                fade_sl, fade_tp1, fade_tp2, fade_rr = _levels("SELL", price, atr_value, settings, symbol)
                if fade_rr < settings.min_rr_ratio:
                    action = "HOLD"
                    sl = tp1 = tp2 = rr = None
                    confluence = []
                    reason = f"R:R {fade_rr:.2f} below minimum {settings.min_rr_ratio}"
                else:
                    action = "SELL"
                    confluence = [f for f in bear_factors if f != vol_note] + ([vol_note] if vol_note else [])
                    confluence.append("Fade of the M5 spike")
                    sl, tp1, tp2, rr = fade_sl, fade_tp1, fade_tp2, fade_rr
                    reason = "; ".join(confluence)
            else:
                action = "HOLD"
                sl = tp1 = tp2 = rr = None
                confluence = []
                reason = (
                    f"Will not buy a spike (RSI {rsi_value:.1f}"
                    f"{', WaveTrend overbought' if wt_spike else ''}"
                    f"{', sitting on the upper band' if at_upper else ''}). "
                    "Wait for RSI to reset or a higher low."
                )

    is_fade = any(
        "fade" in item.lower() or "bounce off the m5 washout" in item.lower()
        for item in confluence
    )
    body_atr = candle_body_atr(row)
    if action in {"BUY", "SELL"} and not is_fade and body_atr is not None and body_atr < 0.25:
        action = "HOLD"
        sl = tp1 = tp2 = rr = None
        confluence = []
        reason = (
            f"Indecision candle (body {body_atr:.2f} ATR) — wait for a committed close, "
            "not a doji through the envelope."
        )
    elif action in {"BUY", "SELL"} and body_atr is not None and body_atr >= 0.6:
        tag = f"Committed close ({body_atr:.1f} ATR body)"
        if tag not in confluence:
            confluence.append(tag)
    regime = classify_regime(row, bias, d1_bias)
    if action in {"BUY", "SELL"}:
        tag = f"Regime {regime}"
        if tag not in confluence:
            confluence.append(tag)

    if settings.session_filter and not session_is_open(now, settings):
        action = "HOLD"
        sl = tp1 = tp2 = rr = None
        confluence = []
        reason = _session_hold_reason(now, settings)

    strength = int(round(100 * max(len(bull_factors), len(bear_factors)) / 10.0))
    strength = max(0, min(100, strength))
    if action == "HOLD":
        strength = min(strength, 55)

    return TradeSignal(
        symbol=symbol,
        timeframe=timeframe,
        action=action,
        timestamp=ts if isinstance(ts, datetime) else utcnow(),
        price=price,
        entry=price if action != "HOLD" else None,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        risk_reward=rr,
        atr=atr_value,
        rsi=rsi_value,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        bb_upper=bb_upper,
        bb_mid=bb_mid,
        bb_lower=bb_lower,
        htf_bias=bias,
        confluence=confluence,
        reason=reason,
        strength=strength,
        divergence=divergence.kind if divergence else None,
        d1_bias=d1_bias,
        macd=macd_line,
        macd_signal=macd_sig,
        macd_hist=macd_hist,
        stoch_k=stoch_k,
        stoch_d=stoch_d,
        adx=adx_value,
        plus_di=plus_di,
        minus_di=minus_di,
        cci=cci_value,
        vwap=vwap,
        supertrend=_num(row, "supertrend"),
        squeeze=squeeze_label,
        wt=wt1,
        signal_type=classify_signal_type(action, confluence),
        source="live",
    )


def bars_to_frame(rows: list[Any]) -> pd.DataFrame:
    """Convert storage.Bar objects or dicts into an indicator-ready frame."""
    records = []
    for row in rows:
        if isinstance(row, dict):
            records.append(row)
        else:
            records.append(
                {
                    "ts": row.ts,
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                    "volume": float(row.volume or 0),
                }
            )
    if not records:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = pd.DataFrame.from_records(records)
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    frame = frame.sort_values("ts")
    frame = frame.set_index("ts")
    return frame
