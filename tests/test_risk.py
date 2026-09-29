from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.execution.paper_broker import PaperBroker
from src.execution.risk_manager import AccountState, RiskManager, pick_risk_fraction


class _EmptySession:
    def scalars(self, *_args, **_kwargs):  # pragma: no cover - protocol stub
        return []

    def scalar(self, *_args, **_kwargs):
        return None

    def get(self, *_args, **_kwargs):
        return None


def test_size_respects_risk_and_cap() -> None:
    settings = Settings(risk_per_trade_pct=0.01, max_units_per_trade=100_000)
    mgr = RiskManager(settings)
    account = AccountState(
        balance=100_000,
        nav=100_000,
        unrealized_pl=0,
        realized_pl=0,
        margin_used=0,
        margin_available=100_000,
        open_trade_count=0,
    )
    # 15 pips on EURUSD → 0.0015 USD per unit. $1000 risk → 666_666 units, capped.
    units, risk, pips = mgr.size_position(
        symbol="EUR/USD",
        side="BUY",
        entry=1.10000,
        stop_loss=1.09850,
        account=account,
        quote_to_usd=1.0,
    )
    assert risk == pytest.approx(150.0)
    assert abs(pips - 15) < 0.01
    assert units == 100_000


def test_jpy_conversion() -> None:
    settings = Settings(risk_per_trade_pct=0.01, max_units_per_trade=1_000_000)
    mgr = RiskManager(settings)
    account = AccountState(100_000, 100_000, 0, 0, 0, 100_000, 0)
    # USD/JPY stop 0.15 JPY, quote_to_usd = 1/150.
    units, _, pips = mgr.size_position(
        symbol="USD/JPY",
        side="BUY",
        entry=150.00,
        stop_loss=149.85,
        account=account,
        quote_to_usd=1 / 150.00,
    )
    assert abs(pips - 15) < 0.01
    assert units > 0


def test_blocks_when_trading_disabled() -> None:
    mgr = RiskManager(Settings(enable_trading=False))
    account = AccountState(100_000, 100_000, 0, 0, 0, 100_000, 0)
    decision = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="BUY",
        entry=1.1,
        stop_loss=1.098,
        account=account,
        instrument_tradeable=True,
    )
    assert decision.allowed is False
    assert "disabled" in decision.reason.lower()


def test_blocks_closed_market() -> None:
    mgr = RiskManager(Settings(enable_trading=True))
    account = AccountState(100_000, 100_000, 0, 0, 0, 100_000, 0)
    decision = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="BUY",
        entry=1.1,
        stop_loss=1.098,
        account=account,
        instrument_tradeable=False,
        today=date(2026, 9, 16),
    )
    assert decision.allowed is False


def test_min_stop_allows_float_rounding() -> None:
    mgr = RiskManager(Settings(enable_trading=True, min_stop_pips=2.0))
    account = AccountState(100_000, 100_000, 0, 0, 0, 100_000, 0)
    decision = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="SELL",
        entry=1.15441,
        stop_loss=1.15461,
        account=account,
        instrument_tradeable=True,
        today=date(2026, 9, 16),
    )
    assert decision.allowed is True


def test_min_stop_pips_is_configurable() -> None:
    mgr = RiskManager(Settings(enable_trading=True, min_stop_pips=3.0))
    account = AccountState(100_000, 100_000, 0, 0, 0, 100_000, 0)
    decision = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="BUY",
        entry=1.10000,
        stop_loss=1.09980,
        account=account,
        instrument_tradeable=True,
        today=date(2026, 9, 16),
    )
    assert decision.allowed is False
    assert "3.0-pip" in decision.reason


def test_protect_from_fill_uses_min_stop() -> None:
    broker = PaperBroker.__new__(PaperBroker)
    broker.settings = Settings(min_stop_pips=5.0, atr_sl_multiplier=1.5, atr_tp1_multiplier=2.0)
    sl, tp = broker._protect_from_fill(
        symbol="EUR/USD",
        side="SELL",
        fill_price=1.15440,
        requested_entry=1.15441,
        stop_loss=1.15461,
        take_profit=1.15390,
    )
    assert sl >= 1.15440 + 0.0005 - 1e-9
    assert tp < 1.15440


def _account(nav: float = 100_000) -> AccountState:
    return AccountState(nav, nav, 0, 0, 0, nav, 0)


def _open_sell(*, source: str = "bot", fill: float = 1.15400, stop: float = 1.15480, units: int = 50_000):
    return SimpleNamespace(
        symbol="EUR/USD",
        side="SELL",
        source=source,
        status="open",
        fill_price=fill,
        requested_entry=fill,
        stop_loss=stop,
        remaining_units=units,
        units=units,
    )


