import json
from types import SimpleNamespace
from threading import RLock
from unittest.mock import Mock

import pandas as pd
import pytest

from src.analysis import strategy_lab as lab
from src.config import Settings
from src.pipeline import TradingPipeline


def spec(tmp_path):
    return lab.register(Settings(_env_file=None, signal_timeframe='M5'),
                        pd.Timestamp('2026-09-29T16:00:00Z'), tmp_path)


def rows(pips, count=60):
    return [{'pips':pips, 'reason':'stop' if pips<0 else 'target',
             'opened_at':pd.Timestamp('2026-09-30T08:00Z')+pd.Timedelta(days=i%5),
             'closed_at':pd.Timestamp('2026-09-30T09:00Z')+pd.Timedelta(days=i%5)}
            for i in range(count)]


def test_registered_parameters_and_cutoff_survive_restart(tmp_path):
    original=spec(tmp_path)
    changed=Settings(_env_file=None, min_confluence=99)
    assert lab.register(changed,pd.Timestamp('2026-10-15T00:00Z'),tmp_path)==original
    text=(tmp_path/'experiment.json').read_text()
    assert 'oanda_api_token' not in text and 'account_id' not in text


def test_positive_tiny_sample_and_forced_closes_cannot_pass(tmp_path):
    s=spec(tmp_path)
    r=lab.assess(rows(10,6)+[dict(r,reason='end_of_data') for r in rows(99)],[],s,
        pd.Timestamp('2026-09-30T00:00Z'),pd.Timestamp('2026-10-07T00:00Z'))
    assert not r['passed']
    assert r['metrics']['trades']==6
    assert 'insufficient_completed_trades' in r['reasons']


def test_losses_and_no_reference_improvement_rejected(tmp_path):
    s=spec(tmp_path)
    a,b=pd.Timestamp('2026-09-30T00:00Z'),pd.Timestamp('2026-10-07T00:00Z')
    assert 'no_positive_expectancy_after_modeled_costs' in lab.assess(rows(-1),[],s,a,b)['reasons']
    assert 'improvement_over_reference_not_established' in lab.assess(rows(1),rows(2),s,a,b)['reasons']
    assert lab.assess(rows(2),rows(1),s,a,b)['passed']


def test_incomplete_prospective_window_never_replays_old_holdout(tmp_path,monkeypatch):
    s=spec(tmp_path)
    idx=pd.date_range('2026-09-29',periods=100,freq='min',tz='UTC')
    f=pd.DataFrame({k:1.1 for k in ['open','high','low','close','volume']},index=idx)
    mock=Mock(side_effect=AssertionError('must not replay registration history'))
    monkeypatch.setattr(lab,'replay',mock)
    r=lab.evaluate(s,{'M1':f,'H1':f,'D1':f},pd.Timestamp('2026-09-30T00:00Z'))
    assert r['status']=='collecting_prospective_evidence'
    assert not r['validated_for_live'] and not r['runs']
    mock.assert_not_called()


def test_research_mode_blocks_toggle_and_order_submission():
    pipe=TradingPipeline.__new__(TradingPipeline)
    pipe.settings=SimpleNamespace(strategy_research_only=True)
    pipe._lock=RLock();pipe.broker=Mock();pipe.trading_enabled=False
    with pytest.raises(ValueError,match='research-only'): pipe.set_trading(True)
    with pytest.raises(ValueError,match='research-only'): pipe._submit_order(None,'BUY',100,'test')
    assert 'research-only' in pipe._final_entry_check(None)
    pipe.broker.place_market_order.assert_not_called()
    pipe.broker.account_summary.assert_not_called()
    pipe.set_trading(False)
    assert pipe.trading_enabled is False


def test_code_change_invalidates_experiment_without_replay(tmp_path,monkeypatch):
    spec(tmp_path)
    monkeypatch.setattr(lab,'source_hashes',lambda:{'changed':'version'})
    monkeypatch.setattr(lab,'ROOT',tmp_path)
    monkeypatch.setattr(lab,'load_frames',Mock(side_effect=AssertionError('must not replay')))
    r=lab.run(tmp_path)
    assert r['status']=='source_changed_requires_new_experiment'
    assert not r['validated_for_live']


def test_worker_failure_clears_old_success(tmp_path,monkeypatch):
    from src.analysis import strategy_lab_job as job
    monkeypatch.setattr(job,'LAB',tmp_path)
    monkeypatch.setattr(job,'ROOT',tmp_path)
    monkeypatch.setattr(job.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1))
    (tmp_path/'latest.json').write_text('{"status":"forward_review_required"}')
    job.run_lab_job()
    assert json.loads((tmp_path/'latest.json').read_text())['status']=='evaluation_failed'


def test_complete_windows_compare_same_periods_and_costs_without_promotion(tmp_path,monkeypatch):
    s=spec(tmp_path)
    idx=pd.date_range('2026-09-28', '2026-10-14',freq='min',inclusive='left',tz='UTC')
    f=pd.DataFrame({k:1.1 for k in ['open','high','low','close','volume']},index=idx)
    seen=[]
    def simulated(frame,h1,d1,settings,**kw):
        held=frame.tail(kw['lookback'])
        seen.append((held.index.min(),held.index.max(),kw['costs'].spread_pips))
        amount=1 if settings.min_confluence==s['candidates'][0]['settings']['min_confluence'] else 2
        result=[]
        for i in range(60):
            ts=held.index[0]+pd.Timedelta(days=i%5,hours=8,minutes=i)
            result.append({'pips':amount,'reason':'target','opened_at':ts,'closed_at':ts+pd.Timedelta(minutes=5)})
        return result,[]
    monkeypatch.setattr(lab,'replay',simulated)
    frames={'M1':f,'H1':f,'D1':f}
    r=lab.evaluate(s,frames,pd.Timestamp('2026-10-14T00:00Z'))
    assert len(seen)==12
    assert all(a>=pd.Timestamp('2026-09-30T00:00Z') for a,b,c in seen)
    assert r['candidates'][0]['status']=='eligible_for_forward_review'
    assert r['candidates'][1]['status']=='rejected'
    assert not r['validated_for_live']
    monkeypatch.setattr(lab,'replay',Mock(side_effect=AssertionError('frozen completed windows cannot be rerun')))
    second=lab.evaluate(s,frames,pd.Timestamp('2026-10-15T00:00Z'),r)
    assert second['runs']==r['runs']


def test_worker_marks_active_generation_failed_for_retry(tmp_path,monkeypatch):
    from src.analysis import strategy_lab_job as job
    monkeypatch.setattr(job,'LAB',tmp_path)
    monkeypatch.setattr(job,'ROOT',tmp_path)
    monkeypatch.setattr(job.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1))
    (tmp_path/'controller.json').write_text('{"active_id":"generation-0001"}')
    job.run_lab_job()
    report=json.loads((tmp_path/'experiments/generation-0001/latest.json').read_text())
    assert report['status']=='evaluation_failed'
