"""Textbook Forex mistakes this desk is trained to see and refuse.

Sources (common-mistake + bot-build articles, 2026-09-19):

- Forex.com, Taurex, Titan FX, MultiBank: no plan, no stop, overleverage,
  revenge, overtrading, chasing, news, weekend gaps, emotions.
- ForTraders / J2T: martingale and grid bots, unattended robots, overfitting.
- CoinBureau: rules before code, kill switch, fees and slippage.
- OpoFinance / SocialVPS / ForexVPS: demo first, always a stop, VPS is not a
  strategy, do not trade the Friday close or Sunday reopen.

The Ox scalp book already had a plan, stops, news blackout, and revenge
cooldown. This module is the remaining avoidance layer: calendar, ticket
count, cost, stale quotes, named anti-martingale, and a journal taxonomy so
a loss is labelled as a *kind of mistake*, not just a red P/L.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import Settings, get_settings
from src.utils import price_to_pips, utcnow

# Stable codes written onto TradeJournal.mistakes and desk/MISTAKES.md.
TAXONOMY: dict[str, str] = {
    "no_plan": "Took a ticket without a written thesis.",
    "no_stop": "Opened without a hard stop-loss.",
    "overleverage": "Size was too large versus NAV or the stop.",
    "revenge": "Re-entered too fast after a stop.",
    "overtrading": "Too many tickets in one UTC day.",
    "chasing": "Bought a spike or sold a washout instead of waiting for a pullback.",
    "news": "Traded through a high-impact EUR/USD print.",
    "weekend_gap": "Held or opened into the Friday close / Sunday reopen.",
    "session_open": "Traded the thin Monday Tokyo open.",
    "averaging_down": "Added to a loser (martingale / grid / averaging down).",
    "fees_slippage": "Spread or fill slippage ate the edge.",
    "stale_quote": "Quoted off a stale or disagreed print.",
    "chop_stop": "Stopped in minutes — chop, not a thesis failing over a swing.",
    "unattended": "No kill switch / no human review of a runaway book.",
    "overfitting": "Kitchen-sink or curve-fit model replaced the Ox book.",
}

_CHASE_BUY = {"overbought", "upper_band"}
_CHASE_SELL = {"oversold", "lower_band"}


@dataclass(frozen=True, slots=True)
class MistakeGate:
    allowed: bool
    reason: str
    code: str = "ok"


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _utc(now: datetime | None) -> datetime:
    ts = _aware(now) or utcnow()
    return ts.astimezone(timezone.utc)


def calendar_hold_reason(now: datetime | None, settings: Settings | None = None) -> str | None:
    """Why the desk is closed. None means the calendar is open for a scalp."""
    settings = settings or get_settings()
    ts = _utc(now)
    weekday = ts.weekday()
    window = (
        f"{settings.trade_session_start_hour:02d}:00–"
        f"{settings.trade_session_end_hour:02d}:00 UTC"
    )
    if weekday == 5:
        return (
            "Weekend gap — Saturday FX is shut. Do not invent Monday tickets "
            f"from a closed tape (session {window} weekdays)."
        )
    if weekday == 6:
        return (
            "Weekend gap — Sunday reopen is not a scalp. Sit until Monday Tokyo "
            f"after the open buffer (session {window})."
        )
    friday_hour = int(getattr(settings, "friday_flat_hour", 20) or 20)
    if weekday == 4 and ts.hour >= friday_hour:
        return (
            f"Weekend gap — Friday after {friday_hour:02d}:00 UTC. "
            "No new tickets into the weekend gap; flatten or sit."
        )
    start = int(settings.trade_session_start_hour)
    end = int(settings.trade_session_end_hour)
    end = 24 if end > 24 else end
    if start < end:
        inside = start <= ts.hour < end
    else:
        inside = ts.hour >= start or ts.hour < end
    if not inside:
        return f"Outside weekday EUR/USD hours ({window}, Tokyo through New York)"
    if weekday == 0:
        skip_min = int(getattr(settings, "monday_open_skip_minutes", 45) or 0)
        if skip_min > 0:
            open_at = ts.replace(hour=start, minute=0, second=0, microsecond=0)
            if ts < open_at + timedelta(minutes=skip_min):
                until = open_at + timedelta(minutes=skip_min)
                return (
                    f"Session-open buffer — Monday Tokyo is thin for {skip_min} minutes. "
                    f"First ticket after {until.strftime('%H:%M')} UTC."
                )
    return None


def session_is_open(now: datetime | None, settings: Settings | None = None) -> bool:
    return calendar_hold_reason(now, settings) is None


def is_bot_ticket(trade: Any) -> bool:
    return str(getattr(trade, "source", "bot") or "bot") != "human"


def bot_tickets_opened_on(session: Session, day: date) -> int:
    """Bot fills that opened on ``day`` (UTC). Rejected / human rows do not count."""
    from src.data.storage import Trade

    n = 0
    for trade in session.scalars(select(Trade)):
        if not is_bot_ticket(trade):
            continue
        if str(getattr(trade, "status", "") or "") not in {"open", "partial", "closed"}:
            continue
        opened = _aware(getattr(trade, "opened_at", None) or getattr(trade, "created_at", None))
        if opened is None:
            continue
        if opened.date() != day:
            continue
        n += 1
    return n


def had_bot_loss_on(session: Session, day: date, *, scratch_usd: float = 2.0) -> bool:
    from src.data.storage import Trade

    for trade in session.scalars(select(Trade).where(Trade.status == "closed")):
        if not is_bot_ticket(trade):
            continue
        closed = _aware(getattr(trade, "closed_at", None))
        if closed is None or closed.date() != day:
            continue
        pl = float(getattr(trade, "realized_pl", 0) or 0)
        if pl <= -abs(float(scratch_usd or 0)):
            return True
    return False


def last_bot_fill(session: Session) -> Any | None:
    from src.data.storage import Trade

    rows = list(
        session.scalars(
            select(Trade)
            .where(Trade.status.in_(["open", "partial", "closed"]))
            .order_by(Trade.opened_at.desc(), Trade.id.desc())
        )
    )
    for trade in rows:
        if is_bot_ticket(trade) and getattr(trade, "opened_at", None) is not None:
            return trade
    return None


def averaging_down_reason(side: str, min_pips: float) -> str:
    return (
        f"Anti-martingale: will not add another {side} onto an underwater ticket "
        f"(no grid, no averaging down). Wait for it to pay {min_pips:.1f} pips or stop."
    )


def quote_age_seconds(quote: Any, now: datetime | None = None) -> float | None:
    ts = getattr(quote, "ts", None) if quote is not None else None
    ts = _aware(ts)
    if ts is None:
        return None
    return max(0.0, (_utc(now) - ts).total_seconds())


def cost_eats_stop(spread_pips: float | None, stop_pips: float | None, fraction: float) -> bool:
    if spread_pips is None or stop_pips is None:
        return False
    if spread_pips <= 0 or stop_pips <= 0:
        return False
    return (spread_pips / stop_pips) >= max(0.01, float(fraction))


def live_mistake_gate(
    *,
    session: Session,
    signal: Any,
    quote: Any | None,
    intel: Any | None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> MistakeGate:
    """Pipeline gates that sit in front of risk: overtrading, cost, slippage, stale quote."""
    settings = settings or get_settings()
    ts = _utc(now)
    day = ts.date()

    cap = int(getattr(settings, "max_trades_per_day", 8) or 8)
    opened = bot_tickets_opened_on(session, day)
    if opened >= cap:
        return MistakeGate(
            False,
            (
                f"Overtrading halt: {opened} desk tickets already opened today "
                f"(cap {cap}). Quality over quantity — sit until the next UTC day."
            ),
            "overtrading",
        )

    stale_sec = int(getattr(settings, "stale_quote_seconds", 90) or 90)
    age = quote_age_seconds(quote, ts)
    intel_stale = bool(getattr(getattr(intel, "price", None), "stale", False))
    if (age is not None and age > stale_sec) or intel_stale:
        age_txt = f"{int(age)}s" if age is not None else "intel-stale"
        return MistakeGate(
            False,
            (
                f"Kill switch: OANDA quote is stale ({age_txt}, cap {stale_sec}s). "
                "Do not size a ticket off a dead print."
            ),
            "stale_quote",
        )

    spread_pips = None
    if quote is not None and getattr(quote, "spread", None) is not None:
        spread_pips = price_to_pips(getattr(signal, "symbol", "EUR/USD"), float(quote.spread))
    entry = float(getattr(signal, "entry", None) or getattr(signal, "price", 0) or 0)
    stop = float(getattr(signal, "stop_loss", None) or 0)
    stop_pips = price_to_pips(getattr(signal, "symbol", "EUR/USD"), abs(entry - stop)) if entry and stop else None
    from src.analysis.sampling import sampling_policy
    fraction = sampling_policy(settings)["cost_stop_fraction"]
    if cost_eats_stop(spread_pips, stop_pips, fraction):
        return MistakeGate(
            False,
            (
                f"Cost: spread {spread_pips:.1f} pips eats "
                f"{100 * (spread_pips / stop_pips):.0f}% of a {stop_pips:.1f}-pip stop "
                f"(cap {100 * fraction:.0f}%). Not a scalp — wait for compression."
            ),
            "fees_slippage",
        )

    slip_cap = float(getattr(settings, "max_fill_slippage_pips", 1.5) or 1.5)
    cool_min = int(getattr(settings, "slippage_cooloff_minutes", 20) or 20)
    last = last_bot_fill(session)
    if last is not None and cool_min > 0:
        slip = getattr(last, "slippage_pips", None)
        filled_at = _aware(getattr(last, "opened_at", None))
        if slip is not None and filled_at is not None and abs(float(slip)) >= slip_cap:
            until = filled_at + timedelta(minutes=cool_min)
            if ts < until:
                remain = int((until - ts).total_seconds() // 60) + 1
                return MistakeGate(
                    False,
                    (
                        f"Slippage cool-off: last fill was {float(slip):+.1f} pips "
                        f"(cap {slip_cap:.1f}). Wait {remain} more minute(s) — "
                        "hostile liquidity, not a new thesis."
                    ),
                    "fees_slippage",
                )
    return MistakeGate(True, "Mistake checks passed", "ok")


def classify_closed_mistakes(
    trade: Any,
    journal: Any,
    settings: Settings | None = None,
) -> list[str]:
    """Label a closed ticket with textbook mistake codes the desk already refuses."""
    settings = settings or get_settings()
    if str(getattr(trade, "source", "bot") or "bot") == "human":
        return []
    outcome = str(getattr(journal, "outcome", "") or "")
    if outcome in {"win", "scratch", "open"}:
        return []
    codes: list[str] = []
    ctx = getattr(journal, "entry_context", None) or {}
    close_reason = str(getattr(trade, "close_reason", "") or getattr(journal, "close_reason", "") or "")
    hold = getattr(journal, "hold_minutes", None)
    side = str(getattr(trade, "side", "") or "").upper()
    bucket = str(getattr(journal, "rsi_bucket", "") or "")
    zone = str(getattr(journal, "bb_zone", "") or "")
    opened = _aware(getattr(trade, "opened_at", None))
    if opened is not None and calendar_hold_reason(opened, settings):
        reason = calendar_hold_reason(opened, settings) or ""
        if "weekend" in reason.lower() or "friday" in reason.lower():
            codes.append("weekend_gap")
        if "session-open" in reason.lower() or "monday" in reason.lower():
            codes.append("session_open")
    if close_reason == "stop_loss" and hold is not None and hold < 20:
        codes.append("chop_stop")
    if side == "BUY" and (bucket in _CHASE_BUY or zone in _CHASE_BUY):
        codes.append("chasing")
    if side == "SELL" and (bucket in _CHASE_SELL or zone in _CHASE_SELL):
        codes.append("chasing")
    slip = getattr(trade, "slippage_pips", None)
    if slip is not None and abs(float(slip)) >= float(getattr(settings, "max_fill_slippage_pips", 1.5) or 1.5):
        codes.append("fees_slippage")
    stop = float(getattr(trade, "stop_loss", None) or 0)
    if stop <= 0:
        codes.append("no_stop")
    news = str(ctx.get("reason") or "") + " " + str(ctx.get("skip_reason") or "")
    if "news blackout" in news.lower() or "nfp" in news.lower() or "fomc" in news.lower():
        codes.append("news")
    seen: list[str] = []
    for code in codes:
        if code in TAXONOMY and code not in seen:
            seen.append(code)
    return seen


def describe_mistakes(codes: Iterable[str]) -> str:
    lines = []
    for code in codes:
        label = TAXONOMY.get(code)
        if label:
            lines.append(f"{code}: {label}")
    return "\n".join(lines)
