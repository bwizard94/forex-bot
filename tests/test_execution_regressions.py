"""Offline regressions for ownership and risk sizing boundaries."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import Settings
from src.execution.risk_manager import AccountState, RiskManager
from src.execution.mt4 import MT4Broker
from src.pipeline import TradingPipeline
from src.execution.trade_guard import (
    SOURCE_HUMAN,
    classify_remote_trade,
    should_flatten_scalp,
)


@pytest.mark.parametrize("extension_key", ["clientExtensions", "tradeClientExtensions"])
def test_pair_tag_and_comment_do_not_grant_bot_ownership(extension_key):
    row = {extension_key: {"id": "operator-1", "tag": "EURUSD", "comment": "SELL EUR/USD"}}
    assert classify_remote_trade(row) == SOURCE_HUMAN


def test_unknown_ticket_is_not_time_stopped():
    now = datetime.now(timezone.utc)
    trade = SimpleNamespace(opened_at=now - timedelta(hours=3), signal_id=None)
    allowed, reason = should_flatten_scalp(trade, now=now, max_hold_minutes=90)
    assert not allowed
    assert "hands off" in reason


def test_cleanup_only_closes_stamped_off_watchlist_trades():
    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline.settings = Settings(_env_file=None)
    pipeline.broker = Mock()
    pipeline.broker.open_trades.return_value = [
        {"id": "human", "instrument": "GBP_USD"},
        {"id": "desk", "instrument": "GBP_USD", "clientExtensions": {"id": "fs-old"}},
        {"id": "eur", "instrument": "EUR_USD", "clientExtensions": {"id": "fs-eur"}},
    ]
    pipeline._flatten_off_watchlist()
    pipeline.broker.close_trade.assert_called_once_with("desk", units="ALL")


def test_sync_corrects_previously_misclassified_operator_ticket(monkeypatch):
    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline.broker = Mock()
    pipeline.broker.open_trades.return_value = [{"id": "manual", "instrument": "EUR_USD"}]
    pipeline._maybe_take_partial = Mock()
    pipeline._maybe_time_stop = Mock()
    pipeline._sync_mt4_trades = Mock()
    trade = SimpleNamespace(source="bot", venue="oanda", broker_trade_id="manual")
    monkeypatch.setattr("src.pipeline.session_scope", lambda: nullcontext(None))
    monkeypatch.setattr("src.pipeline.get_open_trades", lambda _: [trade])
    pipeline._sync_open_trades(_inputs()["account"])
    assert trade.source == SOURCE_HUMAN
    pipeline._maybe_take_partial.assert_not_called()
    pipeline._maybe_time_stop.assert_not_called()


@pytest.mark.parametrize("magic", [None, 0, 42])
def test_mt4_mapping_does_not_invent_desk_ownership(magic):
    broker = MT4Broker.__new__(MT4Broker)
    broker.settings = Settings(_env_file=None)
    row = broker._position_row({"id": "manual", "magic": magic, "volume": 0.01})
    assert row["magic"] == (magic or 0)
    assert classify_remote_trade(row) == SOURCE_HUMAN


def test_mt4_comment_cannot_override_operator_magic():
    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline.mt4 = Mock(magic=212100)
    pipeline.mt4.mode.return_value = "bridge"
    pipeline.mt4.open_trades.return_value = [
        {"id": "manual", "magic": 0, "comment": "fs-teacher"},
        {"id": "desk", "magic": 212100},
    ]
    pipeline._adopt_remote_trade = Mock()
    session = Mock()
    session.scalars.return_value = []
    pipeline._sync_mt4_trades(session, _inputs()["account"])
    sources = [call.kwargs["source"] for call in pipeline._adopt_remote_trade.call_args_list]
    assert sources == ["human", "bot"]


def test_metaapi_excludes_manual_and_other_ea_positions(monkeypatch):
    broker = MT4Broker.__new__(MT4Broker)
    broker.settings = Settings(_env_file=None)
    broker.mode = lambda: "metaapi"
    broker._client_root = lambda: "https://example.invalid"
    broker._headers = lambda: {}
    broker._last_open = []
    response = Mock(status_code=200, content=b"positions")
    response.json.return_value = [
        {"id": str(magic), "magic": magic, "volume": 0.01}
        for magic in (None, 0, 42, 212100)
    ]
    monkeypatch.setattr("src.execution.mt4.requests.get", lambda *a, **kw: response)
    assert [row["id"] for row in broker.open_trades()] == ["212100"]


def _inputs():
    return dict(
        symbol="EUR/USD", side="BUY", entry=1.1, stop_loss=1.099,
        account=AccountState(100_000, 100_000, 0, 0, 0, 100_000, 0),
        quote_to_usd=1.0,
    )


@pytest.mark.parametrize("override", [
    {"side": "HOLD"},
    {"stop_loss": 1.101},
    {"side": "SELL", "stop_loss": 1.099},
    {"stop_loss": 0.0},
    {"stop_loss": float("nan")},
    {"entry": float("inf")},
    {"quote_to_usd": float("nan")},
    {"quote_to_usd": 0.0},
    {"account": AccountState(100_000, float("nan"), 0, 0, 0, 100_000, 0)},
])
def test_invalid_risk_inputs_fail_closed(override):
    manager = RiskManager(Settings(_env_file=None, enable_trading=True))
    inputs = _inputs() | override
    assert manager.size_position(**inputs) == (0, 0.0, 0.0)
    # Must reject before querying storage or submitting an order.
    decision = manager.evaluate(session=None, instrument_tradeable=True, **inputs)
    assert not decision.allowed


def test_capped_order_fits_remaining_budget(monkeypatch):
    # $600 intended risk, but 100k units at a 10-pip stop risks only $100.
    # An existing $2,350 risk leaves $150: no scaling or rejection is needed.
    trade = SimpleNamespace(
        source="bot", venue="oanda", side="SELL", fill_price=1.1,
        stop_loss=1.1235, units=100_000, remaining_units=100_000,
    )
    monkeypatch.setattr("src.execution.risk_manager.get_open_trades", lambda _: [trade])
    monkeypatch.setattr("src.execution.risk_manager.peak_nav", lambda _, fallback: fallback)
    monkeypatch.setattr("src.execution.risk_manager.closed_realized_today", lambda *_: 0.0)
    monkeypatch.setattr("src.execution.risk_manager.had_bot_loss_on", lambda *a, **kw: False)
    manager = RiskManager(Settings(_env_file=None, enable_trading=True))
    decision = manager.evaluate(session=None, instrument_tradeable=True, **_inputs())
    assert decision.allowed
    assert decision.size_mode == "base"
    assert decision.units == 100_000
    assert decision.risk_amount == pytest.approx(100.0)


def test_scaled_risk_matches_integer_units(monkeypatch):
    trade = SimpleNamespace(
        source="bot", venue="oanda", side="SELL", fill_price=1.1,
        stop_loss=1.123, units=100_000, remaining_units=100_000,
    )
    monkeypatch.setattr("src.execution.risk_manager.get_open_trades", lambda _: [trade])
    monkeypatch.setattr("src.execution.risk_manager.peak_nav", lambda _, fallback: fallback)
    monkeypatch.setattr("src.execution.risk_manager.closed_realized_today", lambda *_: 0.0)
    monkeypatch.setattr("src.execution.risk_manager.had_bot_loss_on", lambda *a, **kw: False)
    manager = RiskManager(Settings(_env_file=None, enable_trading=True, max_units_per_trade=1_000_000))
    inputs = _inputs() | {"stop_loss": 1.097}
    decision = manager.evaluate(session=None, instrument_tradeable=True, **inputs)
    assert decision.allowed
    assert decision.size_mode == "base-scaled"
    assert decision.risk_amount == pytest.approx(decision.units * (1.1 - 1.097))
    assert decision.risk_amount <= 200.0 + 1e-9
