"""Descriptive learning statistics; evidence alone never promotes live risk."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analysis.signals import TradeSignal
from src.analysis.reflection import fingerprint_from_signal
from src.config import Settings, get_settings
from src.data.datasets import HistoryReport
from src.data.storage import Trade, TradeJournal
from src.utils import pip_size, price_to_pips, utcnow

GROWTH_PATH_NAME = "GROWTH.md"


@dataclass(slots=True)
class BucketStats:
    key: str
    scope: str
    samples: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0
    net_pl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    expectancy: float = 0.0
    profit_factor: float | None = None
    r_samples: int = 0
    mean_r: float | None = None
    missing_risk_samples: int = 0
    evidence_status: str = "unvalidated"
    teacher_wins: int = 0
    last_outcome: str | None = None
    median_pl: float = 0.0
    losing_streak: int = 0
    lesson: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "scope": self.scope,
            "samples": self.samples,
            "wins": self.wins,
            "losses": self.losses,
            "scratches": self.scratches,
            "net_pl": round(self.net_pl, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "win_rate": round(self.win_rate, 3),
            "expectancy": round(self.expectancy, 2),
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor is not None else None,
            "r_samples": self.r_samples, "mean_r": self.mean_r,
            "missing_risk_samples": self.missing_risk_samples,
            "evidence_status": self.evidence_status,
            "teacher_wins": self.teacher_wins,
            "last_outcome": self.last_outcome,
            "median_pl": round(self.median_pl, 2),
            "losing_streak": self.losing_streak,
            "lesson": self.lesson,
        }


@dataclass(slots=True)
class GrowthDecision:
    allowed: bool
    reason: str
    min_stop_pips: float
    note: str = ""
    action: str = "observe"


@dataclass(slots=True)
class GrowthReport:
    ts: datetime
    symbol: str = "EUR/USD"
    buckets: list[BucketStats] = field(default_factory=list)
    preferred_side: str | None = None
    recommended_min_stop_pips: float = 5.0
    stop_out_count: int = 0
    avg_losing_stop_pips: float | None = None
    next_focus: str = ""
    rules: list[str] = field(default_factory=list)

    def bucket(self, key: str) -> BucketStats | None:
        for item in self.buckets:
            if item.key == key:
                return item
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "symbol": self.symbol,
            "preferred_side": self.preferred_side,
            "recommended_min_stop_pips": self.recommended_min_stop_pips,
            "stop_out_count": self.stop_out_count,
            "avg_losing_stop_pips": self.avg_losing_stop_pips,
            "next_focus": self.next_focus,
            "rules": list(self.rules),
            "buckets": [b.as_dict() for b in self.buckets],
        }


def hour_bucket(ts: datetime | None) -> str:
    """Analytic local-clock windows; not broker hours or entry permission."""
    if ts is None:
        return "unknown"
    from datetime import timezone
    from zoneinfo import ZoneInfo
    # SQLite returns our UTC timestamps without timezone metadata.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    london = 8 <= ts.astimezone(ZoneInfo("Europe/London")).hour < 17
    new_york = 8 <= ts.astimezone(ZoneInfo("America/New_York")).hour < 17
    if london and new_york:
        return "overlap"
    if london:
        return "london"
    if new_york:
        return "new_york"
    if 9 <= ts.astimezone(ZoneInfo("Asia/Tokyo")).hour < 18:
        return "tokyo"
    return "off"


def _pl(row: TradeJournal) -> float:
    return float(row.realized_pl or 0)


def _score(rows: list[TradeJournal], *, key: str, scope: str, teacher_wins: int = 0) -> BucketStats:
    # Monetary outcomes include scratches; missing or nonfinite values are not zero.
    closed = [r for r in rows if r.outcome in {"win", "loss", "scratch"}
              and r.realized_pl is not None and math.isfinite(float(r.realized_pl))]
    pls = [_pl(r) for r in closed]
    positive = [p for p in pls if p > 0]
    negative = [p for p in pls if p < 0]
    decided = [r for r in closed if r.outcome != "scratch"]
    streak = 0
    for row in reversed(decided):
        if row.outcome != "loss":
            break
        streak += 1
    rs = []
    for row in closed:
        risk = (row.entry_context or {}).get("initial_risk") or {}
        amount = risk.get("amount")
        # Do not guess historical initial stops from mutable Trade.stop_loss.
        if risk.get("basis") == "entry_snapshot" and risk.get("currency") == "USD":
            try:
                amount = float(amount)
                if math.isfinite(amount) and amount > 0:
                    rs.append(_pl(row) / amount)
            except (ValueError, TypeError):
                pass
    n = len(closed)
    stats = BucketStats(
        key=key, scope=scope, samples=n,
        wins=sum(r.outcome == "win" for r in closed),
        losses=sum(r.outcome == "loss" for r in closed),
        scratches=sum(r.outcome == "scratch" for r in closed),
        net_pl=sum(pls), avg_win=sum(positive)/len(positive) if positive else 0.0,
        avg_loss=sum(negative)/len(negative) if negative else 0.0,
        win_rate=sum(r.outcome == "win" for r in closed)/n if n else 0.0,
        expectancy=sum(pls)/n if n else 0.0,
        profit_factor=sum(positive)/abs(sum(negative)) if negative else None,
        teacher_wins=0, last_outcome=closed[-1].outcome if closed else None,
        median_pl=float(median(pls)) if pls else 0.0, losing_streak=streak,
        r_samples=len(rs), mean_r=sum(rs)/len(rs) if rs else None,
        missing_risk_samples=n-len(rs),
        evidence_status="insufficient_evidence" if n < 30 else "unvalidated",
    )
    stats.lesson = (
        f"Observe {key}: {n} outcomes, {len(rs)} with recorded initial risk; "
        "descriptive results do not establish an edge or authorize size increases."
    )
    if streak >= 2:
        stats.lesson += " Stand down under the existing consecutive-loss controls."

    return stats


def _desk_closed(
    session: Session, symbol: str
) -> tuple[list[tuple[TradeJournal, Trade | None]], dict[int, Trade]]:
    trades = {t.id: t for t in session.scalars(select(Trade).where(Trade.symbol == symbol))}
    journals = list(
        session.scalars(
            select(TradeJournal)
            .where(
                TradeJournal.symbol == symbol,
                TradeJournal.outcome.in_(["win", "loss", "scratch", "open"]),
            )
            .order_by(TradeJournal.updated_at.asc())
        )
    )
    paired: list[tuple[TradeJournal, Trade | None]] = []
    for journal in journals:
        paired.append((journal, trades.get(journal.trade_id)))
    # Restudying a journal must not change the sequence of actual trade outcomes.
    from datetime import timezone
    def closed_key(pair):
        journal, trade = pair
        ts = (trade.closed_at if trade else None) or journal.created_at
        if ts is None:
            ts = datetime.min.replace(tzinfo=timezone.utc)
        elif ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts, journal.id
    paired.sort(key=closed_key)
    return paired, trades


def study_book(session: Session, *, symbol: str = "EUR/USD", settings: Settings | None = None) -> GrowthReport:
    """Separate manual examples and venue copies from primary bot evidence."""
    settings = settings or get_settings()
    paired, _ = _desk_closed(session, symbol)
    groups: dict[tuple[str, str], list[TradeJournal]] = {}
    stops = []
    for journal, trade in paired:
        if trade is None or trade.status != "closed" or journal.outcome not in {"win", "loss", "scratch"}:
            continue
        if trade.source == "human":
            groups.setdefault(("human", f"human:{symbol}|{journal.side}"), []).append(journal)
            continue
        if trade.source != "bot" or trade.venue != "oanda" or trade.parent_trade_id is not None:
            continue
        entries = [("book", f"{symbol}|{journal.side}"),
                   ("family", f"{symbol}|{journal.side}|{journal.htf_bias or 'neutral'}"),
                   ("exact", journal.fingerprint or f"{symbol}|{journal.side}"),
                   ("session", f"session:{hour_bucket(trade.opened_at)}")]
        for scope, key in entries:
            groups.setdefault((scope, key), []).append(journal)
        version = ((journal.entry_context or {}).get("decision_evidence") or {}).get("code_sha256")
        groups.setdefault(("version", f"version:{version or 'unknown'}"), []).append(journal)
        risk = (journal.entry_context or {}).get("initial_risk") or {}
        if journal.close_reason == "stop_loss" and risk.get("basis") == "entry_snapshot":
            value = risk.get("stop_pips")
            if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
                stops.append(value)
    buckets = [_score(rows, key=key, scope=scope) for (scope, key), rows in sorted(groups.items())]
    return GrowthReport(
        ts=utcnow(), symbol=symbol, buckets=buckets, preferred_side=None,
        recommended_min_stop_pips=float(settings.min_stop_pips),
        stop_out_count=len(stops), avg_losing_stop_pips=median(stops) if stops else None,
        next_focus="Collect decision-time evidence and compare frozen candidates forward; no statistical promotion yet.",
        rules=["Manual outcomes and mirrored venues do not contribute to primary bot performance.",
               "Include scratches; normalize only against recorded initial risk.",
               "Keep the configured stop floor and risk limits; no automatic widening or winner-based size-up."],
    )


def preferred_side_from_intel(intel: Any | None) -> str | None:
    if intel is None:
        return None
    h1 = getattr(intel, "h1_bias", None) or (intel.get("h1_bias") if isinstance(intel, dict) else None)
    d1 = getattr(intel, "d1_bias", None) or (intel.get("d1_bias") if isinstance(intel, dict) else None)
    if h1 in {"bullish", "bearish"} and h1 == d1:
        return "BUY" if h1 == "bullish" else "SELL"
    stance = str(getattr(intel, "stance", "") or (intel.get("stance") if isinstance(intel, dict) else "") or "")
    low = stance.lower()
    if "short" in low and "long" not in low:
        return "SELL"
    if "long" in low and "short" not in low:
        return "BUY"
    return None


def growth_gate(
    signal: TradeSignal,
    report: GrowthReport | None,
    *,
    intel: Any | None = None,
    history: HistoryReport | None = None,
    settings: Settings | None = None,
) -> GrowthDecision:
    settings = settings or get_settings()
    # Historical summaries do not earn live influence merely by accumulating samples.
    if history is not None and not getattr(history, "validated_for_live", False):
        history = None
    min_stop = float(settings.min_stop_pips)
    # Descriptive reports cannot alter initial stop geometry.
    if signal.action == "HOLD":
        return GrowthDecision(True, "No directional ticket", min_stop)

    intel_side = preferred_side_from_intel(intel)
    hist_side = None
    if history is not None and getattr(history, "replay_trades", 0) >= 40:
        hist_side = history.preferred_side
    exact = (
        report.bucket(fingerprint_from_signal(signal)) if report is not None else None
    )
    book = report.bucket(f"{signal.symbol}|{signal.action}") if report else None

    counter = None
    if intel_side and signal.action != intel_side:
        counter = intel_side
    elif hist_side and signal.action != hist_side:
        counter = hist_side

    if counter:
        fade_min = int(settings.fade_strength_min)
        if int(signal.strength or 0) >= fade_min:
            return GrowthDecision(
                True,
                (
                    f"Growth: calculated fade — tape prefers {counter} {signal.symbol} but "
                    f"strength {signal.strength} clears {fade_min}. Taking a smaller {signal.action}."
                ),
                min_stop,
                note="fade",
                action="fade",
            )
        return GrowthDecision(
            False,
            (
                f"Growth: tape and book prefer {counter} {signal.symbol}. "
                f"Skipping {signal.action} until H1/D1 flip or strength ≥ {fade_min}."
            ),
            min_stop,
            action="skip",
        )
    if history is not None and signal.action in {"BUY", "SELL"}:
        stype = getattr(signal, "signal_type", None) or ""
        typed = [
            item
            for item in (history.setups or [])
            if item.get("signal_type") == stype and item.get("side") == signal.action
        ]
        if typed:
            weight = sum(float(item.get("expectancy_pips") or 0) * int(item.get("samples") or 0) for item in typed)
            n = sum(int(item.get("samples") or 0) for item in typed)
            exp = (weight / n) if n else 0.0
            if n >= 25 and exp < -0.25 and int(signal.strength or 0) < int(settings.fade_strength_min):
                return GrowthDecision(
                    False,
                    (
                        f"Growth: historical `{stype}` {signal.action} expectancy {exp:+.1f} pips "
                        f"over {n} tickets. Sitting this setup out."
                    ),
                    min_stop,
                    action="skip",
                )

    stretched = False
    rsi = signal.rsi
    if signal.action == "SELL" and rsi is not None and rsi >= 60:
        stretched = True
    if signal.action == "BUY" and rsi is not None and rsi <= 40:
        stretched = True
    stype = str(getattr(signal, "signal_type", "") or "")
    if "fade" in stype:
        stretched = True

    contextual = settings.oanda_environment == "practice" and settings.practice_contextual_loss_review
    if not contextual and book and book.losing_streak >= 2:
        if stretched and int(signal.strength or 0) >= int(settings.conviction_strength_min):
            return GrowthDecision(
                True,
                (
                    f"Growth: last {book.losing_streak} {book.key} fills were stops "
                    f"(median ${book.median_pl:+.2f}). Re-entering only as a stretched extreme."
                ),
                min_stop,
                note="fade",
                action="fade",
            )
        return GrowthDecision(
            False,
            (
                f"Growth: last {book.losing_streak} {book.key} fills were stops "
                f"(net ${book.net_pl:+.2f} is an outlier, median ${book.median_pl:+.2f}). "
                "Sitting this side out."
            ),
            min_stop,
            action="skip",
        )
    if not contextual and exact and exact.losing_streak >= 1 and exact.losses >= exact.wins and exact.samples >= 1:
        if not stretched or int(signal.strength or 0) < int(settings.conviction_strength_min):
            return GrowthDecision(
                False,
                (
                    f"Growth: `{exact.key}` last closed as a {exact.last_outcome} "
                    f"({exact.wins}W/{exact.losses}L, median ${exact.median_pl:+.2f}). Need a cleaner snapshot."
                ),
                min_stop,
                action="skip",
            )
    if not contextual and book and book.samples >= 2 and book.net_pl < 0 and book.wins == 0:
        return GrowthDecision(
            False,
            (
                f"Growth: {book.key} has {book.losses} loss(es) and no win (net ${book.net_pl:+.2f}). "
                f"Sit out this side."
            ),
            min_stop,
            action="skip",
        )
    return GrowthDecision(True, "Growth checks passed", min_stop)


def widen_to_min_stop(signal: TradeSignal, min_pips: float, settings: Settings | None = None) -> TradeSignal:
    """Move SL/TP out if the ATR stop is tighter than what the book learned."""
    settings = settings or get_settings()
    entry = signal.entry or signal.price
    if not entry or signal.action not in {"BUY", "SELL"}:
        return signal
    floor = pip_size(signal.symbol) * float(min_pips)
    sl = signal.stop_loss
    current = abs(entry - sl) if sl else 0.0
    if current + 1e-12 >= floor:
        return signal
    sl_mult = float(settings.atr_sl_multiplier) or 1.5
    tp1_mult = float(settings.atr_tp1_multiplier) or 2.0
    tp2_mult = float(settings.atr_tp2_multiplier) or 3.5
    tp1_dist = floor * (tp1_mult / sl_mult)
    tp2_dist = floor * (tp2_mult / sl_mult)
    if signal.action == "BUY":
        signal.stop_loss = entry - floor
        signal.take_profit_1 = entry + tp1_dist
        signal.take_profit_2 = entry + tp2_dist
    else:
        signal.stop_loss = entry + floor
        signal.take_profit_1 = entry - tp1_dist
        signal.take_profit_2 = entry - tp2_dist
    rr_den = floor
    signal.risk_reward = (tp1_dist / rr_den) if rr_den else signal.risk_reward
    return signal


def render_growth(report: GrowthReport) -> str:
    lines = [
        "# EUR/USD growth ledger",
        "",
        f"_Last studied: {report.ts.strftime('%Y-%m-%d %H:%M UTC')}. Rewritten after every fill and intel cycle._",
        "",
        "## What to do next",
        "",
        report.next_focus or "Watch the next closed fill.",
        "",
        f"Preferred side: **{report.preferred_side or 'none yet'}**. "
        f"Stop floor: **{report.recommended_min_stop_pips:.1f} pips**"
        + (
            f" (losing stops clustered at {report.avg_losing_stop_pips:.1f})."
            if report.avg_losing_stop_pips is not None
            else "."
        ),
        "",
        "## Learned rules",
        "",
    ]
    if report.rules:
        lines.extend(f"- {r}" for r in report.rules)
    else:
        lines.append("- Not enough closed EUR/USD desk fills to promote a rule.")
    lines += ["", "## Book, family, and snapshot scores", ""]
    ranked = [b for b in report.buckets if b.scope in {"book", "family", "exact", "human"} and b.samples]
    ranked.sort(key=lambda b: (b.scope != "book", -b.net_pl))
    if not ranked:
        lines.append("- No decided EUR/USD desk fills yet.")
    for bucket in ranked[:16]:
        lines.append(
            f"- `{bucket.key}` ({bucket.scope}) · {bucket.wins}W/{bucket.losses}L · "
            f"{bucket.scratches} scratches · R samples {bucket.r_samples}/{bucket.samples} · "
            f"mean R {bucket.mean_r if bucket.mean_r is not None else 'unknown'} · {bucket.evidence_status} · "
            f"E ${bucket.expectancy:+.2f} · median ${bucket.median_pl:+.2f} · net ${bucket.net_pl:+.2f} · {bucket.lesson}"
        )
    sessions = [b for b in report.buckets if b.scope == "session"]
    if sessions:
        lines += ["", "## Session memory", ""]
        for bucket in sessions:
            lines.append(
                f"- {bucket.key.replace('session:', '')}: {bucket.wins}W/{bucket.losses}L "
                f"net ${bucket.net_pl:+.2f}"
            )
    lines += [
        "",
        "## How the desk uses this",
        "",
        "- Last two stops on a side sit that side out — a fat outlier win is not a license to keep firing.",
        "- Dollar statistics are descriptive; initial-risk R is reported only when recorded at entry.",
        "- No winning bucket automatically earns preference, increased risk or wider stops.",
        "- Manual outcomes are a separate comparison group; mirrored copies are excluded.",
        "- Historical summaries remain unvalidated unless separately qualified.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_growth(report: GrowthReport, path: Any | None = None) -> Any:
    from src.analysis.playbook import GROWTH_PATH, ensure_desk_dir

    ensure_desk_dir()
    target = path or GROWTH_PATH
    target.write_text(render_growth(report), encoding="utf-8")
    return target
