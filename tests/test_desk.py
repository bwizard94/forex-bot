from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.analysis.desk import build_morning_brief, build_night_recap, upsert_desk_note
from src.config import Settings, reload_settings
from src.dashboard.queries import TABLES, hub_summary, list_briefings
from src.data.news import CalendarEvent, Headline, NewsBundle, NewsDesk, score_sentiment
from src.data.storage import (
    TradeJournal,
    get_desk_note,
    init_db,
    insert_trade,
    reset_engine,
    session_scope,
)
from src.notifications.slack_bot import SlackNotifier


def _db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'desk.db'}")
    reset_engine()
    reload_settings()
    init_db()


def test_score_sentiment_eurusd() -> None:
    assert score_sentiment("hawkish fed hot cpi payrolls beat") < 0
    assert score_sentiment("dovish fed weaker dollar euro rallies") > 0
    assert score_sentiment("nothing relevant here") == 0


def test_high_impact_news_blackout() -> None:
    desk = NewsDesk()
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    desk._bundle = NewsBundle(
        events=[
            CalendarEvent(title="CPI m/m", country="USD", impact="High", ts=now),
            CalendarEvent(title="Housing", country="USD", impact="Low", ts=now),
        ]
    )
    desk._as_of = now
    reason = desk.blackout_reason(now, 30)
    assert reason is not None
    assert "CPI" in reason
    assert "Stand aside" in reason
    assert desk.blackout_reason(now + timedelta(hours=2), 30) is None


