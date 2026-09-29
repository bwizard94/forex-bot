from __future__ import annotations
import pytest

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.analysis.reflection import (
    backfill_missing_journals,
    build_entry_thesis,
    build_tape_reflection,
    fingerprint_from_signal,
    fingerprint_is_current,
    infer_close_reason,
    lesson_gate,
    make_fingerprint,
    record_entry,
    record_exit,
    rsi_bucket,
)
from src.analysis.signals import TradeSignal
from src.config import Settings, reload_settings
from src.data.storage import (
    TradeJournal,
    get_journal_for_trade,
    get_learned_rule,
    insert_trade,
    init_db,
    reset_engine,
    session_scope,
)
from src.notifications.slack_bot import journal_blocks, postmortem_blocks
from src.utils import utcnow


def _signal(**overrides) -> TradeSignal:
    base = dict(
        symbol="GBP/USD",
        timeframe="M5",
        action="SELL",
        timestamp=datetime.now(timezone.utc),
        price=1.34655,
        entry=1.34655,
        stop_loss=1.34800,
        take_profit_1=1.34460,
        take_profit_2=1.34290,
        risk_reward=1.33,
        atr=0.00097,
        rsi=62.4,
        ema_fast=1.34680,
        ema_slow=1.34710,
        bb_upper=1.34690,
        bb_mid=1.34580,
        bb_lower=1.34470,
        htf_bias="bearish",
        confluence=[
            "EMA 9 below EMA 21",
            "RSI supports shorts (62.4)",
            "Close at/over upper Bollinger band",
            "H1 trend bearish",
        ],
        reason="EMA 9 below EMA 21; RSI supports shorts (62.4); Close at/over upper Bollinger band",
        strength=67,
    )
    base.update(overrides)
    return TradeSignal(**base)  # type: ignore[arg-type]


def _db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'journal.db'}")
    reset_engine()
    reload_settings()
    init_db()


def test_rsi_buckets_and_fingerprint() -> None:
    assert rsi_bucket(31) == "oversold"
    assert rsi_bucket(62) == "overbought"
    fp, bucket, zone = make_fingerprint(
        "GBP/USD", "SELL", "bearish", 62.4, 1.34690, 1.34470, 1.34580, 1.34690
    )
    assert bucket == "overbought"
    assert zone == "upper_band"
    assert fp == "GBP/USD|SELL|bearish|rsi_overbought|bb_upper_band"
    sig = _signal()
    assert fingerprint_from_signal(sig) == fp


def test_entry_thesis_explains_sell() -> None:
    sig = _signal()

    class T:
        fill_price = 1.34655
        requested_entry = 1.34655
        stop_loss = 1.34800
        take_profit_1 = 1.34460
        take_profit_2 = 1.34290
        slippage_pips = 0.3
        units = 10000
        side = "SELL"

    text = build_entry_thesis(
        symbol="GBP/USD",
        side="SELL",
        signal=sig,
        trade=T(),  # type: ignore[arg-type]
        context={},
    )
    assert "I sold GBP/USD" in text
    assert "upper Bollinger" in text
    assert "bearish" in text


def test_buy_thesis_explains_buy() -> None:
    sig = _signal(
        action="BUY",
        symbol="EUR/USD",
        rsi=32.0,
        price=1.0800,
        bb_lower=1.0801,
        bb_mid=1.0820,
        bb_upper=1.0840,
        htf_bias="bullish",
        confluence=["RSI oversold (32.0)", "Close at/under lower Bollinger band", "H1 trend bullish"],
        reason="RSI oversold (32.0); Close at/under lower Bollinger band",
    )

    class T:
        fill_price = 1.0800
        requested_entry = 1.0800
        stop_loss = 1.0780
        take_profit_1 = 1.0830
        take_profit_2 = 1.0850
        slippage_pips = -0.1
        units = 8000
        side = "BUY"

    text = build_entry_thesis(
        symbol="EUR/USD",
        side="BUY",
        signal=sig,
        trade=T(),  # type: ignore[arg-type]
        context={},
    )
    assert "I bought EUR/USD" in text
    assert "oversold" in text.lower() or "RSI" in text


