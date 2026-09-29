from datetime import date,datetime,timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.data.storage import Base,Trade
from src.analysis.daily_journey import render_daily_journey


def test_empty_day_does_not_invent_learning():
    e=create_engine('sqlite:///:memory:');Base.metadata.create_all(e)
    with Session(e) as s:
        text=render_daily_journey(s,date(2026,9,29))
        assert 'Saved bar decisions: 0' in text
        assert 'no new realized-outcome evidence' in text
    e.dispose()


def test_human_and_mirror_closes_do_not_enter_daily_bot_results():
    e=create_engine('sqlite:///:memory:');Base.metadata.create_all(e)
    with Session(e) as s:
        for source,venue,pl in [('bot','oanda',-10),('human','oanda',500),('bot','mt4',500)]:
            s.add(Trade(symbol='EUR/USD',side='BUY',units=100,requested_entry=1.1,
                stop_loss=1.099,take_profit_1=1.101,take_profit_2=1.102,broker_take_profit=1.102,
                source=source,venue=venue,status='closed',realized_pl=pl,
                closed_at=datetime(2026,9,29,tzinfo=timezone.utc)))
        s.flush()
        text=render_daily_journey(s,date(2026,9,29))
        assert 'primary bot closes: 1; price P/L: -10' in text
        assert '500' not in text
    e.dispose()
