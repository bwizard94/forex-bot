from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.analysis.charting import build_chart_pack, oanda_thesis_comment, oanda_trade_comment
from src.analysis.signals import TradeSignal
from src.config import Settings, reload_settings
from src.data.news import CalendarEvent, NewsBundle
from src.data.storage import init_db, insert_signal, insert_trade, reset_engine, session_scope, upsert_bars


def _db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'chart.db'}")
    reset_engine()
    reload_settings()
    init_db()


def _bars(n: int = 80) -> list[dict]:
    start = datetime(2026, 9, 16, 7, 0, tzinfo=timezone.utc)
    rows = []
    price = 1.1540
    for i in range(n):
        ts = start + timedelta(minutes=5 * i)
        price += 0.00002 if i % 3 else -0.00001
        rows.append(
            {
                "symbol": "EUR/USD",
                "timeframe": "M5",
                "ts": ts,
                "open": price,
                "high": price + 0.0003,
                "low": price - 0.0003,
                "close": price + 0.0001,
                "volume": 40 + i,
                "source": "oanda",
                "complete": True,
            }
        )
    return rows


def _signal() -> TradeSignal:
    return TradeSignal(
        symbol="EUR/USD",
        timeframe="M5",
        action="SELL",
        timestamp=datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc),
        price=1.1542,
        entry=1.1542,
        stop_loss=1.1558,
        take_profit_1=1.1520,
        take_profit_2=1.1505,
        risk_reward=1.4,
        atr=0.0009,
        rsi=62.0,
        ema_fast=1.1540,
        ema_slow=1.1544,
        bb_upper=1.1550,
        bb_mid=1.1540,
        bb_lower=1.1530,
        htf_bias="bearish",
        confluence=["H1 trend bearish"],
        reason="EMA 9 below EMA 21",
        strength=71,
    )


def test_oanda_comment_fits_and_names_the_setup() -> None:
    text = oanda_trade_comment(side="SELL", signal=_signal())
    assert len(text) <= 128
    assert text.startswith("SELL EURUSD")
    assert "SL" in text and "TP" in text
    thesis = oanda_thesis_comment("I sold EUR/USD because H1 is bearish.\nMore.")
    assert thesis.startswith("I sold")
    assert len(thesis) <= 128
    stamped = oanda_trade_comment(side="SELL", signal=_signal(), pattern_name="bearish engulfing")
    assert "engulf" in stamped
    assert len(stamped) <= 128


def test_chart_pack_marks_signals_levels_and_news(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    bars = _bars()
    last = bars[-1]
    settings = Settings()
    with session_scope() as session:
        upsert_bars(session, bars)
        upsert_bars(
            session,
            [
                {
                    "symbol": "EUR/USD",
                    "timeframe": "D1",
                    "ts": datetime(2026, 9, 15, 21, 0, tzinfo=timezone.utc),
                    "open": 1.1500,
                    "high": 1.1580,
                    "low": 1.1480,
                    "close": 1.1530,
                    "volume": 1,
                    "source": "oanda",
                    "complete": True,
                }
            ],
        )
        insert_signal(
            session,
            {
                "ts": last["ts"],
                "symbol": "EUR/USD",
                "timeframe": "M5",
                "action": "SELL",
                "price": last["close"],
                "entry": last["close"],
                "stop_loss": last["close"] + 0.0015,
                "take_profit_1": last["close"] - 0.002,
                "take_profit_2": last["close"] - 0.0035,
                "reason": "H1 bearish fade",
                "skipped": False,
                "strength": 70,
            },
        )
        insert_trade(
            session,
            {
                "symbol": "EUR/USD",
                "side": "SELL",
                "units": 10000,
                "requested_entry": last["close"],
                "fill_price": last["close"],
                "stop_loss": last["close"] + 0.0015,
                "take_profit_1": last["close"] - 0.002,
                "take_profit_2": last["close"] - 0.0035,
                "broker_take_profit": last["close"] - 0.0035,
                "status": "open",
                "remaining_units": 10000,
                "opened_at": last["ts"],
                "created_at": last["ts"],
            },
        )
        pack = build_chart_pack(
            session,
            symbol="EUR/USD",
            timeframe="M5",
            settings=settings,
            news=NewsBundle(
                events=[
                    CalendarEvent(
                        title="FOMC Statement",
                        country="USD",
                        impact="High",
                        ts=last["ts"],
                    )
                ]
            ),
            last_price=float(last["close"]),
        )
    assert len(pack["candles"]) == len(bars)
    assert pack["source"] == "oanda"
    assert pack["overlays"]["ema_fast"]
    texts = " ".join(m["text"] for m in pack["markers"])
    assert "SELL" in texts
    assert "FOMC" in texts or "FILL" in texts
    titles = " ".join(line["title"] for line in pack["price_lines"])
    assert "SL" in titles
    assert "TP1" in titles
    assert "Y day high" in titles
    drawings = pack.get("drawings") or []
    assert drawings
    tools = " ".join(d["tool"] for d in drawings)
    assert "text" in tools
    assert pack.get("thesis")
    assert pack.get("tools_used")
    reset_engine()