def test_conviction_sizes_up_when_h1_agrees() -> None:
    settings = Settings(risk_per_trade_pct=0.01, conviction_risk_pct=0.015, max_units_per_trade=10_000_000)
    pct, mode = pick_risk_fraction(
        settings, strength=80, htf_aligned=True, growth_action="prefer", adding_to_winner=False
    )
    assert mode == "conviction"
    assert pct == 0.015
    mgr = RiskManager(settings)
    account = _account()
    conviction = mgr.size_position(
        symbol="EUR/USD",
        side="SELL",
        entry=1.10000,
        stop_loss=1.10500,
        account=account,
        quote_to_usd=1.0,
        risk_pct=0.015,
    )
    base = mgr.size_position(
        symbol="EUR/USD",
        side="SELL",
        entry=1.10000,
        stop_loss=1.10500,
        account=account,
        quote_to_usd=1.0,
        risk_pct=0.01,
    )
    assert conviction[1] == pytest.approx(1500.0, abs=0.005)
    assert base[1] == pytest.approx(1000.0, abs=0.005)
    assert conviction[0] > base[0]


def test_operator_ticket_does_not_consume_desk_capacity(monkeypatch) -> None:
    human = _open_sell(source="human", units=1, fill=1.14670, stop=1.14720)
    monkeypatch.setattr("src.execution.risk_manager.get_open_trades", lambda session, symbol=None: [human])
    mgr = RiskManager(Settings(enable_trading=True, max_open_positions=3, min_stop_pips=5.0))
    decision = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="SELL",
        entry=1.15440,
        stop_loss=1.15520,
        account=_account(),
        instrument_tradeable=True,
        today=date(2026, 9, 17),
        mark=1.15410,
        strength=72,
        htf_aligned=True,
        growth_action="prefer",
    )
    assert decision.allowed is True
    assert decision.size_mode == "conviction"


def test_mt4_copy_does_not_consume_desk_capacity(monkeypatch) -> None:
    copy = _open_sell(source="bot", units=100_000, fill=1.15480, stop=1.15560)
    copy.venue = "mt4"
    monkeypatch.setattr("src.execution.risk_manager.get_open_trades", lambda session, symbol=None: [copy])
    mgr = RiskManager(Settings(enable_trading=True, max_open_positions=1, min_stop_pips=5.0))
    decision = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="SELL",
        entry=1.15440,
        stop_loss=1.15520,
        account=_account(),
        instrument_tradeable=True,
        today=date(2026, 9, 17),
        mark=1.15410,
        strength=72,
        htf_aligned=True,
        growth_action="prefer",
    )
    assert decision.allowed is True


def test_addon_only_when_same_side_is_paying(monkeypatch) -> None:
    winner = _open_sell(units=40_000, fill=1.15480, stop=1.15560)
    monkeypatch.setattr("src.execution.risk_manager.get_open_trades", lambda session, symbol=None: [winner])
    settings = Settings(
        enable_trading=True,
        max_open_positions=3,
        max_same_side_positions=2,
        max_units_per_trade=10_000_000,
        min_stop_pips=5.0,
    )
    mgr = RiskManager(settings)
    paying = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="SELL",
        entry=1.15400,
        stop_loss=1.15480,
        account=_account(),
        instrument_tradeable=True,
        today=date(2026, 9, 17),
        mark=1.15420,
        strength=70,
        htf_aligned=True,
        growth_action="prefer",
    )
    assert paying.allowed is True
    assert paying.size_mode == "add-on"
    assert abs(paying.risk_pct - 0.004) < 1e-9

    scratch = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="SELL",
        entry=1.15400,
        stop_loss=1.15480,
        account=_account(),
        instrument_tradeable=True,
        today=date(2026, 9, 17),
        mark=1.15470,
        strength=70,
        htf_aligned=True,
        growth_action="prefer",
    )
    assert scratch.allowed is False
    assert "underwater" in scratch.reason.lower() or "2.0 pips" in scratch.reason

    underwater = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="SELL",
        entry=1.15400,
        stop_loss=1.15480,
        account=_account(),
        instrument_tradeable=True,
        today=date(2026, 9, 17),
        mark=1.15510,
        strength=70,
        htf_aligned=True,
        growth_action="prefer",
    )
    assert underwater.allowed is False
    assert "underwater" in underwater.reason.lower()


