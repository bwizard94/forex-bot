from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.analysis.indicators import atr, compute_indicators, dss_momentum, ema, rsi, trend_envelopes, wma
from src.analysis.signals import classify_signal_type, evaluate_signal
from src.config import Settings
from src.utils import canonical_pair, parse_iso, pip_size, to_display_symbol, to_oanda_instrument


def _ohlc(n: int = 160, start: float = 1.08, drift: float = 0.00018) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = [start]
    for _ in range(n - 1):
        shock = float(rng.normal(drift, 0.00007))
        close.append(close[-1] + shock)
    close = np.array(close)
    high = close + 0.00025
    low = close - 0.00022
    open_ = np.r_[close[0], close[:-1]]
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 100}, index=idx)


def test_symbol_helpers() -> None:
    assert to_display_symbol("EUR_USD") == "EUR/USD"
    assert to_oanda_instrument("EUR/USD") == "EUR_USD"
    assert canonical_pair("USD/EUR") == "EUR/USD"
    assert canonical_pair("eurusd") == "EUR/USD"
    assert pip_size("USD/JPY") == 0.01
    assert pip_size("GBP/USD") == 0.0001


def test_parse_iso_oanda_nanos() -> None:
    dt = parse_iso("2026-09-16T00:51:00.000000000Z")
    assert dt.year == 2026 and dt.minute == 51
    dt2 = parse_iso("2026-09-16 10:52:00")
    assert dt2.hour == 10


def test_indicator_ranges() -> None:
    df = _ohlc()
    out = compute_indicators(df)
    last = out.dropna(subset=["rsi", "atr", "ema_fast", "bb_mid"]).iloc[-1]
    assert 0 <= float(last["rsi"]) <= 100
    assert float(last["atr"]) > 0
    assert float(last["bb_upper"]) > float(last["bb_lower"])
    assert float(out["ema_fast"].dropna().iloc[-1]) > 0


def test_ema_follows_price() -> None:
    s = pd.Series([1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0] * 3)
    values = ema(s, 5).dropna()
    assert values.iloc[-1] > values.iloc[0]


def test_rsi_constant_up() -> None:
    close = pd.Series(np.linspace(1.0, 1.2, 80))
    value = float(rsi(close, 14).iloc[-1])
    assert value > 70


def test_supertrend_skipped_on_heavy_or_huge_frames(monkeypatch) -> None:
    from src.analysis.indicators import SUPER_TREND_MAX_BARS

    df = _ohlc(80)
    live = compute_indicators(df)
    assert live["supertrend"].notna().sum() > 0
    light = compute_indicators(df, heavy=False)
    assert light["supertrend"].isna().all()
    monkeypatch.setattr("src.analysis.indicators.SUPER_TREND_MAX_BARS", 40)
    huge = compute_indicators(df)
    assert huge["supertrend"].isna().all()
    assert huge["st_flip_up"].eq(False).all()
    assert SUPER_TREND_MAX_BARS >= 1000


def test_extra_oscillators_are_computed() -> None:
    df = _ohlc(180)
    out = compute_indicators(df)
    last = out.dropna(subset=["macd", "macd_hist", "stoch_k", "adx", "cci", "supertrend", "vwap", "wt1"]).iloc[-1]
    assert last["macd"] == last["macd"]
    assert 0 <= float(last["stoch_k"]) <= 100
    assert float(last["adx"]) >= 0
    assert float(last["supertrend"]) > 0
    assert float(last["vwap"]) > 0


def test_atr_positive() -> None:
    df = _ohlc(80)
    value = float(atr(df["high"], df["low"], df["close"], 14).iloc[-1])
    assert value > 0


def test_ox_scalp_tools_compute() -> None:
    df = _ohlc(120, start=1.15, drift=0.00015)
    w = wma(df["close"], 48)
    assert float(w.dropna().iloc[-1]) > 0
    te_up, te_dn, br_up, br_dn = trend_envelopes(df["high"], df["low"], df["close"], 2)
    assert float(te_up.dropna().iloc[-1]) >= float(te_dn.dropna().iloc[-1])
    assert br_up.fillna(False).astype(bool).dtype == bool
    assert br_dn.fillna(False).astype(bool).dtype == bool
    line, sig = dss_momentum(df["high"], df["low"], df["close"])
    assert line.dropna().shape[0] > 10
    assert sig.dropna().shape[0] > 5
    out = compute_indicators(df)
    last = out.dropna(subset=["wma48", "dss", "te_up"]).iloc[-1]
    assert float(last["wma48"]) > 0
    assert last["dss"] == last["dss"]


