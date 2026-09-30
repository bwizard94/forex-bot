from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as N
import pytest
from src.config import Settings
from src.analysis.mistakes import calendar_hold_reason
from src.pipeline import TradingPipeline


@pytest.mark.parametrize('day,hour',[(29,23),(27,22),(25,21),(28,0),(26,12)])
def test_practice_broker_schedule_removes_desk_calendar_veto(day,hour):
    now=datetime(2026,9,day,hour,tzinfo=timezone.utc)
    s=Settings(_env_file=None,oanda_environment='practice',practice_broker_market_hours=True,trade_session_end_hour=22)
    assert calendar_hold_reason(now,s) is None
    s.oanda_environment='live'
    assert calendar_hold_reason(now,s) is not None


def test_broker_schedule_still_rejects_untradeable_and_stale_quotes():
    p=TradingPipeline.__new__(TradingPipeline)
    p.settings=Settings(_env_file=None,practice_broker_market_hours=True)
    q=N(symbol='EUR/USD',tradeable=False,source='oanda',ts=datetime.now(timezone.utc),bid=1.1,ask=1.10015)
    p.fetcher=N(fetch_quotes=lambda symbols:[q])
    assert 'not fresh tradeable' in p._final_entry_check(N(symbol='EUR/USD'))
    q.tradeable=True;q.ts-=timedelta(minutes=10)
    assert 'not fresh tradeable' in p._final_entry_check(N(symbol='EUR/USD'))


def test_no_early_friday_flat_in_broker_hours(monkeypatch):
    now=datetime(2026,9,25,20,30,tzinfo=timezone.utc)
    monkeypatch.setattr('src.pipeline.utcnow',lambda:now)
    monkeypatch.setattr('src.pipeline.should_flatten_scalp',lambda *a,**kw:(False,'fresh trade'))
    p=TradingPipeline.__new__(TradingPipeline)
    p.settings=Settings(_env_file=None,practice_broker_market_hours=True)
    p._management_quote_ready=lambda _:pytest.fail('Should not reach close logic solely because of Friday hour')
    p._quotes={}
    p._maybe_time_stop(None,N(source='bot',symbol='EUR/USD'),{},None)
