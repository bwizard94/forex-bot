"""Morning briefing and night recap for the EUR/USD specialist desk."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analysis.indicators import compute_indicators
from src.analysis.signals import _htf_bias, bars_to_frame
from src.config import Settings, get_settings
from src.data.news import CalendarEvent, Headline, NewsBundle, score_sentiment
from src.data.storage import (
    DeskNote,
    IndicatorRow,
    LearnedRule,
    SignalRow,
    Trade,
    TradeJournal,
    _as_float,
    load_bars,
)
from src.utils import format_price, utcnow


def _weekday_name(day: date) -> str:
    return day.strftime("%A %d %b %Y")


def _latest_indicator(session: Session, timeframe: str) -> IndicatorRow | None:
    return session.scalar(
        select(IndicatorRow)
        .where(IndicatorRow.symbol == "EUR/USD", IndicatorRow.timeframe == timeframe)
        .order_by(IndicatorRow.ts.desc())
        .limit(1)
    )


def _bias_from_bars(session: Session, timeframe: str, settings: Settings) -> str:
    rows = load_bars(session, "EUR/USD", timeframe, limit=250)
    frame = bars_to_frame(rows)
    if frame.empty:
        return "neutral"
    computed = compute_indicators(
        frame,
        ema_fast=settings.ema_fast,
        ema_slow=settings.ema_slow,
        rsi_period=settings.rsi_period,
        atr_period=settings.atr_period,
        bb_period=settings.bb_period,
        bb_std=settings.bb_std,
    )
    return _htf_bias(computed)


def _technical_snapshot(session: Session, settings: Settings) -> dict[str, Any]:
    h1 = _latest_indicator(session, "H1")
    m5 = _latest_indicator(session, "M5")
    d1_bias = _bias_from_bars(session, "D1", settings)
    h1_bias = _bias_from_bars(session, "H1", settings)
    return {
        "h1_bias": h1_bias,
        "d1_bias": d1_bias,
        "rsi": m5.rsi if m5 else None,
        "atr": m5.atr if m5 else None,
        "ema_fast": m5.ema_fast if m5 else None,
        "ema_slow": m5.ema_slow if m5 else None,
        "price_hint": h1.rsi if h1 else None,
        "m5_rsi": m5.rsi if m5 else None,
    }


def _sentiment_label(tech: dict[str, Any], news_score: int, events: list[CalendarEvent]) -> tuple[str, str]:
    h1 = tech.get("h1_bias") or "neutral"
    d1 = tech.get("d1_bias") or "neutral"
    tech_score = 0
    if h1 == "bullish":
        tech_score += 2
    elif h1 == "bearish":
        tech_score -= 2
    if d1 == "bullish":
        tech_score += 2
    elif d1 == "bearish":
        tech_score -= 2
    event_heat = sum(1 for e in events if e.impact == "High")
    total = tech_score + news_score
    if total >= 3:
        label = "Bullish"
        tone = "The tape and the news both lean toward a higher EUR/USD."
    elif total <= -3:
        label = "Bearish"
        tone = "The tape and the news both lean toward a lower EUR/USD."
    elif h1 == d1 and h1 != "neutral":
        label = f"Cautiously {h1}"
        tone = (
            f"H1 and D1 agree {h1}, but news is mixed — trade with the trend, "
            "not against a headline spike."
        )
    else:
        label = "Mixed / two-way"
        tone = "Trend and headlines disagree. Wait for H1 to pick a side before committing."
    if event_heat:
        tone += f" {event_heat} high-impact EUR/USD event(s) on the calendar — volatility will expand."
    return label, tone


def _looking_for(
    tech: dict[str, Any],
    events: list[CalendarEvent],
    rules: list[LearnedRule],
    settings: Settings,
) -> str:
    h1 = tech.get("h1_bias") or "neutral"
    d1 = tech.get("d1_bias") or "neutral"
    lines = []
    if h1 == "bullish":
        lines.append(
            "H1 is bullish. I want M5 pullbacks toward the 21-EMA / lower band, "
            "RSI not already overbought, then a long with the 1.5×ATR stop — "
            "or a continuation if MACD/ADX still agree."
        )
    elif h1 == "bearish":
        lines.append(
            "H1 is bearish. I want M5 rallies into the 21-EMA / upper band, "
            "RSI not already oversold, then a short with the 1.5×ATR stop — "
            "or a continuation if MACD/ADX still agree."
        )
    else:
        lines.append(
            "H1 is flat. I will only trade EUR/USD on a strong M5 snapshot "
            "(extra confluence), not a two-factor grind."
        )
    if d1 == "bearish":
        lines.append("D1 is bearish — I will not buy EUR/USD against the daily trend.")
    elif d1 == "bullish":
        lines.append("D1 is bullish — I will not sell EUR/USD against the daily trend.")
    if events:
        names = ", ".join(f"{e.country} {e.title}" for e in events[:4])
        lines.append(
            f"Around {names} I stand aside for 30 minutes either side of the print "
            "and only re-enter if H1 still agrees after the spike."
        )
    skips = [r for r in rules if r.active and r.action in {"skip", "require_high_strength"}]
    if skips:
        lines.append(
            "Lessons in force: "
            + "; ".join(
                f"{r.action} on {r.fingerprint}" + (f" (min strength {r.min_strength})" if r.min_strength else "")
                for r in skips[:4]
            )
        )
    lines.append(
        f"Discipline: {settings.post_loss_cooldown_minutes}-minute pause after a stop; "
        f"{settings.reentry_cooldown_minutes}-minute pause after a win; two consecutive losses on THIS pair "
        "sit out until the next session open. Intraday EUR/USD scalp — Ox LWMA + envelopes + DSS, short SL/TP. Preserve capital. "
        "Entries: Ox triad, extremes, crosses, divergence, squeeze fire, sweep, or H1-aligned continuation."
    )
    lines.append(
        f"Session: {settings.trade_session_start_hour:02d}:00–{settings.trade_session_end_hour:02d}:00 UTC "
        f"(Tokyo through New York, weekdays; no Sunday reopen; Friday flat after "
        f"{int(getattr(settings, 'friday_flat_hour', 20) or 20):02d}:00 UTC). Up to {settings.max_open_positions} desk tickets "
        f"(max {settings.max_same_side_positions} same-side) when the tape is worth it. Base {settings.risk_per_trade_pct:.0%} "
        f"of NAV, {settings.conviction_risk_pct:.1%} conviction, {settings.addon_risk_pct:.2%} add-on onto a winner, "
        f"{settings.fade_risk_pct:.1%} fade. Combined open risk cap {settings.max_open_risk_pct:.1%}."
    )
    return "\n".join(f"• {line}" for line in lines)


def _goals(
    tech: dict[str, Any],
    events: list[CalendarEvent],
    day: date,
    settings: Settings,
    history: Any | None = None,
) -> str:
    h1 = tech.get("h1_bias") or "neutral"
    goals = [
        f"Trade only EUR/USD on {_weekday_name(day)} during Tokyo through New York hours.",
        "Take a setup when H1 agrees, a D1-aligned fade if H1 is flat, or a strong M5 Ox scalp triad.",
        "Risk a sized slice of NAV per ticket (base/conviction/add-on/fade). Stack up to "
        f"{settings.max_open_positions} desk positions when the tape is worth it — never more than "
        f"{settings.max_same_side_positions} on the same side, and never add to an underwater ticket.",
        "Write a thesis on every fill and a post-mortem on every close.",
        f"After a stop, wait {settings.post_loss_cooldown_minutes} minutes. After a win, wait "
        f"{settings.reentry_cooldown_minutes} minutes. Two consecutive EUR/USD losses sit out until the next session.",
    ]
    if h1 == "bullish":
        goals.append("Primary hunt: discounted longs. Do not chase RSI > 70.")
    elif h1 == "bearish":
        goals.append("Primary hunt: expensive shorts. Do not chase RSI < 30.")
    else:
        d1 = tech.get("d1_bias") or "neutral"
        if d1 == "bearish":
            goals.append("Primary hunt: fade M5 rallies under a bearish D1. Do not buy the spike.")
        elif d1 == "bullish":
            goals.append("Primary hunt: buy discounted dips under a bullish D1. Do not chase shorts.")
        else:
            goals.append("Primary hunt: wait for H1, or take a stretched M5 fade / strong continuation.")
    if (history is not None and getattr(history, "validated_for_live", False)
            and getattr(history, "preferred_side", None)):
        sess = getattr(history, "preferred_session", None) or "the historical session"
        span = getattr(history, "eurusd_span", None) or "extra datasets"
        goals.append(
            f"History from extra datasets ({span}) leans {history.preferred_side} in {sess}. "
            "Hunt that unless live H1 has flipped."
        )
    if events:
        goals.append(
            "Protect capital through "
            + ", ".join(e.title for e in events if e.impact == "High")[:180]
            + " — flatten or stay flat if the print is live."
        )
    goals.append("End the day with a written recap at 23:30 UTC whether I traded or not.")
    return "\n".join(f"{i}. {g}" for i, g in enumerate(goals, 1))


def build_morning_brief(
    *,
    session: Session,
    bundle: NewsBundle,
    settings: Settings | None = None,
    day: date | None = None,
    quote_mid: float | None = None,
    history: Any | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    day = day or utcnow().date()
    tech = _technical_snapshot(session, settings)
    events = [
        e
        for e in bundle.events
        if e.ts is not None
        and e.ts.astimezone(timezone.utc).date() == day
        and e.impact in {"High", "Medium"}
    ]
    headlines = bundle.headlines[:8]
    news_text = " ".join(h.title for h in headlines) + " " + " ".join(e.title for e in events)
    news_score = score_sentiment(news_text)
    rules = list(
        session.scalars(
            select(LearnedRule).where(
                LearnedRule.active.is_(True),
                LearnedRule.action.in_(["skip", "require_high_strength"]),
            )
        )
    )
    label, tone = _sentiment_label(tech, news_score, events)
    looking = _looking_for(tech, events, rules, settings)
    goals = _goals(tech, events, day, settings, history=history)
    price = f" {format_price('EUR/USD', quote_mid)}" if quote_mid else ""
    news_lines = []
    if events:
        news_lines.append("Calendar (EUR & USD, medium+):")
        for event in events[:8]:
            when = event.ts.strftime("%H:%M UTC") if event.ts else "untimed"
            extra = []
            if event.forecast:
                extra.append(f"forecast {event.forecast}")
            if event.previous:
                extra.append(f"prev {event.previous}")
            meta = f" ({', '.join(extra)})" if extra else ""
            news_lines.append(f"• {when} {event.country} {event.impact}: {event.title}{meta}")
    else:
        news_lines.append("No medium/high EUR or USD prints on today's public calendar (or the calendar feed was down).")
    if headlines:
        news_lines.append("Headlines that can move EUR/USD:")
        for h in headlines[:6]:
            news_lines.append(f"• {h.title} ({h.source})")
    elif bundle.errors:
        news_lines.append("Headline feeds were unreachable: " + "; ".join(bundle.errors[:3]))
    rsi = tech.get("m5_rsi")
    rsi_txt = f"{rsi:.1f}" if isinstance(rsi, (int, float)) else "n/a"
    body = (
        f"EUR/USD desk — {_weekday_name(day)} 08:00 UTC\n\n"
        f"Spot{price}\n"
        f"Market sentiment: {label}\n{tone}\n\n"
        f"Technical: H1 {tech.get('h1_bias')}, D1 {tech.get('d1_bias')}, "
        f"M5 RSI {rsi_txt}. Session {settings.trade_session_start_hour:02d}:00–{settings.trade_session_end_hour:02d}:00 UTC "
        f"(Friday flat after {int(getattr(settings, 'friday_flat_hour', 20) or 20):02d}:00; no Sunday reopen).\n\n"
        f"News that could impact EUR/USD:\n"
        + "\n".join(news_lines)
        + "\n\nWhat I am looking for:\n"
        + looking
        + "\n\nGoals for the day:\n"
        + goals
    )
    return {
        "day": day,
        "kind": "morning",
        "sentiment": label,
        "looking_for": looking,
        "goals": goals,
        "what_went_right": None,
        "what_went_wrong": None,
        "verdict": None,
        "why": tone,
        "learned": None,
        "body": body,
        "news": {
            "events": [e.as_dict() for e in events],
            "headlines": [h.as_dict() for h in headlines],
            "errors": bundle.errors,
        },
        "technical": tech,
        "realized_pl": 0.0,
    }


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def build_night_recap(
    *,
    session: Session,
    settings: Settings | None = None,
    day: date | None = None,
    ending_nav: float | None = None,
    unrealized_pl: float = 0.0,
) -> dict[str, Any]:
    settings = settings or get_settings()
    day = day or utcnow().date()
    start, end = _day_bounds(day)
    opened = list(
        session.scalars(
            select(Trade).where(
                Trade.symbol == "EUR/USD",
                Trade.created_at >= start,
                Trade.created_at < end,
            )
        )
    )
    closed = list(
        session.scalars(
            select(Trade).where(
                Trade.symbol == "EUR/USD",
                Trade.status == "closed",
                Trade.closed_at >= start,
                Trade.closed_at < end,
            )
        )
    )
    realized = sum(_as_float(t.realized_pl) for t in closed)
    seen_ids = {t.id for t in opened} | {t.id for t in closed}
    journals = []
    if seen_ids:
        journals = list(session.scalars(select(TradeJournal).where(TradeJournal.trade_id.in_(seen_ids))))
    wins = [j for j in journals if j.outcome == "win"]
    losses = [j for j in journals if j.outcome == "loss"]
    scratches = [j for j in journals if j.outcome == "scratch"]
    skipped = list(
        session.scalars(
            select(SignalRow).where(
                SignalRow.symbol == "EUR/USD",
                SignalRow.ts >= start,
                SignalRow.ts < end,
                SignalRow.skipped.is_(True),
            )
        )
    )
    if realized > settings.lesson_scratch_usd:
        verdict = "positive"
    elif realized < -settings.lesson_scratch_usd:
        verdict = "negative"
    else:
        verdict = "flat"

    right: list[str] = []
    wrong: list[str] = []
    if wins:
        right.append(
            f"{len(wins)} winning EUR/USD trade(s) paid "
            f"${sum(_as_float(j.realized_pl) for j in wins):+,.2f}."
        )
        for j in wins[:3]:
            first = (j.what_went_right or j.lesson or "").splitlines()[0]
            if first:
                right.append(first)
    if not opened:
        right.append("I did not force a EUR/USD trade. Sitting out is a valid day when H1 is unclear or news is live.")
    news_skips = [s for s in skipped if s.skip_reason and "Stand aside" in (s.skip_reason or "")]
    if news_skips:
        right.append(f"I stood aside through {len(news_skips)} high-impact news window(s) instead of gambling the print.")
    session_holds = [
        s
        for s in session.scalars(
            select(SignalRow).where(
                SignalRow.symbol == "EUR/USD",
                SignalRow.ts >= start,
                SignalRow.ts < end,
                SignalRow.reason.contains("Outside the London"),
            )
        )
    ]
    if session_holds:
        right.append("I stayed out of the Asia session instead of fading thin EUR/USD liquidity.")

    if losses:
        wrong.append(
            f"{len(losses)} losing EUR/USD trade(s) cost "
            f"${sum(_as_float(j.realized_pl) for j in losses):+,.2f}."
        )
        for j in losses[:4]:
            line = (j.how_to_avoid or j.what_went_wrong or "").splitlines()[0]
            if line:
                wrong.append(line)
    rejected = [t for t in opened if t.status == "rejected"]
    if rejected:
        wrong.append(f"{len(rejected)} order(s) were rejected at the broker.")
    if verdict == "negative" and not losses:
        wrong.append("The book finished down without a clean journaled loss — check slippage and broker closes.")
    if not right:
        right.append("Nothing paid. The useful result is the list of mistakes below.")
    if not wrong:
        wrong.append("No material unforced error on EUR/USD today.")

    if verdict == "positive":
        why = (
            f"Positive day because realized P/L is ${realized:+,.2f} "
            f"on {len(wins)} win(s) vs {len(losses)} loss(es). "
            "The process (session filter, H1 wind, 1% risk) produced a net edge."
        )
    elif verdict == "negative":
        why = (
            f"Negative day because realized P/L is ${realized:+,.2f}. "
            f"{len(losses)} stop-out(s) outweighed {len(wins)} win(s). "
            "Size stayed at 1% so the damage is a lesson, not an account event."
        )
    else:
        why = (
            f"Flat day (${realized:+,.2f}). Either I did not trade or wins and losses cancelled. "
            "EUR/USD specialist days are allowed to be quiet."
        )
    if ending_nav is not None:
        why += f" Ending NAV ${ending_nav:,.2f} (unrealized ${unrealized_pl:+,.2f})."

    learned_bits = []
    for j in losses:
        if j.lesson:
            learned_bits.append(j.lesson.splitlines()[0])
    for j in wins:
        if j.lesson:
            learned_bits.append(j.lesson.splitlines()[0])
    rules = list(
        session.scalars(
            select(LearnedRule).where(
                LearnedRule.symbol == "EUR/USD",
                LearnedRule.active.is_(True),
                LearnedRule.updated_at >= start,
            )
        )
    )
    for r in rules:
        learned_bits.append(
            f"Updated rule {r.action} on {r.fingerprint} (losses={r.loss_count}, wins={r.win_count})."
        )
    if not learned_bits:
        learned_bits.append(
            "No new fingerprint rule today. Tomorrow I still require H1 agreement or a strong "
            "M5 continuation, D1 not strongly against, and weekday Tokyo–NY hours."
        )
    learned = "\n".join(f"• {item}" for item in learned_bits[:8])
    right_txt = "\n".join(f"• {item}" for item in right[:8])
    wrong_txt = "\n".join(f"• {item}" for item in wrong[:8])
    body = (
        f"EUR/USD daily analysis — {_weekday_name(day)} 23:30 UTC\n\n"
        f"Verdict: {verdict.upper()}  ·  realized P/L ${realized:+,.2f}  ·  "
        f"opened {len(opened)} / closed {len(closed)}  ·  "
        f"{len(wins)} wins / {len(losses)} losses / {len(scratches)} scratches\n\n"
        f"Why it was {verdict}:\n{why}\n\n"
        f"What went right:\n{right_txt}\n\n"
        f"What went wrong:\n{wrong_txt}\n\n"
        f"What I learned:\n{learned}"
    )
    return {
        "day": day,
        "kind": "recap",
        "sentiment": None,
        "looking_for": None,
        "goals": None,
        "what_went_right": right_txt,
        "what_went_wrong": wrong_txt,
        "verdict": verdict,
        "why": why,
        "learned": learned,
        "body": body,
        "news": None,
        "technical": None,
        "realized_pl": realized,
    }


def upsert_desk_note(session: Session, payload: dict[str, Any]) -> DeskNote:
    day = payload["day"]
    kind = payload["kind"]
    row = session.scalar(select(DeskNote).where(DeskNote.day == day, DeskNote.kind == kind))
    fields = {
        "sentiment": payload.get("sentiment"),
        "looking_for": payload.get("looking_for"),
        "goals": payload.get("goals"),
        "what_went_right": payload.get("what_went_right"),
        "what_went_wrong": payload.get("what_went_wrong"),
        "verdict": payload.get("verdict"),
        "why": payload.get("why"),
        "learned": payload.get("learned"),
        "body": payload.get("body") or "",
        "news": payload.get("news"),
        "technical": payload.get("technical"),
        "realized_pl": payload.get("realized_pl") or 0,
        "updated_at": utcnow(),
    }
    if row is None:
        row = DeskNote(day=day, kind=kind, **fields)
        session.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    session.flush()
    return row
