"""Technical indicators: EMA, RSI, ATR, Bollinger, MACD, Stochastic, ADX, CCI,
plus TradingView-community tools the EUR/USD desk actually hunts with.

Community catalog (https://www.tradingview.com/scripts/) mapped onto this book:
Supertrend, TTM Squeeze (BB inside Keltner), session VWAP (Reaction Path fair
price), Donchian liquidity sweeps, Ichimoku Kumo, WaveTrend, TMA, EWMAC.

Ox Securities scalp recipe (https://oxsecurities.com/most-profitable-trading-strategies/)
mapped onto this book: LWMA 48, Trend Envelopes period 2, DSS of momentum.
All series use Wilder smoothing where that is the market convention (RSI, ATR, ADX).
No ta-lib C extension is required — everything is pandas/numpy so the bot
installs cleanly on any Python 3.11+ host.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Supertrend is a Python loop. On ForexSB-sized frames it holds the GIL long
# enough for APScheduler to miss quote/minute/intel jobs. Live M5 is ~300 bars.
SUPER_TREND_MAX_BARS = 4_000


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def wma(series: pd.Series, period: int = 48) -> pd.Series:
    """Linear weighted moving average (Ox LWMA 48). Later bars weigh more."""
    weights = np.arange(1, int(period) + 1, dtype=float)
    denom = float(weights.sum())

    def _dot(window: np.ndarray) -> float:
        return float(np.dot(window, weights) / denom)

    return series.rolling(window=int(period), min_periods=int(period)).apply(_dot, raw=True)


def trend_envelopes(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 2
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Ox Trend Envelopes V2: EMA of highs (orange) and lows (blue).

    Returns te_up, te_down, break_up, break_down. A long is a close through
    the orange line; a short is a close through the blue line.
    """
    te_up = ema(high.astype(float), period)
    te_down = ema(low.astype(float), period)
    prev_close = close.shift(1)
    break_up = (prev_close <= te_up.shift(1)) & (close > te_up)
    break_down = (prev_close >= te_down.shift(1)) & (close < te_down)
    return te_up, te_down, break_up.fillna(False), break_down.fillna(False)


