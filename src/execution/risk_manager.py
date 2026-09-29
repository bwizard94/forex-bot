"""Position sizing, daily loss cap, and drawdown circuit breaker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Iterable

from loguru import logger

from src.config import Settings, get_settings
from src.data.storage import DailyPnL, Trade, closed_realized_today, get_open_trades, peak_nav
from src.execution.trade_guard import SOURCE_HUMAN
from src.analysis.mistakes import averaging_down_reason, had_bot_loss_on
from src.utils import pip_size, price_to_pips


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: str
    units: int = 0
    risk_amount: float = 0.0
    stop_pips: float = 0.0
    size_mode: str = "base"
    risk_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class AccountState:
    balance: float
    nav: float
    unrealized_pl: float
    realized_pl: float
    margin_used: float
    margin_available: float
    open_trade_count: int
    currency: str = "USD"
    raw: dict | None = None


def is_bot_ticket(trade: Any) -> bool:
    return str(getattr(trade, "source", "bot") or "bot") != SOURCE_HUMAN


def desk_open_trades(open_trades: Iterable[Any]) -> list[Any]:
    """Capacity counts OANDA desk tickets only — operator fills and MT4 copies stay out of the stack."""
    out = []
    for trade in open_trades:
        if not is_bot_ticket(trade):
            continue
        venue = str(getattr(trade, "venue", "oanda") or "oanda").lower()
        if venue == "mt4":
            continue
        out.append(trade)
    return out


def same_side_tickets(open_trades: Iterable[Any], side: str) -> list[Any]:
    want = str(side or "").upper()
    return [t for t in desk_open_trades(open_trades) if str(getattr(t, "side", "") or "").upper() == want]


def ticket_in_profit(trade: Any, mark: float | None, *, min_pips: float = 0.0) -> bool:
    fill = float(getattr(trade, "fill_price", None) or getattr(trade, "requested_entry", None) or 0)
    if not fill or mark is None or float(mark) <= 0:
        return False
    mid = float(mark)
    side = str(getattr(trade, "side", "") or "").upper()
    symbol = str(getattr(trade, "symbol", "") or "EUR/USD")
    if side == "BUY":
        pips = (mid - fill) / pip_size(symbol)
    elif side == "SELL":
        pips = (fill - mid) / pip_size(symbol)
    else:
        return False
    return pips > max(0.0, float(min_pips or 0.0))


def ticket_open_risk_usd(trade: Any, quote_to_usd: float = 1.0) -> float:
    fill = float(getattr(trade, "fill_price", None) or getattr(trade, "requested_entry", None) or 0)
    stop = float(getattr(trade, "stop_loss", None) or 0)
    units = abs(int(getattr(trade, "remaining_units", None) or getattr(trade, "units", None) or 0))
    if not fill or not stop or units < 1:
        return 0.0
    return abs(fill - stop) * units * float(quote_to_usd or 1.0)


def _base_risk_fraction(
    settings: Settings,
    *,
    strength: int,
    htf_aligned: bool,
    growth_action: str,
    adding_to_winner: bool,
    losing_day: bool = False,
) -> tuple[float, str]:
    """Base 0.6%, conviction 0.9% on a good H1-aligned tape, smaller add-ons, fades, and losing days."""
    action = (growth_action or "observe").lower()
    if losing_day:
        return float(settings.fade_risk_pct), "reduced"
    if action == "fade":
        return float(settings.fade_risk_pct), "fade"
    if adding_to_winner:
        return float(settings.addon_risk_pct), "add-on"
    confident = strength >= int(settings.conviction_strength_min) and htf_aligned
    if confident and action in {"prefer", "edge", "observe", ""}:
        return float(settings.conviction_risk_pct), "conviction"
    return float(settings.risk_per_trade_pct), "base"


def pick_risk_fraction(settings, **kwargs):
    from src.analysis.sampling import sampling_policy
    fraction, mode = _base_risk_fraction(settings, **kwargs)
    cap = sampling_policy(settings)["risk_cap"]
    if cap is not None:
        return min(fraction, cap), "practice-sampling/" + mode
    return fraction, mode


def notional_unit_cap(settings, account, price, quote_to_usd=1.0):
    """Order-value ceiling in base units; USD accounts only, never NAV/margin."""
    fraction = settings.max_order_notional_pct
    if fraction is None:
        return settings.max_units_per_trade
    if (account.currency != "USD" or not all(isfinite(v) and v > 0
            for v in (account.balance, price, quote_to_usd, fraction))):
        return 0
    return max(0, int(account.balance * fraction / (price * quote_to_usd)))


class RiskManager:
    """Hard limits: sized risk, daily loss, stacked positions, max drawdown."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def size_position(
        self,
        *,
        symbol: str,
        side: str,
        entry: float,
        stop_loss: float,
        account: AccountState,
        quote_to_usd: float = 1.0,
        risk_pct: float | None = None,
        notional_price: float | None = None,
    ) -> tuple[int, float, float]:
        """Return (units, actual_dollar_risk, stop_pips) after caps and rounding.

        OANDA units are the number of units of the *base* currency.
        PnL in quote currency ≈ units * price_move; convert quote → USD via
        ``quote_to_usd`` (1.0 for *USD quotes).
        """
        side = str(side or "").upper()
        fraction = float(self.settings.risk_per_trade_pct if risk_pct is None else risk_pct)
        if (
            side not in {"BUY", "SELL"}
            or not all(isfinite(v) and v > 0 for v in (entry, stop_loss, account.nav, quote_to_usd, fraction))
            or fraction > 1
            or (side == "BUY" and stop_loss >= entry)
            or (side == "SELL" and stop_loss <= entry)
        ):
            return 0, 0.0, 0.0
        stop_distance = abs(entry - stop_loss)
        stop_pips = price_to_pips(symbol, stop_distance)
        risk_amount = account.nav * fraction
        # Loss per unit in account currency.
        loss_per_unit = stop_distance * quote_to_usd
        raw_units = risk_amount / loss_per_unit if loss_per_unit else 0.0
        ceiling = notional_unit_cap(self.settings, account, entry if notional_price is None else notional_price, quote_to_usd)
        units = int(max(0, min(raw_units, self.settings.max_units_per_trade, ceiling)))
        # OANDA rejects 0 and prefers integer units.
        if units < 1:
            units = 0
        return units, units * loss_per_unit, stop_pips

    def evaluate(
        self,
        *,
        session,
        symbol: str,
        side: str,
        entry: float,
        stop_loss: float,
        account: AccountState,
        instrument_tradeable: bool,
        quote_to_usd: float = 1.0,
        today: date | None = None,
        mark: float | None = None,
        notional_price: float | None = None,
        strength: int = 0,
        htf_aligned: bool = False,
        growth_action: str = "observe",
    ) -> RiskDecision:
        settings = self.settings
        today = today or datetime.now(timezone.utc).date()
        side = str(side or "").upper()

        if not settings.enable_trading:
            return RiskDecision(False, "Trading disabled by ENABLE_TRADING=false")
        if not instrument_tradeable:
            return RiskDecision(False, "Instrument is not currently tradeable (market closed)")
        if not isfinite(account.nav) or account.nav <= 0:
            return RiskDecision(False, "Account NAV must be finite and positive")
        if (
            side not in {"BUY", "SELL"}
            or not all(isfinite(v) and v > 0 for v in (entry, stop_loss, quote_to_usd))
            or (side == "BUY" and stop_loss >= entry)
            or (side == "SELL" and stop_loss <= entry)
        ):
            return RiskDecision(False, "Invalid price, conversion, side, or stop-loss direction")

        open_trades: list[Trade] = get_open_trades(session)
        desk = desk_open_trades(open_trades)
        if len(desk) >= settings.max_open_positions:
            return RiskDecision(
                False,
                f"Max open desk positions reached ({settings.max_open_positions})",
            )
        same = same_side_tickets(open_trades, side)
        if len(same) >= settings.max_same_side_positions:
            return RiskDecision(
                False,
                f"Max same-side desk positions reached ({settings.max_same_side_positions} {side})",
            )
        adding_to_winner = False
        if same:
            min_pips = float(getattr(settings, "addon_min_profit_pips", 2.0) or 2.0)
            if not any(ticket_in_profit(t, mark, min_pips=min_pips) for t in same):
                return RiskDecision(
                    False,
                    averaging_down_reason(side, min_pips),
                )
            adding_to_winner = True

        hist_peak = peak_nav(session, fallback=account.nav)
        peak = max(hist_peak, account.nav)
        drawdown = (peak - account.nav) / peak if peak else 0.0
        if drawdown >= settings.max_drawdown_pct:
            return RiskDecision(
                False,
                f"Max drawdown breached ({drawdown:.2%} >= {settings.max_drawdown_pct:.2%})",
            )

        daily = closed_realized_today(session, today)
        daily_halt_enabled = (settings.oanda_environment != "practice" or
                              settings.practice_daily_loss_halt_enabled)
        if daily_halt_enabled and daily <= -abs(settings.daily_loss_limit_pct * account.balance):
            return RiskDecision(
                False,
                f"Daily loss limit hit ({daily:.2f} vs "
                f"{-settings.daily_loss_limit_pct * account.balance:.2f})",
            )
        soft_halt = abs(float(settings.daily_soft_halt_pct) * account.nav)
        if daily_halt_enabled and daily <= -soft_halt:
            return RiskDecision(
                False,
                (
                    f"Soft daily halt: desk is down ${daily:.2f} today "
                    f"(cap ${soft_halt:.0f}). No new tickets until the next UTC day — re-evaluate H1 first."
                ),
            )
        losing_day = daily <= -abs(float(settings.daily_reduce_at_pct) * account.nav)
        if not losing_day:
            losing_day = had_bot_loss_on(
                session, today, scratch_usd=float(settings.lesson_scratch_usd)
            )

        risk_pct, size_mode = pick_risk_fraction(
            settings,
            strength=int(strength or 0),
            htf_aligned=bool(htf_aligned),
            growth_action=growth_action,
            adding_to_winner=adding_to_winner,
            losing_day=losing_day,
        )

        units, risk_amount, stop_pips = self.size_position(
            symbol=symbol,
            side=side,
            entry=entry,
            stop_loss=stop_loss,
            account=account,
            quote_to_usd=quote_to_usd,
            risk_pct=risk_pct,
            notional_price=notional_price,
        )
        if units <= 0:
            return RiskDecision(False, "Computed position size is zero (stop too wide or equity too small)")
        if stop_pips + 0.05 < settings.min_stop_pips:
            return RiskDecision(
                False,
                f"Stop distance {stop_pips:.1f} pips is below {settings.min_stop_pips:.1f}-pip minimum",
            )

        open_risk = sum(ticket_open_risk_usd(t, quote_to_usd) for t in desk)
        budget = float(settings.max_open_risk_pct) * account.nav
        remaining = budget - open_risk
        if remaining <= 0:
            return RiskDecision(
                False,
                f"Open-risk budget used (${open_risk:.0f} / {settings.max_open_risk_pct:.1%} NAV)",
            )
        if risk_amount > remaining:
            stop_distance = abs(entry - stop_loss)
            loss_per_unit = stop_distance * quote_to_usd
            scaled = int(remaining / loss_per_unit) if loss_per_unit else 0
            scaled = min(scaled, units, settings.max_units_per_trade)
            if scaled < 1 or remaining < account.nav * min(risk_pct, settings.fade_risk_pct) * 0.4:
                return RiskDecision(
                    False,
                    f"Open-risk budget too tight for another ticket (${remaining:.0f} left of {settings.max_open_risk_pct:.1%})",
                )
            units = scaled
            risk_amount = units * loss_per_unit
            size_mode = f"{size_mode}-scaled"

        logger.info(
            "Risk OK {} {} units={} mode={} risk=${:.2f} ({:.2%}) stop={:.1f} pips desk={}/{}",
            side,
            symbol,
            units,
            size_mode,
            risk_amount,
            risk_pct,
            stop_pips,
            len(desk) + 1,
            settings.max_open_positions,
        )
        return RiskDecision(
            allowed=True,
            reason=f"Risk checks passed ({size_mode})",
            units=units,
            risk_amount=risk_amount,
            stop_pips=stop_pips,
            size_mode=size_mode,
            risk_pct=risk_pct,
        )

    def mark_daily_halt(self, daily_row: DailyPnL, reason: str) -> None:
        daily_row.halted = True
        daily_row.halt_reason = reason
