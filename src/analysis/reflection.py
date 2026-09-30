"""Trade journal: why we bought/sold, what went wrong, and how we improve.

Reflections are deterministic (no LLM). Every demo fill gets a written thesis
from the confluence snapshot. Every close gets a post-mortem. Repeat-loser
setups are remembered at three levels (exact snapshot, pair+side+H1, pair+side).
One similar loss demands a stronger score; two skip the setup. A stop is followed
by a cooldown so the desk cannot revenge-trade the same print.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analysis.mistakes import classify_closed_mistakes, describe_mistakes
from src.analysis.signals import TradeSignal
from src.config import Settings, get_settings
from src.data.storage import (
    IndicatorRow,
    LearnedRule,
    SignalRow,
    Trade,
    TradeJournal,
    _as_float,
    get_active_learned_rules,
    get_journal_for_trade,
    get_learned_rule,
)
from src.utils import format_price, price_to_pips, utcnow


def rsi_bucket(rsi: float | None) -> str:
    """Coarse RSI regime so similar losses actually cluster."""
    if rsi is None:
        return "unknown"
    if rsi <= 40:
        return "oversold"
    if rsi >= 60:
        return "overbought"
    return "mid"


def bb_zone(price: float | None, lower: float | None, mid: float | None, upper: float | None) -> str:
    if price is None or lower is None or mid is None or upper is None:
        return "unknown"
    if price <= lower * 1.0004:
        return "lower_band"
    if price >= upper * 0.9996:
        return "upper_band"
    return "mid"


def family_fingerprint(symbol: str, side: str, htf_bias: str) -> str:
    return f"{symbol}|{side}|{htf_bias or 'neutral'}"


def book_fingerprint(symbol: str, side: str) -> str:
    return f"{symbol}|{side}"


def related_fingerprints(fingerprint: str) -> list[str]:
    parts = [p for p in (fingerprint or "").split("|") if p]
    out = [fingerprint]
    if len(parts) >= 3:
        out.append("|".join(parts[:3]))
    if len(parts) >= 2:
        out.append("|".join(parts[:2]))
    seen: list[str] = []
    for item in out:
        if item not in seen:
            seen.append(item)
    return seen


_CURRENT_RSI = {"rsi_oversold", "rsi_mid", "rsi_overbought", "rsi_unknown"}
_CURRENT_BB = {"bb_lower_band", "bb_mid", "bb_upper_band", "bb_unknown"}


def make_fingerprint(
    symbol: str,
    side: str,
    htf_bias: str,
    rsi: float | None,
    price: float | None,
    bb_lower: float | None,
    bb_mid: float | None,
    bb_upper: float | None,
) -> tuple[str, str, str]:
    bucket = rsi_bucket(rsi)
    zone = bb_zone(price, bb_lower, bb_mid, bb_upper)
    bias = htf_bias or "neutral"
    fp = f"{symbol}|{side}|{bias}|rsi_{bucket}|bb_{zone}"
    return fp, bucket, zone


def fingerprint_is_current(fp: str) -> bool:
    """True when the fingerprint uses coarse RSI/band buckets (not rsi_high/low)."""
    parts = [p for p in (fp or "").split("|") if p]
    if len(parts) != 5:
        return False
    return parts[3] in _CURRENT_RSI and parts[4] in _CURRENT_BB


def estimate_realized_pl(trade: Trade, exit_price: float, quote_to_usd: float = 1.0) -> float:
    fill = trade.fill_price
    units = abs(int(trade.units or 0))
    if fill is None or units <= 0 or exit_price <= 0:
        return 0.0
    move = (exit_price - fill) if trade.side == "BUY" else (fill - exit_price)
    return move * units * (quote_to_usd or 1.0)


def infer_close_reason(trade: Trade, exit_price: float | None) -> str:
    existing = trade.close_reason or ""
    if existing in {"manual", "manual_no_broker_id"}:
        return existing
    fill = trade.fill_price
    if exit_price is None or fill is None:
        return existing or "broker_closed"
    sl = float(trade.stop_loss or 0)
    tp1 = float(trade.take_profit_1 or 0)
    tp2 = float(trade.take_profit_2 or 0)
    pip = price_to_pips(trade.symbol, 1.0)
    # 3 pips or 15% of stop distance, whichever is larger.
    stop_dist = abs(fill - sl) if sl else 0.0
    tolerance = max(3 * (0.01 if "JPY" in trade.symbol else 0.0001), stop_dist * 0.15)
    d_sl = abs(exit_price - sl) if sl else 1e9
    d_tp2 = abs(exit_price - tp2) if tp2 else 1e9
    d_tp1 = abs(exit_price - tp1) if tp1 else 1e9
    nearest = min(d_sl, d_tp2, d_tp1)
    if nearest <= tolerance:
        if nearest == d_sl:
            return "stop_loss"
        if nearest == d_tp2:
            return "take_profit"
        return "take_profit_1"
    if trade.tp1_filled:
        return existing or "runner_closed"
    _ = pip
    return existing or "broker_closed"


def _verb(side: str) -> tuple[str, str]:
    if side.upper() == "BUY":
        return "bought", "long"
    return "sold", "short"


def _bullet(text: str) -> str:
    return f"• {text}"


def build_entry_thesis(
    *,
    symbol: str,
    side: str,
    signal: TradeSignal | None,
    trade: Trade,
    context: dict[str, Any],
    adopted: bool = False,
) -> str:
    bought, posture = _verb(side)
    price = trade.fill_price or trade.requested_entry
    px = format_price(symbol, price) if price else "n/a"
    operator = (getattr(trade, "source", None) or "") == "human"
    lines: list[str] = []
    if operator:
        lines.append(
            f"The operator opened this {posture} {symbol} at {px} on the OANDA practice account "
            f"to demonstrate a trade. The desk will not scale, stop, or flatten this ticket. "
            f"It will journal the fill, copy the setup into the playbook, and learn from whatever "
            f"the operator eventually realizes."
        )
    elif adopted and signal is None:
        lines.append(
            f"I {bought} {symbol} at {px} after adopting the fill from the OANDA practice book "
            f"(the local write missed the original commit). No live confluence snapshot was saved "
            f"at entry, so this thesis is reconstructed from stored indicators."
        )
    else:
        lines.append(
            f"I {bought} {symbol} at {px} to go {posture} on the "
            f"{(signal.timeframe if signal else 'M5')} chart because independent factors lined up:"
        )
    confluence = []
    if signal and signal.confluence:
        confluence = list(signal.confluence)
    elif context.get("confluence"):
        confluence = list(context["confluence"])
    reason = (signal.reason if signal else None) or context.get("reason")
    if confluence:
        lines.extend(_bullet(item) for item in confluence)
    elif reason:
        lines.append(_bullet(str(reason)))
    else:
        lines.append(_bullet("No confluence list was stored — see indicator snapshot in context."))

    htf = (signal.htf_bias if signal else None) or context.get("htf_bias") or "neutral"
    rsi = (signal.rsi if signal else None)
    if rsi is None:
        rsi = context.get("rsi")
    strength = (signal.strength if signal else None) or context.get("strength")
    lines.append("")
    lines.append(
        f"Higher-timeframe bias is {htf}. RSI sits at "
        f"{f'{rsi:.1f}' if rsi is not None else 'n/a'} "
        f"({rsi_bucket(float(rsi) if rsi is not None else None)}). "
        f"Strength score is {strength if strength is not None else 'n/a'}/100."
    )
    sl = trade.stop_loss
    tp1 = trade.take_profit_1
    tp2 = trade.take_profit_2
    if operator:
        lines.append(
            "Risk: operator-managed. Native OANDA stop/target stay wherever they placed them."
        )
    elif sl and price:
        sl_pips = price_to_pips(symbol, abs(price - sl))
        lines.append(
            f"Risk: stop {format_price(symbol, sl)} ({sl_pips:.1f} pips, 1.5×ATR). "
            f"First scale {format_price(symbol, tp1) if tp1 else 'n/a'} (2.0×ATR); "
            f"runner {format_price(symbol, tp2) if tp2 else 'n/a'} (3.5×ATR)."
        )
    slip = trade.slippage_pips
    if slip is not None:
        direction = "worse" if slip > 0.2 else "better" if slip < -0.2 else "in line"
        lines.append(f"Fill slippage was {slip:+.1f} pips ({direction} than the signal price).")
    units = trade.units
    if units:
        if operator:
            lines.append(
                f"Size: {units} units — studying this fill instead of replacing it with a desk ticket."
            )
        else:
            lines.append(f"Size: {units} units on the {symbol.split('/')[0]} base, risk scaled to the conviction table.")
    return "\n".join(lines)


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def next_session_open(after: datetime | None, start_hour: int = 7) -> datetime:
    ts = _aware(after) or utcnow()
    candidate = ts.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if ts >= candidate:
        candidate = candidate + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate = candidate + timedelta(days=1)
    return candidate


def _hold_minutes(trade: Trade) -> float | None:
    if not trade.opened_at or not trade.closed_at:
        return None
    opened = trade.opened_at
    closed = trade.closed_at
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=timezone.utc)
    return max(0.0, (closed - opened).total_seconds() / 60.0)


def build_postmortem(
    *,
    trade: Trade,
    journal: TradeJournal,
    exit_price: float | None,
    realized_pl: float,
    close_reason: str,
    settings: Settings,
) -> dict[str, str]:
    bought, posture = _verb(trade.side)
    fill = trade.fill_price or trade.requested_entry or 0.0
    hold = _hold_minutes(trade)
    hold_txt = f"{hold:.0f} minutes" if hold is not None else "an unknown duration"
    pips = price_to_pips(trade.symbol, abs((exit_price or fill) - fill)) if fill else 0.0
    signed_pips = pips if realized_pl >= 0 else -pips
    exit_txt = format_price(trade.symbol, exit_price) if exit_price else "an unrecorded price"
    fill_txt = format_price(trade.symbol, fill) if fill else "n/a"
    headline = (
        f"I {bought} {trade.symbol} {posture} at {fill_txt} and closed at {exit_txt} "
        f"({close_reason}) after {hold_txt}. Realized P/L is ${realized_pl:+,.2f} "
        f"({signed_pips:+.1f} pips)."
    )

    scratch = abs(realized_pl) < settings.lesson_scratch_usd
    operator = (getattr(trade, "source", None) or "") == "human"

    if not operator and settings.oanda_environment == "practice" and settings.practice_contextual_loss_review:
        outcome = "scratch" if scratch else ("win" if realized_pl > 0 else "loss")
        context = journal.entry_context or {}
        fast, slow = context.get('ema_fast'), context.get('ema_slow')
        notes = [headline]
        if fast is not None and slow is not None:
            opposed = (trade.side == 'BUY' and fast < slow) or (trade.side == 'SELL' and fast > slow)
            notes.append('Entry EMA direction opposed the trade.' if opposed else 'Entry EMA direction did not oppose the trade.')
        notes.append('This outcome alone does not establish a cause or a repeatable edge.')
        improvement = ('Compare local trend, reversal confirmation, spread/original stop risk and exit fills '
                       'with comparable winners and losers. A high heuristic score is not a win probability.')
        if settings.confirmed_entry_policy and outcome == 'loss':
            improvement += ' Same-side re-entry requires a fresh post-close directional price trigger; no whole-strategy ban.'
        return {'outcome':outcome, 'exit_verdict':close_reason,
                'what_went_wrong':' '.join(notes) if outcome == 'loss' else None,
                'what_went_right':' '.join(notes) if outcome != 'loss' else None,
                'how_to_avoid':improvement,
                'lesson':f'Recorded {outcome} on {journal.fingerprint}. {improvement}'}
    if operator and scratch:
        what_right = (
            f"{headline} This was an operator demonstration that closed near breakeven. "
            f"Do not treat a hands-off (or previously auto-flattened) teacher ticket as a "
            f"desk loss — keep observing {journal.fingerprint}."
        )
        return {
            "outcome": "scratch",
            "exit_verdict": close_reason,
            "what_went_right": what_right,
            "what_went_wrong": None,
            "how_to_avoid": None,
            "lesson": (
                f"Operator scratch on {journal.fingerprint}: study the next demonstration. "
                f"Do not skip this setup from a near-zero close."
            ),
        }

    if operator and realized_pl >= 0:
        lesson = (
            f"Teacher win on {journal.fingerprint}. Prefer this pair/side/RSI/band when the "
            f"same EUR/USD setup repeats; the operator showed it can pay."
        )
        return {
            "outcome": "win",
            "exit_verdict": close_reason,
            "what_went_right": (
                f"{headline} The operator's {posture} worked. Copy the direction and the "
                f"indicator snapshot stored on this journal; do not fade it next time it prints."
            ),
            "what_went_wrong": None,
            "how_to_avoid": None,
            "lesson": lesson,
        }

    if operator and realized_pl < 0:
        lesson = (
            f"Teacher loss on {journal.fingerprint}. Still respect the demonstration as a "
            f"data point — wait for a cleaner extreme before repeating this long/short."
        )
        return {
            "outcome": "loss",
            "exit_verdict": close_reason,
            "what_went_right": None,
            "what_went_wrong": (
                f"{headline} The operator's {posture} did not pay. Note the RSI/band snapshot "
                f"and do not revenge-trade the print."
            ),
            "how_to_avoid": (
                f"Wait for a stretched RSI/band extreme aligned with H1 before repeating "
                f"{journal.fingerprint}."
            ),
            "lesson": lesson,
        }

    if scratch:
        what_right = (
            f"{headline} The trade closed near breakeven, so the thesis was neither proven nor "
            f"disproved. Treat this as noise — do not promote a skip rule from scratches."
        )
        return {
            "outcome": "scratch",
            "exit_verdict": close_reason,
            "what_went_right": what_right,
            "what_went_wrong": None,
            "how_to_avoid": None,
            "lesson": (
                f"Scratch on {journal.fingerprint}: keep observing. Do not skip this setup "
                f"from a near-zero close."
            ),
        }

    if realized_pl >= 0:
        why_right = [headline]
        if close_reason in {"take_profit", "take_profit_1"}:
            why_right.append(
                "Price reached the ATR target, so the confluence (trend + RSI + band location) held."
            )
        elif close_reason == "runner_closed":
            why_right.append("TP1 paid and the runner was later flattened with a profit.")
        else:
            why_right.append("The position was flattened in profit without hitting the written target.")
        why_right.append(
            f"Keep taking {journal.fingerprint} when strength is at least as high as this entry."
        )
        lesson = (
            f"Win on {journal.fingerprint}. Continue this pair/side/RSI/band combination; "
            f"do not loosen stops just because it paid."
        )
        return {
            "outcome": "win",
            "exit_verdict": close_reason,
            "what_went_right": "\n".join(why_right),
            "what_went_wrong": None,
            "how_to_avoid": None,
            "lesson": lesson,
        }

    # Loss
    ctx = journal.entry_context or {}
    rsi = ctx.get("rsi")
    bucket = journal.rsi_bucket or rsi_bucket(rsi)
    zone = journal.bb_zone
    htf = journal.htf_bias
    wrong: list[str] = [headline]
    if close_reason == "stop_loss":
        wrong.append(
            f"Price ran {pips:.1f} pips against the {posture} and hit the 1.5×ATR stop at "
            f"{format_price(trade.symbol, trade.stop_loss) if trade.stop_loss else 'the stop'}."
        )
    elif close_reason == "manual":
        wrong.append("The desk flattened the position manually before the stop or target.")
    else:
        wrong.append(
            "The broker closed the trade without a recorded stop or target hit; the book still lost money."
        )

    if bucket in {"mid", "unknown"}:
        wrong.append(
            f"RSI was in the '{bucket}' bucket at entry — there was no stretched extreme to fade or ride."
        )
    elif trade.side == "BUY" and bucket == "overbought":
        wrong.append(
            f"A long was taken with RSI already overbought ({rsi}). Buying strength that is already "
            f"extended often walks into the stop."
        )
    elif trade.side == "SELL" and bucket == "oversold":
        wrong.append(
            f"A short was taken with RSI already oversold ({rsi}). Selling weakness that is already "
            f"stretched often mean-reverts through the stop."
        )
    else:
        wrong.append(
            f"RSI sat in '{bucket}' and the Bollinger zone was '{zone}' with H1 {htf}. "
            f"The snapshot looked aligned, but price did not follow through."
        )

    if not trade.tp1_filled:
        wrong.append("Price never reached TP1, so the first scale never paid to cushion the stop.")

    avoid: list[str] = []
    if close_reason == "stop_loss" and zone in {"upper_band", "lower_band"}:
        avoid.append(
            f"Do not fade {trade.symbol} from the {zone.replace('_', ' ')} unless RSI is a true "
            f"extreme (oversold ≤35 for longs, overbought ≥65 for shorts) and strength is high."
        )
    elif trade.side == "BUY" and htf == "bearish":
        avoid.append(f"Do not buy {trade.symbol} against a bearish H1 bias on this RSI/band mix.")
    elif trade.side == "SELL" and htf == "bullish":
        avoid.append(f"Do not sell {trade.symbol} against a bullish H1 bias on this RSI/band mix.")
    else:
        avoid.append(
            f"Require a cleaner snapshot before repeating {journal.fingerprint}: "
            f"stronger RSI extreme, H1 agreement, and a higher strength score."
        )
    if hold is not None and hold < 20:
        wrong.append(
            f"The trade was stopped in {hold:.0f} minutes. That is chop, not a thesis failing over a full swing."
        )
        avoid.insert(
            0,
            f"Do not re-enter a stopped idea inside a {settings.post_loss_cooldown_minutes}-minute window. Wait for a new H1 impulse.",
        )
    avoid.append(
        f"After enough similar losses this fingerprint will demand strength "
        f">={settings.lesson_high_strength_min} or be skipped for {settings.lesson_skip_hours} hours. "
        f"A stop is followed by a {settings.post_loss_cooldown_minutes}-minute cool-off."
    )
    lesson = (
        f"Loss on {journal.fingerprint} via {close_reason}. Next time: {avoid[0]} "
        f"Track this pair/side/RSI/band mix and tighten it as losses repeat."
    )
    return {
        "outcome": "loss",
        "exit_verdict": close_reason,
        "what_went_right": None,
        "what_went_wrong": "\n".join(wrong),
        "how_to_avoid": "\n".join(avoid),
        "lesson": lesson,
    }


def context_from_signal(signal: TradeSignal) -> dict[str, Any]:
    return {
        "rsi": signal.rsi,
        "ema_fast": signal.ema_fast,
        "ema_slow": signal.ema_slow,
        "atr": signal.atr,
        "bb_upper": signal.bb_upper,
        "bb_mid": signal.bb_mid,
        "bb_lower": signal.bb_lower,
        "htf_bias": signal.htf_bias,
        "confluence": list(signal.confluence),
        "reason": signal.reason,
        "strength": signal.strength,
        "divergence": signal.divergence,
        "timeframe": signal.timeframe,
        "price": signal.price,
        "d1_bias": signal.d1_bias,
        "macd": signal.macd,
        "macd_signal": signal.macd_signal,
        "macd_hist": signal.macd_hist,
        "stoch_k": signal.stoch_k,
        "stoch_d": signal.stoch_d,
        "adx": signal.adx,
        "plus_di": signal.plus_di,
        "minus_di": signal.minus_di,
        "cci": signal.cci,
    }


def context_from_db(session: Session, trade: Trade) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    if trade.signal_id:
        sig = session.get(SignalRow, trade.signal_id)
        if sig is not None:
            ctx.update(
                {
                    "reason": sig.reason,
                    "confluence": sig.confluence,
                    "strength": sig.strength,
                    "timeframe": sig.timeframe,
                    "price": sig.price,
                }
            )
    ts = trade.opened_at or trade.created_at

    def _latest_indicator(timeframe: str) -> IndicatorRow | None:
        stmt = (
            select(IndicatorRow)
            .where(IndicatorRow.symbol == trade.symbol, IndicatorRow.timeframe == timeframe)
            .order_by(IndicatorRow.ts.desc())
            .limit(1)
        )
        if ts is not None:
            stmt = (
                select(IndicatorRow)
                .where(
                    IndicatorRow.symbol == trade.symbol,
                    IndicatorRow.timeframe == timeframe,
                    IndicatorRow.ts <= ts,
                )
                .order_by(IndicatorRow.ts.desc())
                .limit(1)
            )
        return session.scalar(stmt)

    row = _latest_indicator("M5") or _latest_indicator("M1")
    if row is not None:
        ctx.setdefault("rsi", row.rsi)
        ctx.setdefault("ema_fast", row.ema_fast)
        ctx.setdefault("ema_slow", row.ema_slow)
        ctx.setdefault("atr", row.atr)
        ctx.setdefault("bb_upper", row.bb_upper)
        ctx.setdefault("bb_mid", row.bb_mid)
        ctx.setdefault("bb_lower", row.bb_lower)
        ctx.setdefault("price", float(trade.fill_price or trade.requested_entry or 0) or None)
    htf = _latest_indicator("H1")
    if htf is not None and htf.ema_fast is not None and htf.ema_slow is not None:
        ctx.setdefault("htf_bias", "bullish" if htf.ema_fast > htf.ema_slow else "bearish")
    ctx.setdefault("htf_bias", "neutral")
    return ctx


def fingerprint_from_signal(signal: TradeSignal) -> str:
    fp, _, _ = make_fingerprint(
        signal.symbol,
        signal.action,
        signal.htf_bias,
        signal.rsi,
        signal.price,
        signal.bb_lower,
        signal.bb_mid,
        signal.bb_upper,
    )
    return fp


def record_entry(
    session: Session,
    trade: Trade,
    signal: TradeSignal | None = None,
    *,
    adopted: bool = False,
) -> TradeJournal:
    journal = get_journal_for_trade(session, trade.id)
    new_journal = journal is None
    if journal is None:
        journal = TradeJournal(
            trade_id=trade.id,
            signal_id=trade.signal_id,
            symbol=trade.symbol,
            side=trade.side,
            outcome="open",
        )
        session.add(journal)
        session.flush()
    ctx: dict[str, Any] = {}
    if journal.entry_context:
        ctx.update(journal.entry_context)
    if new_journal and not adopted and trade.status == "open" and trade.symbol == "EUR/USD":
        import math
        fill = float(trade.fill_price or 0)
        stop = float(trade.stop_loss or 0)
        units = abs(int(trade.units or 0))
        distance = fill - stop if trade.side == "BUY" else stop - fill
        account_currency = ((signal.decision_context or {}).get("account") or {}).get("currency") if signal else None
        if math.isfinite(distance) and fill > 0 and stop > 0 and distance > 0 and units and account_currency == "USD":
            ctx["initial_risk"] = {
                "basis": "entry_snapshot", "currency": "USD",
                "amount": units * distance, "fill": fill, "stop": stop,
                "units": units, "stop_pips": distance * 10000,
                "captured_at": utcnow().isoformat(),
            }
    dbctx = context_from_db(session, trade)
    for key, value in dbctx.items():
        if value in (None, [], ""):
            continue
        if (
            key == "htf_bias"
            and value == "neutral"
            and ctx.get("htf_bias") in {"bullish", "bearish"}
        ):
            continue
        ctx[key] = value
    if signal is not None:
        if new_journal and signal.decision_context:
            from src.analysis.evidence import json_safe
            ctx["decision_evidence"] = json_safe(signal.decision_context)
        live = context_from_signal(signal)
        for key, value in live.items():
            if value in (None, [], ""):
                continue
            if (
                key == "htf_bias"
                and value == "neutral"
                and ctx.get("htf_bias") in {"bullish", "bearish"}
            ):
                # Reconstructed SignalRow snapshots default to neutral; keep the stored bias.
                continue
            ctx[key] = value
    price = (
        ctx.get("price")
        or (signal.price if signal is not None else None)
        or trade.fill_price
        or trade.requested_entry
    )
    fp, bucket, zone = make_fingerprint(
        trade.symbol,
        trade.side,
        str(ctx.get("htf_bias") or (signal.htf_bias if signal else "neutral")),
        ctx.get("rsi") if ctx.get("rsi") is not None else (signal.rsi if signal else None),
        price,
        ctx.get("bb_lower") if ctx.get("bb_lower") is not None else (signal.bb_lower if signal else None),
        ctx.get("bb_mid") if ctx.get("bb_mid") is not None else (signal.bb_mid if signal else None),
        ctx.get("bb_upper") if ctx.get("bb_upper") is not None else (signal.bb_upper if signal else None),
    )
    journal.signal_id = trade.signal_id
    journal.symbol = trade.symbol
    journal.side = trade.side
    journal.fingerprint = fp
    journal.rsi_bucket = bucket
    journal.bb_zone = zone
    journal.htf_bias = str(ctx.get("htf_bias") or "neutral")
    journal.entry_context = ctx
    if not journal.entry_thesis:
        journal.entry_thesis = build_entry_thesis(
            symbol=trade.symbol,
            side=trade.side,
            signal=signal,
            trade=trade,
            context=ctx,
            adopted=adopted,
        )
    journal.updated_at = utcnow()
    session.flush()
    logger.info("Journaled {} {} #{} [{}]", trade.side, trade.symbol, trade.id, fp)
    return journal


def record_exit(
    session: Session,
    trade: Trade,
    *,
    exit_price: float | None,
    realized_pl: float,
    close_reason: str,
    settings: Settings | None = None,
) -> TradeJournal:
    settings = settings or get_settings()
    journal = get_journal_for_trade(session, trade.id)
    if journal is None:
        journal = record_entry(session, trade, adopted=True)
    post = build_postmortem(
        trade=trade,
        journal=journal,
        exit_price=exit_price,
        realized_pl=realized_pl,
        close_reason=close_reason,
        settings=settings,
    )
    journal.outcome = post["outcome"]
    journal.exit_verdict = post["exit_verdict"]
    journal.what_went_wrong = post["what_went_wrong"]
    journal.how_to_avoid = post["how_to_avoid"]
    journal.what_went_right = post["what_went_right"]
    journal.lesson = post["lesson"]
    journal.realized_pl = realized_pl
    journal.hold_minutes = _hold_minutes(trade)
    journal.close_reason = close_reason
    from src.analysis.loss_review import review_loss
    journal.entry_context = dict(journal.entry_context or {}, loss_review=review_loss(trade, journal))
    journal.mistakes = classify_closed_mistakes(trade, journal, settings)
    if journal.mistakes:
        labelled = describe_mistakes(journal.mistakes)
        extra = f"Textbook mistakes this fill repeated:\n{labelled}"
        if journal.how_to_avoid:
            journal.how_to_avoid = f"{journal.how_to_avoid}\n{extra}"
        else:
            journal.how_to_avoid = extra
        if journal.lesson:
            journal.lesson = f"{journal.lesson} Tags: {', '.join(journal.mistakes)}."
    journal.updated_at = utcnow()
    session.flush()
    if trade.source == "bot" and trade.venue == "oanda" and trade.parent_trade_id is None:
        upsert_learned_rule(session, journal, settings)
    logger.info(
        "Post-mortem {} {} #{} outcome={} pl={:.2f}",
        trade.side,
        trade.symbol,
        trade.id,
        journal.outcome,
        realized_pl,
    )
    return journal


def _tune_rule(rule: LearnedRule, rows: list[TradeJournal], settings: Settings, *, skip_at: int, high_at: int) -> None:
    ordered = sorted(rows, key=lambda r: _aware(r.updated_at) or _aware(r.created_at) or utcnow())
    decided = [r for r in ordered if r.outcome in {"win", "loss"}]
    rule.sample_count = len(ordered)
    rule.win_count = sum(1 for r in decided if r.outcome == "win")
    rule.loss_count = sum(1 for r in decided if r.outcome == "loss")
    rule.scratch_count = sum(1 for r in ordered if r.outcome == "scratch")
    rule.net_pl = sum(_as_float(r.realized_pl or 0) for r in ordered)
    net = _as_float(rule.net_pl)
    last = decided[-1] if decided else None
    last_two_losses = (
        len(decided) >= 2
        and decided[-1].outcome == "loss"
        and decided[-2].outcome == "loss"
    )
    if last_two_losses:
        parts = [p for p in (rule.fingerprint or "").split("|") if p]
        if len(parts) <= 3:
            # Book / family: demand a stretched extreme. Do not hard-ban the H1 side.
            rule.action = "require_high_strength"
            rule.min_strength = max(
                int(settings.lesson_high_strength_min),
                int(getattr(settings, "conviction_strength_min", 68) or 68),
            )
            rule.skip_until = None
            rule.lesson = (
                f"Last two {rule.fingerprint} fills were losses "
                f"({rule.win_count}W/{rule.loss_count}L, net ${net:+.2f}). "
                "An outlier win is not a license to keep grinding. "
                "Re-enter only as a stretched extreme aligned with H1."
            )
            rule.updated_at = utcnow()
            return
        rule.action = "skip"
        rule.min_strength = max(settings.lesson_high_strength_min, 80)
        until = utcnow() + timedelta(hours=max(12, int(settings.lesson_skip_hours)))
        existing = _aware(rule.skip_until)
        if existing is None or existing <= utcnow():
            rule.skip_until = until
        rule.lesson = (
            f"Last two {rule.fingerprint} fills were losses "
            f"({rule.win_count}W/{rule.loss_count}L, net ${net:+.2f}). "
            "An outlier win is not a license to keep firing. Sit this out."
        )
        rule.updated_at = utcnow()
        return
    # A fat winner with more losers than winners is only a good book if the last fill paid.
    if rule.win_count >= 1 and net > 0 and last is not None and last.outcome == "win":
        rule.action = "observe"
        rule.min_strength = 0
        rule.skip_until = None
        if not rule.lesson or "Keep taking" not in (rule.lesson or ""):
            rule.lesson = (
                f"Observe {rule.fingerprint}: {rule.win_count}W/{rule.loss_count}L "
                f"recorded P/L ${net:+.2f}; positive history is not a validated edge."
            )
        rule.updated_at = utcnow()
        return
    if rule.win_count >= 1 and net > 0 and last is not None and last.outcome == "loss":
        rule.action = "require_high_strength"
        rule.min_strength = settings.lesson_high_strength_min
        rule.skip_until = None
        rule.lesson = (
            f"{rule.fingerprint} last fill was a stop ({rule.win_count}W/{rule.loss_count}L, "
            f"net ${net:+.2f}). Need a stretched extreme, not a continuation grind."
        )
        rule.updated_at = utcnow()
        return
    if rule.loss_count >= skip_at and rule.loss_count > rule.win_count:
        rule.action = "skip"
        rule.min_strength = max(settings.lesson_high_strength_min, 80)
        until = utcnow() + timedelta(hours=settings.lesson_skip_hours)
        existing = _aware(rule.skip_until)
        if existing is None or existing <= utcnow():
            rule.skip_until = until
    elif rule.loss_count >= high_at and net < 0:
        rule.action = "require_high_strength"
        rule.min_strength = settings.lesson_high_strength_min
        rule.skip_until = None
    else:
        rule.action = "observe"
        rule.min_strength = 0
        rule.skip_until = None
    rule.updated_at = utcnow()


def upsert_learned_rule(session: Session, journal: TradeJournal, settings: Settings | None = None) -> LearnedRule:
    settings = settings or get_settings()
    cutoff = utcnow() - timedelta(days=settings.lesson_lookback_days)

    def _rows(*, fingerprint: str | None = None, family: bool = False, book: bool = False) -> list[TradeJournal]:
        stmt = select(TradeJournal).join(Trade, Trade.id == TradeJournal.trade_id).where(
            Trade.source == "bot", Trade.venue == "oanda", Trade.parent_trade_id.is_(None),
            Trade.status == "closed",
            TradeJournal.outcome.in_(["win", "loss", "scratch"]),
            TradeJournal.updated_at >= cutoff,
        )
        if fingerprint:
            stmt = stmt.where(TradeJournal.fingerprint == fingerprint)
        elif book:
            stmt = stmt.where(TradeJournal.symbol == journal.symbol, TradeJournal.side == journal.side)
        elif family:
            stmt = stmt.where(
                TradeJournal.symbol == journal.symbol,
                TradeJournal.side == journal.side,
                TradeJournal.htf_bias == journal.htf_bias,
            )
        return list(session.scalars(stmt))

    def _ensure(fp: str, *, scope: str = "exact") -> LearnedRule:
        rule = get_learned_rule(session, fp)
        if rule is None:
            rule = LearnedRule(
                fingerprint=fp,
                symbol=journal.symbol,
                side=journal.side,
                htf_bias=journal.htf_bias,
                rsi_bucket=journal.rsi_bucket,
                bb_zone=journal.bb_zone,
            )
            session.add(rule)
            session.flush()
        rule.last_outcome = journal.outcome
        rule.last_trade_id = journal.trade_id
        rule.lesson = journal.how_to_avoid or journal.lesson
        rule.symbol = journal.symbol
        rule.side = journal.side
        if scope == "family":
            rule.htf_bias = journal.htf_bias
            rule.rsi_bucket = "any"
            rule.bb_zone = "any"
        elif scope == "book":
            rule.htf_bias = "any"
            rule.rsi_bucket = "any"
            rule.bb_zone = "any"
        else:
            rule.htf_bias = journal.htf_bias
            rule.rsi_bucket = journal.rsi_bucket
            rule.bb_zone = journal.bb_zone
        rule.active = True
        return rule

    exact = _ensure(journal.fingerprint, scope="exact")
    _tune_rule(
        exact,
        _rows(fingerprint=journal.fingerprint),
        settings,
        skip_at=settings.lesson_loss_skip,
        high_at=settings.lesson_loss_high_strength,
    )
    family_fp = family_fingerprint(journal.symbol, journal.side, journal.htf_bias)
    family = _ensure(family_fp, scope="family")
    _tune_rule(
        family,
        _rows(family=True),
        settings,
        skip_at=settings.family_loss_skip,
        high_at=1,
    )
    book_fp = book_fingerprint(journal.symbol, journal.side)
    book = _ensure(book_fp, scope="book")
    _tune_rule(
        book,
        _rows(book=True),
        settings,
        skip_at=settings.family_loss_skip,
        high_at=max(2, settings.family_loss_skip),
    )
    session.flush()
    return exact


def restudy_learned_rules(session: Session, settings: Settings | None = None) -> int:
    """Re-score every active fingerprint so a losing streak sits out even after an outlier win."""
    settings = settings or get_settings()
    cutoff = utcnow() - timedelta(days=settings.lesson_lookback_days)
    journals = list(
        session.scalars(
            select(TradeJournal).join(Trade, Trade.id == TradeJournal.trade_id).where(
                Trade.source == "bot", Trade.venue == "oanda", Trade.parent_trade_id.is_(None),
                Trade.status == "closed",
                TradeJournal.outcome.in_(["win", "loss", "scratch"]),
                TradeJournal.updated_at >= cutoff,
            )
        )
    )
    n = 0
    for rule in get_active_learned_rules(session):
        parts = [p for p in (rule.fingerprint or "").split("|") if p]
        if len(parts) >= 5:
            matched = [j for j in journals if j.fingerprint == rule.fingerprint]
            skip_at = settings.lesson_loss_skip
            high_at = settings.lesson_loss_high_strength
        elif len(parts) == 3:
            matched = [
                j
                for j in journals
                if j.symbol == parts[0] and j.side == parts[1] and (j.htf_bias or "neutral") == parts[2]
            ]
            skip_at = settings.family_loss_skip
            high_at = 1
        elif len(parts) == 2:
            matched = [j for j in journals if j.symbol == parts[0] and j.side == parts[1]]
            skip_at = settings.family_loss_skip
            high_at = max(2, settings.family_loss_skip)
        else:
            continue
        _tune_rule(rule, matched, settings, skip_at=skip_at, high_at=high_at)
        n += 1
    session.flush()
    logger.info("Restudied {} learned rules from the journal", n)
    return n


@dataclass(frozen=True, slots=True)
class LessonGate:
    allowed: bool
    reason: str
    rule_action: str = "observe"


def lesson_gate(
    session: Session,
    fingerprint: str,
    strength: int,
    *,
    signal: TradeSignal | None = None,
    settings: Settings | None = None,
) -> LessonGate:
    settings = settings or get_settings()
    now = utcnow()

    def _blocked_by_rule(rule: LearnedRule | None) -> LessonGate | None:
        if settings.oanda_environment == "practice" and settings.practice_contextual_loss_review:
            return None
        if rule is None or not rule.active:
            return None
        skip_until = rule.skip_until
        if skip_until is not None and skip_until.tzinfo is None:
            skip_until = skip_until.replace(tzinfo=timezone.utc)
        if rule.action == "skip" and skip_until and now < skip_until:
            until = skip_until.strftime("%Y-%m-%d %H:%M UTC")
            return LessonGate(
                False,
                (
                    f"Lesson skip: {rule.fingerprint} lost {rule.loss_count} times "
                    f"(net ${float(rule.net_pl):+.2f}). Cooling off until {until}. "
                    f"{(rule.lesson or '')[:240]}"
                ),
                rule.action,
            )
        required = rule.min_strength or 0
        if rule.action in {"require_high_strength", "skip"} and required and strength < required:
            return LessonGate(
                False,
                (
                    f"Lesson: {rule.fingerprint} lost {rule.loss_count} similar trades "
                    f"(net ${float(rule.net_pl):+.2f}). Need strength >={required}, got {strength}. "
                    f"{(rule.lesson or '')[:240]}"
                ),
                "require_high_strength",
            )
        return None

    related_blocks: list[LessonGate] = []
    for fp in related_fingerprints(fingerprint):
        blocked = _blocked_by_rule(get_learned_rule(session, fp))
        if blocked is not None:
            related_blocks.append(blocked)
    skip_block = next((b for b in related_blocks if b.rule_action == "skip"), None)

    consecutive_block: LessonGate | None = None
    cooldown_block: LessonGate | None = None
    if signal is not None:
        closed = list(
            session.scalars(
                select(TradeJournal)
                .outerjoin(Trade, Trade.id == TradeJournal.trade_id)
                .where(
                    TradeJournal.outcome.in_(["win", "loss", "scratch"]),
                    TradeJournal.symbol == signal.symbol,
                )
                .where(Trade.source == "bot", Trade.venue == "oanda",
                       Trade.parent_trade_id.is_(None), Trade.status == "closed")
                .order_by(TradeJournal.updated_at.desc())
                .limit(12)
            )
        )
        consecutive = 0
        last_loss = None
        for row in closed:
            if row.outcome == "scratch":
                continue
            if row.outcome == "loss":
                consecutive += 1
                if last_loss is None:
                    last_loss = row
                continue
            break
        daily_halt_enabled = (settings.oanda_environment != "practice" or
                              settings.practice_daily_loss_halt_enabled)
        if daily_halt_enabled and consecutive >= settings.max_consecutive_losses and last_loss is not None:
            until = next_session_open(
                _aware(last_loss.updated_at),
                start_hour=settings.trade_session_start_hour,
            )
            if now < until:
                consecutive_block = LessonGate(
                    False,
                    (
                        f"Consecutive-loss halt: {consecutive} losers in a row "
                        f"(last {last_loss.side} {last_loss.symbol} ${float(last_loss.realized_pl or 0):+.2f}). "
                        f"Sit out until the next session open at {until.strftime('%Y-%m-%d %H:%M UTC')}."
                    ),
                    "consecutive_halt",
                )
        last_closed = closed[0] if closed else None
        if last_closed is not None and last_closed.outcome in {"win", "scratch"}:
            closed_at = _aware(last_closed.updated_at) or now
            cool = timedelta(minutes=max(0, settings.reentry_cooldown_minutes))
            if now - closed_at < cool:
                remain = int((cool - (now - closed_at)).total_seconds() // 60) + 1
                cooldown_block = LessonGate(
                    False,
                    (
                        f"Re-entry pause: last {last_closed.outcome} on {last_closed.symbol} "
                        f"${float(last_closed.realized_pl or 0):+.2f}. Wait {remain} more minute(s) "
                        f"so fills stay semi-frequent, not every M5 print."
                    ),
                    "reentry_cooldown",
                )
        if last_loss is not None:
            lost_at = _aware(last_loss.updated_at) or now
            cool = timedelta(minutes=max(0, settings.post_loss_cooldown_minutes))
            if now - lost_at < cool:
                remain = int((cool - (now - lost_at)).total_seconds() // 60) + 1
                cooldown_block = LessonGate(
                    False,
                    (
                        f"Post-loss cooldown: last stop was {last_loss.side} {last_loss.symbol} "
                        f"${float(last_loss.realized_pl or 0):+.2f}. Wait {remain} more minute(s) "
                        f"instead of revenge-trading the same print."
                    ),
                    "cooldown",
                )
    # Family/book skip beats a weaker exact "need more strength" so two similar
    # losses actually take the desk off the setup. Consecutive halt and cooldown
    # still sit in front of high-strength so a losing streak cannot keep firing.
    if consecutive_block is not None:
        return consecutive_block
    if skip_block is not None:
        return skip_block
    if cooldown_block is not None:
        return cooldown_block
    if related_blocks:
        return related_blocks[0]
    if settings.oanda_environment == "practice" and settings.practice_contextual_loss_review:
        if signal is not None:
            from src.analysis.loss_review import review_loss
            recent = session.execute(select(Trade, TradeJournal).join(TradeJournal, TradeJournal.trade_id == Trade.id)
                .where(Trade.source == "bot", Trade.venue == "oanda", Trade.parent_trade_id.is_(None),
                       Trade.status == "closed", Trade.symbol == signal.symbol, Trade.side == signal.action,
                       TradeJournal.outcome == "loss").order_by(Trade.closed_at.desc()).limit(3)).all()
            signal.decision_context = dict(signal.decision_context or {}, loss_reviews=[
                {"trade_id": t.id, "assessment": review_loss(t,j)} for t,j in recent])
        return LessonGate(True, "Contextual loss review: outcome-only bans are advisory; current entry checks and cooldowns still apply", "observe")
    return LessonGate(True, "Lesson checks passed", "observe")


def _nearest_signal(session: Session, trade: Trade) -> SignalRow | None:
    if trade.signal_id:
        row = session.get(SignalRow, trade.signal_id)
        if row is not None:
            return row
    ts = trade.opened_at or trade.created_at
    stmt = select(SignalRow).where(
        SignalRow.symbol == trade.symbol,
        SignalRow.action == trade.side,
        SignalRow.skipped.is_(False),
    )
    if ts is not None:
        stmt = stmt.where(SignalRow.ts <= ts)
    return session.scalar(stmt.order_by(SignalRow.ts.desc()).limit(1))


def _signal_from_row(sig: SignalRow, trade: Trade) -> TradeSignal:
    return TradeSignal(
        symbol=sig.symbol,
        timeframe=sig.timeframe,
        action=sig.action if sig.action in {"BUY", "SELL"} else trade.side,  # type: ignore[arg-type]
        timestamp=sig.ts,
        price=sig.price,
        entry=sig.entry,
        stop_loss=sig.stop_loss,
        take_profit_1=sig.take_profit_1,
        take_profit_2=sig.take_profit_2,
        risk_reward=sig.risk_reward,
        atr=None,
        rsi=None,
        ema_fast=None,
        ema_slow=None,
        bb_upper=None,
        bb_mid=None,
        bb_lower=None,
        htf_bias="neutral",
        confluence=list(sig.confluence or []),
        reason=sig.reason,
        strength=sig.strength,
    )


def backfill_missing_journals(
    session: Session,
    *,
    quotes: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> int:
    """Write theses/post-mortems for trades that predate the journal tables."""
    settings = settings or get_settings()
    trades = list(session.scalars(select(Trade).order_by(Trade.id)))
    count = 0
    for trade in trades:
        journal = get_journal_for_trade(session, trade.id)
        sig_row = _nearest_signal(session, trade)
        signal = _signal_from_row(sig_row, trade) if sig_row is not None else None
        adopted = trade.signal_id is None and sig_row is None
        weak = journal is not None and (
            not fingerprint_is_current(journal.fingerprint)
            or "unknown" in (journal.fingerprint or "")
            or "adopting the fill" in (journal.entry_thesis or "")
        )
        if journal is None or weak:
            if sig_row is not None and not trade.signal_id:
                trade.signal_id = sig_row.id
            record_entry(session, trade, signal, adopted=adopted)
            # Rebuild thesis when we now have a real snapshot.
            journal = get_journal_for_trade(session, trade.id)
            if journal is not None and (weak or not journal.entry_thesis):
                ctx = journal.entry_context or {}
                journal.entry_thesis = build_entry_thesis(
                    symbol=trade.symbol,
                    side=trade.side,
                    signal=signal,
                    trade=trade,
                    context=ctx,
                    adopted=adopted,
                )
            count += 1
            journal = get_journal_for_trade(session, trade.id)
        if trade.status == "closed" and journal is not None and (
            journal.outcome == "open" or weak
        ):
            exit_price = trade.exit_price
            if exit_price is None and quotes and trade.symbol in quotes:
                q = quotes[trade.symbol]
                exit_price = getattr(q, "mid", None) or (q.get("mid") if isinstance(q, dict) else None)
            pl = _as_float(trade.realized_pl or 0)
            if abs(pl) < 1e-9 and exit_price and trade.fill_price:
                pl = estimate_realized_pl(trade, float(exit_price))
                trade.realized_pl = pl
            if exit_price and not trade.exit_price:
                trade.exit_price = float(exit_price)
            reason = infer_close_reason(trade, float(exit_price) if exit_price else None)
            trade.close_reason = reason
            record_exit(
                session,
                trade,
                exit_price=float(exit_price) if exit_price else None,
                realized_pl=pl,
                close_reason=reason,
                settings=settings,
            )
            count += 1
    rebuild_learned_rules(session, settings)
    return count


def rebuild_learned_rules(session: Session, settings: Settings | None = None) -> int:
    """Recompute exact + family + book rules. Keep aggregated fingerprints active."""
    settings = settings or get_settings()
    closed = list(
        session.scalars(
            select(TradeJournal).where(TradeJournal.outcome.in_(["win", "loss", "scratch"]))
        )
    )
    seen: set[str] = set()
    for row in closed:
        if not row.fingerprint or row.fingerprint in seen:
            continue
        seen.add(row.fingerprint)
        upsert_learned_rule(session, row, settings)
    valid: set[str] = set()
    for row in session.scalars(select(TradeJournal)):
        if row.fingerprint:
            valid.update(related_fingerprints(row.fingerprint))
        if row.symbol and row.side:
            valid.add(family_fingerprint(row.symbol, row.side, row.htf_bias or "neutral"))
            valid.add(book_fingerprint(row.symbol, row.side))
    deactivated = 0
    for rule in list(session.scalars(select(LearnedRule))):
        if rule.fingerprint not in valid:
            if rule.active or rule.action != "observe":
                deactivated += 1
            rule.active = False
            rule.action = "observe"
            rule.skip_until = None
    session.flush()
    return deactivated


def daily_lesson_digest(session: Session, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = list(
        session.scalars(
            select(TradeJournal)
            .where(TradeJournal.updated_at >= start, TradeJournal.outcome != "open")
            .order_by(TradeJournal.updated_at.desc())
        )
    )
    if not rows:
        return "No closed demo trades today, so there is nothing new to learn yet."
    wins = sum(1 for r in rows if r.outcome == "win")
    losses = sum(1 for r in rows if r.outcome == "loss")
    scratches = sum(1 for r in rows if r.outcome == "scratch")
    net = sum(_as_float(r.realized_pl or 0) for r in rows)
    lines = [
        f"Today's book: {len(rows)} closed · {wins} wins · {losses} losses · "
        f"{scratches} scratches · net ${net:+,.2f}."
    ]
    for row in rows:
        if row.outcome == "loss" and row.how_to_avoid:
            lines.append(f"LOSS {row.side} {row.symbol}: {row.how_to_avoid.splitlines()[0]}")
        elif row.outcome == "win" and row.what_went_right:
            first = row.what_went_right.splitlines()[0]
            lines.append(f"WIN {row.side} {row.symbol}: {first[:220]}")
    rules = list(
        session.scalars(
            select(LearnedRule).where(
                LearnedRule.action.in_(["skip", "require_high_strength"]),
                LearnedRule.active.is_(True),
            )
        )
    )
    if rules:
        lines.append("Active lessons going into tomorrow:")
        for rule in rules:
            until = ""
            if rule.skip_until:
                until = f" until {rule.skip_until.strftime('%Y-%m-%d %H:%M UTC')}"
            lines.append(
                f"• {rule.action} {rule.fingerprint} (losses={rule.loss_count}, "
                f"min strength={rule.min_strength}){until}"
            )
    return "\n".join(lines)


def build_tape_reflection(signal: TradeSignal, *, skip_reason: str | None = None) -> str:
    """Plain-English read of the tape: why we would trade, or why we are sitting."""
    px = format_price(signal.symbol, signal.price)
    lines: list[str] = []
    if skip_reason:
        lines.append(
            f"I would {signal.action} {signal.symbol} at {px}, but I am standing aside: {skip_reason}"
        )
    elif signal.action == "HOLD":
        lines.append(f"I am not trading {signal.symbol} at {px}. {signal.reason}.")
    else:
        verb = "buy" if signal.action == "BUY" else "sell"
        lines.append(
            f"I want to {verb} {signal.symbol} at {px} (strength {signal.strength}/100) because:"
        )
        if signal.confluence:
            lines.extend(f"• {item}" for item in signal.confluence[:6])
        else:
            lines.append(f"• {signal.reason}")

    bits: list[str] = []
    if signal.rsi is not None:
        bits.append(f"RSI {signal.rsi:.1f} ({rsi_bucket(signal.rsi)})")
    if signal.stoch_k is not None:
        bits.append(f"Stoch %K {signal.stoch_k:.0f}")
    if signal.macd_hist is not None:
        bits.append(f"MACD hist {signal.macd_hist:+.5f}")
    if signal.adx is not None:
        bits.append(f"ADX {signal.adx:.0f}")
    if signal.cci is not None:
        bits.append(f"CCI {signal.cci:.0f}")
    bits.append(f"H1 {signal.htf_bias}")
    bits.append(f"D1 {signal.d1_bias}")
    if signal.ema_fast is not None and signal.ema_slow is not None:
        stack = "bullish EMA stack" if signal.ema_fast > signal.ema_slow else "bearish EMA stack"
        bits.append(stack)
    lines.append("Tape: " + " · ".join(bits) + ".")
    if signal.action == "HOLD":
        lines.append(
            "I will keep reading M5 and only step in on a trigger (band/RSI/stoch/CCI extreme, "
            "EMA or MACD cross, or divergence) that agrees with H1."
        )
    return "\n".join(lines)
