from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.analysis.playbook import MT4_PATH, read_mt4
from src.config import Settings, reload_settings
from src.data.storage import (
    init_db,
    insert_mt4_command,
    insert_trade,
    list_pending_mt4_commands,
    reset_engine,
    session_scope,
)
from src.execution.mt4 import MAGIC, MT4Broker, lots_to_units, units_to_lots
from src.execution.risk_manager import desk_open_trades


def test_lot_conversion_floors_at_one_centi_lot() -> None:
    assert units_to_lots(100_000) == 1.0
    assert units_to_lots(1) == 0.01
    assert lots_to_units(0.01) == 1000
    assert MAGIC == 212100


def test_mt4_docs_name_the_three_modes() -> None:
    text = read_mt4()
    assert text
    assert MT4_PATH.name == "MT4.md"
    blob = text.lower()
    assert "metaapi" in blob
    assert "bridge" in blob
    assert "ledger" in blob
    assert "212100" in text
    assert "open_only" in blob or "hands-off" in blob or "hands off" in blob
    ea = Path("mt4/ForexSentinelBridge.mq4")
    assert ea.exists()
    src = ea.read_text(encoding="utf-8")
    assert "212100" in src
    assert "/api/mt4/bridge" in src


def test_disconnected_without_credentials() -> None:
    broker = MT4Broker(Settings(mt4_enabled=True, mt4_login="", mt4_server=""))
    assert broker.mode() == "disconnected"
    report = broker.place_market_order(
        symbol="EUR/USD",
        side="SELL",
        units=100_000,
        stop_loss=1.155,
        take_profit=1.147,
        requested_entry=1.154,
    )
    assert report.ok is False
    assert "not connected" in (report.error or "").lower()


def test_ledger_fill_and_command_queue(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "mt4.db"
    env = tmp_path / ".env"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.chdir(tmp_path)
    env.write_text("", encoding="utf-8")
    reset_engine()
    reload_settings()
    init_db()
    settings = Settings(
        mt4_enabled=True,
        mt4_login="123456",
        mt4_password="demo",
        mt4_server="Broker-Demo",
        mt4_bridge_secret="unit-secret",
        database_url=f"sqlite:///{db}",
    )
    broker = MT4Broker(settings)
    assert broker.mode() == "ledger"
    report = broker.place_market_order(
        symbol="EUR/USD",
        side="SELL",
        units=100_000,
        stop_loss=1.15520,
        take_profit=1.14770,
        requested_entry=1.15440,
        comment="fs-120",
    )
    assert report.ok is True
    assert str(report.broker_trade_id).startswith("ledger-")
    broker.note_heartbeat({"balance": 10_000, "equity": 10_010, "open": []})
    assert broker.mode() == "bridge"
    queued = broker.place_market_order(
        symbol="EUR/USD",
        side="BUY",
        units=50_000,
        stop_loss=1.15300,
        take_profit=1.15600,
        requested_entry=1.15400,
        comment="fs-121",
    )
    assert queued.ok is True
    assert str(queued.broker_trade_id).startswith("pending-")
    pulled = broker.pull_commands(secret="unit-secret", limit=4)
    assert pulled["ok"] is True
    assert pulled["commands"]
    cmd = pulled["commands"][0]
    applied = broker.apply_bridge(
        {
            "secret": "unit-secret",
            "heartbeat": {"balance": 10000, "equity": 10000, "open": []},
            "results": [{"id": cmd["id"], "ok": True, "ticket": "888", "fill": 1.15401}],
        }
    )
    assert applied["ok"] is True
    assert applied["applied"] == 1
    with session_scope() as session:
        pending = list_pending_mt4_commands(session)
        assert pending == []
    bad = broker.pull_commands(secret="wrong", limit=1)
    assert bad["ok"] is False
    reset_engine()


def test_insert_mt4_command_roundtrip(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "cmd.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    reload_settings()
    init_db()
    with session_scope() as session:
        row = insert_mt4_command(
            session,
            {
                "action": "open",
                "symbol": "EURUSD",
                "side": "SELL",
                "lots": 1.0,
                "units": 100000,
                "stop_loss": 1.155,
                "take_profit": 1.147,
                "magic": 212100,
                "comment": "fs-1",
                "status": "pending",
            },
        )
        assert row.id >= 1
        pending = list_pending_mt4_commands(session)
        assert len(pending) == 1
        oanda = insert_trade(
            session,
            {
                "symbol": "EUR/USD",
                "side": "SELL",
                "units": 100000,
                "requested_entry": 1.1544,
                "fill_price": 1.1544,
                "stop_loss": 1.1552,
                "take_profit_1": 1.1538,
                "take_profit_2": 1.1477,
                "broker_take_profit": 1.1477,
                "status": "open",
                "remaining_units": 100000,
                "source": "bot",
                "venue": "oanda",
                "opened_at": datetime(2026, 9, 19, 6, 0, tzinfo=timezone.utc),
                "broker_trade_id": "120",
            },
        )
        copy = insert_trade(
            session,
            {
                "symbol": "EUR/USD",
                "side": "SELL",
                "units": 100000,
                "requested_entry": 1.1544,
                "fill_price": 1.1544,
                "stop_loss": 1.1552,
                "take_profit_1": 1.1538,
                "take_profit_2": 1.1477,
                "broker_take_profit": 1.1477,
                "status": "open",
                "remaining_units": 100000,
                "source": "bot",
                "venue": "mt4",
                "parent_trade_id": oanda.id,
                "opened_at": datetime(2026, 9, 19, 6, 0, tzinfo=timezone.utc),
                "broker_trade_id": "ledger-abc",
            },
        )
        from src.data.storage import get_mt4_sibling

        sib = get_mt4_sibling(session, oanda)
        assert sib is not None
        assert sib.id == copy.id
        assert sib.venue == "mt4"
    reset_engine()


def test_mt4_copy_does_not_eat_oanda_stack() -> None:
    oanda = type("T", (), {})()
    oanda.symbol = "EUR/USD"
    oanda.side = "SELL"
    oanda.source = "bot"
    oanda.venue = "oanda"
    oanda.status = "open"
    oanda.fill_price = 1.1548
    oanda.requested_entry = 1.1548
    oanda.stop_loss = 1.1556
    oanda.remaining_units = 40_000
    oanda.units = 40_000
    copy = type("T", (), {})()
    copy.symbol = "EUR/USD"
    copy.side = "SELL"
    copy.source = "bot"
    copy.venue = "mt4"
    copy.status = "open"
    copy.fill_price = 1.1548
    copy.requested_entry = 1.1548
    copy.stop_loss = 1.1556
    copy.remaining_units = 40_000
    copy.units = 40_000
    desk = desk_open_trades([oanda, copy])
    assert desk == [oanda]
    assert len(desk) == 1
