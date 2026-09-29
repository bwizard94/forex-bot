import json
import pandas as pd
from src.analysis import continuous_lab as ctl
from src.config import Settings

NOW=pd.Timestamp('2026-09-29T18:00Z')


def setup(tmp_path):
    return ctl.advance(tmp_path,Settings(_env_file=None,signal_timeframe='M5'),NOW)


def test_restart_preserves_active_cutoff(tmp_path):
    state,path=setup(tmp_path)
    before=(path/'experiment.json').read_text()
    later,again=ctl.advance(tmp_path,Settings(_env_file=None),NOW+pd.Timedelta(hours=6))
    assert later['generation']==1 and path==again
    assert (path/'experiment.json').read_text()==before


def test_rejection_automatically_registers_fresh_different_candidates(tmp_path):
    state,path=setup(tmp_path)
    old=json.loads((path/'experiment.json').read_text())
    ctl.write_json(path/'latest.json',{'status':'all_candidates_rejected',
        'candidates':[{'name':c['name'],'status':'rejected','reasons':['negative_edge']} for c in old['candidates'][1:]]})
    now=NOW+pd.Timedelta(days=15)
    state,new=ctl.advance(tmp_path,Settings(_env_file=None),now)
    spec=json.loads((new/'experiment.json').read_text())
    assert state['generation']==2 and new!=path
    assert spec['registered_at']==now.isoformat()
    assert state['history'][0]['research_winner'] is None
    assert state['history'][0]['candidates'][0]['outcome']['reasons']==['negative_edge']
    oldkeys={ctl.fingerprint(c['settings']) for c in old['candidates'][1:]}
    assert all(ctl.fingerprint(c['settings']) not in oldkeys for c in spec['candidates'][1:])
    assert (path/'experiment.json').exists()


def test_success_adapts_research_reference_only(tmp_path):
    state,path=setup(tmp_path)
    old=json.loads((path/'experiment.json').read_text());win=old['candidates'][1]
    ctl.write_json(path/'latest.json',{'status':'forward_review_required',
        'candidates':[{'name':win['name'],'status':'eligible_for_forward_review','reasons':[]}],
        'runs':[{'candidate':win['name'],'window':w,'spread_pips':spread,'assessment':{'passed':True,'lower_daily_improvement_99pct':1}} for w in range(2) for spread in (1.6,1.8)]})
    state,new=ctl.advance(tmp_path,Settings(_env_file=None),NOW+pd.Timedelta(days=15))
    spec=json.loads((new/'experiment.json').read_text())
    assert spec['candidates'][0]['settings']==win['settings']
    assert state['history'][0]['research_winner']==win['name']
    assert state['history'][0]['validated_for_live'] is False
    assert spec['validated_for_live'] is False
    assert 'risk_per_trade_pct' not in state['research_reference']


def test_source_change_restarts_with_fresh_cutoff_not_reused_evidence(tmp_path,monkeypatch):
    state,path=setup(tmp_path)
    monkeypatch.setattr(ctl.lab,'source_hashes',lambda:{'new':'source'})
    now=NOW+pd.Timedelta(hours=6)
    state,new=ctl.advance(tmp_path,Settings(_env_file=None),now)
    assert state['history'][0]['reason']=='source_changed'
    assert json.loads((new/'experiment.json').read_text())['registered_at']==now.isoformat()
    assert not (new/'evidence.json').exists()


def test_incomplete_data_cannot_stall_forever_or_select_winner(tmp_path):
    state,path=setup(tmp_path)
    ctl.write_json(path/'latest.json',{'status':'collecting_prospective_evidence'})
    state,new=ctl.advance(tmp_path,Settings(_env_file=None),NOW+pd.Timedelta(days=16))
    assert state['generation']==2
    assert state['history'][0]['reason']=='insufficient_evidence_at_deadline'
    assert state['history'][0]['research_winner'] is None


def test_failed_worker_retries_same_experiment(tmp_path):
    state,path=setup(tmp_path)
    ctl.write_json(path/'latest.json',{'status':'evaluation_failed'})
    state,new=ctl.advance(tmp_path,Settings(_env_file=None),NOW+pd.Timedelta(days=16))
    assert path==new and state['generation']==1


def test_incomplete_success_report_cannot_adapt_reference(tmp_path):
    state,path=setup(tmp_path)
    old=json.loads((path/'experiment.json').read_text());win=old['candidates'][1]
    ctl.write_json(path/'latest.json',{'status':'forward_review_required',
        'candidates':[{'name':win['name'],'status':'eligible_for_forward_review'}],'runs':[]})
    state,new=ctl.advance(tmp_path,Settings(_env_file=None),NOW+pd.Timedelta(days=15))
    assert state['history'][0]['research_winner'] is None
    assert 'research_reference' not in state