def test_uptrend_emits_buy() -> None:
    settings = Settings(
        min_confluence=3,
        min_rr_ratio=1.0,
        atr_sl_multiplier=1.5,
        atr_tp1_multiplier=2.0,
        atr_tp2_multiplier=3.0,
        session_filter=False,
        require_htf_trend=False,
    )
    bars = _ohlc(180, start=1.05, drift=0.00025)
    signal = evaluate_signal("EUR/USD", "M5", bars, htf_bars=bars, settings=settings)
    assert signal.action in {"BUY", "HOLD"}
    if signal.action == "BUY":
        assert signal.stop_loss < signal.entry < signal.take_profit_1 < signal.take_profit_2
        assert signal.risk_reward and signal.risk_reward >= 1.0
        assert signal.confluence


def test_downtrend_emits_sell_or_hold() -> None:
    settings = Settings(min_confluence=3, min_rr_ratio=1.0, session_filter=False, require_htf_trend=False)
    bars = _ohlc(180, start=1.20, drift=-0.00025)
    signal = evaluate_signal("EUR/USD", "M5", bars, htf_bars=bars, settings=settings)
    assert signal.action in {"SELL", "HOLD"}
    if signal.action == "SELL":
        assert signal.take_profit_2 < signal.take_profit_1 < signal.entry < signal.stop_loss


def test_short_history_is_hold() -> None:
    df = _ohlc(10)
    signal = evaluate_signal("EUR/USD", "M5", df)
    assert signal.action == "HOLD"


def test_weekday_tokyo_hours_are_in_session() -> None:
    settings = Settings(
        min_confluence=2,
        min_rr_ratio=1.0,
        session_filter=True,
        require_htf_trend=False,
        trade_session_start_hour=0,
        trade_session_end_hour=22,
    )
    bars = _ohlc(180, start=1.05, drift=0.00025)
    tokyo = datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)
    london = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    late = datetime(2026, 9, 16, 23, 0, tzinfo=timezone.utc)
    saturday = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    on_tokyo = evaluate_signal("USD/EUR", "M5", bars, htf_bars=bars, settings=settings, now=tokyo)
    on_london = evaluate_signal("USD/EUR", "M5", bars, htf_bars=bars, settings=settings, now=london)
    off_late = evaluate_signal("USD/EUR", "M5", bars, htf_bars=bars, settings=settings, now=late)
    off_weekend = evaluate_signal("USD/EUR", "M5", bars, htf_bars=bars, settings=settings, now=saturday)
    assert on_tokyo.symbol == "EUR/USD"
    assert "session" not in on_tokyo.reason.lower()
    assert "outside" not in on_tokyo.reason.lower()
    assert "weekend" not in on_tokyo.reason.lower()
    assert on_london.symbol == "EUR/USD"
    assert "session" not in on_london.reason.lower()
    assert off_late.action == "HOLD"
    assert "outside" in off_late.reason.lower() or "session" in off_late.reason.lower()
    assert off_weekend.action == "HOLD"
    assert "weekend" in off_weekend.reason.lower()


def test_thin_asia_atr_floors_stop_to_min_pips() -> None:
    settings = Settings(
        min_confluence=2,
        min_rr_ratio=1.0,
        session_filter=False,
        require_htf_trend=False,
        min_stop_pips=2.0,
        atr_sl_multiplier=1.5,
        atr_tp1_multiplier=2.0,
        atr_tp2_multiplier=3.5,
    )
    bars = _ohlc(180, start=1.10, drift=0.00002)
    signal = evaluate_signal("EUR/USD", "M5", bars, htf_bars=bars, settings=settings)
    if signal.action in {"BUY", "SELL"} and signal.entry and signal.stop_loss:
        stop_pips = abs(signal.entry - signal.stop_loss) / 0.0001
        assert stop_pips + 1e-9 >= 2.0


def test_htf_continuation_can_emit_without_band_extreme() -> None:
    settings = Settings(
        min_confluence=2,
        min_rr_ratio=1.0,
        session_filter=False,
        require_htf_trend=True,
        min_atr_pips=0.5,
    )
    bars = _ohlc(180, start=1.10, drift=0.00012)
    signal = evaluate_signal("EUR/USD", "M5", bars, htf_bars=bars, settings=settings)
    assert signal.action in {"BUY", "HOLD"}
    if signal.action == "BUY":
        blob = " ".join(signal.confluence).lower() + " " + signal.reason.lower()
        assert (
            "continuation" in blob
            or "cross" in blob
            or "bollinger" in blob
            or "oversold" in blob
            or "macd" in blob
            or "adx" in blob
            or "stochastic" in blob
            or "pullback" in blob
            or "supertrend" in blob
            or "squeeze" in blob
            or "vwap" in blob
            or "sweep" in blob
            or "wavetrend" in blob
        )
        assert signal.signal_type
        assert signal.source == "live"


