"""Autonomous research lifecycle; research champions never authorize broker orders."""
from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path

import pandas as pd

from src.analysis import strategy_lab as lab
from src.analysis.documentation import atomic_write
from src.config import get_settings

TERMINAL = {'all_candidates_rejected', 'forward_review_required'}


def read_json(path, fallback=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return fallback


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2, default=str)+'\n')


def fingerprint(settings):
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def propose(base, history):
    """Bounded hypotheses. No risk, sizing, execution, or cost assumptions are tuned."""
    tried = {c['fingerprint'] for h in history for c in h.get('candidates', [])}
    choices = []
    if not base.get('confirmed_entry_policy', False):
        confirmation = dict(base, confirmed_entry_policy=True)
        choices.append({'name':'confirmed-reversals', 'settings':confirmation,
                        'fingerprint':fingerprint(confirmation),
                        'hypothesis':'Test local reversal confirmation and fresh post-loss entries on prospective data; diagnostic late-period evidence was negative'})
    for stop in (5., 6., 8., 10.):
        for confluence in sorted({base['min_confluence'], min(10, base['min_confluence']+1),
                                  min(10, base['min_confluence']+2)}):
            if not 1 <= confluence <= 10:
                continue
            settings = dict(base, min_stop_pips=stop, min_confluence=confluence)
            key = fingerprint(settings)
            if key == fingerprint(base):
                continue
            choices.append({'name': f'stop-{stop:g}-confluence-{confluence}', 'settings': settings,
                            'fingerprint':key,
                            'hypothesis':'Test stop distance and required confluence on new prospective data'})
    # Previously rejected versions are retained, with unused hypotheses tried first.
    choices.sort(key=lambda c: (c['fingerprint'] in tried,
                               abs(c['settings']['min_stop_pips']-base['min_stop_pips'])+
                               abs(c['settings']['min_confluence']-base['min_confluence'])))
    return choices[:2]


def finish(state, spec, report, reason, now):
    """Update only the simulated research reference, never execution settings."""
    accepted = []
    if reason == 'completed' and spec['source_hashes'] == lab.source_hashes():
        accepted = [c for c in report.get('candidates', []) if c['status']=='eligible_for_forward_review']
        expected = {(w,s) for w in range(spec['windows']) for s in spec['spreads']}
        accepted = [c for c in accepted if
                    {(r['window'],r['spread_pips']) for r in report.get('runs',[]) if r['candidate']==c['name']}==expected
                    and all(r['assessment']['passed'] for r in report['runs'] if r['candidate']==c['name'])]
    winner = None
    if accepted:
        def score(c):
            values=[r['assessment']['lower_daily_improvement_99pct'] for r in report['runs']
                    if r['candidate']==c['name']]
            return min(values) if values else float('-inf')
        winner = max(accepted, key=score)['name']
        chosen = next(c for c in spec['candidates'] if c['name']==winner)
        state['research_reference'] = chosen['settings']
        state['reference_source_hashes'] = spec['source_hashes']
    state['history'].append({'experiment_id':state['active_id'], 'finished_at':now.isoformat(),
        'reason':reason, 'status':report.get('status','no_complete_evaluation'),
        'research_winner':winner, 'validated_for_live':False,
        'candidates':[{'name':c['name'],'fingerprint':fingerprint(c['settings']),
                       'outcome':next((r for r in report.get('candidates',[]) if r['name']==c['name']),
                                      {'status':'insufficient_evidence'})}
                      for c in spec['candidates'][1:]]})
    state['active_id'] = None


def advance(directory, settings, now):
    """Crash-resumable registration and rollover. Cutoffs only move in new versions."""
    state_path=directory/'controller.json'
    state=read_json(state_path, {'active_id':None, 'generation':0, 'history':[]})
    if state['active_id']:
        active=directory/'experiments'/state['active_id']
        spec=read_json(active/'experiment.json')
        report=read_json(active/'latest.json', {})
        end=pd.Timestamp(spec['registered_at']).normalize()+pd.Timedelta(days=1+spec['window_days']*spec['windows'])
        reason = None
        if spec['source_hashes'] != lab.source_hashes():
            reason='source_changed'
        elif report.get('status') in TERMINAL:
            reason='completed'
        # Give the worker one full scheduling interval to finish a just-ended window.
        elif now >= end+pd.Timedelta(hours=12) and report.get('status')=='collecting_prospective_evidence':
            reason='insufficient_evidence_at_deadline'
        if reason:
            finish(state,spec,report,reason,now)
    if not state['active_id']:
        state['generation']+=1
        state['active_id']=f"generation-{state['generation']:04d}"
        active=directory/'experiments'/state['active_id']
        spec=lab.register(settings,now,active)
        base=spec['candidates'][0]['settings']
        if state.get('reference_source_hashes')==lab.source_hashes():
            base=state['research_reference']
        candidates=propose(base,state['history'])
        spec['candidates']=[{'name':'reference','settings':base,'hypothesis':'Frozen research reference'}]+candidates
        spec['generation']=state['generation']
        spec['reference_kind']='simulation_only'
        write_json(active/'experiment.json',spec)
    write_json(state_path,state)
    return state,active


def run(directory=lab.LAB):
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'controller.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status':'already_running','validated_for_live':False}
        now=pd.Timestamp.now(tz='UTC')
        state,active=advance(directory,get_settings(),now)
        # Legacy single-experiment files are preserved untouched; new generations
        # start with future data and never claim that legacy history is unseen.
        result=lab.run(active)
        result.update({'autonomous_research':True,'generation':state['generation'],
            'experiment_id':state['active_id'],
            'archived_experiments':len(state['history']),
            'invalidated_experiments':sum(h.get('reason')=='source_changed' for h in state['history']),
            'completed_experiments':sum(h.get('reason')=='completed' and h.get('status') in TERMINAL for h in state['history']),
            'research_champion_only':True,
            'next_action':'Automatically evaluate, archive outcomes, and register the next experiment; no operator prompt required.',
            'execution_policy':('New orders disabled by research-only mode. ' if get_settings().strategy_research_only else 'Operator-authorized practice trading; existing risk gates apply. ')+ 'Simulated selection cannot change broker settings or enable orders.'})
        write_json(directory/'latest.json',result)
        lines=['# Autonomous strategy learning','',f"Generation: **{state['generation']}** · status: **{result['status']}**",'',
               'Runs at startup and every six hours. New experiments start automatically after completion or invalidation.',
               result['execution_policy'], '',
               f"Last evaluation: {result['evaluated_at']}", '',
               f"Completed evaluations: {result['completed_experiments']}; invalidated: {result['invalidated_experiments']}; archived: {result['archived_experiments']}",
               '', '## Experiment history', '']
        for h in state['history']:
            lines.append(f"- {h['experiment_id']}: {h['reason']}; research winner: {h['research_winner'] or 'none'}")
            for c in h['candidates']:
                lines.append(f"  - {c['name']}: {c['outcome']['status']}; "+', '.join(c['outcome'].get('reasons',[])))
        if not result['completed_experiments']:
            lines.append('No completed prospective experiment yet. No improvement has been established.')
        lines.extend(['','Experiment specifications and evidence: `data/research/strategy-lab/experiments/`.',
                      'Persistent controller and outcome history: `data/research/strategy-lab/controller.json`.',''])
        atomic_write(lab.ROOT/'desk/STRATEGY_LEARNING_STATUS.md','\n'.join(lines))
        return {k:v for k,v in result.items() if k!='runs'}


if __name__=='__main__':
    print(json.dumps(run(),default=str))
