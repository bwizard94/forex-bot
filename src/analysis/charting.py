"""OANDA-backed EUR/USD chart pack: candles plus desk markings.

OANDA's REST API cannot draw on fxTrade/TradingView charts. This module
builds the same annotations a specialist would put on those candles —
EMAs, bands, session stamps, news, signals, SL/TP — so the hub chart
and OANDA trade comments stay in lockstep with the demo book.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analysis.indicators import compute_indicators
from src.analysis.markup import build_markup, oanda_markup_comment
from src.analysis.signals import _htf_bias, bars_to_frame
from src.config import Settings, get_settings
from src.data.news import CalendarEvent, NewsBundle
from src.data.storage import SignalRow, Trade, TradeJournal, load_bars
from src.utils import utcnow


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def unix_ts(ts: datetime | None) -> int | None:
    aware = _aware(ts)
    if aware is None:
        return None
    return int(aware.timestamp())


def oanda_trade_comment(*, side: str, signal: Any, pattern_name: str = "") -> str:
    """<=128 char stamp that appears on the OANDA demo trade."""
    return oanda_markup_comment(side=side, signal=signal, pattern_name=pattern_name)


def oanda_thesis_comment(thesis: str | None) -> str:
    line = (thesis or "EURUSD desk fill").splitlines()[0].strip()
    return line[:128]


def _snap(target: int, times: Sequence[int]) -> int | None:
    if not times:
        return None
    return min(times, key=lambda t: abs(t - target))


def _line(time: int, value: float | None) -> dict[str, float | int] | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return {"time": time, "value": number}


def _price_line(price: float, title: str, color: str, style: str = "dashed") -> dict[str, Any]:
    return {
        "price": float(price),
        "title": title,
        "color": color,
        "style": style,
    }


def _round_levels(price: float) -> list[dict[str, Any]]:
    figure = round(price / 0.01) * 0.01
    half = round(price / 0.005) * 0.005
    lines = [_price_line(figure, f"Big fig {figure:.2f}", "#8aa094", "dotted")]
    if abs(half - figure) > 1e-8:
        lines.append(_price_line(half, f"50-pip {half:.3f}", "#8aa094", "dotted"))
    return lines


def build_chart_pack(
    session: Session,
    *,
    symbol: str = "EUR/USD",
    timeframe: str = "M5",
    settings: Settings | None = None,
    news: NewsBundle | None = None,
    last_price: float | None = None,
    limit: int = 240,
) -> dict[str, Any]:
    settings = settings or get_settings()
    timeframe = (timeframe or "M5").upper()
    if timeframe not in {"M1", "M5", "H1", "D1"}:
        timeframe = "M5"
    bars = load_bars(session, symbol, timeframe, limit=max(80, min(int(limit), 500)))
    frame = bars_to_frame(bars)
    candles: list[dict[str, Any]] = []
    volumes: list[dict[str, Any]] = []
    times: list[int] = []
    for bar in bars:
        t = unix_ts(bar.ts)
        if t is None:
            continue
        candles.append(
            {
                "time": t,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
            }
        )
        volumes.append(
            {
                "time": t,
                "value": float(bar.volume or 0),
                "color": "rgba(62,224,176,0.28)" if float(bar.close) >= float(bar.open) else "rgba(255,107,115,0.28)",
            }
        )
        times.append(t)
    overlays: dict[str, list[dict[str, Any]]] = {
        "ema_fast": [],
        "ema_slow": [],
        "bb_upper": [],
        "bb_mid": [],
        "bb_lower": [],
        "rsi": [],
        "macd_hist": [],
        "stoch_k": [],
        "adx": [],
        "vwap": [],
        "supertrend": [],
    }
    last_ind: dict[str, Any] = {}
    if not frame.empty:
        computed = compute_indicators(
            frame,
            ema_fast=settings.ema_fast,
            ema_slow=settings.ema_slow,
            rsi_period=settings.rsi_period,
            atr_period=settings.atr_period,
            bb_period=settings.bb_period,
            bb_std=settings.bb_std,
        )
        for ts, row in computed.iterrows():
            t = unix_ts(ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts)
            if t is None:
                continue
            for key in ("ema_fast", "ema_slow", "bb_upper", "bb_mid", "bb_lower", "rsi", "macd_hist", "stoch_k", "adx", "vwap", "supertrend"):
                if key not in overlays:
                    overlays[key] = []
                point = _line(t, row.get(key))
                if point:
                    overlays[key].append(point)
        ready = computed.dropna(subset=["ema_fast", "ema_slow", "rsi", "atr"])
        if not ready.empty:
            last = ready.iloc[-1]
            last_ind = {
                "ema_fast": float(last["ema_fast"]),
                "ema_slow": float(last["ema_slow"]),
                "rsi": float(last["rsi"]),
                "atr": float(last["atr"]),
                "macd": float(last["macd"]) if last.get("macd") == last.get("macd") else None,
                "macd_hist": float(last["macd_hist"]) if last.get("macd_hist") == last.get("macd_hist") else None,
                "stoch_k": float(last["stoch_k"]) if last.get("stoch_k") == last.get("stoch_k") else None,
                "adx": float(last["adx"]) if last.get("adx") == last.get("adx") else None,
                "cci": float(last["cci"]) if last.get("cci") == last.get("cci") else None,
                "bb_upper": float(last["bb_upper"]) if last.get("bb_upper") == last.get("bb_upper") else None,
                "bb_mid": float(last["bb_mid"]) if last.get("bb_mid") == last.get("bb_mid") else None,
                "bb_lower": float(last["bb_lower"]) if last.get("bb_lower") == last.get("bb_lower") else None,
                "vwap": float(last["vwap"]) if last.get("vwap") == last.get("vwap") else None,
                "supertrend": float(last["supertrend"]) if last.get("supertrend") == last.get("supertrend") else None,
                "wt1": float(last["wt1"]) if last.get("wt1") == last.get("wt1") else None,
            }

    h1_rows = load_bars(session, symbol, "H1", limit=180)
    d1_rows = load_bars(session, symbol, "D1", limit=40)
    h1_bias = _htf_bias(compute_indicators(bars_to_frame(h1_rows))) if h1_rows else "neutral"
    d1_bias = _htf_bias(compute_indicators(bars_to_frame(d1_rows))) if d1_rows else "neutral"

    start = _aware(bars[0].ts) if bars else utcnow() - timedelta(days=2)
    end = _aware(bars[-1].ts) if bars else utcnow()
    markers: list[dict[str, Any]] = []
    legend: list[dict[str, Any]] = []
    price_lines: list[dict[str, Any]] = []

    signals = list(
        session.scalars(
            select(SignalRow)
            .where(
                SignalRow.symbol == symbol,
                SignalRow.ts >= start,
                SignalRow.ts <= (end + timedelta(minutes=5) if end else end),
                SignalRow.action.in_(["BUY", "SELL"]),
            )
            .order_by(SignalRow.ts.asc())
        )
    )
    for sig in signals[-80:]:
        t = _snap(unix_ts(sig.ts) or 0, times)
        if t is None:
            continue
        skipped = bool(sig.skipped)
        if sig.action == "BUY":
            color, shape, pos = ("#3ee0b0", "arrowUp", "belowBar")
        else:
            color, shape, pos = ("#ff6b73", "arrowDown", "aboveBar")
        if skipped:
            shape, color = "circle", "#d6ba7a"
        label = f"{sig.action}" + (" skip" if skipped else "")
        markers.append(
            {
                "time": t,
                "position": pos,
                "color": color,
                "shape": shape,
                "text": label,
            }
        )
        legend.append(
            {
                "kind": "skip" if skipped else "signal",
                "ts": sig.ts.isoformat() if sig.ts else None,
                "title": f"{sig.action} {symbol} · {sig.timeframe} · str {sig.strength}",
                "detail": sig.skip_reason or sig.reason,
                "price": sig.price,
                "color": color,
            }
        )

    if last_ind.get("rsi") is not None:
        last_t = times[-1] if times else None
        rsi = last_ind["rsi"]
        if last_t is not None and rsi >= 70:
            markers.append(
                {"time": last_t, "position": "aboveBar", "color": "#ff6b73", "shape": "square", "text": f"RSI {rsi:.0f}"}
            )
        elif last_t is not None and rsi <= 30:
            markers.append(
                {"time": last_t, "position": "belowBar", "color": "#3ee0b0", "shape": "square", "text": f"RSI {rsi:.0f}"}
            )

    for bar in bars:
        ts = _aware(bar.ts)
        if ts is None or timeframe == "D1":
            continue
        if ts.minute == 0 and ts.hour in {0, 7, 12, 21}:
            t = unix_ts(ts)
            if t is None:
                continue
            label = {0: "TKY", 7: "LDN", 12: "NY", 21: "END"}[ts.hour]
            markers.append(
                {
                    "time": t,
                    "position": "aboveBar",
                    "color": "#d6ba7a",
                    "shape": "square",
                    "text": label,
                }
            )

    events: Iterable[CalendarEvent] = news.events if news else []
    for event in events:
        ts = _aware(event.ts)
        if ts is None or event.impact not in {"High", "Medium"}:
            continue
        if start and ts < start - timedelta(hours=2):
            continue
        t = _snap(unix_ts(ts) or 0, times)
        if t is None and times and ts.date() == utcnow().date() and event.impact == "High":
            t = times[-1]
        if t is None:
            continue
        if end and ts > end + timedelta(hours=6) and t != (times[-1] if times else None):
            continue
        markers.append(
            {
                "time": t,
                "position": "aboveBar",
                "color": "#d6ba7a",
                "shape": "arrowDown" if event.impact == "High" else "circle",
                "text": (f"{event.title} {ts.strftime('%H:%M')}" if ts > (end or ts) else event.title)[:18],
            }
        )
        legend.append(
            {
                "kind": "news",
                "ts": ts.isoformat(),
                "title": f"{event.impact} {event.country} {event.title}",
                "detail": f"forecast {event.forecast} · prev {event.previous}".strip(" ·"),
                "price": None,
                "color": "#d6ba7a",
            }
        )

    trades = list(
        session.scalars(
            select(Trade)
            .where(Trade.symbol == symbol)
            .order_by(Trade.created_at.desc())
            .limit(40)
        )
    )
    open_trades = [t for t in trades if t.status in {"open", "partial"}]
    for trade in trades:
        opened = unix_ts(trade.opened_at or trade.created_at)
        if opened is None:
            continue
        t = _snap(opened, times)
        if t is None:
            continue
        buy = trade.side == "BUY"
        markers.append(
            {
                "time": t,
                "position": "belowBar" if buy else "aboveBar",
                "color": "#3ee0b0" if buy else "#ff6b73",
                "shape": "arrowUp" if buy else "arrowDown",
                "text": f"FILL {trade.side}",
            }
        )
        if trade.status == "closed" and trade.closed_at:
            xt = _snap(unix_ts(trade.closed_at) or 0, times)
            if xt is not None:
                markers.append(
                    {
                        "time": xt,
                        "position": "aboveBar" if buy else "belowBar",
                        "color": "#3ee0b0" if float(trade.realized_pl or 0) >= 0 else "#ff6b73",
                        "shape": "circle",
                        "text": f"X {float(trade.realized_pl or 0):+.0f}",
                    }
                )
        journal = session.scalar(select(TradeJournal).where(TradeJournal.trade_id == trade.id))
        legend.append(
            {
                "kind": "trade",
                "ts": (trade.opened_at or trade.created_at).isoformat() if (trade.opened_at or trade.created_at) else None,
                "title": f"{trade.side} {symbol} #{trade.broker_trade_id or trade.id} · {trade.status}",
                "detail": (journal.entry_thesis if journal else None) or trade.close_reason or "",
                "price": trade.fill_price,
                "color": "#3ee0b0" if buy else "#ff6b73",
            }
        )

    last_close = candles[-1]["close"] if candles else last_price
    if last_close:
        price_lines.extend(_round_levels(float(last_close)))
        price_lines.append(_price_line(float(last_close), "Last", "#e8efe9", "solid"))
    if last_ind.get("ema_fast"):
        price_lines.append(_price_line(last_ind["ema_fast"], "EMA9", "#d6ba7a", "solid"))
    if last_ind.get("ema_slow"):
        price_lines.append(_price_line(last_ind["ema_slow"], "EMA21", "#8aa094", "solid"))
    if last_ind.get("vwap"):
        price_lines.append(_price_line(last_ind["vwap"], "VWAP", "#7ec8e3", "dashed"))
    if last_ind.get("supertrend"):
        price_lines.append(_price_line(last_ind["supertrend"], "Supertrend", "#c084fc", "dashed"))

    d1_sorted = sorted(d1_rows, key=lambda b: b.ts)
    if d1_sorted:
        today = utcnow().date()
        prior = [b for b in d1_sorted if _aware(b.ts) and _aware(b.ts).date() < today]
        current = [b for b in d1_sorted if _aware(b.ts) and _aware(b.ts).date() == today]
        if prior:
            y = prior[-1]
            price_lines.append(_price_line(float(y.high), "Y day high", "#3ee0b0", "dotted"))
            price_lines.append(_price_line(float(y.low), "Y day low", "#ff6b73", "dotted"))
        open_src = current[-1] if current else (prior[-1] if prior else None)
        if open_src is not None:
            price_lines.append(_price_line(float(open_src.open), "Daily open", "#d6ba7a", "dashed"))

    for trade in open_trades:
        fill = float(trade.fill_price or trade.requested_entry)
        side_color = "#3ee0b0" if trade.side == "BUY" else "#ff6b73"
        price_lines.append(_price_line(fill, f"Entry {trade.side}", side_color, "solid"))
        price_lines.append(_price_line(float(trade.stop_loss), "SL", "#ff6b73", "dashed"))
        price_lines.append(_price_line(float(trade.take_profit_1), "TP1", "#d6ba7a", "dashed"))
        price_lines.append(_price_line(float(trade.take_profit_2), "TP2", "#3ee0b0", "dashed"))

    # Deduplicate marker times+text so lightweight-charts does not drop them.
    seen: set[tuple[int, str]] = set()
    unique_markers = []
    for mark in markers:
        key = (int(mark["time"]), str(mark.get("text") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique_markers.append(mark)
    unique_markers.sort(key=lambda m: m["time"])

    source = bars[-1].source if bars else "oanda"
    markup = build_markup(
        candles,
        last_ind=last_ind,
        h1_bias=h1_bias,
        d1_bias=d1_bias,
        news=events,
    )
    for drawing in markup["drawings"]:
        if drawing["tool"] not in {"text", "pattern"}:
            continue
        if drawing.get("icon") == "🚩":
            continue
        label = drawing.get("label")
        if not label:
            continue
        legend.append(
            {
                "kind": drawing["tool"],
                "ts": None,
                "title": str(label),
                "detail": drawing.get("layer"),
                "price": (drawing.get("points") or [{}])[0].get("price"),
                "color": drawing.get("color") or "#d6ba7a",
            }
        )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": source,
        "bias": {"h1": h1_bias, "d1": d1_bias},
        "last": last_ind,
        "spot": last_price or last_close,
        "candles": candles,
        "volume": volumes,
        "overlays": overlays,
        "markers": unique_markers,
        "price_lines": price_lines,
        "drawings": markup["drawings"],
        "layers": markup["layers"],
        "tools_used": markup["tools_used"],
        "thesis": markup["thesis"],
        "pattern": markup["pattern"],
        "legend": legend[-48:],
        "note": (
            f"{symbol} {timeframe} · OANDA {source} candles · "
            f"{markup['thesis']}"
        ),
    }
