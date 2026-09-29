from types import SimpleNamespace as NS
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.data.storage import Base, LearnedRule
from src.analysis.loss_review import review_loss
from src.analysis.reflection import lesson_gate
from src.analysis.growth import growth_gate
from src.config import Settings


def test_review_separates_execution_evidence_from_causation():
    t=NS(symbol='EUR/USD',slippage_pips=.8)
    j=NS(realized_pl=-110,close_reason='stop_loss',entry_context={'initial_risk':{'basis':'entry_snapshot','currency':'USD','amount':100,'stop_pips':10},'decision_evidence':{'final_entry_quality':{'bid':1.1,'ask':1.10015}}})
    r=review_loss(t,j)
    assert r['loss_r']==1.1 and r['spread_stop_fraction']==pytest.approx(.15)
    assert r['cause_proven'] is False
    assert any('Reconcile stop fill' in x for x in r['hypotheses_to_test'])
    j.entry_context={}
    assert review_loss(t,j)['loss_r'] is None


@pytest.mark.parametrize('environment,contextual,allowed',[('practice',True,True),('practice',False,False),('live',True,False)])
def test_broad_ban_advisory_only_in_contextual_practice(environment,contextual,allowed):
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    fp='EUR/USD|SELL|bearish|rsi_overbought|bb_upper_band'
    with Session(engine) as s:
        s.add(LearnedRule(fingerprint=fp,symbol='EUR/USD',side='SELL',action='skip',active=True,loss_count=2,net_pl=-20,min_strength=100,skip_until=datetime.now(timezone.utc)+timedelta(days=3)))
        s.flush()
        settings=Settings(_env_file=None,oanda_environment=environment,practice_contextual_loss_review=contextual)
        assert lesson_gate(s,fp,80,settings=settings).allowed is allowed


def test_growth_loss_streak_does_not_reintroduce_side_ban():
    bucket=NS(losing_streak=2,key='EUR/USD|SELL',median_pl=-10,net_pl=-20,losses=2,wins=0,samples=2,last_outcome='loss')
    report=NS(bucket=lambda _:bucket)
    signal=NS(action='SELL',symbol='EUR/USD',rsi=50,strength=50,signal_type='test',htf_bias='bearish',bb_upper=None,bb_lower=None,bb_mid=None,price=1.1,confluence=[])
    settings=Settings(_env_file=None,practice_contextual_loss_review=True,oanda_environment='practice')
    assert growth_gate(signal,report,settings=settings).allowed
    settings.practice_contextual_loss_review=False
    assert not growth_gate(signal,report,settings=settings).allowed
