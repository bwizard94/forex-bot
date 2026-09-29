from __future__ import annotations

from src.analysis.markup import build_markup, detect_candle_pattern, latest_setup_label


def _candle(i: int, open_: float, high: float, low: float, close: float) -> dict:
    return {"time": 1_700_000_000 + i * 300, "open": open_, "high": high, "low": low, "close": close}


def _downtrend(n: int = 48) -> list[dict]:
    rows = []
    price = 1.1600
    for i in range(n):
        swing_high = i % 11 == 0
        swing_low = i % 11 == 6
        high = price + (0.0018 if swing_high else 0.00035)
        low = price - (0.0018 if swing_low else 0.00035)
        close = price - 0.00022
        rows.append(_candle(i, price, high, low, close))
        price -= 0.00028
    return rows


def test_bearish_engulfing_is_named() -> None:
    rows = _downtrend(20)
    rows.append(_candle(20, 1.15400, 1.15490, 1.15390, 1.15470))
    rows.append(_candle(21, 1.15475, 1.15480, 1.15370, 1.15380))
    pattern = detect_candle_pattern(rows)
    assert pattern is not None
    assert pattern["name"] == "bearish engulfing"
    assert latest_setup_label(rows) == "bearish engulfing"


def test_markup_draws_trend_fib_zone_and_text() -> None:
    candles = _downtrend()
    pack = build_markup(
        candles,
        last_ind={"atr": 0.0009, "rsi": 72.0},
        h1_bias="bearish",
        d1_bias="bearish",
    )
    tools = " ".join(d["tool"] for d in pack["drawings"])
    layers = {d["layer"] for d in pack["drawings"]}
    assert "trendline" in tools
    assert "fib" in tools
    assert "zone" in tools
    assert "text" in tools
    assert "icon" in tools
    assert "trend" in layers
    assert "drawing" in layers
    assert "text" in layers
    assert "icons" in layers
    assert pack["thesis"]
    assert "hunt shorts" in pack["thesis"]
    used = " ".join(pack["tools_used"]).lower()
    assert "trend line" in used
    assert "fibonacci" in used
    assert any(d["label"] == "Resistance trend" for d in pack["drawings"])
    assert any(d["tool"] == "channel" for d in pack["drawings"])
