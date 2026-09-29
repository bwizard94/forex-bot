from __future__ import annotations

from types import SimpleNamespace

from datetime import datetime, timezone

from src.execution.trade_guard import (
    SOURCE_BOT,
    SOURCE_HUMAN,
    adopted_levels,
    broker_open_on_symbol,
    classify_remote_trade,
    mark_price,
    new_order_block_reason,
    operator_open_on_symbol,
    partial_close_units,
    should_flatten_scalp,
    should_take_partial,
)


def _human_buy(units: int = 1, price: float = 1.14670) -> dict:
    return {
        "id": "99",
        "instrument": "EUR_USD",
        "price": str(price),
        "currentUnits": str(units),
        "initialUnits": str(units),
        "unrealizedPL": "-0.12",
        "openTime": "2026-09-17T04:50:00.000000000Z",
    }


def _bot_sell(units: int = 100000, price: float = 1.15437) -> dict:
    return {
        "id": "12",
        "instrument": "EUR_USD",
        "price": str(price),
        "currentUnits": str(-units),
        "initialUnits": str(-units),
        "unrealizedPL": "12.50",
        "clientExtensions": {
            "id": "fs-045501-S",
            "tag": "EURUSD",
            "comment": "SELL EURUSD @1.15437 SL1.15600 TP1.15200 bearish s72",
        },
        "takeProfitOrder": {"price": "1.15000"},
        "stopLossOrder": {"price": "1.15600"},
    }


def test_classify_operator_one_unit_buy() -> None:
    assert classify_remote_trade(_human_buy()) == SOURCE_HUMAN


def test_classify_stamped_desk_fill_is_bot() -> None:
    assert classify_remote_trade(_bot_sell()) == SOURCE_BOT


def test_adopted_levels_never_invent_tp1_at_fill() -> None:
    levels = adopted_levels(_human_buy(), source=SOURCE_HUMAN)
    assert levels["take_profit_1"] == 0.0
    assert levels["take_profit_2"] == 0.0
    fill = 1.14670
    assert levels["take_profit_1"] != fill


def test_bot_adopt_derives_tp1_only_when_runner_exists() -> None:
    levels = adopted_levels(_bot_sell(), source=SOURCE_BOT)
    assert levels["take_profit_2"] == 1.15000
    assert 1.15000 < levels["take_profit_1"] < 1.15437
    # Must be a real distance, not the fill.
    assert abs(levels["take_profit_1"] - 1.15437) > 0.0004


def test_mark_price_ignores_open_trade_fill_field() -> None:
    # The OANDA open-trade `price` field is the fill. Using it as mark was the bug.
    mark = mark_price(
        quote_mid=1.14640,
        fill=1.14670,
        side="BUY",
        unrealized_pl=-0.30,
        units=1,
        remote_open_price=1.14670,
    )
    assert mark == 1.14640


def test_mark_price_can_imply_from_unrealized_when_quote_missing() -> None:
    mark = mark_price(
        quote_mid=None,
        fill=1.14670,
        side="BUY",
        unrealized_pl=-0.00030,
        units=1,
        remote_open_price=1.14670,
    )
    assert mark is not None
    assert mark < 1.14670


def test_never_flatten_operator_ticket_even_if_tp1_equals_fill() -> None:
    trade = SimpleNamespace(
        source=SOURCE_HUMAN,
        side="BUY",
        symbol="EUR/USD",
        fill_price=1.14670,
        take_profit_1=1.14670,
        remaining_units=1,
        tp1_filled=False,
        units=1,
    )
    ok, why = should_take_partial(trade, mark=1.14670, unrealized_pl=-0.0001)
    assert ok is False
    assert "hands off" in why


def test_never_partial_a_one_unit_desk_ticket() -> None:
    trade = SimpleNamespace(
        source=SOURCE_BOT,
        side="BUY",
        symbol="EUR/USD",
        fill_price=1.14670,
        take_profit_1=1.14750,
        remaining_units=1,
        tp1_filled=False,
        units=1,
    )
    ok, why = should_take_partial(trade, mark=1.14760, unrealized_pl=0.80)
    assert ok is False
    assert "1-unit" in why
    assert partial_close_units(1) == 0
    assert partial_close_units(100_000) == 50_000


def test_tp1_requires_profit_and_real_target() -> None:
    trade = SimpleNamespace(
        source=SOURCE_BOT,
        side="BUY",
        symbol="EUR/USD",
        fill_price=1.14670,
        take_profit_1=1.14750,  # 8 pips
        remaining_units=100_000,
        tp1_filled=False,
        units=100_000,
    )
    # Negative unrealized — old code would still close because fill >= invented TP1.
    ok, why = should_take_partial(trade, mark=1.14670, unrealized_pl=-12.0)
    assert ok is False
    assert "not positive" in why

    ok, why = should_take_partial(trade, mark=1.14760, unrealized_pl=80.0)
    assert ok is True
    assert "hit in profit" in why


def test_tight_tp1_is_not_a_real_target() -> None:
    trade = SimpleNamespace(
        source=SOURCE_BOT,
        side="BUY",
        symbol="EUR/USD",
        fill_price=1.14670,
        take_profit_1=1.14670,  # 0 pips — the old adopt bug
        remaining_units=100_000,
        tp1_filled=False,
        units=100_000,
    )
    ok, why = should_take_partial(trade, mark=1.14670, unrealized_pl=0.01)
    assert ok is False
    assert "not a real target" in why or "pips from fill" in why


def test_new_order_allowed_beside_open_tickets() -> None:
    human = SimpleNamespace(
        status="open",
        symbol="EUR/USD",
        source=SOURCE_HUMAN,
    )
    bot = SimpleNamespace(
        status="open",
        symbol="EUR/USD",
        source=SOURCE_BOT,
        side="SELL",
    )
    assert new_order_block_reason("EUR/USD", remote_rows=[], local_open=[human]) is None
    assert new_order_block_reason("EUR/USD", remote_rows=[_human_buy()], local_open=[]) is None
    assert new_order_block_reason("EUR/USD", remote_rows=[_bot_sell()], local_open=[bot]) is None
    assert operator_open_on_symbol("EUR/USD", remote_rows=[], local_open=[human]) is True
    assert operator_open_on_symbol("EUR/USD", remote_rows=[_human_buy()], local_open=[]) is True
    assert operator_open_on_symbol("EUR/USD", remote_rows=[_bot_sell()], local_open=[bot]) is False
    assert broker_open_on_symbol([_human_buy()], "EUR/USD") is True
    assert new_order_block_reason("EUR/USD", remote_rows=[], local_open=[]) is None


def test_scalp_time_stop_skips_operator_and_fresh_tickets() -> None:
    now = datetime(2026, 9, 18, 19, 30, tzinfo=timezone.utc)
    human = SimpleNamespace(
        source=SOURCE_HUMAN,
        opened_at=datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc),
    )
    ok, why = should_flatten_scalp(human, now=now, max_hold_minutes=90)
    assert ok is False
    assert "hands off" in why
    fresh = SimpleNamespace(
        source=SOURCE_BOT,
        opened_at=datetime(2026, 9, 18, 18, 30, tzinfo=timezone.utc),
    )
    ok, why = should_flatten_scalp(fresh, now=now, max_hold_minutes=90)
    assert ok is False
    stale = SimpleNamespace(
        source=SOURCE_BOT,
        opened_at=datetime(2026, 9, 18, 17, 30, tzinfo=timezone.utc),
    )
    ok, why = should_flatten_scalp(stale, now=now, max_hold_minutes=90)
    assert ok is True
    assert "time stop" in why.lower()
