from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.config import reload_settings
from src.data.storage import (
    init_db,
    insert_signal,
    load_bars,
    reset_engine,
    session_scope,
    upsert_bars,
)
from src.notifications.slack_bot import signal_blocks
from src.analysis.signals import TradeSignal


def test_upsert_and_signal_roundtrip(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    reload_settings()
    init_db()
    ts = datetime(2026, 9, 16, 1, 2, tzinfo=timezone.utc)
    with session_scope() as session:
        n = upsert_bars(
            session,
            [
                {
                    "symbol": "EUR/USD",
                    "timeframe": "M1",
                    "ts": ts,
                    "open": 1.1,
                    "high": 1.11,
                    "low": 1.09,
                    "close": 1.105,
                    "volume": 10,
                    "source": "test",
                    "complete": True,
                }
            ],
        )
        assert n == 1
        upsert_bars(
            session,
            [
                {
                    "symbol": "EUR/USD",
                    "timeframe": "M1",
                    "ts": ts,
                    "open": 1.1,
                    "high": 1.12,
                    "low": 1.09,
                    "close": 1.11,
                    "volume": 11,
                    "source": "test",
                    "complete": True,
                }
            ],
        )
        bars = load_bars(session, "EUR/USD", "M1", limit=10)
        assert len(bars) == 1
        assert float(bars[0].close) == 1.11
        row = insert_signal(
            session,
            {
                "ts": ts,
                "symbol": "EUR/USD",
                "timeframe": "M5",
                "action": "HOLD",
                "price": 1.11,
                "reason": "unit test",
                "skipped": True,
                "skip_reason": "no confluence",
            },
        )
        assert row.id is not None
        again = insert_signal(
            session,
            {
                "ts": ts,
                "symbol": "EUR/USD",
                "timeframe": "M5",
                "action": "SELL",
                "price": 1.12,
                "reason": "updated same bar",
                "skipped": False,
            },
        )
        assert again.id == row.id
        from sqlalchemy import select
        from src.data.storage import SignalRow

        rows = list(session.scalars(select(SignalRow).where(SignalRow.symbol == "EUR/USD")))
        assert len(rows) == 1
        assert rows[0].action == "SELL"
        assert rows[0].reason == "updated same bar"
    reset_engine()


def test_history_signals_do_not_clobber_live(tmp_path, monkeypatch) -> None:
    db = tmp_path / "hist-live.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    reload_settings()
    init_db()
    ts = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        live = insert_signal(
            session,
            {
                "ts": ts,
                "symbol": "EUR/USD",
                "timeframe": "M5",
                "action": "SELL",
                "price": 1.14871,
                "reason": "live fade",
                "source": "live",
            },
        )
        hist = insert_signal(
            session,
            {
                "ts": ts,
                "symbol": "EUR/USD",
                "timeframe": "M5",
                "action": "BUY",
                "price": 1.14000,
                "reason": "replay",
                "skipped": True,
                "skip_reason": "historical_replay",
                "source": "history",
            },
        )
        assert live.id != hist.id
        from src.data.storage import get_recent_signals, purge_mislabelled_history_signals, SignalRow
        from sqlalchemy import select

        overview = get_recent_signals(session, 10, source="live")
        assert len(overview) == 1
        assert overview[0].action == "SELL"
        assert overview[0].source == "live"
        pollute = insert_signal(
            session,
            {
                "ts": datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
                "symbol": "EUR/USD",
                "timeframe": "M5",
                "action": "HOLD",
                "price": 1.14,
                "reason": "old replay",
                "skipped": True,
                "skip_reason": "historical_replay",
                "source": "live",
            },
        )
        removed = purge_mislabelled_history_signals(session)
        assert removed == 1
        left = list(session.scalars(select(SignalRow)))
        ids = {row.id for row in left}
        assert live.id in ids
        assert hist.id in ids
        assert pollute.id not in ids
    reset_engine()


def test_resolves_forex_channel_by_name() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.joined = None

        def conversations_list(self, **_kwargs):
            return {
                "channels": [
                    {"id": "C111", "name": "general"},
                    {"id": "CFOREX99", "name": "forex"},
                ],
                "response_metadata": {},
            }

        def conversations_join(self, channel):
            self.joined = channel
            return {"ok": True}

    from src.config import Settings
    from src.notifications.slack_bot import SlackNotifier

    settings = Settings(slack_bot_token="xoxb-test", slack_channel="forex")
    n = SlackNotifier(settings)
    n._client = FakeClient()
    cid = n.resolve_channel()
    assert cid == "CFOREX99"
    assert n._client.joined == "CFOREX99"
    assert n.target_label.startswith("#forex")


def test_slack_blocks_include_risk_and_fill() -> None:
    signal = TradeSignal(
        symbol="EUR/USD",
        timeframe="M5",
        action="BUY",
        timestamp=datetime.now(timezone.utc),
        price=1.1535,
        entry=1.1535,
        stop_loss=1.1510,
        take_profit_1=1.1570,
        take_profit_2=1.1600,
        risk_reward=1.4,
        atr=0.0016,
        rsi=48.2,
        ema_fast=1.1532,
        ema_slow=1.1528,
        bb_upper=1.156,
        bb_mid=1.153,
        bb_lower=1.150,
        htf_bias="bullish",
        confluence=["EMA 9 above EMA 21", "RSI supports longs (48.2)"],
        reason="EMA 9 above EMA 21; RSI supports longs (48.2)",
        strength=72,
    )
    blocks = signal_blocks(signal, order_status="Demo Order Placed (#12345)", lot_size=10000)
    kinds = [b["type"] for b in blocks]
    assert "header" in kinds
    blob = str(blocks)
    assert "EUR/USD" in blob
    assert "Take Profit" in blob
    assert "Demo Order Placed (#12345)" in blob
    assert "10000" in blob


def test_closed_realized_today_counts_naive_bot_timestamps(tmp_path: Path, monkeypatch) -> None:
    from datetime import date

    from src.data.storage import closed_realized_today, insert_trade

    db = tmp_path / "pnl.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    reload_settings()
    init_db()
    with session_scope() as session:
        insert_trade(
            session,
            {
                "symbol": "EUR/USD",
                "side": "SELL",
                "units": 100000,
                "requested_entry": 1.14674,
                "fill_price": 1.14674,
                "stop_loss": 1.14755,
                "take_profit_1": 1.14575,
                "take_profit_2": 1.14490,
                "broker_take_profit": 1.14490,
                "status": "closed",
                "remaining_units": 0,
                "exit_price": 1.14755,
                "realized_pl": -81.5,
                "close_reason": "stop_loss",
                "source": "bot",
                "opened_at": datetime(2026, 9, 17, 8, 25),
                "closed_at": datetime(2026, 9, 17, 9, 2),
            },
        )
        insert_trade(
            session,
            {
                "symbol": "EUR/USD",
                "side": "BUY",
                "units": 1,
                "requested_entry": 1.1467,
                "fill_price": 1.1467,
                "stop_loss": 1.1450,
                "take_profit_1": 1.1480,
                "take_profit_2": 1.1490,
                "broker_take_profit": 1.1490,
                "status": "closed",
                "remaining_units": 0,
                "exit_price": 1.1467,
                "realized_pl": -400.0,
                "close_reason": "manual",
                "source": "human",
                "opened_at": datetime(2026, 9, 17, 10, 0),
                "closed_at": datetime(2026, 9, 17, 10, 5),
            },
        )
        # Mirrored account results must not change the OANDA daily risk budget,
        # whether they are losses or gains, or lack a parent link.
        for venue, parent_id, pnl in [("mt4", None, -500), ("mt4", 1, 900), ("oanda", 1, -250)]:
            insert_trade(session, {
                "symbol": "EUR/USD", "side": "SELL", "units": 100,
                "requested_entry": 1.1467, "fill_price": 1.1467,
                "stop_loss": 1.1475, "take_profit_1": 1.1457,
                "take_profit_2": 1.1449, "broker_take_profit": 1.1449,
                "status": "closed", "remaining_units": 0,
                "realized_pl": pnl, "source": "bot", "venue": venue,
                "parent_trade_id": parent_id,
                "opened_at": datetime(2026, 9, 17, 8, 25),
                "closed_at": datetime(2026, 9, 17, 9, 2),
            })
        assert closed_realized_today(session, date(2026, 9, 17)) == -81.5
        assert closed_realized_today(session, date(2026, 9, 16)) == 0.0
    reset_engine()
