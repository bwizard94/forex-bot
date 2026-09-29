from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.analysis.growth import (
    growth_gate,
    preferred_side_from_intel,
    render_growth,
    study_book,
    widen_to_min_stop,
)
from src.analysis.reflection import record_entry, record_exit
from src.analysis.signals import TradeSignal
from src.config import Settings, reload_settings
from src.data.storage import init_db, insert_trade, reset_engine, session_scope
from src.utils import utcnow


def _signal(**overrides) -> TradeSignal:
    base = dict(
        symbol="EUR/USD",
        timeframe="M5",
        action="SELL",
        timestamp=datetime.now(timezone.utc),
        price=1.14659,
        entry=1.14659,
        stop_loss=1.14710,
        take_profit_1=1.14604,
        take_profit_2=1.14540,
        risk_reward=1.33,
        atr=0.00034,
        rsi=70.2,
        ema_fast=1.14680,
        ema_slow=1.14710,
        bb_upper=1.14690,
        bb_mid=1.14580,
        bb_lower=1.14470,
        htf_bias="bearish",
        d1_bias="bearish",
        confluence=["RSI overbought (70.2)", "Close at/over upper Bollinger band", "H1 trend bearish"],
        reason="RSI overbought",
        strength=75,
    )
    base.update(overrides)
    return TradeSignal(**base)  # type: ignore[arg-type]


def _db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'growth.db'}")
    reset_engine()
    reload_settings()
    init_db()


def test_widen_stop_lifts_five_pip_chop() -> None:
    sig = _signal()
    # 5.1 pips of room originally.
    out = widen_to_min_stop(sig, 8.0, Settings(min_stop_pips=5.0))
    assert out.stop_loss is not None and out.entry is not None
    from src.utils import price_to_pips

    assert price_to_pips("EUR/USD", abs(out.stop_loss - out.entry)) >= 7.9
    assert out.take_profit_2 < out.take_profit_1 < out.entry < out.stop_loss


def test_intel_alignment_prefers_shorts() -> None:
    intel = SimpleNamespace(h1_bias="bearish", d1_bias="bearish", stance="Primary hunt: EUR/USD shorts.")
    assert preferred_side_from_intel(intel) == "SELL"
    buy = _signal(action="BUY", stop_loss=1.14500, take_profit_1=1.14800, take_profit_2=1.14900)
    decision = growth_gate(buy, None, intel=intel, settings=Settings())
    assert decision.allowed is False
    assert "prefer SELL" in decision.reason


def test_study_keeps_the_winning_short_book(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings()
    sig = _signal()
    with session_scope() as session:
        fills = [
            (1.15437, 1.15488, 775.0, "broker_closed", "win"),
            (1.15439, 1.15461, -13.5, "stop_loss", "loss"),
            (1.14659, 1.14710, -47.0, "stop_loss", "loss"),
        ]
        for fill, sl, pl, reason, _outcome in fills:
            trade = insert_trade(
                session,
                {
                    "symbol": "EUR/USD",
                    "side": "SELL",
                    "units": 100000,
                    "requested_entry": fill,
                    "fill_price": fill,
                    "stop_loss": sl,
                    "take_profit_1": fill - 0.00055,
                    "take_profit_2": fill - 0.00120,
                    "broker_take_profit": fill - 0.00120,
                    "status": "closed",
                    "remaining_units": 0,
                    "exit_price": sl if pl < 0 else fill - 0.007,
                    "realized_pl": pl,
                    "close_reason": reason,
                    "source": "bot",
                    "opened_at": utcnow(),
                    "closed_at": utcnow(),
                },
            )
            record_entry(session, trade, sig)
            record_exit(
                session,
                trade,
                exit_price=sl if pl < 0 else fill - 0.007,
                realized_pl=pl,
                close_reason=reason,
                settings=settings,
            )
        report = study_book(session, symbol="EUR/USD", settings=settings)
        book = report.bucket("EUR/USD|SELL")
        assert book is not None
        assert book.net_pl > 700
        assert book.wins == 1
        assert book.losses == 2
        assert book.losing_streak >= 2
        assert book.median_pl < book.expectancy
        assert report.preferred_side is None
        md = render_growth(report)
        assert "Stand down" in md or "outlier" in md.lower()
        sell = _signal(rsi=52.0, strength=50)
        gate = growth_gate(sell, report, intel=SimpleNamespace(h1_bias="bearish", d1_bias="bearish", stance="shorts"), settings=settings)
        assert gate.allowed is False
        assert "stops" in gate.reason.lower() or "outlier" in gate.reason.lower()
        stretched = _signal(rsi=72.0, strength=88)
        retry = growth_gate(stretched, report, intel=SimpleNamespace(h1_bias="bearish", d1_bias="bearish", stance="shorts"), settings=settings)
        assert retry.allowed is True
        assert retry.action == "fade"
        buy = _signal(action="BUY", stop_loss=1.1450, take_profit_1=1.1480, take_profit_2=1.1490)
        blocked = growth_gate(buy, report, intel=SimpleNamespace(h1_bias="bearish", d1_bias="bearish", stance="shorts"), settings=settings)
        assert blocked.allowed is False
    reset_engine()
