from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import json
import pandas as pd
import pytest
from src.analysis.excursion_tracker import update_excursion
from src.analysis.execution_assumptions import ExecutionAssumptions
from src.analysis.diagnostic_replay import replay
from src.analysis.replay import ReplayCosts
from src.analysis.policy_experiments import register,evaluate
from src.analysis.promotion_review import review,rollback_assessment,save_plan
from src.config import Settings
from test_replay_execution import frame
from test_research_priorities import signal
from test_learning_evidence import session


def test_excursions_use_executable_side_original_stop_and_dedupe():
    now=datetime.now(timezone.utc)
    t=SimpleNamespace(source='bot',venue='oanda',parent_trade_id=None,status='open',side='BUY',opened_at=now-timedelta(seconds=30),stop_loss=1.1)
    j=SimpleNamespace(entry_context={'initial_risk':{'basis':'entry_snapshot','fill':1.1,'stop_pips':10}})
    q=SimpleNamespace(ts=now,bid=1.1005,ask=1.1007,source='oanda',tradeable=True)
    assert update_excursion(t,j,q,now)
    assert j.entry_context['sampled_excursion']['mfe_r']==pytest.approx(.5)
    assert not update_excursion(t,j,q,now)
    q.ts+=timedelta(seconds=15);q.bid=1.0997;q.ask=1.0999
    assert update_excursion(t,j,q,q.ts)
    assert j.entry_context['sampled_excursion']['mae_r']==pytest.approx(.3)
    assert j.entry_context['sampled_excursion']['mfe_r']==pytest.approx(.5)
    t.source='human'
    assert not update_excursion(t,j,q,q.ts)
    t.source='bot';q.ts-=timedelta(hours=1)
    assert not update_excursion(t,j,q,now)


def test_short_uses_ask_and_missing_risk_never_backfilled():
    now=datetime.now(timezone.utc)
    t=SimpleNamespace(source='bot',venue='oanda',parent_trade_id=None,status='open',side='SELL',opened_at=now-timedelta(seconds=1))
    q=SimpleNamespace(ts=now,bid=1.0993,ask=1.0995,source='oanda',tradeable=True)
    j=SimpleNamespace(entry_context={})
    assert not update_excursion(t,j,q,now)
    j.entry_context={'initial_risk':{'basis':'entry_snapshot','fill':1.1,'stop_pips':10}}
    assert update_excursion(t,j,q,now)
    assert j.entry_context['sampled_excursion']['mfe_r']==pytest.approx(.5)


def test_measured_spread_and_commission_with_minimum():
    f=frame();bars={str(ts):{'bid':{'o':1.0999,'h':1.1,'l':1.0998,'c':1.0999},'ask':{'o':1.1001,'h':1.1002,'l':1.1,'c':1.1001}} for ts in f.index}
    a=ExecutionAssumptions(market_timeframe="M5",market_bars=bars,commission_structure={'commission':5,'unitsTraded':100000,'minimumCommission':1})
    rows,_=replay(f,None,None,Settings(_env_file=None,max_open_positions=1,scalp_max_spread_pips=2.1),costs=ReplayCosts(0,0),
                  evaluator=lambda *a,**k:signal('BUY'),assumptions=a)
    assert len(rows)==1
    assert rows[0]['gross_pips']==pytest.approx(-2)
    assert rows[0]['commission_pips']>=1
    assert rows[0]['pips']==pytest.approx(-2-rows[0]['commission_pips'])
    bad=dict(bars);bad.pop(str(f.index[91]))
    with pytest.raises(ValueError,match='coverage'):
        replay(f,None,None,Settings(_env_file=None),assumptions=ExecutionAssumptions(market_timeframe="M5",market_bars=bad))