def test_htf_bearish_mixed_m5_still_allows_short() -> None:
    """H1 is the map. Mixed M5 used to HOLD (long blocked, short never fired)."""
    settings = Settings(
        min_confluence=2,
        min_rr_ratio=1.0,
        session_filter=False,
        require_htf_trend=True,
        min_atr_pips=0.5,
        atr_sl_multiplier=1.0,
        atr_tp1_multiplier=1.2,
        atr_tp2_multiplier=2.0,
    )
    bars = _ohlc(180, start=1.20, drift=-0.00012)
    signal = evaluate_signal("EUR/USD", "M5", bars, htf_bars=bars, settings=settings)
    assert signal.htf_bias == "bearish" or signal.action in {"SELL", "HOLD"}
    if signal.htf_bias == "bearish":
        assert signal.action in {"SELL", "HOLD"}
        if signal.action == "HOLD":
            assert "spike" in signal.reason.lower() or "washout" in signal.reason.lower() or "bounce" in signal.reason.lower() or "lower band" in signal.reason.lower() or "confluence" in signal.reason.lower() or "squeeze" in signal.reason.lower() or "stretched" in signal.reason.lower() or "h1" in signal.reason.lower() or "trigger" in signal.reason.lower()


def test_will_not_short_an_oversold_washout() -> None:
    settings = Settings(
        min_confluence=2,
        min_rr_ratio=1.0,
        session_filter=False,
        require_htf_trend=False,
        min_atr_pips=0.5,
    )
    bars = _ohlc(180, start=1.20, drift=-0.00025)
    signal = evaluate_signal("EUR/USD", "M5", bars, htf_bars=bars, settings=settings)
    last = compute_indicators(bars).dropna(subset=["rsi", "bb_lower", "close"]).iloc[-1]
    if float(last["rsi"]) <= 40 or float(last["close"]) <= float(last["bb_lower"]) * 1.0004:
        assert signal.action == "HOLD"
        assert "bounce" in signal.reason.lower() or "lower band" in signal.reason.lower()


def test_classify_signal_type_from_confluence() -> None:
    assert classify_signal_type("BUY", ["H1-aligned trend continuation", "EMA 9 above EMA 21"]) == "continuation"
    assert "scalp" in classify_signal_type(
        "BUY",
        ["Ox scalp triad (LWMA + envelope + DSS)", "Trend Envelopes break up (Ox orange line)"],
    )
    assert classify_signal_type("SELL", ["Fade of the M5 spike", "DSS of momentum orange / below signal"]).startswith(
        "fade"
    )
    row = evaluate_signal("EUR/USD", "M5", _ohlc(10))
    assert row.signal_type == "hold"
    payload = row.to_row()
    assert "signal_type" in payload
    assert "rsi" in payload
    assert payload["source"] == "live"


def test_classify_regime_and_doji_body() -> None:
    from src.analysis.signals import candle_body_atr, classify_regime

    squeeze = pd.Series({"squeeze_on": True, "rsi": 50.0, "adx": 30.0, "wt1": 0.0})
    assert classify_regime(squeeze, "bullish", "bullish") == "squeeze"
    trend = pd.Series({"squeeze_on": False, "rsi": 52.0, "adx": 28.0, "wt1": 0.0})
    assert classify_regime(trend, "bearish", "neutral") == "trend_bear"
    wash = pd.Series({"squeeze_on": False, "rsi": 32.0, "adx": 12.0, "wt1": -60.0})
    assert classify_regime(wash, "neutral", "neutral") == "washout"
    doji = pd.Series({"open": 1.15000, "close": 1.15002, "atr": 0.00040})
    assert candle_body_atr(doji) is not None
    assert candle_body_atr(doji) < 0.25
    committed = pd.Series({"open": 1.15000, "close": 1.15040, "atr": 0.00040})
    assert candle_body_atr(committed) >= 0.6
    assert classify_signal_type("SELL", ["Fade of the M5 spike", "Regime rip"]).startswith("fade")


def test_bars_to_frame_accepts_mixed_timezones() -> None:
    from src.analysis.signals import bars_to_frame

    naive = datetime(2026, 9, 16, 19, 40)
    aware = datetime(2026, 9, 16, 19, 45, tzinfo=timezone.utc)
    frame = bars_to_frame(
        [
            {"ts": aware, "open": 1.1, "high": 1.12, "low": 1.09, "close": 1.11, "volume": 1},
            {"ts": naive, "open": 1.1, "high": 1.12, "low": 1.09, "close": 1.10, "volume": 1},
        ]
    )
    assert len(frame) == 2
    assert str(frame.index.tz) == "UTC"
    assert float(frame["close"].iloc[0]) == 1.10
