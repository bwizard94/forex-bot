import json
from types import SimpleNamespace
import fcntl
import subprocess
import pandas as pd
import pytest
from src.config import Settings
from src.analysis.research_settings import freeze_settings, thaw_settings
from src.analysis.diagnostic_replay import replay
from src.analysis.replay import ReplayCosts
from src.analysis.execution_assumptions import ExecutionAssumptions
from src.analysis.context_report import compare_versions
from src.analysis import research_jobs
from test_replay_execution import frame
from test_research_priorities import signal


def settings(**kw):
    return Settings(_env_file=None,**kw)


def test_snapshot_secrets_tampering_and_environment(monkeypatch):
    original=settings(signal_timeframe='M1',risk_per_trade_pct=.01,oanda_api_token='DO_NOT_EXPORT')
    snap=freeze_settings(original)
    assert 'DO_NOT_EXPORT' not in json.dumps(snap)
    monkeypatch.setenv('RISK_PER_TRADE_PCT','0.009')
    assert thaw_settings(snap).risk_per_trade_pct==.01
    snap['configuration']['risk_per_trade_pct']=.008
    with pytest.raises(ValueError): thaw_settings(snap)


def run(side='BUY', assumptions=None, **kw):
    diagnostics={}
    f=frame(95)
    rows,_=replay(f,None,None,settings(**kw),evaluator=lambda *a,**k:signal(side),
                  costs=ReplayCosts(0,0),diagnostics=diagnostics,assumptions=assumptions)
    return rows,diagnostics


def test_multiple_positions_caps_and_diagnostics():
    rows,d=run(max_open_positions=2,max_same_side_positions=2,addon_min_profit_pips=0)
    assert len(rows)==2 and d['accepted_entries']==2
    assert d['rejections']['position_cap']==2
    assert d['directional_signals']==d['accepted_entries']+sum(d['rejections'].values())
    rows,d=run(max_open_risk_pct=.006,risk_per_trade_pct=.006,max_same_side_positions=3,addon_min_profit_pips=0)
    assert len(rows)==1 and d['rejections']['open_risk_cap']==3


def test_news_only_blocks_when_previously_known():
    event={'ts':'2026-09-21T13:35:00Z','known_at':'2026-09-21T12:00:00Z','currency':'USD','impact':'High'}
    rows,d=run(assumptions=ExecutionAssumptions(events=(event,)))
    assert rows==[] and d['rejections']['news_blackout']==4
    event=dict(event,known_at='2026-09-22T00:00:00Z')
    rows,d=run(assumptions=ExecutionAssumptions(events=(event,)))
    assert rows and d['rejections']['news_blackout']==0


def test_commission_and_signed_carry_no_double_charge():
    rows,d=run(max_open_positions=1,assumptions=ExecutionAssumptions(
        commission_pips_roundtrip=.4,long_carry_pips_per_day=-24))
    assert len(rows)==1
    # Entry bar 91 to exit bar 94: fifteen minutes, at -1 pip/hour.
    assert rows[0]['gross_pips']==pytest.approx(0)
    assert rows[0]['financing_pips']==pytest.approx(-.25)
    assert rows[0]['pips']==pytest.approx(-.65)


def test_rejection_all_checks_explain_cost_filters():
    d={}
    rows,_=replay(frame(),None,None,settings(),evaluator=lambda *a,**k:signal('BUY'),
                  costs=ReplayCosts(4,0),diagnostics=d)
    assert rows==[] and d['all_failed_checks']['spread_cap']==3


def test_comparisons_match_context_and_flag_small_samples():
    def row(version,side='BUY',samples=3):
        return dict(code_sha256=version,configuration_sha256='c',timeframe='M1',side=side,session='London',htf_bias='bullish',
                    performance={'r_samples':samples,'mean_r':.2 if version=='a' else -.1})
    result=compare_versions([row('a'),row('b'),row('c','SELL')])
    assert len(result)==1 and result[0]['evidence_status']=='insufficient_samples'
    assert result[0]['mean_r_difference_b_minus_a']==pytest.approx(-.3)
    assert compare_versions([row('unknown'),row('b')])==[]


