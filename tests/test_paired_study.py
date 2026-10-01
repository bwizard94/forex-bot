from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
from src.analysis.exit_plan import payoff
from src.analysis.paired_study import outcome,registration,paired_metrics
from src.analysis.measured_archive import store,load


def test_payoff_tracks_split_minimum_odd_units_and_unknown_fees():
    r=payoff('BUY',1.1,1.099,1.1006,1.102,units=3)
    assert r['weighted_target_pips']==pytest.approx(46/3)
    assert r['net_target_r'] is None
    assert payoff('BUY',1.1,1.099,1.1004,1.102)['partial_fraction']==0
    assert payoff('BUY',1.1,1.099,1.1006,1.102,units=1)['partial_fraction']==0
    short=payoff('SELL',1.1,1.101,1.0994,1.098,units=2,fee_pips=1)
    assert short['weighted_target_r']==pytest.approx(1.3)
    assert short['net_target_r']==pytest.approx(1.2)


def setup(tmp_path,side='BUY'):
    captured=datetime(2026,10,2,23,58,30,tzinfo=timezone.utc)
    spec=registration(tmp_path,captured)
    p={'action':side,'stop_loss':1.099,'take_profit_1':1.101,'take_profit_2':1.102,
       'decision_context':{'configuration':{'scalp_max_hold_minutes':4},
        'bars':{'signal':{'last_ohlc':{'high':1.1003,'low':1.0997}}}}}
    bars={}
    for i in range(12):
        ts=captured.replace(second=0)+timedelta(minutes=i+1)
        bars[ts.isoformat()]={'bid':{'o':1.1,'h':1.1004,'l':1.0998,'c':1.1002},
                             'ask':{'o':1.1002,'h':1.1006,'l':1.1,'c':1.1004}}
    return captured,spec,p,bars


def test_cross_midnight_hold_and_skip_never_counts_win(tmp_path):
    t,s,p,b=setup(tmp_path);now=t+timedelta(minutes=20)
    r=outcome(p,t,b,'immediate',s,now)
    assert r['reason']=='time' and r['closed_at'].startswith('2026-10-03')
    assert r['net_pips'] is None and not r['fees_verified']
    assert outcome(p,t,b,'skip',s,now)['traded'] is False
    del b[sorted(b)[1]]
    assert outcome(p,t,b,'immediate',s,now)['status']=='coverage_gap'


def test_confirm_enters_after_completed_trigger_not_same_bar(tmp_path):
    t,s,p,b=setup(tmp_path);first=b[sorted(b)[0]]
    first['bid']['c']=1.1005;first['bid']['h']=1.1005
    first['ask']['c']=1.1007;first['ask']['h']=1.1007
    r=outcome(p,t,b,'confirm',s,t+timedelta(minutes=20))
    assert r['opened_at']==sorted(b)[1]
    assert outcome(p,t,b,'confirm',s,t+timedelta(seconds=40))['status']=='pending'


def test_ambiguous_bar_stops_first(tmp_path):
    t,s,p,b=setup(tmp_path);b[sorted(b)[0]]['bid'].update(h=1.103,l=1.098)
    r=outcome(p,t,b,'immediate',s,t+timedelta(minutes=20))
    assert r['reason']=='stop' and r['pips']<0


def test_protection_is_next_bar_only(tmp_path):
    t,s,p,b=setup(tmp_path);p['take_profit_1']=1.1019;p['take_profit_2']=1.103
    b[sorted(b)[0]]['bid'].update(h=1.1016,l=1.0998)
    b[sorted(b)[1]]['bid'].update(o=1.1007,l=1.1003,h=1.1008,c=1.1004)
    r=outcome(p,t,b,'protect',s,t+timedelta(minutes=20))
    assert r['closed_at']==sorted(b)[1] and r['pips']>0


