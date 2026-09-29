"""Paginated reads for the review hub: bars, indicators, signals, trades, account."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from src.data.storage import (
    AccountSnapshot,
    Bar,
    DailyPnL,
    DeskNote,
    IndicatorRow,
    LearnedRule,
    NewsItem,
    NotificationLog,
    PipelineRun,
    SetupMemory,
    SignalRow,
    Trade,
    TradeJournal,
    _as_float,
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _page_args(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, int(page or 1))
    page_size = min(5000, max(1, int(page_size or 100)))
    return page, page_size


def _paginate(
    session: Session,
    stmt: Select,
    *,
    page: int,
    page_size: int,
) -> tuple[int, int, int, list]:
    page, page_size = _page_args(page, page_size)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(session.scalar(count_stmt) or 0)
    rows = list(session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
    return total, page, page_size, rows


def hub_summary(session: Session) -> dict[str, Any]:
    bars = int(session.scalar(select(func.count()).select_from(Bar)) or 0)
    indicators = int(session.scalar(select(func.count()).select_from(IndicatorRow)) or 0)
    signals = int(session.scalar(select(func.count()).select_from(SignalRow)) or 0)
    trades = int(session.scalar(select(func.count()).select_from(Trade)) or 0)
    buy_signals = int(
        session.scalar(select(func.count()).select_from(SignalRow).where(SignalRow.action == "BUY")) or 0
    )
    sell_signals = int(
        session.scalar(select(func.count()).select_from(SignalRow).where(SignalRow.action == "SELL")) or 0
    )
    hold_signals = int(
        session.scalar(select(func.count()).select_from(SignalRow).where(SignalRow.action == "HOLD")) or 0
    )
    skipped = int(
        session.scalar(select(func.count()).select_from(SignalRow).where(SignalRow.skipped.is_(True))) or 0
    )
    history_signals = int(
        session.scalar(select(func.count()).select_from(SignalRow).where(SignalRow.source == "history")) or 0
    )
    open_trades = int(
        session.scalar(
            select(func.count()).select_from(Trade).where(Trade.status.in_(["open", "partial"]))
        )
        or 0
    )
    closed_trades = int(
        session.scalar(select(func.count()).select_from(Trade).where(Trade.status == "closed")) or 0
    )
    realized = float(session.scalar(select(func.coalesce(func.sum(Trade.realized_pl), 0))) or 0)
    journals = int(session.scalar(select(func.count()).select_from(TradeJournal)) or 0)
    journal_losses = int(
        session.scalar(select(func.count()).select_from(TradeJournal).where(TradeJournal.outcome == "loss"))
        or 0
    )
    active_skips = int(
        session.scalar(
            select(func.count())
            .select_from(LearnedRule)
            .where(LearnedRule.active.is_(True), LearnedRule.action.in_(["skip", "require_high_strength"]))
        )
        or 0
    )
    setups = int(session.scalar(select(func.count()).select_from(SetupMemory)) or 0)
    briefings = int(session.scalar(select(func.count()).select_from(DeskNote)) or 0)
    morning_notes = int(
        session.scalar(select(func.count()).select_from(DeskNote).where(DeskNote.kind == "morning")) or 0
    )
    recap_notes = int(
        session.scalar(select(func.count()).select_from(DeskNote).where(DeskNote.kind == "recap")) or 0
    )
    news_items = int(session.scalar(select(func.count()).select_from(NewsItem)) or 0)
    news_pending = int(
        session.scalar(select(func.count()).select_from(NewsItem).where(NewsItem.verdict == "pending")) or 0
    )
    symbols = [row[0] for row in session.execute(select(Bar.symbol).distinct().order_by(Bar.symbol))]
    timeframes = [row[0] for row in session.execute(select(Bar.timeframe).distinct().order_by(Bar.timeframe))]
    return {
        "counts": {
            "bars": bars,
            "indicators": indicators,
            "signals": signals,
            "trades": trades,
            "open_trades": open_trades,
            "closed_trades": closed_trades,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "hold_signals": hold_signals,
            "skipped_signals": skipped,
            "history_signals": history_signals,
            "journals": journals,
            "journal_losses": journal_losses,
            "active_lessons": active_skips,
            "briefings": briefings,
            "morning_notes": morning_notes,
            "recap_notes": recap_notes,
            "setups": setups,
            "news_items": news_items,
            "news_pending": news_pending,
        },
        "realized_pl": realized,
        "symbols": symbols,
        "timeframes": timeframes or ["M1", "M5", "H1", "D1"],
    }


def serialize_bar(row: Bar) -> dict[str, Any]:
    return {
        "id": row.id,
        "ts": _iso(row.ts),
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "open": float(row.open),
        "high": float(row.high),
        "low": float(row.low),
        "close": float(row.close),
        "volume": float(row.volume or 0),
        "source": row.source,
        "complete": row.complete,
    }


def _first_class(row: Any, extra: dict[str, Any], key: str) -> Any:
    value = getattr(row, key, None)
    if value is not None:
        return value
    return extra.get(key)


def serialize_indicator(row: IndicatorRow) -> dict[str, Any]:
    extra = row.extra or {}
    return {
        "id": row.id,
        "ts": _iso(row.ts),
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "ema_fast": row.ema_fast,
        "ema_slow": row.ema_slow,
        "rsi": row.rsi,
        "atr": row.atr,
        "bb_upper": row.bb_upper,
        "bb_mid": row.bb_mid,
        "bb_lower": row.bb_lower,
        "d1_bias": extra.get("d1_bias"),
        "trend": _first_class(row, extra, "trend"),
        "bb_pct": extra.get("bb_pct"),
        "macd": _first_class(row, extra, "macd"),
        "macd_signal": _first_class(row, extra, "macd_signal"),
        "macd_hist": _first_class(row, extra, "macd_hist"),
        "stoch_k": _first_class(row, extra, "stoch_k"),
        "stoch_d": _first_class(row, extra, "stoch_d"),
        "adx": _first_class(row, extra, "adx"),
        "plus_di": _first_class(row, extra, "plus_di"),
        "minus_di": _first_class(row, extra, "minus_di"),
        "cci": _first_class(row, extra, "cci"),
        "vwap": extra.get("vwap"),
        "supertrend": extra.get("supertrend"),
        "st_dir": extra.get("st_dir"),
        "squeeze_on": extra.get("squeeze_on"),
        "wt1": extra.get("wt1"),
        "ewmac": extra.get("ewmac"),
        "tma": extra.get("tma"),
    }


def serialize_signal(row: SignalRow) -> dict[str, Any]:
    confluence = row.confluence
    if isinstance(confluence, list):
        confluence_text = "; ".join(str(item) for item in confluence)
    else:
        confluence_text = ""
    return {
        "id": row.id,
        "ts": _iso(row.ts),
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "action": row.action,
        "price": row.price,
        "entry": row.entry,
        "stop_loss": row.stop_loss,
        "take_profit_1": row.take_profit_1,
        "take_profit_2": row.take_profit_2,
        "risk_reward": row.risk_reward,
        "strength": row.strength,
        "confluence": confluence_text,
        "reason": row.reason,
        "skipped": row.skipped,
        "skip_reason": row.skip_reason,
        "signal_type": getattr(row, "signal_type", None) or "",
        "fingerprint": getattr(row, "fingerprint", None) or "",
        "htf_bias": getattr(row, "htf_bias", None) or "",
        "d1_bias": getattr(row, "d1_bias", None) or "",
        "rsi": getattr(row, "rsi", None),
        "atr": getattr(row, "atr", None),
        "macd": getattr(row, "macd", None),
        "stoch_k": getattr(row, "stoch_k", None),
        "adx": getattr(row, "adx", None),
        "cci": getattr(row, "cci", None),
        "source": getattr(row, "source", None) or "live",
    }


def serialize_trade(row: Trade) -> dict[str, Any]:
    return {
        "id": row.id,
        "broker_order_id": row.broker_order_id,
        "broker_trade_id": row.broker_trade_id,
        "signal_id": row.signal_id,
        "symbol": row.symbol,
        "side": row.side,
        "units": row.units,
        "remaining_units": row.remaining_units,
        "requested_entry": row.requested_entry,
        "fill_price": row.fill_price,
        "slippage_pips": row.slippage_pips,
        "stop_loss": row.stop_loss,
        "take_profit_1": row.take_profit_1,
        "take_profit_2": row.take_profit_2,
        "status": row.status,
        "tp1_filled": row.tp1_filled,
        "exit_price": row.exit_price,
        "realized_pl": _as_float(row.realized_pl or 0),
        "close_reason": row.close_reason,
        "error_message": row.error_message,
        "source": getattr(row, "source", None) or "bot",
        "venue": getattr(row, "venue", None) or "oanda",
        "opened_at": _iso(row.opened_at),
        "closed_at": _iso(row.closed_at),
        "created_at": _iso(row.created_at),
    }


def serialize_snapshot(row: AccountSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "ts": _iso(row.ts),
        "balance": _as_float(row.balance),
        "nav": _as_float(row.nav),
        "unrealized_pl": _as_float(row.unrealized_pl),
        "realized_pl": _as_float(row.realized_pl),
        "margin_used": _as_float(row.margin_used),
        "margin_available": _as_float(row.margin_available),
        "open_trade_count": row.open_trade_count,
        "peak_nav": _as_float(row.peak_nav),
        "drawdown_pct": row.drawdown_pct,
    }


def serialize_daily(row: DailyPnL) -> dict[str, Any]:
    return {
        "id": row.id,
        "day": row.day.isoformat() if row.day else None,
        "starting_balance": _as_float(row.starting_balance),
        "realized_pl": _as_float(row.realized_pl),
        "trades_opened": row.trades_opened,
        "trades_closed": row.trades_closed,
        "halted": row.halted,
        "halt_reason": row.halt_reason,
    }


def serialize_notification(row: NotificationLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "ts": _iso(row.ts),
        "kind": row.kind,
        "title": row.title,
        "delivered": row.delivered,
        "error": row.error,
    }


def serialize_run(row: PipelineRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "status": row.status,
        "symbols_processed": row.symbols_processed,
        "signals_emitted": row.signals_emitted,
        "orders_placed": row.orders_placed,
        "error": row.error,
        "notes": row.notes,
    }


def serialize_journal(row: TradeJournal) -> dict[str, Any]:
    return {
        "id": row.id,
        "trade_id": row.trade_id,
        "signal_id": row.signal_id,
        "updated_at": _iso(row.updated_at),
        "symbol": row.symbol,
        "side": row.side,
        "fingerprint": row.fingerprint,
        "rsi_bucket": row.rsi_bucket,
        "bb_zone": row.bb_zone,
        "htf_bias": row.htf_bias,
        "outcome": row.outcome,
        "exit_verdict": row.exit_verdict,
        "realized_pl": _as_float(row.realized_pl or 0),
        "hold_minutes": row.hold_minutes,
        "close_reason": row.close_reason,
        "entry_thesis": row.entry_thesis,
        "what_went_wrong": row.what_went_wrong,
        "how_to_avoid": row.how_to_avoid,
        "what_went_right": row.what_went_right,
        "lesson": row.lesson,
        "mistakes": list(row.mistakes or []),
    }


def serialize_lesson(row: LearnedRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "updated_at": _iso(row.updated_at),
        "fingerprint": row.fingerprint,
        "symbol": row.symbol,
        "side": row.side,
        "htf_bias": row.htf_bias,
        "rsi_bucket": row.rsi_bucket,
        "bb_zone": row.bb_zone,
        "sample_count": row.sample_count,
        "win_count": row.win_count,
        "loss_count": row.loss_count,
        "scratch_count": row.scratch_count,
        "net_pl": _as_float(row.net_pl or 0),
        "action": row.action,
        "min_strength": row.min_strength,
        "skip_until": _iso(row.skip_until),
        "lesson": row.lesson,
        "last_outcome": row.last_outcome,
        "active": row.active,
    }


def list_bars(
    session: Session,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    stmt = select(Bar)
    if symbol and symbol.upper() not in {"ALL", ""}:
        stmt = stmt.where(Bar.symbol == symbol)
    if timeframe and timeframe.upper() not in {"ALL", ""}:
        stmt = stmt.where(Bar.timeframe == timeframe.upper())
    stmt = stmt.order_by(desc(Bar.ts), Bar.symbol)
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {"total": total, "page": page, "page_size": page_size, "rows": [serialize_bar(r) for r in rows]}


def list_indicators(
    session: Session,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    stmt = select(IndicatorRow)
    if symbol and symbol.upper() not in {"ALL", ""}:
        stmt = stmt.where(IndicatorRow.symbol == symbol)
    if timeframe and timeframe.upper() not in {"ALL", ""}:
        stmt = stmt.where(IndicatorRow.timeframe == timeframe.upper())
    stmt = stmt.order_by(desc(IndicatorRow.ts), IndicatorRow.symbol)
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_indicator(r) for r in rows],
    }


def list_signals(
    session: Session,
    *,
    symbol: str | None = None,
    action: str | None = None,
    skipped: str | None = None,
    source: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    stmt = select(SignalRow)
    if symbol and symbol.upper() not in {"ALL", ""}:
        stmt = stmt.where(SignalRow.symbol == symbol)
    if action and action.upper() not in {"ALL", ""}:
        stmt = stmt.where(SignalRow.action == action.upper())
    if skipped in {"true", "1", "yes"}:
        stmt = stmt.where(SignalRow.skipped.is_(True))
    elif skipped in {"false", "0", "no"}:
        stmt = stmt.where(SignalRow.skipped.is_(False))
    if source and source.lower() not in {"all", ""}:
        stmt = stmt.where(SignalRow.source == source.lower())
    stmt = stmt.order_by(desc(SignalRow.ts), desc(SignalRow.id))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_signal(r) for r in rows],
    }


def serialize_setup(row: SetupMemory) -> dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "signal_type": row.signal_type,
        "side": row.side,
        "session": row.session,
        "samples": row.samples,
        "wins": row.wins,
        "losses": row.losses,
        "expectancy_pips": row.expectancy_pips,
        "win_rate": row.win_rate,
        "avg_strength": row.avg_strength,
        "last_studied": _iso(row.last_studied),
    }


def list_setups(
    session: Session,
    *,
    symbol: str | None = None,
    side: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    stmt = select(SetupMemory)
    if symbol and symbol.upper() not in {"ALL", ""}:
        stmt = stmt.where(SetupMemory.symbol == symbol)
    if side and side.upper() not in {"ALL", ""}:
        stmt = stmt.where(SetupMemory.side == side.upper())
    stmt = stmt.order_by(desc(SetupMemory.expectancy_pips), desc(SetupMemory.samples))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_setup(r) for r in rows],
    }


def list_trades(
    session: Session,
    *,
    symbol: str | None = None,
    side: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    stmt = select(Trade)
    if symbol and symbol.upper() not in {"ALL", ""}:
        stmt = stmt.where(Trade.symbol == symbol)
    if side and side.upper() not in {"ALL", ""}:
        stmt = stmt.where(Trade.side == side.upper())
    if status and status.lower() not in {"all", ""}:
        stmt = stmt.where(Trade.status == status.lower())
    stmt = stmt.order_by(desc(Trade.created_at), desc(Trade.id))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_trade(r) for r in rows],
    }


def list_snapshots(
    session: Session, *, page: int = 1, page_size: int = 100
) -> dict[str, Any]:
    stmt = select(AccountSnapshot).order_by(desc(AccountSnapshot.ts))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_snapshot(r) for r in rows],
    }


def list_daily_pnl(session: Session, *, page: int = 1, page_size: int = 100) -> dict[str, Any]:
    stmt = select(DailyPnL).order_by(desc(DailyPnL.day))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_daily(r) for r in rows],
    }


def list_notifications(
    session: Session, *, kind: str | None = None, page: int = 1, page_size: int = 100
) -> dict[str, Any]:
    stmt = select(NotificationLog)
    if kind and kind.lower() not in {"all", ""}:
        stmt = stmt.where(NotificationLog.kind == kind.lower())
    stmt = stmt.order_by(desc(NotificationLog.ts), desc(NotificationLog.id))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_notification(r) for r in rows],
    }


def list_pipeline_runs(
    session: Session, *, page: int = 1, page_size: int = 100
) -> dict[str, Any]:
    stmt = select(PipelineRun).order_by(desc(PipelineRun.started_at))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_run(r) for r in rows],
    }


def list_journals(
    session: Session,
    *,
    symbol: str | None = None,
    side: str | None = None,
    outcome: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    stmt = select(TradeJournal)
    if symbol and symbol.upper() not in {"ALL", ""}:
        stmt = stmt.where(TradeJournal.symbol == symbol)
    if side and side.upper() not in {"ALL", ""}:
        stmt = stmt.where(TradeJournal.side == side.upper())
    if outcome and outcome.lower() not in {"all", ""}:
        stmt = stmt.where(TradeJournal.outcome == outcome.lower())
    stmt = stmt.order_by(desc(TradeJournal.updated_at), desc(TradeJournal.id))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_journal(r) for r in rows],
    }


def serialize_desk_note(row: DeskNote) -> dict[str, Any]:
    return {
        "id": row.id,
        "day": row.day.isoformat() if row.day else None,
        "kind": row.kind,
        "sentiment": row.sentiment,
        "looking_for": row.looking_for,
        "goals": row.goals,
        "what_went_right": row.what_went_right,
        "what_went_wrong": row.what_went_wrong,
        "verdict": row.verdict,
        "why": row.why,
        "learned": row.learned,
        "body": row.body,
        "news": row.news,
        "technical": row.technical,
        "realized_pl": _as_float(row.realized_pl or 0),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def list_briefings(
    session: Session,
    *,
    kind: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    stmt = select(DeskNote)
    if kind and kind.lower() not in {"all", ""}:
        stmt = stmt.where(DeskNote.kind == kind.lower())
    stmt = stmt.order_by(desc(DeskNote.day), DeskNote.kind.asc(), desc(DeskNote.id))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_desk_note(r) for r in rows],
    }


def list_lessons(
    session: Session,
    *,
    symbol: str | None = None,
    side: str | None = None,
    rule: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    stmt = select(LearnedRule)
    if symbol and symbol.upper() not in {"ALL", ""}:
        stmt = stmt.where(LearnedRule.symbol == symbol)
    if side and side.upper() not in {"ALL", ""}:
        stmt = stmt.where(LearnedRule.side == side.upper())
    if rule and rule.lower() not in {"all", ""}:
        stmt = stmt.where(LearnedRule.action == rule.lower())
    stmt = stmt.order_by(desc(LearnedRule.updated_at), desc(LearnedRule.id))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_lesson(r) for r in rows],
    }


def list_news(
    session: Session,
    *,
    source: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    from src.analysis.news_patterns import serialize_news_item

    stmt = select(NewsItem)
    if source and source.lower() not in {"all", ""}:
        stmt = stmt.where(NewsItem.category == source.lower())
    stmt = stmt.order_by(desc(NewsItem.ts), desc(NewsItem.id))
    total, page, page_size, rows = _paginate(session, stmt, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": [serialize_news_item(r) for r in rows],
    }


TABLES: dict[str, dict[str, Any]] = {
    "bars": {
        "list": list_bars,
        "filename": "bars.csv",
        "headers": [
            "ts",
            "symbol",
            "timeframe",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
            "complete",
        ],
    },
    "indicators": {
        "list": list_indicators,
        "filename": "indicators.csv",
        "headers": [
            "ts",
            "symbol",
            "timeframe",
            "ema_fast",
            "ema_slow",
            "rsi",
            "atr",
            "bb_upper",
            "bb_mid",
            "bb_lower",
            "trend",
            "bb_pct",
            "macd",
            "macd_hist",
            "stoch_k",
            "stoch_d",
            "adx",
            "cci",
        ],
    },
    "signals": {
        "list": list_signals,
        "filename": "signals.csv",
        "headers": [
            "ts",
            "symbol",
            "timeframe",
            "action",
            "price",
            "entry",
            "stop_loss",
            "take_profit_1",
            "take_profit_2",
            "risk_reward",
            "strength",
            "signal_type",
            "fingerprint",
            "htf_bias",
            "rsi",
            "macd",
            "stoch_k",
            "adx",
            "cci",
            "skipped",
            "skip_reason",
            "confluence",
            "reason",
            "source",
        ],
    },
    "setups": {
        "list": list_setups,
        "filename": "setup_memory.csv",
        "headers": [
            "last_studied",
            "symbol",
            "signal_type",
            "side",
            "session",
            "samples",
            "wins",
            "losses",
            "expectancy_pips",
            "win_rate",
            "avg_strength",
        ],
    },
    "trades": {
        "list": list_trades,
        "filename": "trades.csv",
        "headers": [
            "id",
            "broker_trade_id",
            "opened_at",
            "closed_at",
            "symbol",
            "side",
            "units",
            "fill_price",
            "slippage_pips",
            "stop_loss",
            "take_profit_1",
            "take_profit_2",
            "exit_price",
            "realized_pl",
            "status",
            "close_reason",
            "source",
            "venue",
            "error_message",
        ],
    },
    "snapshots": {
        "list": list_snapshots,
        "filename": "account_snapshots.csv",
        "headers": [
            "ts",
            "balance",
            "nav",
            "unrealized_pl",
            "realized_pl",
            "margin_used",
            "margin_available",
            "open_trade_count",
            "peak_nav",
            "drawdown_pct",
        ],
    },
    "daily": {
        "list": list_daily_pnl,
        "filename": "daily_pnl.csv",
        "headers": [
            "day",
            "starting_balance",
            "realized_pl",
            "trades_opened",
            "trades_closed",
            "halted",
            "halt_reason",
        ],
    },
    "alerts": {
        "list": list_notifications,
        "filename": "alerts.csv",
        "headers": ["ts", "kind", "title", "delivered", "error"],
    },
    "cycles": {
        "list": list_pipeline_runs,
        "filename": "pipeline_runs.csv",
        "headers": [
            "id",
            "started_at",
            "finished_at",
            "status",
            "symbols_processed",
            "signals_emitted",
            "orders_placed",
            "error",
        ],
    },
    "journal": {
        "list": list_journals,
        "filename": "trade_journal.csv",
        "headers": [
            "id",
            "trade_id",
            "updated_at",
            "symbol",
            "side",
            "outcome",
            "realized_pl",
            "close_reason",
            "fingerprint",
            "rsi_bucket",
            "bb_zone",
            "htf_bias",
            "entry_thesis",
            "what_went_wrong",
            "how_to_avoid",
            "what_went_right",
            "lesson",
            "mistakes",
        ],
    },
    "briefings": {
        "list": list_briefings,
        "filename": "desk_notes.csv",
        "headers": [
            "day",
            "kind",
            "sentiment",
            "verdict",
            "realized_pl",
            "why",
            "looking_for",
            "goals",
            "what_went_right",
            "what_went_wrong",
            "learned",
            "body",
        ],
    },
    "lessons": {
        "list": list_lessons,
        "filename": "learned_rules.csv",
        "headers": [
            "updated_at",
            "fingerprint",
            "symbol",
            "side",
            "action",
            "min_strength",
            "skip_until",
            "sample_count",
            "win_count",
            "loss_count",
            "scratch_count",
            "net_pl",
            "last_outcome",
            "lesson",
        ],
    },
    "news": {
        "list": list_news,
        "filename": "eurusd_news.csv",
        "headers": [
            "ts",
            "published",
            "source",
            "category",
            "predicted",
            "verdict",
            "title",
            "price_at",
            "move_1h_pips",
            "url",
        ],
    },
}


def export_rows(session: Session, table: str, **filters: Any) -> tuple[Sequence[str], list[dict[str, Any]]]:
    spec = TABLES[table]
    payload = spec["list"](session, page=1, page_size=5000, **filters)
    return spec["headers"], payload["rows"]