def test_caps_same_side_and_allows_opposite_hedge(monkeypatch) -> None:
    first = _open_sell(units=40_000, fill=1.15480, stop=1.15560)
    second = _open_sell(units=20_000, fill=1.15450, stop=1.15530)
    monkeypatch.setattr(
        "src.execution.risk_manager.get_open_trades", lambda session, symbol=None: [first, second]
    )
    mgr = RiskManager(
        Settings(
            enable_trading=True,
            max_open_positions=3,
            max_same_side_positions=2,
            min_stop_pips=5.0,
            max_units_per_trade=10_000_000,
        )
    )
    blocked = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="SELL",
        entry=1.15400,
        stop_loss=1.15480,
        account=_account(),
        instrument_tradeable=True,
        today=date(2026, 9, 17),
        mark=1.15410,
        strength=80,
        htf_aligned=True,
        growth_action="prefer",
    )
    assert blocked.allowed is False
    assert "same-side" in blocked.reason.lower()

    fade = mgr.evaluate(
        session=_EmptySession(),
        symbol="EUR/USD",
        side="BUY",
        entry=1.15400,
        stop_loss=1.15320,
        account=_account(),
        instrument_tradeable=True,
        today=date(2026, 9, 17),
        mark=1.15410,
        strength=88,
        htf_aligned=False,
        growth_action="fade",
    )
    assert fade.allowed is True
    assert fade.size_mode == "fade"


def test_losing_day_cuts_size() -> None:
    settings = Settings(risk_per_trade_pct=0.01, fade_risk_pct=0.006, conviction_risk_pct=0.015)
    pct, mode = pick_risk_fraction(
        settings,
        strength=80,
        htf_aligned=True,
        growth_action="prefer",
        adding_to_winner=False,
        losing_day=True,
    )
    assert mode == "reduced"
    assert pct == 0.006


def test_loss_today_cuts_size_even_if_day_not_red(monkeypatch) -> None:
    """Anti-martingale: a real stop today reduces the next ticket even if net P/L is still small."""
    from datetime import datetime, timezone

    loss = SimpleNamespace(
        source="bot",
        status="closed",
        closed_at=datetime(2026, 9, 16, 11, 0, tzinfo=timezone.utc),
        opened_at=datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc),
        realized_pl=-50.0,
        side="SELL",
        symbol="EUR/USD",
    )

    class _LossSession:
        def scalars(self, *_args, **_kwargs):
            return [loss]

        def scalar(self, *_args, **_kwargs):
            return None

        def get(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("src.execution.risk_manager.get_open_trades", lambda session, symbol=None: [])
    monkeypatch.setattr("src.execution.risk_manager.closed_realized_today", lambda session, today: 0.0)
    monkeypatch.setattr("src.execution.risk_manager.peak_nav", lambda session, fallback=0: fallback)
    mgr = RiskManager(
        Settings(
            enable_trading=True,
            min_stop_pips=5.0,
            risk_per_trade_pct=0.006,
            conviction_risk_pct=0.009,
            fade_risk_pct=0.004,
            max_units_per_trade=10_000_000,
        )
    )
    decision = mgr.evaluate(
        session=_LossSession(),
        symbol="EUR/USD",
        side="SELL",
        entry=1.15400,
        stop_loss=1.15480,
        account=_account(),
        instrument_tradeable=True,
        today=date(2026, 9, 16),
        mark=1.15390,
        strength=80,
        htf_aligned=True,
        growth_action="prefer",
    )
    assert decision.allowed is True
    assert decision.size_mode == "reduced"
    assert abs(decision.risk_pct - 0.004) < 1e-9


def test_open_only_fill_policy() -> None:
    import inspect

    source = inspect.getsource(PaperBroker.place_market_order)
    assert '"positionFill": "OPEN_ONLY"' in source


@pytest.mark.parametrize('environment,enabled,allowed', [('practice',False,True),('practice',True,False),('live',False,False)])
@pytest.mark.parametrize('loss',[-1000.,-5000.])
def test_daily_loss_halts_can_only_be_disabled_for_practice(monkeypatch,environment,enabled,allowed,loss):
    monkeypatch.setattr('src.execution.risk_manager.get_open_trades',lambda *a,**kw:[])
    monkeypatch.setattr('src.execution.risk_manager.closed_realized_today',lambda *a:loss)
    monkeypatch.setattr('src.execution.risk_manager.peak_nav',lambda session,fallback:fallback)
    settings=Settings(_env_file=None,oanda_environment=environment,practice_daily_loss_halt_enabled=enabled,
        enable_trading=True,daily_loss_limit_pct=.03,daily_soft_halt_pct=.005,
        practice_sampling_enabled=False)
    result=RiskManager(settings).evaluate(session=_EmptySession(),symbol='EUR/USD',side='BUY',
        entry=1.1,stop_loss=1.099,account=AccountState(100000,100000,0,0,0,100000,0),
        instrument_tradeable=True,today=date(2026,9,29))
    assert result.allowed is allowed
    if not allowed: assert 'halt' in result.reason.lower() or 'daily loss limit' in result.reason.lower()
