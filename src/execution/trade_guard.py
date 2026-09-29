"""Hands-off rules for operator demo fills and honest TP1 management.

The desk used to adopt unknown OANDA tickets, invent take-profit-1 at the
fill price, then call TradeClose because the open-trade payload's ``price``
field is the fill — not the mark. A 1-unit BUY taught by the operator was
therefore flattened at a scratch or a loss. This module is the gate that
stops that. Operator tickets stay unmanaged; new desk fills use OPEN_ONLY
so they can sit beside them instead of netting against them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
import math

from src.utils import canonical_pair, price_to_pips, to_display_symbol

SOURCE_BOT = "bot"
SOURCE_HUMAN = "human"

MIN_PARTIAL_UNITS = 2
MIN_TP1_PIPS = 5.0

OPERATOR_SKIP = (
    "Hands off — an operator EUR/USD ticket is open. Desk fills use OPEN_ONLY "
    "so they sit beside it instead of netting against it."
)


def _extensions(remote_row: Mapping[str, Any]) -> dict[str, Any]:
    ext = remote_row.get("clientExtensions") or remote_row.get("tradeClientExtensions") or {}
    return ext if isinstance(ext, dict) else {}


def classify_remote_trade(remote_row: Mapping[str, Any]) -> str:
    """Only an explicit ``fs-…`` ID grants the desk ownership of a fill."""
    ext = _extensions(remote_row)
    cid = str(ext.get("id") or "")
    if cid.startswith("fs-"):
        return SOURCE_BOT
    return SOURCE_HUMAN


def is_operator_trade(trade: Any, remote_row: Mapping[str, Any] | None = None) -> bool:
    source = getattr(trade, "source", None)
    if source == SOURCE_HUMAN:
        return True
    if source == SOURCE_BOT:
        return False
    if remote_row is not None:
        return classify_remote_trade(remote_row) == SOURCE_HUMAN
    if getattr(trade, "signal_id", None) is None:
        return True
    return False


def adopted_levels(
    remote_row: Mapping[str, Any],
    *,
    source: str,
) -> dict[str, float]:
    """SL/TP copied from the broker. Never invent TP1 equal to the fill."""
    fill = float(remote_row.get("price") or 0)
    sl = float((remote_row.get("stopLossOrder") or {}).get("price") or 0)
    tp2 = float((remote_row.get("takeProfitOrder") or {}).get("price") or 0)
    if source == SOURCE_HUMAN:
        return {"stop_loss": sl, "take_profit_1": 0.0, "take_profit_2": tp2}
    tp1 = 0.0
    if tp2 and fill:
        units = float(remote_row.get("currentUnits") or remote_row.get("initialUnits") or 0)
        side = "BUY" if units >= 0 else "SELL"
        try:
            from src.config import get_settings

            settings = get_settings()
            sl_m = float(settings.atr_sl_multiplier) or 1.0
            tp1_m = float(settings.atr_tp1_multiplier) or 1.2
            tp2_m = float(settings.atr_tp2_multiplier) or 2.0
            frac = tp1_m / tp2_m if tp2_m else (tp1_m / sl_m if sl_m else 0.6)
        except Exception:
            frac = 0.6
        if side == "BUY" and tp2 > fill:
            tp1 = fill + (tp2 - fill) * frac
        elif side == "SELL" and tp2 < fill:
            tp1 = fill - (fill - tp2) * frac
        symbol = canonical_pair(to_display_symbol(str(remote_row.get("instrument") or "EUR/USD")))
        if tp1 and price_to_pips(symbol, abs(tp1 - fill)) < MIN_TP1_PIPS:
            tp1 = 0.0
    return {"stop_loss": sl, "take_profit_1": tp1, "take_profit_2": tp2}


def mark_price(
    *,
    quote_mid: float | None,
    fill: float | None = None,
    side: str = "BUY",
    unrealized_pl: float | None = None,
    units: int = 0,
    remote_open_price: float | None = None,
) -> float | None:
    """Live mark. Never use the open-trade ``price`` field (that is the fill)."""
    _ = remote_open_price  # explicitly ignored — that field is the fill
    if quote_mid is not None and float(quote_mid) > 0:
        return float(quote_mid)
    if fill and units and unrealized_pl is not None:
        move = float(unrealized_pl) / abs(int(units))
        return float(fill) + move if side.upper() == "BUY" else float(fill) - move
    return None


def should_take_partial(
    trade: Any,
    *,
    mark: float | None,
    unrealized_pl: float | None,
    min_tp1_pips: float = MIN_TP1_PIPS,
) -> tuple[bool, str]:
    """Whether the desk may send TradeClose for TP1.

    Requires a bot-managed ticket, at least two remaining units, a real TP1
    several pips from the fill, a positive unrealized P/L, and a mark that
    has actually reached the target.
    """
    if is_operator_trade(trade):
        return False, "operator trade — hands off"
    if getattr(trade, "tp1_filled", False):
        return False, "tp1 already filled"
    fill = float(trade.fill_price or 0)
    tp1 = float(trade.take_profit_1 or 0)
    if not fill or not tp1:
        return False, "no tp1/fill"
    remaining = int(trade.remaining_units or 0)
    if remaining < MIN_PARTIAL_UNITS:
        return False, "cannot split a 1-unit ticket"
    symbol = getattr(trade, "symbol", "EUR/USD") or "EUR/USD"
    side = str(getattr(trade, "side", "")).upper()
    if side not in {"BUY", "SELL"} or not all(math.isfinite(x) for x in (fill, tp1)):
        return False, "invalid target/side"
    move = (tp1 - fill) * (1 if side == "BUY" else -1)
    if move <= 0:
        return False, "not a real target — must be on the profitable side of the fill"
    tp1_pips = price_to_pips(symbol, move)
    if tp1_pips + 1e-9 < min_tp1_pips:
        return False, f"tp1 only {tp1_pips:.1f} pips from fill — not a real target"
    if unrealized_pl is None or not math.isfinite(float(unrealized_pl)) or float(unrealized_pl) <= 0:
        return False, "unrealized P/L is not positive"
    if mark is None or not math.isfinite(mark) or mark <= 0:
        return False, "no mark price"
    side = str(getattr(trade, "side", "BUY") or "BUY").upper()
    hit = mark >= tp1 if side == "BUY" else mark <= tp1
    if not hit:
        return False, "tp1 not reached"
    return True, "tp1 hit in profit"


def partial_close_units(remaining_units: int) -> int:
    """Half the ticket, but never the whole 1-unit position."""
    remaining = int(remaining_units or 0)
    if remaining < MIN_PARTIAL_UNITS:
        return 0
    half = remaining // 2
    if half < 1 or half >= remaining:
        return 0
    return half


def remote_symbol(remote_row: Mapping[str, Any]) -> str:
    return canonical_pair(to_display_symbol(str(remote_row.get("instrument") or "")))


def broker_open_on_symbol(remote_rows: Iterable[Mapping[str, Any]], symbol: str) -> bool:
    want = canonical_pair(symbol)
    for row in remote_rows:
        if remote_symbol(row) == want:
            units = float(row.get("currentUnits") or row.get("initialUnits") or 0)
            if abs(units) > 0:
                return True
    return False


def operator_open_on_symbol(
    symbol: str,
    *,
    remote_rows: Iterable[Mapping[str, Any]] | None = None,
    local_open: Iterable[Any] | None = None,
) -> bool:
    """True when a human EUR/USD ticket is live — desk still may add OPEN_ONLY fills."""
    want = canonical_pair(symbol)
    if local_open is not None:
        for trade in local_open:
            status = str(getattr(trade, "status", "") or "")
            if status not in {"open", "partial"}:
                continue
            if canonical_pair(str(getattr(trade, "symbol", "") or "")) != want:
                continue
            if getattr(trade, "source", SOURCE_BOT) == SOURCE_HUMAN:
                return True
    if remote_rows is not None:
        for row in remote_rows:
            units = float(row.get("currentUnits") or row.get("initialUnits") or 0)
            if abs(units) <= 0:
                continue
            if remote_symbol(row) == want and classify_remote_trade(row) == SOURCE_HUMAN:
                return True
    return False


def new_order_block_reason(
    symbol: str,
    *,
    remote_rows: Iterable[Mapping[str, Any]] | None = None,
    local_open: Iterable[Any] | None = None,
) -> str | None:
    """Capacity lives in RiskManager. Operator tickets no longer veto a new desk fill."""
    _ = (symbol, remote_rows, local_open)
    return None


def should_flatten_scalp(
    trade: Any,
    *,
    now: datetime,
    max_hold_minutes: float,
) -> tuple[bool, str]:
    """Time-stop a bot scalp that has sat past the Ox short-hold window."""
    if is_operator_trade(trade):
        return False, "operator trade — hands off"
    opened = getattr(trade, "opened_at", None)
    if opened is None:
        return False, "no open time"
    if getattr(opened, "tzinfo", None) is None:
        opened = opened.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = (now - opened).total_seconds() / 60.0
    if age < float(max_hold_minutes):
        return False, "still in scalp window"
    return True, f"Scalp time stop after {age:.0f} minutes (max {max_hold_minutes:.0f})"
