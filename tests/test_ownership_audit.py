from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.data.storage import Base, Trade
from src.analysis.ownership_audit import reconcile_legacy_closed_ownership


@pytest.mark.parametrize('stamp,state,signal,expected',[
    ('','CLOSED',None,'human'),('fs-owned','CLOSED',None,'bot'),
    ('','OPEN',None,'bot'),('','CLOSED',123,'bot'),
])
def test_only_verified_legacy_closed_imports_are_reclassified(stamp,state,signal,expected):
    engine=create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with Session(engine) as s:
        t=Trade(symbol='EUR/USD',side='BUY',units=100,requested_entry=1.1,
            stop_loss=0,take_profit_1=0,take_profit_2=0,broker_take_profit=0,
            status='closed',source='bot',venue='oanda',broker_trade_id='123',signal_id=signal)
        s.add(t);s.flush()
        broker=SimpleNamespace(trade_details=lambda _: {'id':'123','state':state,
            'instrument':'EUR_USD','clientExtensions':{'id':stamp}})
        reconcile_legacy_closed_ownership(s,broker)
        assert t.source==expected
        assert t.units==100 and t.stop_loss==0
    engine.dispose()