def test_loss_postmortem_and_skip_rule(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings(
        lesson_lookback_days=14,
        lesson_loss_high_strength=2,
        lesson_loss_skip=3,
        lesson_skip_hours=48,
        lesson_high_strength_min=70,
        lesson_scratch_usd=2.0,
        family_loss_skip=5,
        post_loss_cooldown_minutes=0,
        max_consecutive_losses=9,
    )
    sig = _signal()
    opened = utcnow() - timedelta(minutes=40)
    with session_scope() as session:
        journals = []
        for _ in range(3):
            trade = insert_trade(
                session,
                {
                    "symbol": "GBP/USD",
                    "side": "SELL",
                    "units": 10000,
                    "requested_entry": 1.34655,
                    "fill_price": 1.34655,
                    "stop_loss": 1.34800,
                    "take_profit_1": 1.34460,
                    "take_profit_2": 1.34290,
                    "broker_take_profit": 1.34290,
                    "status": "closed",
                    "remaining_units": 0,
                    "exit_price": 1.34805,
                    "realized_pl": -15.0,
                    "close_reason": "stop_loss",
                    "opened_at": opened,
                    "closed_at": utcnow(),
                },
            )
            record_entry(session, trade, sig)
            journal = record_exit(
                session,
                trade,
                exit_price=1.34805,
                realized_pl=-15.0,
                close_reason="stop_loss",
                settings=settings,
            )
            journals.append(journal)
        assert journals[0].outcome == "loss"
        assert journals[0].what_went_wrong
        assert "stop" in journals[0].what_went_wrong.lower()
        assert journals[0].how_to_avoid
        assert "Do not" in journals[0].how_to_avoid or "Require" in journals[0].how_to_avoid
        fp = journals[0].fingerprint
        weak = lesson_gate(session, fp, strength=50)
        assert weak.allowed is False
        assert weak.rule_action == "skip"
        still_skipped = lesson_gate(session, fp, strength=90)
        assert still_skipped.allowed is False
        blob = str(postmortem_blocks(journals[0]))
        assert "How to avoid" in blob
        assert "Why I sold" in str(journal_blocks(journals[0]))
        # Two losses is enough to demand high strength if we rewind — third already skipped.
        assert journals[1].outcome == "loss"
    reset_engine()


def test_two_losses_require_high_strength(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings(
        lesson_loss_high_strength=2,
        lesson_loss_skip=3,
        lesson_high_strength_min=70,
        lesson_scratch_usd=2.0,
        family_loss_skip=5,
        post_loss_cooldown_minutes=0,
        max_consecutive_losses=9,
    )
    sig = _signal()
    with session_scope() as session:
        for _ in range(2):
            trade = insert_trade(
                session,
                {
                    "symbol": "GBP/USD",
                    "side": "SELL",
                    "units": 10000,
                    "requested_entry": 1.34655,
                    "fill_price": 1.34655,
                    "stop_loss": 1.34800,
                    "take_profit_1": 1.34460,
                    "take_profit_2": 1.34290,
                    "broker_take_profit": 1.34290,
                    "status": "closed",
                    "remaining_units": 0,
                    "exit_price": 1.34805,
                    "realized_pl": -12.0,
                    "close_reason": "stop_loss",
                    "opened_at": utcnow(),
                    "closed_at": utcnow(),
                },
            )
            record_entry(session, trade, sig)
            record_exit(
                session,
                trade,
                exit_price=1.34805,
                realized_pl=-12.0,
                close_reason="stop_loss",
                settings=settings,
            )
        fp = fingerprint_from_signal(sig)
        blocked = lesson_gate(session, fp, strength=55)
        assert blocked.allowed is False
        allowed = lesson_gate(session, fp, strength=80)
        assert allowed.allowed is False
        assert allowed.rule_action == "skip"
    reset_engine()


def test_infer_stop_vs_target() -> None:
    class T:
        close_reason = None
        fill_price = 1.10000
        stop_loss = 1.09850
        take_profit_1 = 1.10200
        take_profit_2 = 1.10350
        side = "BUY"
        symbol = "EUR/USD"
        tp1_filled = False

    assert infer_close_reason(T(), 1.09848) == "stop_loss"  # type: ignore[arg-type]
    assert infer_close_reason(T(), 1.10348) == "take_profit"  # type: ignore[arg-type]


def test_default_lessons_skip_after_two_family_losses(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings()
    sig = _signal()
    with session_scope() as session:
        for i, rsi in enumerate((32.0, 70.0)):
            tweaked = _signal(rsi=rsi)
            trade = insert_trade(
                session,
                {
                    "symbol": "GBP/USD",
                    "side": "SELL",
                    "units": 10000,
                    "requested_entry": 1.34655,
                    "fill_price": 1.34655,
                    "stop_loss": 1.34800,
                    "take_profit_1": 1.34460,
                    "take_profit_2": 1.34290,
                    "broker_take_profit": 1.34290,
                    "status": "closed",
                    "remaining_units": 0,
                    "exit_price": 1.34805,
                    "realized_pl": -20.0,
                    "close_reason": "stop_loss",
                    "opened_at": utcnow(),
                    "closed_at": utcnow(),
                },
            )
            record_entry(session, trade, tweaked)
            record_exit(
                session,
                trade,
                exit_price=1.34805,
                realized_pl=-20.0,
                close_reason="stop_loss",
                settings=settings,
            )
        fp = fingerprint_from_signal(sig)
        weak = lesson_gate(session, fp, strength=50, settings=settings)
        assert weak.allowed is False
        strong = lesson_gate(session, fp, strength=90, settings=settings)
        assert strong.allowed is True
        book = None
        from src.data.storage import get_learned_rule

        book = get_learned_rule(session, "GBP/USD|SELL")
        assert book is not None
        assert book.action == "require_high_strength"
        assert "GBP/USD|SELL" in (book.lesson or "")
    reset_engine()


def test_outlier_win_does_not_keep_a_losing_streak_in_rotation(tmp_path: Path, monkeypatch) -> None:
    """One fat EUR/USD win and two small stops must sit the side out."""
    _db(tmp_path, monkeypatch)
    settings = Settings()
    sig = _signal(symbol="EUR/USD", action="SELL", htf_bias="bearish", rsi=70.0)
    with session_scope() as session:
        for pl, reason in ((775.0, "broker_closed"), (-13.5, "stop_loss"), (-47.0, "stop_loss")):
            trade = insert_trade(
                session,
                {
                    "symbol": "EUR/USD",
                    "side": "SELL",
                    "units": 100000,
                    "requested_entry": 1.15000,
                    "fill_price": 1.15000,
                    "stop_loss": 1.15051,
                    "take_profit_1": 1.14932,
                    "take_profit_2": 1.14821,
                    "broker_take_profit": 1.14821,
                    "status": "closed",
                    "remaining_units": 0,
                    "exit_price": 1.15051 if pl < 0 else 1.14225,
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
                exit_price=1.15051 if pl < 0 else 1.14225,
                realized_pl=pl,
                close_reason=reason,
                settings=settings,
            )
        from src.data.storage import get_learned_rule

        book = get_learned_rule(session, "EUR/USD|SELL")
        assert book is not None
        assert book.action == "require_high_strength"
        assert float(book.net_pl) > 0
        blocked = lesson_gate(session, fingerprint_from_signal(sig), strength=90, settings=settings)
        assert blocked.allowed is False
        assert blocked.rule_action == "skip"
    reset_engine()


def test_cooldown_blocks_revenge_entry(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings(
        lesson_loss_high_strength=9,
        lesson_loss_skip=9,
        family_loss_skip=9,
        post_loss_cooldown_minutes=45,
        max_consecutive_losses=9,
        lesson_scratch_usd=2.0,
    )
    sig = _signal(symbol="EUR/USD")
    with session_scope() as session:
        trade = insert_trade(
            session,
            {
                "symbol": "EUR/USD",
                "side": "SELL",
                "units": 10000,
                "requested_entry": 1.15400,
                "fill_price": 1.15400,
                "stop_loss": 1.15550,
                "take_profit_1": 1.15200,
                "take_profit_2": 1.15050,
                "broker_take_profit": 1.15050,
                "status": "closed",
                "remaining_units": 0,
                "exit_price": 1.15550,
                "realized_pl": -15.0,
                "close_reason": "stop_loss",
                "opened_at": utcnow(),
                "closed_at": utcnow(),
            },
        )
        record_entry(session, trade, sig)
        record_exit(
            session,
            trade,
            exit_price=1.15550,
            realized_pl=-15.0,
            close_reason="stop_loss",
            settings=settings,
        )
        blocked = lesson_gate(
            session,
            fingerprint_from_signal(sig),
            strength=90,
            signal=sig,
            settings=settings,
        )
        assert blocked.allowed is False
        assert blocked.rule_action == "cooldown"
        assert "revenge" in blocked.reason.lower() or "cooldown" in blocked.reason.lower()
    reset_engine()


def test_reentry_pause_after_win(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings(
        lesson_loss_high_strength=9,
        lesson_loss_skip=9,
        family_loss_skip=9,
        post_loss_cooldown_minutes=0,
        reentry_cooldown_minutes=15,
        max_consecutive_losses=9,
        lesson_scratch_usd=2.0,
    )
    sig = _signal(symbol="EUR/USD", action="BUY", htf_bias="bullish", rsi=42.0)
    with session_scope() as session:
        trade = insert_trade(
            session,
            {
                "symbol": "EUR/USD",
                "side": "BUY",
                "units": 10000,
                "requested_entry": 1.15400,
                "fill_price": 1.15400,
                "stop_loss": 1.15250,
                "take_profit_1": 1.15600,
                "take_profit_2": 1.15750,
                "broker_take_profit": 1.15750,
                "status": "closed",
                "remaining_units": 0,
                "exit_price": 1.15600,
                "realized_pl": 20.0,
                "close_reason": "take_profit_1",
                "opened_at": utcnow(),
                "closed_at": utcnow(),
            },
        )
        record_entry(session, trade, sig)
        record_exit(
            session,
            trade,
            exit_price=1.15600,
            realized_pl=20.0,
            close_reason="take_profit_1",
            settings=settings,
        )
        blocked = lesson_gate(
            session,
            fingerprint_from_signal(sig),
            strength=90,
            signal=sig,
            settings=settings,
        )
        assert blocked.allowed is False
        assert blocked.rule_action == "reentry_cooldown"
        assert "semi-frequent" in blocked.reason.lower() or "re-entry" in blocked.reason.lower()
    reset_engine()


def test_operator_scratch_does_not_pause_the_desk(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings(
        lesson_loss_high_strength=9,
        lesson_loss_skip=9,
        family_loss_skip=9,
        post_loss_cooldown_minutes=0,
        reentry_cooldown_minutes=15,
        max_consecutive_losses=9,
        lesson_scratch_usd=2.0,
    )
    sig = _signal(symbol="EUR/USD", action="SELL", htf_bias="bearish", rsi=70.0)
    with session_scope() as session:
        trade = insert_trade(
            session,
            {
                "symbol": "EUR/USD",
                "side": "BUY",
                "units": 1,
                "requested_entry": 1.14676,
                "fill_price": 1.14676,
                "stop_loss": 0.0,
                "take_profit_1": 0.0,
                "take_profit_2": 0.0,
                "broker_take_profit": 0.0,
                "status": "closed",
                "remaining_units": 0,
                "exit_price": 1.14665,
                "realized_pl": -0.0001,
                "close_reason": "take_profit_1",
                "source": "human",
                "opened_at": utcnow(),
                "closed_at": utcnow(),
            },
        )
        record_entry(session, trade, adopted=True)
        record_exit(
            session,
            trade,
            exit_price=1.14665,
            realized_pl=-0.0001,
            close_reason="take_profit_1",
            settings=settings,
        )
        gate = lesson_gate(
            session,
            fingerprint_from_signal(sig),
            strength=75,
            signal=sig,
            settings=settings,
        )
        assert gate.allowed is True
        assert gate.rule_action == "observe"
    reset_engine()


@pytest.mark.parametrize("environment,halt_enabled,expect_halt", [("practice",True,True),("practice",False,False),("live",False,True)])
def test_consecutive_losses_halt_until_session(tmp_path: Path, monkeypatch, environment, halt_enabled, expect_halt) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings(
        oanda_environment=environment,
        practice_daily_loss_halt_enabled=halt_enabled,
        lesson_loss_high_strength=9,
        lesson_loss_skip=9,
        family_loss_skip=9,
        post_loss_cooldown_minutes=0,
        max_consecutive_losses=2,
        trade_session_start_hour=7,
        lesson_scratch_usd=2.0,
    )
    sig = _signal(symbol="EUR/USD")
    with session_scope() as session:
        for _ in range(2):
            trade = insert_trade(
                session,
                {
                    "symbol": "EUR/USD",
                    "side": "SELL",
                    "units": 10000,
                    "requested_entry": 1.15400,
                    "fill_price": 1.15400,
                    "stop_loss": 1.15550,
                    "take_profit_1": 1.15200,
                    "take_profit_2": 1.15050,
                    "broker_take_profit": 1.15050,
                    "status": "closed",
                    "remaining_units": 0,
                    "exit_price": 1.15550,
                    "realized_pl": -18.0,
                    "close_reason": "stop_loss",
                    "opened_at": utcnow(),
                    "closed_at": utcnow(),
                },
            )
            record_entry(session, trade, sig)
            record_exit(
                session,
                trade,
                exit_price=1.15550,
                realized_pl=-18.0,
                close_reason="stop_loss",
                settings=settings,
            )
        blocked = lesson_gate(
            session,
            fingerprint_from_signal(sig),
            strength=90,
            signal=sig,
            settings=settings,
        )
        if expect_halt:
            assert blocked.allowed is False
            assert blocked.rule_action == "consecutive_halt"
            assert "London" in blocked.reason or "sit out" in blocked.reason.lower()
        else:
            # The daily/session halt is gone; independent learned-pattern gates remain.
            assert blocked.rule_action == "skip"
            assert "Consecutive-loss halt" not in blocked.reason
    reset_engine()


def test_gbp_losses_do_not_halt_eurusd(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings(
        lesson_loss_high_strength=9,
        lesson_loss_skip=9,
        family_loss_skip=9,
        post_loss_cooldown_minutes=0,
        max_consecutive_losses=2,
        trade_session_start_hour=7,
        lesson_scratch_usd=2.0,
    )
    gbp = _signal()
    eurusd = _signal(symbol="EUR/USD", action="BUY", htf_bias="bullish", rsi=32.0)
    with session_scope() as session:
        for _ in range(2):
            trade = insert_trade(
                session,
                {
                    "symbol": "GBP/USD",
                    "side": "SELL",
                    "units": 10000,
                    "requested_entry": 1.34655,
                    "fill_price": 1.34655,
                    "stop_loss": 1.34800,
                    "take_profit_1": 1.34460,
                    "take_profit_2": 1.34290,
                    "broker_take_profit": 1.34290,
                    "status": "closed",
                    "remaining_units": 0,
                    "exit_price": 1.34805,
                    "realized_pl": -18.0,
                    "close_reason": "stop_loss",
                    "opened_at": utcnow(),
                    "closed_at": utcnow(),
                },
            )
            record_entry(session, trade, gbp)
            record_exit(
                session,
                trade,
                exit_price=1.34805,
                realized_pl=-18.0,
                close_reason="stop_loss",
                settings=settings,
            )
        allowed = lesson_gate(
            session,
            fingerprint_from_signal(eurusd),
            strength=90,
            signal=eurusd,
            settings=settings,
        )
        assert allowed.allowed is True
    reset_engine()


def test_tape_explains_hold() -> None:
    sig = _signal(action="HOLD", reason="No confluence (bull=1 bear=1 need>=2)", strength=20)
    text = build_tape_reflection(sig)
    assert "not trading" in text.lower()
    assert "Tape:" in text
    skipped = build_tape_reflection(sig, skip_reason="Post-loss cooldown")
    assert "standing aside" in skipped


def test_fingerprint_is_current() -> None:
    assert fingerprint_is_current("GBP/USD|SELL|bearish|rsi_overbought|bb_upper_band")
    assert not fingerprint_is_current("GBP/USD|SELL|bearish|rsi_high|bb_upper_band")
    assert not fingerprint_is_current("GBP/USD|SELL|bearish|rsi_low|bb_lower")


def test_backfill_keeps_family_skip_active(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings()
    with session_scope() as session:
        for rsi in (32.0, 70.0):
            tweaked = _signal(rsi=rsi)
            trade = insert_trade(
                session,
                {
                    "symbol": "GBP/USD",
                    "side": "SELL",
                    "units": 10000,
                    "requested_entry": 1.34655,
                    "fill_price": 1.34655,
                    "stop_loss": 1.34800,
                    "take_profit_1": 1.34460,
                    "take_profit_2": 1.34290,
                    "broker_take_profit": 1.34290,
                    "status": "closed",
                    "remaining_units": 0,
                    "exit_price": 1.34805,
                    "realized_pl": -20.0,
                    "close_reason": "stop_loss",
                    "opened_at": utcnow(),
                    "closed_at": utcnow(),
                },
            )
            record_entry(session, trade, tweaked)
            record_exit(
                session,
                trade,
                exit_price=1.34805,
                realized_pl=-20.0,
                close_reason="stop_loss",
                settings=settings,
            )
        family = get_learned_rule(session, "GBP/USD|SELL|bearish")
        book = get_learned_rule(session, "GBP/USD|SELL")
        assert family is not None and family.action == "require_high_strength" and family.active
        assert book is not None and book.action == "require_high_strength" and book.active
        backfill_missing_journals(session, settings=settings)
        family = get_learned_rule(session, "GBP/USD|SELL|bearish")
        book = get_learned_rule(session, "GBP/USD|SELL")
        assert family is not None and family.active and family.action == "require_high_strength"
        assert book is not None and book.active and book.action == "require_high_strength"
    reset_engine()


def test_backfill_coarsens_rsi_high_fingerprint(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings()
    with session_scope() as session:
        trade = insert_trade(
            session,
            {
                "symbol": "GBP/USD",
                "side": "SELL",
                "units": 10000,
                "requested_entry": 1.34655,
                "fill_price": 1.34655,
                "stop_loss": 1.34800,
                "take_profit_1": 1.34460,
                "take_profit_2": 1.34290,
                "broker_take_profit": 1.34290,
                "status": "closed",
                "remaining_units": 0,
                "exit_price": 1.34805,
                "realized_pl": -20.0,
                "close_reason": "stop_loss",
                "opened_at": utcnow() - timedelta(minutes=30),
                "closed_at": utcnow(),
            },
        )
        session.add(
            TradeJournal(
                trade_id=trade.id,
                symbol="GBP/USD",
                side="SELL",
                fingerprint="GBP/USD|SELL|bearish|rsi_high|bb_upper",
                rsi_bucket="high",
                bb_zone="upper",
                htf_bias="bearish",
                outcome="loss",
                realized_pl=-20.0,
                close_reason="stop_loss",
                entry_thesis="I sold GBP/USD on an old granular snapshot.",
                entry_context={
                    "rsi": 62.4,
                    "price": 1.34690,
                    "bb_lower": 1.34470,
                    "bb_mid": 1.34580,
                    "bb_upper": 1.34690,
                    "htf_bias": "bearish",
                },
            )
        )
        session.flush()
        backfill_missing_journals(session, settings=settings)
        journal = get_journal_for_trade(session, trade.id)
        assert journal is not None
        assert fingerprint_is_current(journal.fingerprint)
        assert journal.fingerprint == "GBP/USD|SELL|bearish|rsi_overbought|bb_upper_band"
        family = get_learned_rule(session, "GBP/USD|SELL|bearish")
        assert family is not None and family.active
    reset_engine()


def test_operator_thesis_is_hands_off() -> None:
    class T:
        fill_price = 1.14670
        requested_entry = 1.14670
        stop_loss = 0.0
        take_profit_1 = 0.0
        take_profit_2 = 0.0
        slippage_pips = None
        units = 1
        side = "BUY"
        source = "human"

    text = build_entry_thesis(
        symbol="EUR/USD",
        side="BUY",
        signal=None,
        trade=T(),  # type: ignore[arg-type]
        context={"htf_bias": "bullish", "rsi": 38.0},
        adopted=True,
    )
    assert "operator opened" in text.lower()
    assert "will not scale, stop, or flatten" in text.lower()
    assert "adopting the fill" not in text


def test_teacher_win_becomes_a_copy_lesson() -> None:
    from src.analysis.reflection import build_postmortem

    class T:
        fill_price = 1.14670
        requested_entry = 1.14670
        stop_loss = 0.0
        take_profit_1 = 0.0
        take_profit_2 = 0.0
        side = "BUY"
        source = "human"
        symbol = "EUR/USD"
        opened_at = utcnow() - timedelta(minutes=25)
        closed_at = utcnow()

    class J:
        fingerprint = "EUR/USD|BUY|bullish|rsi_oversold|bb_lower_band"
        rsi_bucket = "oversold"
        bb_zone = "lower_band"
        htf_bias = "bullish"
        entry_context = {"rsi": 32.0}

    post = build_postmortem(
        trade=T(),  # type: ignore[arg-type]
        journal=J(),  # type: ignore[arg-type]
        exit_price=1.14820,
        realized_pl=1.50,
        close_reason="broker_closed",
        settings=Settings(lesson_scratch_usd=0.25),
    )
    assert post["outcome"] == "win"
    assert "Teacher win" in post["lesson"]
    assert "operator" in post["what_went_right"].lower()


def test_reflection_module_can_rebuild_a_signal() -> None:
    from src.analysis import reflection

    assert reflection.TradeSignal is not None
    row = type("Sig", (), {
        "symbol": "EUR/USD",
        "timeframe": "M5",
        "action": "SELL",
        "ts": datetime.now(timezone.utc),
        "price": 1.15,
        "entry": 1.15,
        "stop_loss": 1.151,
        "take_profit_1": 1.149,
        "take_profit_2": 1.148,
        "risk_reward": 1.2,
        "confluence": ["Ox scalp"],
        "reason": "test",
        "strength": 70,
    })()
    trade = type("Tr", (), {"side": "SELL"})()
    signal = reflection._signal_from_row(row, trade)
    assert signal.action == "SELL"
    assert signal.symbol == "EUR/USD"