def test_rollover_boundary_signed_and_no_continuous_double_charge():
    a=ExecutionAssumptions(long_carry_pips_per_day=-999,rollovers=({'ts':'2026-09-21T21:00:00Z','BUY':-.9,'SELL':.3},))
    before=pd.Timestamp('2026-09-21T20:59Z');after=pd.Timestamp('2026-09-21T21:01Z')
    assert a.financing('BUY',before,after,.5)==pytest.approx(-.45)
    assert a.financing('SELL',before,after,1)==pytest.approx(.3)
    assert a.financing('BUY',after,after+pd.Timedelta(hours=1),1)==0


def test_registration_no_reset_no_premature_evaluation(tmp_path):
    cfg=Settings(_env_file=None)
    spec=register(cfg,pd.Timestamp('2026-09-30T20:00Z'),tmp_path)
    assert register(cfg,pd.Timestamp('2026-10-03T00:00Z'),tmp_path)==spec
    assert evaluate(spec,{},pd.Timestamp('2026-10-01T12:00Z'))['status']=='collecting_prospective_evidence'
    changed=dict(spec,source_hashes={})
    assert evaluate(changed,{},pd.Timestamp('2026-11-01T00:00Z'))['status']=='invalidated_source_change'
    decision=review(spec,{'status':'forward_review_required','eligible':['confirmed-entry']})
    assert decision['state']=='not_eligible'
    assert 'broker_cost_and_execution_validation_required' in decision['reasons']
    plan=save_plan(spec,{},tmp_path/'promotion')
    assert plan['execution_state']=='unchanged'
    assert plan['previous_settings']==spec['baseline']


def test_rollback_only_evaluates_sufficient_finite_original_risk():
    assert rollback_assessment([{'realized_r':-1}])['state']=='collecting'
    assert rollback_assessment([{'realized_r':-.2,'policy_id':'v1'}]*20)['state']=='rollback_review_required'
    assert rollback_assessment([{'realized_r':None,'policy_id':'v1'}]*20)['state']=='review_required'


def test_loss_overlap_excludes_manual_and_groups_winners(session):
    from test_learning_evidence import trade
    from test_growth import _signal
    from src.analysis.reflection import record_entry,record_exit
    from src.analysis.loss_attribution import loss_attribution
    now=datetime.now(timezone.utc)
    for source,minutes,pl in [('bot',60,-10),('bot',30,5),('human',90,-999)]:
        t=trade(session,source=source,opened_at=now-timedelta(minutes=minutes))
        record_entry(session,t,_signal())
        t.status='closed';t.closed_at=now
        record_exit(session,t,exit_price=1.1,realized_pl=pl,close_reason='broker_closed',settings=Settings(_env_file=None))
    session.flush()
    r=loss_attribution(session)
    assert len(r['trades'])==2
    assert sorted(t['overlap_at_entry'] for t in r['trades'])==[0,1]
    assert sum(t['realized_pl'] for t in r['trades'])==-5


def test_prospective_chunk_resumes_and_censors_endings(tmp_path,monkeypatch):
    import src.analysis.policy_experiments as lab
    spec=register(Settings(_env_file=None,signal_timeframe='M1'),pd.Timestamp('2026-09-20T20:00Z'),tmp_path)
    data=frame(200);data.index=pd.date_range('2026-09-20T22:00Z',periods=200,freq='min');data['volume']=1
    monkeypatch.setattr(lab,'replay',lambda *a,**k:([{'opened_at':pd.Timestamp('2026-09-21T00:01Z'),'closed_at':pd.Timestamp('2026-09-21T00:02Z'),'pips':1,'reason':'target'},
                                               {'opened_at':pd.Timestamp('2026-09-21T00:03Z'),'reason':'end_of_data'}],[]))
    frames={'M1':data,'H1':data,'D1':data}
    result=lab.evaluate(spec,frames,pd.Timestamp('2026-09-22T00:00Z'))
    assert result['completed_chunks']==1 and len(result['chunks'][0]['trades'])==1
    resumed=lab.evaluate(spec,frames,pd.Timestamp('2026-09-22T00:00Z'),result)
    assert resumed['completed_chunks']==2
    assert resumed['chunks'][1]['candidate']!=resumed['chunks'][0]['candidate']
