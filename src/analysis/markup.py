"""Professional chart markup on OANDA candles.

fxTrade / Advanced Charts expose Indicators, Text, Trend line, Drawing mode,
Icons, and Patterns only in the UI — v20 cannot inject those objects. This
module uses the same toolkit on the OANDA candles the desk already streams,
so the hub Chart is marked the way a specialist would mark the practice book.
"""

from __future__ import annotations

from typing import Any, Iterable

from src.utils import format_price, price_to_pips

LAYERS = ("indicators", "text", "trend", "drawing", "icons", "patterns")

FIB_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)

_SWING_LOOKBACK = 3


def _drawing(
    *,
    tool: str,
    layer: str,
    points: list[dict[str, float | int]],
    color: str,
    label: str = "",
    style: str = "solid",
    width: int = 1,
    extend: str | None = None,
    icon: str = "",
    fill: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": tool,
        "layer": layer,
        "points": points,
        "color": color,
        "label": label,
        "style": style,
        "width": width,
        "extend": extend,
        "icon": icon,
        "fill": fill,
    }
    if extra:
        payload.update(extra)
    return payload


def _swings(candles: list[dict[str, Any]], kind: str, lookback: int = _SWING_LOOKBACK) -> list[dict[str, Any]]:
    if len(candles) < lookback * 2 + 3:
        return []
    key = "high" if kind == "high" else "low"
    values = [float(c[key]) for c in candles]
    found: list[dict[str, Any]] = []
    for i in range(lookback, len(values) - lookback):
        window = values[i - lookback : i + lookback + 1]
        center = values[i]
        if kind == "high" and center >= max(window) and center > values[i - 1]:
            found.append({"index": i, "time": int(candles[i]["time"]), "price": center})
        elif kind == "low" and center <= min(window) and center < values[i - 1]:
            found.append({"index": i, "time": int(candles[i]["time"]), "price": center})
    return found


def _body(bar: dict[str, Any]) -> float:
    return abs(float(bar["close"]) - float(bar["open"]))


def _range(bar: dict[str, Any]) -> float:
    return max(1e-9, float(bar["high"]) - float(bar["low"]))