def dss_momentum(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 13,
    smooth: int = 8,
) -> tuple[pd.Series, pd.Series]:
    """Double-smoothed stochastic of momentum (Ox DSS of momentum).

    ``line`` is the additional/fast line; ``signal`` is the dotted trigger.
    Green / long when line is above signal; orange / short when below.
    """
    typical = (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0
    mom = typical.diff(1)
    lowest = mom.rolling(window=length, min_periods=length).min()
    highest = mom.rolling(window=length, min_periods=length).max()
    scale = (highest - lowest).replace(0.0, np.nan)
    raw = 100.0 * (mom - lowest) / scale
    line = ema(raw, smooth)
    signal = ema(line, smooth)
    return line, signal


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    values = 100.0 - (100.0 / (1.0 + rs))
    values = values.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    values = values.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    values = values.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return values


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return true_range(high, low, close).ewm(
        alpha=1 / period, min_periods=period, adjust=False
    ).mean()


def bollinger(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = line - sig
    return line, sig, hist


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    lowest = low.rolling(window=k_period, min_periods=k_period).min()
    highest = high.rolling(window=k_period, min_periods=k_period).max()
    scale = (highest - lowest).replace(0.0, np.nan)
    k = 100.0 * (close - lowest) / scale
    d = k.rolling(window=d_period, min_periods=d_period).mean()
    return k, d


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = true_range(high, low, close)
    atr_w = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_w.replace(
        0.0, np.nan
    )
    minus_di = 100.0 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_w.replace(
        0.0, np.nan
    )
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx_line = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx_line, plus_di, minus_di


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    typical = (high + low + close) / 3.0
    mean = sma(typical, period)
    mad = typical.rolling(window=period, min_periods=period).apply(
        lambda window: np.mean(np.abs(window - np.mean(window))), raw=True
    )
    return (typical - mean) / (0.015 * mad.replace(0.0, np.nan))


def tma(series: pd.Series, period: int = 21) -> pd.Series:
    """Triangular moving average (Colored TMA Trend Signals)."""
    half = max(2, (int(period) + 1) // 2)
    return sma(sma(series, half), half)


def keltner(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 20,
    multiplier: float = 1.5,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = ema(close, period)
    width = atr(high, low, close, period) * multiplier
    return mid + width, mid, mid - width


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 10,
    multiplier: float = 3.0,
) -> tuple[pd.Series, pd.Series]:
    """ATR trailing Supertrend. Direction +1 is bullish, -1 is bearish."""
    atr_v = atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    basic_ub = (hl2 + multiplier * atr_v).to_numpy(dtype=float)
    basic_lb = (hl2 - multiplier * atr_v).to_numpy(dtype=float)
    close_v = close.to_numpy(dtype=float)
    n = len(close_v)
    final_ub = np.full(n, np.nan)
    final_lb = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    line = np.full(n, np.nan)
    for i in range(n):
        if not np.isfinite(basic_ub[i]) or not np.isfinite(basic_lb[i]):
            continue
        if i == 0 or not np.isfinite(final_ub[i - 1]) or not np.isfinite(final_lb[i - 1]):
            final_ub[i] = basic_ub[i]
            final_lb[i] = basic_lb[i]
            direction[i] = 1.0 if close_v[i] >= hl2.iloc[i] else -1.0
            line[i] = final_lb[i] if direction[i] > 0 else final_ub[i]
            continue
        prev_close = close_v[i - 1]
        final_lb[i] = (
            max(basic_lb[i], final_lb[i - 1]) if prev_close > final_lb[i - 1] else basic_lb[i]
        )
        final_ub[i] = (
            min(basic_ub[i], final_ub[i - 1]) if prev_close < final_ub[i - 1] else basic_ub[i]
        )
        if direction[i - 1] > 0:
            direction[i] = -1.0 if close_v[i] < final_lb[i] else 1.0
        else:
            direction[i] = 1.0 if close_v[i] > final_ub[i] else -1.0
        line[i] = final_lb[i] if direction[i] > 0 else final_ub[i]
    idx = close.index
    return pd.Series(line, index=idx), pd.Series(direction, index=idx)


def session_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series | None = None,
    index: pd.Index | None = None,
) -> pd.Series:
    """UTC-session VWAP — Reaction Path 'fair price' on FX (no RTH)."""
    typical = (high + low + close) / 3.0
    if volume is None:
        vol = pd.Series(1.0, index=typical.index)
    else:
        vol = volume.astype(float).replace(0.0, np.nan).fillna(1.0)
    idx = index if index is not None else typical.index
    stamps = pd.to_datetime(idx, utc=True)
    day = pd.Series(stamps.date, index=typical.index)
    cum_pv = (typical * vol).groupby(day).cumsum()
    cum_v = vol.groupby(day).cumsum()
    return cum_pv / cum_v.replace(0.0, np.nan)


def donchian(
    high: pd.Series, low: pd.Series, period: int = 20
) -> tuple[pd.Series, pd.Series, pd.Series]:
    upper = high.rolling(window=period, min_periods=period).max()
    lower = low.rolling(window=period, min_periods=period).min()
    mid = (upper + lower) / 2.0
    return upper, mid, lower


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    tenkan_p: int = 9,
    kijun_p: int = 26,
    senkou_p: int = 52,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    tenkan = (high.rolling(tenkan_p).max() + low.rolling(tenkan_p).min()) / 2.0
    kijun = (high.rolling(kijun_p).max() + low.rolling(kijun_p).min()) / 2.0
    span_a = ((tenkan + kijun) / 2.0).shift(kijun_p)
    span_b = ((high.rolling(senkou_p).max() + low.rolling(senkou_p).min()) / 2.0).shift(kijun_p)
    return tenkan, kijun, span_a, span_b


def wavetrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    channel: int = 10,
    average: int = 21,
) -> tuple[pd.Series, pd.Series]:
    """LazyBear WaveTrend — the oscillator the TV community actually uses."""
    ap = (high + low + close) / 3.0
    esa = ema(ap, channel)
    d = ema((ap - esa).abs(), channel)
    ci = (ap - esa) / (0.015 * d.replace(0.0, np.nan))
    wt1 = ema(ci, average)
    wt2 = sma(wt1, 4)
    return wt1, wt2


def ewmac(close: pd.Series, fast: int = 16, slow: int = 64) -> pd.Series:
    """Volatility-normalized EMA spread (QuantAlgo EWMAC)."""
    spread = ema(close, fast) - ema(close, slow)
    sigma = close.diff().rolling(window=slow, min_periods=max(8, slow // 4)).std()
    return spread / sigma.replace(0.0, np.nan)


def _swing_indices(series: pd.Series, kind: str, lookback: int = 3) -> list[int]:
    """Return integer positions of local extrema."""
    values = series.to_numpy(dtype=float)
    found: list[int] = []
    for i in range(lookback, len(values) - lookback):
        window = values[i - lookback : i + lookback + 1]
        if np.isnan(window).any():
            continue
        center = values[i]
        if kind == "high" and center == np.max(window) and center > values[i - 1]:
            found.append(i)
        elif kind == "low" and center == np.min(window) and center < values[i - 1]:
            found.append(i)
    return found


@dataclass(frozen=True, slots=True)
class Divergence:
    kind: str  # bullish | bearish
    confirmed: bool
    note: str


def detect_rsi_divergence(
    close: pd.Series,
    rsi_series: pd.Series,
    lookback_bars: int = 40,
    swing: int = 3,
) -> Divergence | None:
    if len(close) < lookback_bars:
        frame_c = close
        frame_r = rsi_series
    else:
        frame_c = close.iloc[-lookback_bars:]
        frame_r = rsi_series.iloc[-lookback_bars:]

    # Reindex local positions against the sliced frame.
    close_s = frame_c.reset_index(drop=True)
    rsi_s = frame_r.reset_index(drop=True)

    highs = _swing_indices(close_s, "high", lookback=swing)
    lows = _swing_indices(close_s, "low", lookback=swing)

    if len(highs) >= 2:
        i1, i2 = highs[-2], highs[-1]
        price_hh = close_s.iloc[i2] > close_s.iloc[i1]
        rsi_lh = rsi_s.iloc[i2] < rsi_s.iloc[i1]
        if price_hh and rsi_lh:
            return Divergence(
                kind="bearish",
                confirmed=True,
                note=f"Price HH vs RSI LH ({rsi_s.iloc[i1]:.1f} → {rsi_s.iloc[i2]:.1f})",
            )

    if len(lows) >= 2:
        i1, i2 = lows[-2], lows[-1]
        price_ll = close_s.iloc[i2] < close_s.iloc[i1]
        rsi_hl = rsi_s.iloc[i2] > rsi_s.iloc[i1]
        if price_ll and rsi_hl:
            return Divergence(
                kind="bullish",
                confirmed=True,
                note=f"Price LL vs RSI HL ({rsi_s.iloc[i1]:.1f} → {rsi_s.iloc[i2]:.1f})",
            )
    return None


def compute_indicators(
    df: pd.DataFrame,
    *,
    ema_fast: int = 9,
    ema_slow: int = 21,
    rsi_period: int = 14,
    atr_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
    heavy: bool = True,
) -> pd.DataFrame:
    """Append indicator columns onto an OHLCV frame. Index is preserved.

    ``heavy=False`` (or a frame longer than ``SUPER_TREND_MAX_BARS``) skips the
    Supertrend loop so historical restudy cannot stall the live trading clock.
    """
    if df.empty:
        return df.copy()
    required = {"open", "high", "low", "close"}
    missing = required - set(c.lower() for c in df.columns)
    # Normalise column names to lowercase without mutating caller unexpectedly.
    work = df.copy()
    work.columns = [c.lower() for c in work.columns]
    missing = required - set(work.columns)
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {sorted(missing)}")

    close = work["close"].astype(float)
    high = work["high"].astype(float)
    low = work["low"].astype(float)

    work["ema_fast"] = ema(close, ema_fast)
    work["ema_slow"] = ema(close, ema_slow)
    work["ema_fast_prev"] = work["ema_fast"].shift(1)
    work["ema_slow_prev"] = work["ema_slow"].shift(1)
    work["rsi"] = rsi(close, rsi_period)
    work["atr"] = atr(high, low, close, atr_period)
    upper, mid, lower = bollinger(close, bb_period, bb_std)
    work["bb_upper"] = upper
    work["bb_mid"] = mid
    work["bb_lower"] = lower
    work["bb_pct"] = (close - lower) / (upper - lower).replace(0.0, np.nan)
    work["ema_cross_up"] = (
        (work["ema_fast_prev"] <= work["ema_slow_prev"]) & (work["ema_fast"] > work["ema_slow"])
    )
    work["ema_cross_down"] = (
        (work["ema_fast_prev"] >= work["ema_slow_prev"]) & (work["ema_fast"] < work["ema_slow"])
    )
    work["trend"] = np.where(work["ema_fast"] > work["ema_slow"], 1, -1)
    macd_line, macd_sig, macd_hist = macd(close)
    work["macd"] = macd_line
    work["macd_signal"] = macd_sig
    work["macd_hist"] = macd_hist
    work["macd_prev"] = work["macd"].shift(1)
    work["macd_signal_prev"] = work["macd_signal"].shift(1)
    work["macd_cross_up"] = (work["macd_prev"] <= work["macd_signal_prev"]) & (work["macd"] > work["macd_signal"])
    work["macd_cross_down"] = (work["macd_prev"] >= work["macd_signal_prev"]) & (work["macd"] < work["macd_signal"])
    stoch_k, stoch_d = stochastic(high, low, close)
    work["stoch_k"] = stoch_k
    work["stoch_d"] = stoch_d
    work["stoch_k_prev"] = work["stoch_k"].shift(1)
    work["stoch_d_prev"] = work["stoch_d"].shift(1)
    work["stoch_cross_up"] = (work["stoch_k_prev"] <= work["stoch_d_prev"]) & (
        work["stoch_k"] > work["stoch_d"]
    )
    work["stoch_cross_down"] = (work["stoch_k_prev"] >= work["stoch_d_prev"]) & (
        work["stoch_k"] < work["stoch_d"]
    )
    adx_line, plus_di, minus_di = adx(high, low, close)
    work["adx"] = adx_line
    work["plus_di"] = plus_di
    work["minus_di"] = minus_di
    work["cci"] = cci(high, low, close)

    volume = work["volume"].astype(float) if "volume" in work.columns else pd.Series(1.0, index=work.index)
    work["tma"] = tma(close, 21)
    work["tma_prev"] = work["tma"].shift(1)
    run_supertrend = bool(heavy) and len(work) <= SUPER_TREND_MAX_BARS
    if run_supertrend:
        st_line, st_dir = supertrend(high, low, close)
        work["supertrend"] = st_line
        work["st_dir"] = st_dir
        work["st_dir_prev"] = work["st_dir"].shift(1)
        work["st_flip_up"] = (work["st_dir_prev"] < 0) & (work["st_dir"] > 0)
        work["st_flip_down"] = (work["st_dir_prev"] > 0) & (work["st_dir"] < 0)
    else:
        work["supertrend"] = np.nan
        work["st_dir"] = np.nan
        work["st_dir_prev"] = np.nan
        work["st_flip_up"] = False
        work["st_flip_down"] = False
    kc_upper, kc_mid, kc_lower = keltner(high, low, close)
    work["kc_upper"] = kc_upper
    work["kc_mid"] = kc_mid
    work["kc_lower"] = kc_lower
    squeeze_on = (work["bb_upper"] < work["kc_upper"]) & (work["bb_lower"] > work["kc_lower"])
    work["squeeze_on"] = squeeze_on.fillna(False).astype(bool)
    work["squeeze_prev"] = work["squeeze_on"].shift(1, fill_value=False).astype(bool)
    work["squeeze_fire"] = (~work["squeeze_on"]) & work["squeeze_prev"]
    work["vwap"] = session_vwap(high, low, close, volume, work.index)
    dc_upper, dc_mid, dc_lower = donchian(high, low)
    work["dc_upper"] = dc_upper
    work["dc_mid"] = dc_mid
    work["dc_lower"] = dc_lower
    prior_high = dc_upper.shift(1)
    prior_low = dc_lower.shift(1)
    work["sweep_high"] = (high > prior_high) & (close < prior_high)
    work["sweep_low"] = (low < prior_low) & (close > prior_low)
    tenkan, kijun, span_a, span_b = ichimoku(high, low, close)
    work["ichi_tenkan"] = tenkan
    work["ichi_kijun"] = kijun
    work["ichi_span_a"] = span_a
    work["ichi_span_b"] = span_b
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    cloud_bot = pd.concat([span_a, span_b], axis=1).min(axis=1)
    work["ichi_above"] = close > cloud_top
    work["ichi_below"] = close < cloud_bot
    wt1, wt2 = wavetrend(high, low, close)
    work["wt1"] = wt1
    work["wt2"] = wt2
    work["wt1_prev"] = work["wt1"].shift(1)
    work["wt2_prev"] = work["wt2"].shift(1)
    work["wt_cross_up"] = (work["wt1_prev"] <= work["wt2_prev"]) & (work["wt1"] > work["wt2"])
    work["wt_cross_down"] = (work["wt1_prev"] >= work["wt2_prev"]) & (work["wt1"] < work["wt2"])
    work["ewmac"] = ewmac(close)
    vol_mean = volume.rolling(window=20, min_periods=10).mean()
    vol_std = volume.rolling(window=20, min_periods=10).std()
    work["vol_z"] = (volume - vol_mean) / vol_std.replace(0.0, np.nan)
    rng = (high - low).astype(float)
    rng_mean = rng.rolling(window=20, min_periods=10).mean()
    work["vol_expansion"] = (work["vol_z"] >= 2.0) & (rng > rng_mean * 1.2)
    work["vol_absorption"] = (work["vol_z"] >= 2.0) & (rng < rng_mean * 0.8)
    work["tma_stretch"] = (close - work["tma"]).abs() / work["atr"].replace(0.0, np.nan)
    work["vwap_disp"] = (close - work["vwap"]) / work["atr"].replace(0.0, np.nan)
    work["wma48"] = wma(close, 48)
    te_up, te_dn, te_break_up, te_break_dn = trend_envelopes(high, low, close, 2)
    work["te_up"] = te_up
    work["te_down"] = te_dn
    work["te_break_up"] = te_break_up.astype(bool)
    work["te_break_down"] = te_break_dn.astype(bool)
    dss_line, dss_sig = dss_momentum(high, low, close)
    work["dss"] = dss_line
    work["dss_signal"] = dss_sig
    work["dss_prev"] = work["dss"].shift(1)
    work["dss_bull"] = (work["dss"] > work["dss_signal"]) & (work["dss"] >= work["dss_prev"])
    work["dss_bear"] = (work["dss"] < work["dss_signal"]) & (work["dss"] <= work["dss_prev"])
    return work