def test_short_uses_ask_and_open_gap(tmp_path):
    t,s,p,b=setup(tmp_path,'SELL');p.update(stop_loss=1.101,take_profit_1=1.099,take_profit_2=1.098)
    b[sorted(b)[0]]['ask'].update(o=1.1015,h=1.1016,l=1.1012,c=1.1014)
    r=outcome(p,t,b,'immediate',s,t+timedelta(minutes=20))
    assert r['reason']=='stop' and r['pips']<-15


def test_archive_retains_first_seen_and_excludes_incomplete(tmp_path):
    now=datetime(2026,10,2,12,tzinfo=timezone.utc);path=tmp_path/'market.sqlite'
    v={'o':1.1,'h':1.1,'l':1.1,'c':1.1}
    r={'time':(now-timedelta(minutes=2)).isoformat(),'complete':True,'bid':v,'ask':v}
    assert store([r],now,path)==1
    changed=dict(r,bid=dict(v,o=1.2,h=1.2,l=1.2,c=1.2),ask=dict(v,o=1.2,h=1.2,l=1.2,c=1.2))
    store([changed],now,path)
    assert list(load(path).values())[0]['bid']['o']==1.1
    assert store([dict(r,time=now.isoformat())],now,path)==0


def test_paired_metric_counts_winners_harmed_and_coverage():
    rows=[{'captured_at':'2026-10-02','outcomes':{'immediate':{'status':'complete','pips':5},'skip':{'status':'complete','pips':0}}},
          {'captured_at':'2026-10-03','outcomes':{'immediate':{'status':'complete','pips':-10},'skip':{'status':'complete','pips':0}}},
          {'captured_at':'2026-10-03','outcomes':{'immediate':{'status':'pending'},'skip':{'status':'complete','pips':0}}}]
    r=paired_metrics(rows,'skip')
    assert r['pairs']==2 and r['unpaired']==1 and r['baseline_winners_harmed']==1
    assert r['baseline_losses_improved']==1 and r['mean_delta_pips']==2.5


def test_prospective_registration_deduplicates_and_separates_policies(tmp_path,monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from src.data.storage import Base,DecisionObservation
    from src.config import Settings
    import src.analysis.paired_study as module
    t,s,p,b=setup(tmp_path/'study');monkeypatch.setattr(module,'ROOT',tmp_path)
    db=tmp_path/'test.sqlite';engine=create_engine('sqlite:///'+str(db));Base.metadata.create_all(engine)
    p.update(ts=(t-timedelta(minutes=1)).isoformat(),timeframe='M1')
    p['decision_context'].update(code_sha256='code-a',configuration_sha256='config')
    with Session(engine) as session:
        for seconds in (-120,0,10):
            session.add(DecisionObservation(symbol='EUR/USD',captured_at=t+timedelta(seconds=seconds),payload=p))
        import copy
        other=copy.deepcopy(p);other['decision_context']['code_sha256']='code-b'
        session.add(DecisionObservation(symbol='EUR/USD',captured_at=t,payload=other));session.commit()
    r=module.run(Settings(_env_file=None,database_url='sqlite:///'+str(db)),tmp_path/'study',t+timedelta(minutes=20),b)
    assert r['opportunities']==2 and len(r['cohorts'])==2
    assert all(not g['promotion_allowed'] for c in r['gates'].values() for g in c.values())
    assert module.registration(tmp_path/'study',t+timedelta(days=1))==s
    engine.dispose()


def test_missing_hold_policy_is_not_invented(tmp_path):
    t,s,p,b=setup(tmp_path);p['decision_context']['configuration']={}
    assert outcome(p,t,b,'immediate',s,t+timedelta(minutes=20))['status']=='missing_hold_policy'


def test_weighted_payoff_candidate_does_not_change_baseline(tmp_path):
    t,s,p,b=setup(tmp_path);p['decision_context']['configuration']['min_rr_ratio']=1.6
    p['take_profit_1']=1.1008;p['take_profit_2']=1.102
    assert outcome(p,t,b,'weighted_payoff',s,t+timedelta(minutes=20))['reason']=='weighted_payoff_below_minimum'
    assert outcome(p,t,b,'immediate',s,t+timedelta(minutes=20))['traded']
