"""SQLAlchemy models, engine bootstrap, and upsert helpers.

Persists minute bars, computed indicators, every generated signal
(including those skipped by risk rules), and the full trade lifecycle
so the book can be replayed for later backtesting.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Generator, Iterable, Sequence

from loguru import logger
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.config import get_settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Bar(Base):
    __tablename__ = "bars"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts", name="uq_bar_key"),
        Index("ix_bars_symbol_tf_ts", "symbol", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="oanda")
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class IndicatorRow(Base):
    __tablename__ = "indicators"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts", name="uq_indicator_key"),
        Index("ix_indicators_symbol_tf_ts", "symbol", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ema_fast: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_slow: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Float, nullable=True)
    stoch_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    stoch_d: Mapped[float | None] = mapped_column(Float, nullable=True)
    adx: Mapped[float | None] = mapped_column(Float, nullable=True)
    plus_di: Mapped[float | None] = mapped_column(Float, nullable=True)
    minus_di: Mapped[float | None] = mapped_column(Float, nullable=True)
    cci: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SignalRow(Base):
    __tablename__ = "signals"
    __table_args__ = (Index("ix_signals_symbol_ts", "symbol", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confluence: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, default="hold")
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    htf_bias: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    d1_bias: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    rsi: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_fast: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_slow: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd: Mapped[float | None] = mapped_column(Float, nullable=True)
    stoch_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    adx: Mapped[float | None] = mapped_column(Float, nullable=True)
    cci: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="live")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DecisionObservation(Base):
    """Append-only application record; signal upserts must not erase prior decisions."""
    __tablename__ = "decision_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_symbol_status", "symbol", "status"),
        Index("ix_trades_broker_id", "broker_trade_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    broker_trade_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_entry: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_pips: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit_1: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit_2: Mapped[float] = mapped_column(Float, nullable=False)
    broker_take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    tp1_filled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remaining_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pl: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    close_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="bot")
    venue: Mapped[str] = mapped_column(String(16), nullable=False, default="oanda")
    parent_trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    balance: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    nav: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    unrealized_pl: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    realized_pl: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    margin_used: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    margin_available: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    open_trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    peak_nav: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class DailyPnL(Base):
    __tablename__ = "daily_pnl"
    __table_args__ = (UniqueConstraint("day", name="uq_daily_pnl_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    starting_balance: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    realized_pl: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    trades_opened: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trades_closed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    halted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    halt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotificationLog(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    symbols_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_emitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orders_placed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SetupMemory(Base):
    """Historical expectancy by signal type, side, and session."""

    __tablename__ = "setup_memory"
    __table_args__ = (
        UniqueConstraint("symbol", "signal_type", "side", "session", name="uq_setup_memory"),
        Index("ix_setup_memory_symbol", "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    session: Mapped[str] = mapped_column(String(16), nullable=False)
    samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expectancy_pips: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_studied: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TradeJournal(Base):
    """Written thesis on every fill and a post-mortem on every close."""

    __tablename__ = "trade_journals"
    __table_args__ = (
        UniqueConstraint("trade_id", name="uq_journal_trade"),
        Index("ix_journals_fingerprint", "fingerprint"),
        Index("ix_journals_outcome", "outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    rsi_bucket: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    bb_zone: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    htf_bias: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    entry_thesis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    entry_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    exit_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    what_went_wrong: Mapped[str | None] = mapped_column(Text, nullable=True)
    how_to_avoid: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_went_right: Mapped[str | None] = mapped_column(Text, nullable=True)
    lesson: Mapped[str | None] = mapped_column(Text, nullable=True)
    realized_pl: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    hold_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mistakes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class LearnedRule(Base):
    """Fingerprint-level memory: observe, demand a stronger score, or skip."""

    __tablename__ = "learned_rules"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_learned_fingerprint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    htf_bias: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    rsi_bucket: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    bb_zone: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scratch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    net_pl: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="observe")
    min_strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skip_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lesson: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class DeskNote(Base):
    """08:00 morning brief and 23:30 daily analysis for the EUR/USD desk."""

    __tablename__ = "desk_notes"
    __table_args__ = (UniqueConstraint("day", "kind", name="uq_desk_day_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sentiment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    looking_for: Mapped[str | None] = mapped_column(Text, nullable=True)
    goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_went_right: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_went_wrong: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    why: Mapped[str | None] = mapped_column(Text, nullable=True)
    learned: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    news: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    technical: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    realized_pl: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class TapeNote(Base):
    """Periodic tape read: why the desk traded or sat out, with indicator snapshot."""

    __tablename__ = "tape_notes"
    __table_args__ = (Index("ix_tape_symbol_ts", "symbol", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, default="M5")
    action: Mapped[str] = mapped_column(String(8), nullable=False, default="HOLD")
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    indicators: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class NewsItem(Base):
    """EUR/USD headline log with a predicted move and a later tape check."""

    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_news_fingerprint"),
        Index("ix_news_ts", "ts"),
        Index("ix_news_category_verdict", "category", "verdict"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    published: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    fingerprint: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    predicted: Mapped[str] = mapped_column(String(16), nullable=False, default="mixed")
    predicted_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sentiment: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_30m: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_1h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_4h: Mapped[float | None] = mapped_column(Float, nullable=True)
    move_30m_pips: Mapped[float | None] = mapped_column(Float, nullable=True)
    move_1h_pips: Mapped[float | None] = mapped_column(Float, nullable=True)
    move_4h_pips: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    scan_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="harvest")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Mt4Command(Base):
    """Queue for the MT4 Expert Advisor that polls /api/mt4/bridge."""

    __tablename__ = "mt4_commands"
    __table_args__ = (Index("ix_mt4_commands_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, default="EURUSD")
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="BUY")
    lots: Mapped[float] = mapped_column(Float, nullable=False, default=0.01)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    magic: Mapped[int] = mapped_column(Integer, nullable=False, default=212100)
    comment: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    ticket: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    requested_entry: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}
        if url.startswith("sqlite"):
            db_path = url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            with _engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA foreign_keys=ON"))
                conn.commit()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=True, expire_on_commit=False)
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _migrate_trade_source(engine: Engine) -> None:
    """Add trades.source on existing SQLite/Postgres books and tag adopted fills as human."""
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(trades)")).fetchall()}
            if "source" not in cols:
                conn.execute(text("ALTER TABLE trades ADD COLUMN source VARCHAR(16) DEFAULT 'bot'"))
        elif dialect in {"postgresql", "postgres"}:
            conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS source VARCHAR(16) DEFAULT 'bot'"))
        conn.execute(
            text(
                "UPDATE trades SET source = 'human' "
                "WHERE signal_id IS NULL AND COALESCE(units, 0) < 50 "
                "AND COALESCE(source, 'bot') = 'bot'"
            )
        )
        conn.execute(
            text(
                "UPDATE trades SET source = 'bot' "
                "WHERE COALESCE(source, '') = 'human' AND COALESCE(units, 0) >= 50 "
                "AND signal_id IS NULL"
            )
        )


def _add_column(conn, dialect: str, table: str, column: str, decl: str) -> None:
    if dialect == "sqlite":
        cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
        if column not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {decl}"))
    elif dialect in {"postgresql", "postgres"}:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {decl}"))


def _migrate_signal_memory(engine: Engine) -> None:
    dialect = engine.dialect.name
    signal_cols = {
        "signal_type": "VARCHAR(64) DEFAULT 'hold'",
        "fingerprint": "VARCHAR(128) DEFAULT ''",
        "htf_bias": "VARCHAR(16) DEFAULT 'neutral'",
        "d1_bias": "VARCHAR(16) DEFAULT 'neutral'",
        "rsi": "FLOAT",
        "atr": "FLOAT",
        "ema_fast": "FLOAT",
        "ema_slow": "FLOAT",
        "macd": "FLOAT",
        "stoch_k": "FLOAT",
        "adx": "FLOAT",
        "cci": "FLOAT",
        "source": "VARCHAR(16) DEFAULT 'live'",
    }
    indicator_cols = {
        "macd": "FLOAT",
        "macd_signal": "FLOAT",
        "macd_hist": "FLOAT",
        "stoch_k": "FLOAT",
        "stoch_d": "FLOAT",
        "adx": "FLOAT",
        "plus_di": "FLOAT",
        "minus_di": "FLOAT",
        "cci": "FLOAT",
        "trend": "INTEGER",
    }
    with engine.begin() as conn:
        for name, decl in signal_cols.items():
            _add_column(conn, dialect, "signals", name, decl)
        for name, decl in indicator_cols.items():
            _add_column(conn, dialect, "indicators", name, decl)


def _migrate_journal_mistakes(engine: Engine) -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        _add_column(conn, dialect, "trade_journals", "mistakes", "JSON")


def _migrate_trade_venue(engine: Engine) -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        _add_column(conn, dialect, "trades", "venue", "VARCHAR(16) DEFAULT 'oanda'")
        _add_column(conn, dialect, "trades", "parent_trade_id", "INTEGER")
        conn.execute(text("UPDATE trades SET venue = 'oanda' WHERE COALESCE(venue, '') = ''"))


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    try:
        _migrate_trade_source(engine)
    except Exception as exc:
        logger.warning("Trade source migration skipped: {}", exc)
    try:
        _migrate_signal_memory(engine)
    except Exception as exc:
        logger.warning("Signal memory migration skipped: {}", exc)
    try:
        _migrate_journal_mistakes(engine)
    except Exception as exc:
        logger.warning("Journal mistakes migration skipped: {}", exc)
    try:
        _migrate_trade_venue(engine)
    except Exception as exc:
        logger.warning("Trade venue migration skipped: {}", exc)
    logger.info("Database schema ready ({})", get_settings().database_url.split("://")[0])


def reset_engine() -> None:
    """Used by tests to re-bind against a fresh database."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    get_settings.cache_clear()


