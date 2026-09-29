from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.analysis.mistakes import (
    TAXONOMY,
    averaging_down_reason,
    calendar_hold_reason,
    classify_closed_mistakes,
    cost_eats_stop,
    live_mistake_gate,
    session_is_open,
)
from src.analysis.signals import evaluate_signal
from src.config import Settings
from src.pipeline import is_sticky_skip


def _ohlc(n: int = 180, start: float = 1.05, drift: float = 0.00025) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = [start]
    for _ in range(n - 1):
        shock = float(rng.normal(drift, 0.00007))
        close.append(close[-1] + shock)
    close = np.array(close)
    high = close + 0.00025
    low = close - 0.00022
    open_ = np.r_[close[0], close[:-1]]
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 100}, index=idx)


def _settings(**kwargs) -> Settings:
    base = dict(
        trade_session_start_hour=0,
        trade_session_end_hour=22,
        friday_flat_hour=20,
        monday_open_skip_minutes=45,
        max_trades_per_day=8,
        max_fill_slippage_pips=1.5,
        slippage_cooloff_minutes=20,
        stale_quote_seconds=90,
        cost_stop_fraction=0.25,
        session_filter=True,
    )
    base.update(kwargs)
    return Settings(**base)


class _Session:
    def __init__(self, trades: list | None = None) -> None:
        self._trades = trades or []

    def scalars(self, *_args, **_kwargs):
        return list(self._trades)


def test_calendar_blocks_friday_close_sunday_and_monday_open() -> None:
    settings = _settings()
    friday_ok = datetime(2026, 9, 18, 19, 30, tzinfo=timezone.utc)
    friday_flat = datetime(2026, 9, 18, 20, 5, tzinfo=timezone.utc)
    saturday = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    sunday_reopen = datetime(2026, 9, 20, 21, 30, tzinfo=timezone.utc)
    monday_open = datetime(2026, 9, 21, 0, 10, tzinfo=timezone.utc)
    monday_later = datetime(2026, 9, 21, 0, 50, tzinfo=timezone.utc)
    wednesday = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

    assert session_is_open(friday_ok, settings)
    assert calendar_hold_reason(friday_flat, settings)
    assert "weekend" in (calendar_hold_reason(friday_flat, settings) or "").lower()
    assert calendar_hold_reason(saturday, settings)
    assert calendar_hold_reason(sunday_reopen, settings)
    assert "sunday" in (calendar_hold_reason(sunday_reopen, settings) or "").lower()
    assert calendar_hold_reason(monday_open, settings)
    assert "session-open" in (calendar_hold_reason(monday_open, settings) or "").lower()
    assert session_is_open(monday_later, settings)
    assert session_is_open(wednesday, settings)


def test_evaluate_signal_holds_weekend_gap() -> None:

    settings = Settings(
        min_confluence=2,
        min_rr_ratio=1.0,
        session_filter=True,
        require_htf_trend=False,
        trade_session_start_hour=0,
        trade_session_end_hour=22,
        friday_flat_hour=20,
        monday_open_skip_minutes=45,
    )
    bars = _ohlc(180, start=1.05, drift=0.00025)
    friday = evaluate_signal(
        "EUR/USD", "M5", bars, htf_bars=bars, settings=settings,
        now=datetime(2026, 9, 18, 20, 30, tzinfo=timezone.utc),
    )
    sunday = evaluate_signal(
        "EUR/USD", "M5", bars, htf_bars=bars, settings=settings,
        now=datetime(2026, 9, 20, 21, 15, tzinfo=timezone.utc),
    )
    monday = evaluate_signal(
        "EUR/USD", "M5", bars, htf_bars=bars, settings=settings,
        now=datetime(2026, 9, 21, 0, 12, tzinfo=timezone.utc),
    )
    assert friday.action == "HOLD"
    assert "weekend" in friday.reason.lower() or "friday" in friday.reason.lower()
    assert sunday.action == "HOLD"
    assert "weekend" in sunday.reason.lower() or "sunday" in sunday.reason.lower()
    assert monday.action == "HOLD"
    assert "session-open" in monday.reason.lower() or "monday" in monday.reason.lower()


