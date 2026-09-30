from types import SimpleNamespace
import pytest
import pandas as pd
from test_replay_execution import frame
from test_learning_evidence import session, trade
from test_growth import _signal
from src.analysis.replay import replay, ReplayCosts, performance
from src.analysis.cost_stress import stress, SCENARIOS
from src.analysis.context_report import contextual_report
from src.analysis.reflection import record_entry, record_exit
from src.config import Settings


def signal(side):
    d = 1 if side == 'BUY' else -1
    return SimpleNamespace(action=side, entry=1.1, stop_loss=1.1-d*.002,
                           take_profit_1=1.1+d*.003, take_profit_2=1.1+d*.004,
                           signal_type='control', strength=80)


@pytest.mark.parametrize('side,expected', [('BUY',2),('SELL',-2),('WAIT',0)])
@pytest.mark.parametrize('spread,slip', [(0,0),(1.2,.1),(1.8,.2)])
def test_evaluator_control_known_path(side, expected, spread, slip):
    f = frame()
    f.iloc[-1] = [1.1,1.1003,1.0999,1.1002]
    rows,_ = replay(f,None,None,Settings(_env_file=None), costs=ReplayCosts(spread,slip),
                    evaluator=lambda *a,**kw: signal(side),max_trades=1)
    assert performance(rows)['net_pips'] == pytest.approx(expected-(spread+2*slip if side!='WAIT' else 0))
    assert len(rows) == (0 if side=='WAIT' else 1)


def test_stress_retains_errors_and_gate_effects():
    frames={'M1':frame(), 'H1':frame(), 'D1':frame()}
    frames['M1'].index=pd.date_range('2026-09-21 06:00',periods=len(frames['M1']),freq='min',tz='UTC')
    report=stress(frames,Settings(_env_file=None,signal_timeframe='M1',max_open_positions=1),evaluator=lambda *a,**kw: signal('BUY'))
    assert len(report['runs'])==len(SCENARIOS)
    assert report['runs'][0]['metrics']['net_pips']==pytest.approx(-1.4)
    assert report['runs'][-1]['metrics']['trades']==0
    assert not report['validated_for_live']
    def broken(*a,**kw): raise ValueError('fixture failure')
    errors=stress(frames,Settings(_env_file=None,signal_timeframe='M1',max_open_positions=1),evaluator=broken)
    assert all(r['status']=='error' and 'fixture failure' in r['error'] for r in errors['runs'])


def test_context_excludes_other_ownership_and_keeps_unknowns(session):
    for version,source,venue,parent,pl in [('a','bot','oanda',None,10),
            ('b','bot','oanda',None,-5),('a','human','oanda',None,900),
            ('a','bot','mt4',1,800),('a','bot','oanda',1,700)]:
        t=trade(session,source=source,venue=venue,parent_trade_id=parent)
        j=record_entry(session,t,_signal())
        j.entry_context={'decision_evidence':{'code_sha256':version,'configuration_sha256':'config',
             'configuration':{'signal_timeframe':'M1'},'quote':{'bid':1.1,'ask':1.1002}},
             'initial_risk':{'basis':'entry_snapshot','currency':'USD','amount':10,'stop_pips':10}}
        t.status='closed'
        record_exit(session,t,exit_price=1.099,realized_pl=pl,close_reason='broker_closed',settings=Settings(_env_file=None))
    t=trade(session);j=record_entry(session,t,_signal());j.entry_context={};t.status='closed'
    record_exit(session,t,exit_price=1.1,realized_pl=0,close_reason='broker_closed',settings=Settings(_env_file=None))
    session.flush()
    result=contextual_report(session)
    assert result['closed_trades']==3
    assert sum(r['performance']['net_pl'] for r in result['groups'])==5
    groups={r['code_sha256']:r for r in result['groups']}
    assert groups['a']['performance']['mean_r']==1
    assert groups['b']['performance']['mean_r']==-.5
    assert groups['a']['entry_spread_pips']['mean']==pytest.approx(2)
    assert groups['a']['spread_to_initial_stop']['mean']==pytest.approx(.2)
    assert groups['a']['quote_to_fill_adverse_pips']['mean']==0
    assert groups['unknown']['entry_spread_pips']['missing']==1
    assert groups['unknown']['performance']['r_samples']==0