def test_worker_lock_timeout_and_success(tmp_path,monkeypatch):
    monkeypatch.setattr(research_jobs,'ROOT',tmp_path)
    root=tmp_path/'reports';root.mkdir()
    with (root/'attribution.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert research_jobs.run_report('attribution',settings(),root)['state']=='already_running'
    def timeout(*a,**k):raise subprocess.TimeoutExpired('worker',120)
    monkeypatch.setattr(research_jobs.subprocess,'run',timeout)
    assert research_jobs.run_report('attribution',settings(),root)['state']=='failed'
    def success(command,**kw):
        from pathlib import Path
        assert kw['timeout']==120
        Path(command[command.index('--output')+1]).write_text(json.dumps({'contextual_attribution':{'closed_trades':2,'groups':[]}}))
    monkeypatch.setattr(research_jobs.subprocess,'run',success)
    assert research_jobs.run_report('attribution',settings(),root)['state']=='complete'
    assert research_jobs.read_status(root)['attribution']['summary']['closed_trades']==2


def test_calendar_archive_first_seen_not_backdated(tmp_path):
    event=SimpleNamespace(title='CPI',country='USD',impact='High',ts=pd.Timestamp('2026-09-21T00:00:00Z'))
    pipe=SimpleNamespace(news=SimpleNamespace(_bundle=SimpleNamespace(events=[event])))
    research_jobs.archive_calendar(pipe,tmp_path)
    p=next((tmp_path/'calendar').glob('*.json'));first=p.read_text()
    research_jobs.archive_calendar(pipe,tmp_path)
    assert p.read_text()==first
    assert pd.Timestamp(json.loads(first)[0]['known_at'])>event.ts


def test_scheduler_cadence_and_overlap(monkeypatch):
    from src import main
    cfg=settings()
    monkeypatch.setattr(main,'get_settings',lambda:cfg)
    scheduler=main._build_scheduler(SimpleNamespace(settings=cfg))
    jobs={j.id:j for j in scheduler.get_jobs()}
    assert jobs['diagnostic_attribution'].trigger.interval.total_seconds()==3600
    assert jobs['diagnostic_costs'].trigger.interval.total_seconds()==21600
    assert jobs['research_calendar_archive'].trigger.interval.total_seconds()==300
    for name in ('diagnostic_attribution','diagnostic_costs'):
        assert jobs[name].max_instances==1 and jobs[name].coalesce


def test_diagnostic_replay_retains_core_execution_semantics():
    f=frame()
    f.iloc[91,f.columns.get_loc('high')]=1.2
    f.iloc[91,f.columns.get_loc('low')]=1.
    rows,_=replay(f,None,None,settings(max_open_positions=1),
                  evaluator=lambda *a,**k:signal('BUY'),costs=ReplayCosts(0,0),max_trades=1)
    assert rows[0]['opened_at']==f.index[91]
    assert rows[0]['reason']=='stop' and rows[0]['pips']==pytest.approx(-20)


def test_settings_allowlist_covers_direct_signal_inputs():
    import ast
    from pathlib import Path
    from src.analysis.research_settings import NAMES
    tree=ast.parse(Path('src/analysis/signals.py').read_text())
    used={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='settings'}
    assert used <= NAMES


def test_status_compaction_cache_freshness_and_corruption(tmp_path, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from pathlib import Path
    stamp=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
    p=tmp_path/'experiments-status.json'
    p.write_text(json.dumps({'state':'complete','finished_at':stamp}))
    costs=tmp_path/'costs-status.json'
    reasons={f'reason-{i}':i+1 for i in range(100)}
    costs.write_text(json.dumps({'state':'complete','summary':[{'rejections':{'hold_reasons':reasons}}]}))
    research_jobs._status_file.cache_clear()
    first=research_jobs.read_status(tmp_path)
    assert first['experiments']['stale']
    details=first['costs']['summary'][0]['rejections']
    assert research_jobs.compact_diagnostics(details)==details
    assert len(details['hold_reasons'])==10
    assert sum(details['hold_reasons'].values())+details['hold_reasons_omitted_count']==sum(reasons.values())
    first['costs']['summary'].clear()
    assert research_jobs.read_status(tmp_path)['costs']['summary']
    assert research_jobs._status_file.cache_info().hits>=2
    replacement=tmp_path/'replacement';replacement.write_text('{"state":"failed"}')
    replacement.replace(p)
    assert research_jobs.read_status(tmp_path)['experiments']['state']=='failed'
    p.write_text('[]')
    assert research_jobs.read_status(tmp_path)['experiments']['state']=='unavailable'
    p.write_text('{"finished_at":"2026-10-01T00:00:00"}')
    assert research_jobs.read_status(tmp_path)['experiments']['state']=='unavailable'