def test_cost_and_stale_and_overtrading_gates() -> None:
    settings = _settings()
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    signal = SimpleNamespace(
        symbol="EUR/USD",
        action="SELL",
        entry=1.15000,
        price=1.15000,
        stop_loss=1.15050,
    )
    assert cost_eats_stop(1.8, 5.0, 0.25) is True
    assert cost_eats_stop(0.8, 5.0, 0.25) is False

    fat_spread = SimpleNamespace(
        spread=0.00018,
        ts=now,
        tradeable=True,
    )
    gate = live_mistake_gate(
        session=_Session(),
        signal=signal,
        quote=fat_spread,
        intel=None,
        settings=settings,
        now=now,
    )
    assert gate.allowed is False
    assert gate.code == "fees_slippage"
    assert "cost" in gate.reason.lower()

    stale = SimpleNamespace(spread=0.00008, ts=now - timedelta(seconds=200), tradeable=True)
    stale_gate = live_mistake_gate(
        session=_Session(),
        signal=signal,
        quote=stale,
        intel=None,
        settings=settings,
        now=now,
    )
    assert stale_gate.allowed is False
    assert stale_gate.code == "stale_quote"

    opened = [
        SimpleNamespace(
            source="bot",
            status="closed",
            opened_at=now - timedelta(hours=i),
            created_at=now,
            slippage_pips=0.2,
        )
        for i in range(8)
    ]
    over = live_mistake_gate(
        session=_Session(opened),
        signal=signal,
        quote=SimpleNamespace(spread=0.00008, ts=now, tradeable=True),
        intel=None,
        settings=settings,
        now=now,
    )
    assert over.allowed is False
    assert over.code == "overtrading"


def test_slippage_cooloff_after_fat_fill() -> None:
    settings = _settings()
    now = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    last = SimpleNamespace(
        source="bot",
        status="open",
        opened_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=3),
        slippage_pips=2.1,
    )
    signal = SimpleNamespace(
        symbol="EUR/USD", action="BUY", entry=1.15, price=1.15, stop_loss=1.14920
    )
    gate = live_mistake_gate(
        session=_Session([last]),
        signal=signal,
        quote=SimpleNamespace(spread=0.00008, ts=now, tradeable=True),
        intel=None,
        settings=settings,
        now=now,
    )
    assert gate.allowed is False
    assert gate.code == "fees_slippage"
    assert "slippage" in gate.reason.lower()


def test_averaging_down_is_named_anti_martingale() -> None:
    text = averaging_down_reason("SELL", 2.0)
    blob = text.lower()
    assert "anti-martingale" in blob
    assert "averaging down" in blob
    assert "grid" in blob
    assert is_sticky_skip(text)


def test_classify_loss_tags_chase_and_chop() -> None:
    settings = _settings()
    trade = SimpleNamespace(
        source="bot",
        side="BUY",
        close_reason="stop_loss",
        stop_loss=1.1480,
        slippage_pips=0.1,
        opened_at=datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc),
        realized_pl=-80,
    )
    journal = SimpleNamespace(
        outcome="loss",
        rsi_bucket="overbought",
        bb_zone="upper_band",
        hold_minutes=8,
        close_reason="stop_loss",
        entry_context={},
    )
    tags = classify_closed_mistakes(trade, journal, settings)
    assert "chasing" in tags
    assert "chop_stop" in tags
    assert set(tags) <= set(TAXONOMY)


def test_taxonomy_covers_bot_fail_codes() -> None:
    for code in (
        "overtrading",
        "weekend_gap",
        "session_open",
        "averaging_down",
        "fees_slippage",
        "stale_quote",
        "revenge",
        "overfitting",
        "unattended",
    ):
        assert code in TAXONOMY