def _as_float(value: Any) -> float:
    return float(value)


def upsert_bars(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    """Insert or update OHLCV bars keyed by (symbol, timeframe, ts)."""
    if not rows:
        return 0
    count = 0
    for row in rows:
        existing = session.scalar(
            select(Bar).where(
                Bar.symbol == row["symbol"],
                Bar.timeframe == row["timeframe"],
                Bar.ts == row["ts"],
            )
        )
        if existing is None:
            session.add(Bar(**row))
            count += 1
        else:
            for key, value in row.items():
                setattr(existing, key, value)
            count += 1
    session.flush()
    return count


def upsert_bars_fast(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    """Bulk insert-or-replace bars. Prefer this for historical dumps."""
    if not rows:
        return 0
    now = _utcnow()
    payload = []
    for row in rows:
        item = dict(row)
        item.setdefault("created_at", now)
        item.setdefault("volume", 0.0)
        item.setdefault("source", "forexsb")
        item.setdefault("complete", True)
        payload.append(item)
    session.execute(
        text(
            """
            INSERT INTO bars (symbol, timeframe, ts, open, high, low, close, volume, source, complete, created_at)
            VALUES (:symbol, :timeframe, :ts, :open, :high, :low, :close, :volume, :source, :complete, :created_at)
            ON CONFLICT(symbol, timeframe, ts) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                source=excluded.source,
                complete=excluded.complete
            """
        ),
        payload,
    )
    session.flush()
    return len(payload)


def upsert_indicators(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    if not rows:
        return 0
    count = 0
    for row in rows:
        existing = session.scalar(
            select(IndicatorRow).where(
                IndicatorRow.symbol == row["symbol"],
                IndicatorRow.timeframe == row["timeframe"],
                IndicatorRow.ts == row["ts"],
            )
        )
        if existing is None:
            session.add(IndicatorRow(**row))
            count += 1
        else:
            for key, value in row.items():
                setattr(existing, key, value)
            count += 1
    session.flush()
    return count


def replace_setup_memory(session: Session, rows: Sequence[dict[str, Any]], *, symbol: str = "EUR/USD") -> int:
    session.execute(text("DELETE FROM setup_memory WHERE symbol = :symbol"), {"symbol": symbol})
    for row in rows:
        session.add(SetupMemory(**row))
    session.flush()
    return len(rows)


def list_setup_memory(session: Session, symbol: str = "EUR/USD") -> list[SetupMemory]:
    return list(
        session.scalars(
            select(SetupMemory)
            .where(SetupMemory.symbol == symbol)
            .order_by(SetupMemory.expectancy_pips.desc())
        )
    )


def insert_signal(session: Session, payload: dict[str, Any]) -> SignalRow:
    """One live row per symbol/timeframe/bar. Repeat cycles update it instead of cloning HOLDs."""
    if payload.get("source", "live") == "live" and payload.get("decision_context"):
        from src.analysis.evidence import json_safe
        session.add(DecisionObservation(symbol=payload["symbol"], payload=json_safe(payload)))
    allowed = {column.key for column in SignalRow.__table__.columns if column.key != "id"}
    data = {key: value for key, value in payload.items() if key in allowed}
    ts = data.get("ts")
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    if ts is not None and symbol and timeframe:
        existing = session.scalar(
            select(SignalRow)
            .where(
                SignalRow.symbol == symbol,
                SignalRow.timeframe == timeframe,
                SignalRow.ts == ts,
                SignalRow.source == (data.get("source") or "live"),
            )
            .order_by(SignalRow.id.desc())
        )
        if existing is not None:
            for key, value in data.items():
                setattr(existing, key, value)
            session.flush()
            return existing
    row = SignalRow(**data)
    session.add(row)
    session.flush()
    return row


def purge_mislabelled_history_signals(session: Session) -> int:
    """Drop replay rows that were stored as live and polluted the hub tape."""
    result = session.execute(
        text(
            "DELETE FROM signals WHERE skip_reason = 'historical_replay' "
            "AND COALESCE(source, 'live') = 'live'"
        )
    )
    return int(result.rowcount or 0)


def insert_trade(session: Session, payload: dict[str, Any]) -> Trade:
    allowed = {column.key for column in Trade.__table__.columns if column.key != "id"}
    data = {key: value for key, value in payload.items() if key in allowed}
    data.setdefault("venue", "oanda")
    row = Trade(**data)
    session.add(row)
    session.flush()
    return row


def insert_mt4_command(session: Session, payload: dict[str, Any]) -> Mt4Command:
    allowed = {column.key for column in Mt4Command.__table__.columns if column.key != "id"}
    data = {key: value for key, value in payload.items() if key in allowed}
    row = Mt4Command(**data)
    session.add(row)
    session.flush()
    return row


def list_pending_mt4_commands(session: Session, limit: int = 8) -> list[Mt4Command]:
    stmt = (
        select(Mt4Command)
        .where(Mt4Command.status == "pending")
        .order_by(Mt4Command.id.asc())
        .limit(max(1, int(limit or 8)))
    )
    return list(session.scalars(stmt))


def get_mt4_sibling(session: Session, trade: Trade) -> Trade | None:
    """Find the open MT4 copy of an OANDA desk ticket."""
    venue = str(getattr(trade, "venue", "oanda") or "oanda")
    if venue == "mt4":
        return None
    tid = getattr(trade, "id", None)
    if tid:
        found = session.scalar(
            select(Trade).where(
                Trade.parent_trade_id == int(tid),
                Trade.venue == "mt4",
                Trade.status.in_(["open", "partial"]),
            )
        )
        if found is not None:
            return found
    signal_id = getattr(trade, "signal_id", None)
    if signal_id:
        return session.scalar(
            select(Trade).where(
                Trade.signal_id == int(signal_id),
                Trade.venue == "mt4",
                Trade.status.in_(["open", "partial"]),
                Trade.id != int(tid or 0),
            )
        )
    return None


def get_open_trades(session: Session, symbol: str | None = None) -> list[Trade]:
    stmt = select(Trade).where(Trade.status.in_(["open", "partial"]))
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol)
    return list(session.scalars(stmt.order_by(Trade.opened_at.desc())))


def get_recent_signals(
    session: Session, limit: int = 50, *, source: str | None = "live"
) -> list[SignalRow]:
    stmt = select(SignalRow)
    if source:
        stmt = stmt.where(SignalRow.source == source)
    stmt = stmt.order_by(SignalRow.ts.desc()).limit(limit)
    return list(session.scalars(stmt))


def get_recent_trades(session: Session, limit: int = 50) -> list[Trade]:
    stmt = select(Trade).order_by(Trade.created_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def get_recent_notifications(session: Session, limit: int = 30) -> list[NotificationLog]:
    stmt = select(NotificationLog).order_by(NotificationLog.ts.desc()).limit(limit)
    return list(session.scalars(stmt))


def load_bars(
    session: Session,
    symbol: str,
    timeframe: str,
    limit: int = 300,
) -> list[Bar]:
    stmt = (
        select(Bar)
        .where(Bar.symbol == symbol, Bar.timeframe == timeframe)
        .order_by(Bar.ts.desc())
        .limit(limit)
    )
    rows = list(session.scalars(stmt))
    rows.reverse()
    return rows


def latest_bar(session: Session, symbol: str, timeframe: str) -> Bar | None:
    stmt = (
        select(Bar)
        .where(Bar.symbol == symbol, Bar.timeframe == timeframe)
        .order_by(Bar.ts.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def latest_snapshot(session: Session) -> AccountSnapshot | None:
    return session.scalar(select(AccountSnapshot).order_by(AccountSnapshot.ts.desc()).limit(1))


def get_or_create_daily_pnl(session: Session, day: date, starting_balance: float) -> DailyPnL:
    row = session.scalar(select(DailyPnL).where(DailyPnL.day == day))
    if row is None:
        row = DailyPnL(day=day, starting_balance=starting_balance)
        session.add(row)
        session.flush()
    return row


def peak_nav(session: Session, fallback: float) -> float:
    row = session.scalar(select(AccountSnapshot).order_by(AccountSnapshot.nav.desc()).limit(1))
    if row is None:
        return fallback
    return _as_float(row.nav)


def latest_pipeline_run(session: Session) -> PipelineRun | None:
    return session.scalar(select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(1))


def get_journal_for_trade(session: Session, trade_id: int) -> TradeJournal | None:
    return session.scalar(select(TradeJournal).where(TradeJournal.trade_id == trade_id))


def get_recent_journals(session: Session, limit: int = 30) -> list[TradeJournal]:
    stmt = select(TradeJournal).order_by(TradeJournal.updated_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def get_learned_rule(session: Session, fingerprint: str) -> LearnedRule | None:
    return session.scalar(select(LearnedRule).where(LearnedRule.fingerprint == fingerprint))


def get_active_learned_rules(session: Session) -> list[LearnedRule]:
    stmt = select(LearnedRule).where(LearnedRule.active.is_(True)).order_by(LearnedRule.updated_at.desc())
    return list(session.scalars(stmt))


def get_desk_note(session: Session, day: date, kind: str) -> DeskNote | None:
    return session.scalar(select(DeskNote).where(DeskNote.day == day, DeskNote.kind == kind))


def get_recent_desk_notes(session: Session, limit: int = 20) -> list[DeskNote]:
    stmt = select(DeskNote).order_by(DeskNote.day.desc(), DeskNote.kind.asc()).limit(limit)
    return list(session.scalars(stmt))


def insert_tape_note(session: Session, payload: dict[str, Any]) -> TapeNote:
    row = TapeNote(**payload)
    session.add(row)
    session.flush()
    return row


def get_recent_tape_notes(session: Session, limit: int = 20) -> list[TapeNote]:
    stmt = select(TapeNote).order_by(TapeNote.ts.desc()).limit(limit)
    return list(session.scalars(stmt))


def get_undelivered_notifications(session: Session, limit: int = 12) -> list[NotificationLog]:
    stmt = (
        select(NotificationLog)
        .where(NotificationLog.delivered.is_(False))
        .order_by(NotificationLog.ts.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def closed_realized_today(session: Session, day: date) -> float:
    """Sum primary OANDA bot closes on ``day`` (UTC), excluding mirror accounts."""
    rows = session.scalars(
        select(Trade).where(
            Trade.status == "closed",
            Trade.closed_at.is_not(None),
            Trade.source == "bot",
            Trade.venue == "oanda",
            Trade.parent_trade_id.is_(None),
        )
    )
    total = 0.0
    for trade in rows:
        if str(getattr(trade, "source", "bot") or "bot") == "human":
            continue
        closed = trade.closed_at
        if closed is None:
            continue
        if closed.tzinfo is None:
            closed = closed.replace(tzinfo=timezone.utc)
        if closed.astimezone(timezone.utc).date() != day:
            continue
        total += _as_float(trade.realized_pl)
    return total
