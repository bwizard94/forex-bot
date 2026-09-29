from datetime import datetime, timezone
from pathlib import Path

from src.config import reload_settings
from src.dashboard.queries import TABLES, hub_summary, list_bars, list_signals
from src.data.storage import init_db, insert_signal, reset_engine, session_scope, upsert_bars


def test_hub_lists_bars_and_signals(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "hub.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    reload_settings()
    init_db()
    ts = datetime(2026, 9, 16, 2, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        upsert_bars(
            session,
            [
                {
                    "symbol": "EUR/USD",
                    "timeframe": "M1",
                    "ts": ts,
                    "open": 1.1,
                    "high": 1.2,
                    "low": 1.0,
                    "close": 1.15,
                    "volume": 9,
                    "source": "test",
                    "complete": True,
                }
            ],
        )
        insert_signal(
            session,
            {
                "ts": ts,
                "symbol": "EUR/USD",
                "timeframe": "M5",
                "action": "SELL",
                "price": 1.15,
                "reason": "unit",
                "skipped": False,
            },
        )
        summary = hub_summary(session)
        bars = list_bars(session, symbol="EUR/USD", timeframe="M1")
        sells = list_signals(session, action="SELL")
    assert summary["counts"]["bars"] == 1
    assert summary["counts"]["sell_signals"] == 1
    assert bars["total"] == 1
    assert bars["rows"][0]["close"] == 1.15
    assert sells["rows"][0]["action"] == "SELL"
    assert "journal" in TABLES
    assert "lessons" in TABLES
    assert "briefings" in TABLES
    assert "setups" in TABLES
    reset_engine()
