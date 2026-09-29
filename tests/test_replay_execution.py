from types import SimpleNamespace
import pandas as pd
import pytest

from src.analysis.replay import replay, ReplayCosts, completed_bars, performance
from src.config import Settings


def frame(n=94):
    return pd.DataFrame({'open':1.1,'high':1.1001,'low':1.0999,'close':1.1},
                        index=pd.date_range('2026-09-21 06:00',periods=n,freq='5min',tz='UTC'))


def evaluator(*args,**kwargs):
    return SimpleNamespace(action='BUY',entry=1.1,stop_loss=1.099,take_profit_1=1.101,
                           take_profit_2=1.102,signal_type='test',strength=80)


def run(f,**kw):
    return replay(f,None,None,Settings(_env_file=None),evaluator=evaluator,**kw)[0]


def test_signal_cannot_fill_or_exit_on_its_own_bar():
    f=frame()
    f.iloc[90,f.columns.get_loc('high')]=1.2
    f.iloc[90,f.columns.get_loc('low')]=1.0
    result=run(f,costs=ReplayCosts(0,0))
    assert result[0]['opened_at']==f.index[91]
    assert result[0]['pips']==pytest.approx(0)
    assert result[0]['reason']=='end_of_data'


def test_stop_wins_when_both_levels_touched():
    f=frame()
    f.iloc[91,f.columns.get_loc('high')]=1.103
    f.iloc[91,f.columns.get_loc('low')]=1.098
    result=run(f,costs=ReplayCosts(0,0),max_trades=1)
    assert result[0]['pips']==pytest.approx(-10)
    assert result[0]['reason']=='stop'


def test_exit_management_runs_on_candles_between_signal_samples():
    f=frame(105)
    f.iloc[92,f.columns.get_loc('low')]=1.098
    result=run(f,costs=ReplayCosts(0,0),step=10,max_trades=1)
    assert result[0]['closed_at']==f.index[92]
    assert result[0]['pips']==pytest.approx(-10)


def test_tp1_partial_then_next_bar_breakeven():
    f=frame()
    f.iloc[91,f.columns.get_loc('high')]=1.1012
    result=run(f,costs=ReplayCosts(0,0),max_trades=1)
    assert result[0]['closed_at']==f.index[92]
    assert result[0]['pips']==pytest.approx(5)


def test_spread_and_adverse_slippage_make_flat_trade_negative():
    result=run(frame(),costs=ReplayCosts(1.2,.1),max_trades=1)
    assert result[0]['pips']==pytest.approx(-1.4)


def test_gap_stop_uses_worse_open():
    f=frame()
    f.iloc[92]=[1.098,1.0981,1.0979,1.098]
    result=run(f,costs=ReplayCosts(0,0),max_trades=1)
    assert result[0]['pips']==pytest.approx(-20)


def test_higher_timeframes_only_include_completed_bars():
    h=pd.DataFrame({'close':[1,2]},index=pd.date_range('2026-09-21 12:00',periods=2,freq='h',tz='UTC'))
    assert completed_bars(h,pd.Timestamp('2026-09-21 12:55Z'),'1h',120).empty
    assert list(completed_bars(h,pd.Timestamp('2026-09-21 13:00Z'),'1h',120).close)==[1]
    d=pd.DataFrame({'close':[1,2]},index=pd.date_range('2026-09-20',periods=2,freq='D',tz='UTC'))
    assert list(completed_bars(d,pd.Timestamp('2026-09-21 13:00Z'),'1d',80).close)==[1]


def test_replay_passes_bar_close_time_to_evaluator():
    calls=[]
    def observe(*a,**kw):
        calls.append(kw['now'])
        return evaluator(*a,**kw)
    f=frame()
    replay(f,None,None,Settings(_env_file=None),evaluator=observe)
    assert calls[0]==f.index[91]


def test_rejects_m1_mislabelled_as_m5():
    f=frame()
    f.index=pd.date_range('2026-09-21 06:00',periods=len(f),freq='min',tz='UTC')
    with pytest.raises(ValueError,match='Resample'): run(f)


def test_metrics_count_costs_and_drawdown():
    stats=performance([{'pips':5},{'pips':-10},{'pips':2}])
    assert stats['profit_factor']==pytest.approx(.7)
    assert stats['max_drawdown_pips']==10
    assert stats['expectancy_pips']==-1
    assert not stats['validated_for_live']


def test_m1_uses_one_minute_completion_and_retains_fixed_stop():
    f=frame()
    f.index=pd.date_range('2026-09-21 06:00',periods=len(f),freq='min',tz='UTC')
    f.iloc[91,f.columns.get_loc('low')]=1.098
    calls=[]
    def observe(*a,**kw):
        calls.append((a[1],kw['now'],kw['heavy']))
        return evaluator(*a,**kw)
    rows,_=replay(f,None,None,Settings(_env_file=None),evaluator=observe,
                  timeframe='M1',costs=ReplayCosts(1.2,.1),max_trades=1)
    assert calls[0]==('M1',f.index[91],True)
    assert rows[0]['pips']==pytest.approx(-10.8)  # 0.7 pip entry cost + 0.1 stop slippage.


def test_replay_cost_gate_blocks_uneconomic_setup():
    assert run(frame(),costs=ReplayCosts(3,.1))==[]


def test_m5_comparison_drops_partial_minutes_instead_of_filling_gaps():
    from src.analysis.compare_strategies import complete_m5
    f=frame(10)
    f.index=pd.date_range('2026-09-21 06:00',periods=10,freq='min',tz='UTC')
    f['volume']=1
    result=complete_m5(f.drop(f.index[7]))
    assert list(result.index)==[f.index[0]]
    assert result.iloc[0].volume==5