def detect_candle_pattern(candles: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Name the most recent actionable candlestick / structure pattern."""
    if len(candles) < 3:
        return None
    last, prev, older = candles[-1], candles[-2], candles[-3]
    last_bull = float(last["close"]) > float(last["open"])
    prev_bull = float(prev["close"]) > float(prev["open"])
    last_body = _body(last)
    prev_body = _body(prev)
    last_range = _range(last)

    if (
        not prev_bull
        and last_bull
        and float(last["open"]) <= float(prev["close"])
        and float(last["close"]) >= float(prev["open"])
        and last_body > prev_body
    ):
        return {"name": "bullish engulfing", "bias": "BUY", "index": len(candles) - 1, "bar": last}
    if (
        prev_bull
        and not last_bull
        and float(last["open"]) >= float(prev["close"])
        and float(last["close"]) <= float(prev["open"])
        and last_body > prev_body
    ):
        return {"name": "bearish engulfing", "bias": "SELL", "index": len(candles) - 1, "bar": last}

    if float(last["high"]) < float(prev["high"]) and float(last["low"]) > float(prev["low"]):
        return {"name": "inside bar", "bias": "HOLD", "index": len(candles) - 1, "bar": last}

    upper = float(last["high"]) - max(float(last["open"]), float(last["close"]))
    lower = min(float(last["open"]), float(last["close"])) - float(last["low"])
    if lower >= 2.0 * max(last_body, last_range * 0.15) and last_bull:
        return {"name": "hammer", "bias": "BUY", "index": len(candles) - 1, "bar": last}
    if upper >= 2.0 * max(last_body, last_range * 0.15) and not last_bull:
        return {"name": "shooting star", "bias": "SELL", "index": len(candles) - 1, "bar": last}

    # Three-bar evening / morning structure (loose).
    older_bull = float(older["close"]) > float(older["open"])
    if older_bull and _body(older) > last_body and not last_bull and float(last["close"]) < float(older["open"]):
        return {"name": "evening structure", "bias": "SELL", "index": len(candles) - 1, "bar": last}
    if (not older_bull) and _body(older) > last_body and last_bull and float(last["close"]) > float(older["open"]):
        return {"name": "morning structure", "bias": "BUY", "index": len(candles) - 1, "bar": last}
    return None


def detect_structure(highs: list[dict[str, Any]], lows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1]["price"] > highs[-2]["price"]
        hl = lows[-1]["price"] > lows[-2]["price"]
        lh = highs[-1]["price"] < highs[-2]["price"]
        ll = lows[-1]["price"] < lows[-2]["price"]
        if lh and ll:
            return {"name": "lower highs / lower lows", "bias": "SELL"}
        if hh and hl:
            return {"name": "higher highs / higher lows", "bias": "BUY"}
        if lh and hl:
            return {"name": "descending triangle / squeeze", "bias": "HOLD"}
    if len(highs) >= 2:
        pip_gap = price_to_pips("EUR/USD", abs(highs[-1]["price"] - highs[-2]["price"]))
        if pip_gap <= 8.0:
            return {"name": "double top", "bias": "SELL"}
    if len(lows) >= 2:
        pip_gap = price_to_pips("EUR/USD", abs(lows[-1]["price"] - lows[-2]["price"]))
        if pip_gap <= 8.0:
            return {"name": "double bottom", "bias": "BUY"}
    return None


def _impulse(candles: list[dict[str, Any]], window: int = 80) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    sample = candles[-window:] if len(candles) > window else candles
    if len(sample) < 8:
        return None
    hi = max(sample, key=lambda c: float(c["high"]))
    lo = min(sample, key=lambda c: float(c["low"]))
    if int(hi["time"]) == int(lo["time"]):
        return None
    if int(hi["time"]) > int(lo["time"]):
        return lo, hi, "up"
    return hi, lo, "down"


def _fib_price(start: dict[str, Any], end: dict[str, Any], ratio: float, direction: str) -> float:
    high = float(start["high"] if "high" in start else start["price"])
    low = float(end["low"] if "low" in end else end["price"])
    if direction == "up":
        low = float(start["low"] if "low" in start else start["price"])
        high = float(end["high"] if "high" in end else end["price"])
        return low + (high - low) * ratio
    high = float(start["high"] if "high" in start else start["price"])
    low = float(end["low"] if "low" in end else end["price"])
    return high - (high - low) * ratio


def latest_setup_label(candles: list[dict[str, Any]]) -> str:
    pattern = detect_candle_pattern(candles)
    if pattern:
        return str(pattern["name"])
    highs = _swings(candles, "high")
    lows = _swings(candles, "low")
    structure = detect_structure(highs, lows)
    if structure:
        return str(structure["name"])
    return ""


def build_markup(
    candles: list[dict[str, Any]],
    *,
    last_ind: dict[str, Any] | None = None,
    h1_bias: str = "neutral",
    d1_bias: str = "neutral",
    news: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Return drawings + a thesis a specialist would ink on the tape."""
    last_ind = last_ind or {}
    drawings: list[dict[str, Any]] = []
    tools: list[str] = ["Indicators: EMA 9/21, Bollinger, MACD, RSI, Stochastic, ADX"]
    if not candles:
        return {
            "drawings": [],
            "layers": list(LAYERS),
            "tools_used": tools,
            "thesis": "Waiting on OANDA candles.",
            "pattern": None,
        }

    last = candles[-1]
    last_t = int(last["time"])
    last_px = float(last["close"])
    atr = float(last_ind["atr"]) if last_ind.get("atr") else abs(float(last["high"]) - float(last["low"]))
    highs = _swings(candles, "high")
    lows = _swings(candles, "low")
    pattern = detect_candle_pattern(candles)
    structure = detect_structure(highs, lows)

    # --- Trend lines (swing highs / swing lows), extended right ---
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        drawings.append(
            _drawing(
                tool="trendline",
                layer="trend",
                points=[
                    {"time": a["time"], "price": a["price"]},
                    {"time": b["time"], "price": b["price"]},
                ],
                color="#ff6b73",
                label="Resistance trend",
                width=2,
                extend="right",
            )
        )
        tools.append("Trend line: swing-high resistance")
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        drawings.append(
            _drawing(
                tool="trendline",
                layer="trend",
                points=[
                    {"time": a["time"], "price": a["price"]},
                    {"time": b["time"], "price": b["price"]},
                ],
                color="#3ee0b0",
                label="Support trend",
                width=2,
                extend="right",
            )
        )
        tools.append("Trend line: swing-low support")

    # Parallel channel off the dominant H1 side.
    if h1_bias == "bearish" and len(highs) >= 2 and lows:
        a, b = highs[-2], highs[-1]
        anchor = lows[-1]
        dt = max(1, int(b["time"]) - int(a["time"]))
        projected = a["price"] + (b["price"] - a["price"]) * ((int(anchor["time"]) - int(a["time"])) / dt)
        offset = float(anchor["price"]) - projected
        drawings.append(
            _drawing(
                tool="channel",
                layer="drawing",
                points=[
                    {"time": a["time"], "price": a["price"] + offset},
                    {"time": b["time"], "price": b["price"] + offset},
                ],
                color="rgba(62,224,176,0.7)",
                label="Bear channel",
                style="dashed",
                extend="right",
            )
        )
        tools.append("Drawing: parallel bear channel")
    elif h1_bias == "bullish" and len(lows) >= 2 and highs:
        a, b = lows[-2], lows[-1]
        anchor = highs[-1]
        dt = max(1, int(b["time"]) - int(a["time"]))
        projected = a["price"] + (b["price"] - a["price"]) * ((int(anchor["time"]) - int(a["time"])) / dt)
        offset = float(anchor["price"]) - projected
        drawings.append(
            _drawing(
                tool="channel",
                layer="drawing",
                points=[
                    {"time": a["time"], "price": a["price"] + offset},
                    {"time": b["time"], "price": b["price"] + offset},
                ],
                color="rgba(255,107,115,0.7)",
                label="Bull channel",
                style="dashed",
                extend="right",
            )
        )
        tools.append("Drawing: parallel bull channel")

    # --- Fibonacci of the last impulse ---
    impulse = _impulse(candles)
    if impulse:
        start, end, direction = impulse
        t0 = int(start["time"])
        t1 = last_t
        for ratio in FIB_RATIOS:
            price = _fib_price(start, end, ratio, direction)
            tag = f"Fib {ratio:.3f}".replace("0.000", "0").replace("1.000", "1")
            drawings.append(
                _drawing(
                    tool="fib",
                    layer="drawing",
                    points=[
                        {"time": t0, "price": price},
                        {"time": t1, "price": price},
                    ],
                    color="#d6ba7a" if ratio in {0.5, 0.618} else "rgba(214,186,122,0.55)",
                    label=tag if ratio in {0.382, 0.5, 0.618} else "",
                    style="dotted" if ratio not in {0.5, 0.618} else "dashed",
                    extra={"ratio": ratio},
                )
            )
        tools.append(f"Drawing: Fibonacci {direction} impulse")

    # --- Supply / demand zones around latest swings ---
    pad = max(atr * 0.35, 0.00012)
    if highs:
        h = highs[-1]
        drawings.append(
            _drawing(
                tool="zone",
                layer="drawing",
                points=[
                    {"time": h["time"], "price": h["price"] + pad * 0.4},
                    {"time": last_t, "price": h["price"] - pad},
                ],
                color="#ff6b73",
                label="Supply",
                fill="rgba(255,107,115,0.12)",
            )
        )
        tools.append("Drawing: supply zone")
    if lows:
        lo = lows[-1]
        drawings.append(
            _drawing(
                tool="zone",
                layer="drawing",
                points=[
                    {"time": lo["time"], "price": lo["price"] + pad},
                    {"time": last_t, "price": lo["price"] - pad * 0.4},
                ],
                color="#3ee0b0",
                label="Demand",
                fill="rgba(62,224,176,0.12)",
            )
        )
        tools.append("Drawing: demand zone")

    # --- Icons on recent swings ---
    for swing in highs[-4:]:
        drawings.append(
            _drawing(
                tool="icon",
                layer="icons",
                points=[{"time": swing["time"], "price": swing["price"]}],
                color="#ff6b73",
                label="swing high",
                icon="▼",
            )
        )
    for swing in lows[-4:]:
        drawings.append(
            _drawing(
                tool="icon",
                layer="icons",
                points=[{"time": swing["time"], "price": swing["price"]}],
                color="#3ee0b0",
                label="swing low",
                icon="▲",
            )
        )
    if highs or lows:
        tools.append("Icons: swing highs / lows")

    rsi = last_ind.get("rsi")
    if rsi is not None:
        if float(rsi) >= 70:
            drawings.append(
                _drawing(
                    tool="icon",
                    layer="icons",
                    points=[{"time": last_t, "price": last_px}],
                    color="#ff6b73",
                    label=f"RSI {float(rsi):.0f}",
                    icon="⚡",
                )
            )
        elif float(rsi) <= 30:
            drawings.append(
                _drawing(
                    tool="icon",
                    layer="icons",
                    points=[{"time": last_t, "price": last_px}],
                    color="#3ee0b0",
                    label=f"RSI {float(rsi):.0f}",
                    icon="⚡",
                )
            )

    # --- Pattern box + label ---
    named = pattern or (
        {"name": structure["name"], "bias": structure["bias"], "bar": last, "index": len(candles) - 1}
        if structure
        else None
    )
    if named:
        bar = named.get("bar") or last
        drawings.append(
            _drawing(
                tool="pattern",
                layer="patterns",
                points=[
                    {"time": int(bar["time"]), "price": float(bar["high"]) + pad * 0.2},
                    {"time": int(bar["time"]), "price": float(bar["low"]) - pad * 0.2},
                ],
                color="#d6ba7a",
                label=str(named["name"]),
                fill="rgba(214,186,122,0.16)",
                extra={"bias": named.get("bias")},
            )
        )
        drawings.append(
            _drawing(
                tool="text",
                layer="patterns",
                points=[{"time": int(bar["time"]), "price": float(bar["high"])}],
                color="#d6ba7a",
                label=str(named["name"]).upper(),
            )
        )
        tools.append(f"Patterns: {named['name']}")

    # --- Text thesis ---
    hunt = "shorts" if h1_bias == "bearish" else "longs" if h1_bias == "bullish" else "wait for H1"
    thesis_bits = [
        f"H1 {h1_bias}",
        f"D1 {d1_bias}",
        f"hunt {hunt}",
    ]
    if named:
        thesis_bits.append(str(named["name"]))
    if last_ind.get("rsi") is not None:
        thesis_bits.append(f"RSI {float(last_ind['rsi']):.0f}")
    thesis = " · ".join(thesis_bits)
    drawings.append(
        _drawing(
            tool="text",
            layer="text",
            points=[{"time": last_t, "price": float(last["high"])}],
            color="#e8efe9",
            label=thesis,
        )
    )
    tools.append("Text: live thesis on last bar")

    unique_tools: list[str] = []
    for item in tools:
        if item not in unique_tools:
            unique_tools.append(item)

    return {
        "drawings": drawings,
        "layers": list(LAYERS),
        "tools_used": unique_tools,
        "thesis": thesis,
        "pattern": None if named is None else {"name": named["name"], "bias": named.get("bias")},
    }


def oanda_markup_comment(*, side: str, signal: Any, pattern_name: str = "") -> str:
    """Stamp the OANDA ticket with the same thesis the chart just inked."""
    from src.utils import format_price as fmt

    price = fmt("EUR/USD", getattr(signal, "entry", None) or getattr(signal, "price", 0) or 0)
    sl = fmt("EUR/USD", getattr(signal, "stop_loss", None) or 0)
    tp = fmt("EUR/USD", getattr(signal, "take_profit_1", None) or 0)
    bias = getattr(signal, "htf_bias", "") or ""
    strength = getattr(signal, "strength", 0) or 0
    pattern = (pattern_name or "")[:18]
    text = f"{side} EURUSD @{price} SL{sl} TP{tp} {bias} {pattern} s{strength}".replace("  ", " ")
    return text[:128]