def test_morning_brief_covers_sentiment_news_goals(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    day = date(2026, 9, 16)
    bundle = NewsBundle(
        events=[
            CalendarEvent(
                title="CPI m/m",
                country="USD",
                impact="High",
                ts=datetime(2026, 9, 16, 12, 30, tzinfo=timezone.utc),
                forecast="3.0%",
                previous="2.9%",
            )
        ],
        headlines=[Headline(title="Hawkish ECB, euro rallies into US session", source="Yahoo EURUSD")],
    )
    settings = Settings(lesson_scratch_usd=2.0)
    with session_scope() as session:
        payload = build_morning_brief(session=session, bundle=bundle, settings=settings, day=day)
        note = upsert_desk_note(session, payload)
        again = upsert_desk_note(session, payload)
        assert again.id == note.id
        stored = get_desk_note(session, day, "morning")
        summary = hub_summary(session)
        rows = list_briefings(session, kind="morning")
    assert payload["kind"] == "morning"
    assert payload["sentiment"]
    assert "Market sentiment" in payload["body"]
    assert "News that could impact EUR/USD" in payload["body"]
    assert "CPI m/m" in payload["body"]
    assert "What I am looking for" in payload["body"]
    assert "Goals for the day" in payload["body"]
    assert "1." in payload["goals"]
    assert stored is not None
    assert stored.looking_for
    assert stored.goals
    assert summary["counts"]["morning_notes"] == 1
    assert rows["total"] == 1
    assert "briefings" in TABLES
    captured: dict = {}
    notifier = SlackNotifier(Settings())
    notifier.send_blocks = lambda **kwargs: captured.update(kwargs) or True  # type: ignore[method-assign]
    assert notifier.desk_note(stored) is True
    blob = str(captured.get("blocks"))
    assert "Sentiment" in blob
    assert "Goals for the day" in blob
    reset_engine()


def test_night_recap_positive_and_negative(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    day = date(2026, 9, 16)
    opened = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
    closed = datetime(2026, 9, 16, 11, 0, tzinfo=timezone.utc)
    settings = Settings(lesson_scratch_usd=2.0)

    def _trade(pl: float, status: str = "closed") -> dict:
        return {
            "symbol": "EUR/USD",
            "side": "BUY",
            "units": 10000,
            "requested_entry": 1.08,
            "fill_price": 1.08,
            "stop_loss": 1.075,
            "take_profit_1": 1.086,
            "take_profit_2": 1.09,
            "broker_take_profit": 1.09,
            "status": status,
            "remaining_units": 0,
            "exit_price": 1.086,
            "realized_pl": pl,
            "close_reason": "take_profit_1" if pl > 0 else "stop_loss",
            "opened_at": opened,
            "closed_at": closed,
            "created_at": opened,
        }

    with session_scope() as session:
        win = insert_trade(session, _trade(48.0))
        session.add(
            TradeJournal(
                trade_id=win.id,
                symbol="EUR/USD",
                side="BUY",
                fingerprint="EUR/USD|BUY|bullish|rsi_oversold|bb_lower_band",
                outcome="win",
                realized_pl=48.0,
                what_went_right="H1 trend held and TP1 paid.",
                lesson="Keep buying dips only when D1 is also bullish.",
                updated_at=closed,
                created_at=opened,
            )
        )
        positive = build_night_recap(session=session, settings=settings, day=day, ending_nav=100048.0)
        upsert_desk_note(session, positive)

    assert positive["verdict"] == "positive"
    assert "What went right" in positive["body"]
    assert "What went wrong" in positive["body"]
    assert "What I learned" in positive["body"]
    assert "POSITIVE" in positive["body"]
    assert "H1 trend held" in positive["what_went_right"]

    with session_scope() as session:
        loss = insert_trade(session, _trade(-80.0))
        session.add(
            TradeJournal(
                trade_id=loss.id,
                symbol="EUR/USD",
                side="BUY",
                fingerprint="EUR/USD|BUY|bullish|rsi_high|bb_mid",
                outcome="loss",
                realized_pl=-80.0,
                what_went_wrong="Bought into a CPI spike.",
                how_to_avoid="Stand aside ±30m around high-impact USD prints.",
                lesson="Do not fade a red-folder print.",
                updated_at=closed,
                created_at=opened,
            )
        )
        negative = build_night_recap(session=session, settings=settings, day=day)

    assert negative["verdict"] == "negative"
    assert "NEGATIVE" in negative["body"]
    assert "Bought into a CPI spike" in negative["what_went_wrong"] or "Stand aside" in negative["what_went_wrong"]
    assert "Do not fade" in negative["learned"]
    reset_engine()


def test_flat_recap_when_no_trades(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    settings = Settings(lesson_scratch_usd=2.0)
    with session_scope() as session:
        payload = build_night_recap(
            session=session,
            settings=settings,
            day=date(2026, 9, 16),
        )
    assert payload["verdict"] == "flat"
    assert "Sitting out" in payload["what_went_right"]
    assert "What I learned" in payload["body"]
    reset_engine()


def test_recap_ignores_other_pairs(tmp_path: Path, monkeypatch) -> None:
    _db(tmp_path, monkeypatch)
    day = date(2026, 9, 16)
    opened = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
    closed = datetime(2026, 9, 16, 11, 0, tzinfo=timezone.utc)
    settings = Settings(lesson_scratch_usd=2.0)
    with session_scope() as session:
        other = insert_trade(
            session,
            {
                "symbol": "GBP/USD",
                "side": "SELL",
                "units": 10000,
                "requested_entry": 1.34,
                "fill_price": 1.34,
                "stop_loss": 1.345,
                "take_profit_1": 1.335,
                "take_profit_2": 1.33,
                "broker_take_profit": 1.33,
                "status": "closed",
                "remaining_units": 0,
                "exit_price": 1.345,
                "realized_pl": -104.5,
                "close_reason": "stop_loss",
                "opened_at": opened,
                "closed_at": closed,
                "created_at": opened,
            },
        )
        session.add(
            TradeJournal(
                trade_id=other.id,
                symbol="GBP/USD",
                side="SELL",
                fingerprint="GBP/USD|SELL|bearish|rsi_low|bb_lower_band",
                outcome="loss",
                realized_pl=-104.5,
                what_went_wrong="Old pair, should not appear on the EUR/USD recap.",
                updated_at=closed,
                created_at=opened,
            )
        )
        payload = build_night_recap(session=session, settings=settings, day=day)
    assert payload["verdict"] == "flat"
    assert "GBP" not in payload["body"]
    assert "Sitting out" in payload["what_went_right"]
    reset_engine()
