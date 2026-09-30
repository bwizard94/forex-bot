"""Frozen prospective strategy experiments. No broker client or promotion authority."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.analysis.compare_strategies import complete_m5, load_frames
from src.analysis.documentation import atomic_write
from src.analysis.replay import ReplayCosts, performance, replay
from src.analysis.signals import evaluate_signal
from src.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / 'data/research/strategy-lab'
FIELDS = '''signal_timeframe ema_fast ema_slow rsi_period atr_period bb_period bb_std
session_filter trade_session_start_hour trade_session_end_hour require_htf_trend
min_atr_pips min_stop_pips scalp_max_spread_pips scalp_max_hold_minutes
friday_flat_hour monday_open_skip_minutes max_fill_slippage_pips cost_stop_fraction
min_rr_ratio min_confluence confirmed_entry_policy atr_sl_multiplier atr_tp1_multiplier atr_tp2_multiplier
htf_bias_timeframe trading_style oanda_environment practice_broker_market_hours'''.split()
SOURCES = ['analysis/strategy_lab.py', 'analysis/replay.py', 'analysis/signals.py', 'analysis/entry_confirmation.py',
           'analysis/continuous_lab.py',
           'analysis/indicators.py', 'analysis/mistakes.py', 'analysis/compare_strategies.py',
           'data/datasets.py', 'utils.py']


def source_hashes():
    return {p: hashlib.sha256((ROOT/'src'/p).read_bytes()).hexdigest() for p in SOURCES}


def register(settings, now, directory=LAB):
    """A restart cannot move the cutoff or retune a registered candidate."""
    path = directory/'experiment.json'
    if path.exists():
        return json.loads(path.read_text())
    from src.analysis.sampling import sampling_policy
    base = {k: getattr(settings, k) for k in FIELDS}
    base['cost_stop_fraction'] = sampling_policy(settings, now.to_pydatetime())['cost_stop_fraction']
    candidates = [
        {'name': 'reference', 'settings': base, 'hypothesis': 'Unchanged entry strategy at registration'},
        {'name': 'stronger-confluence', 'settings': dict(base, min_confluence=base['min_confluence']+1),
         'hypothesis': 'Require one more supporting signal to reduce weak entries'},
        {'name': 'wider-stop', 'settings': dict(base, min_stop_pips=8.0),
         'hypothesis': 'Test whether more stop distance improves results after costs'},
    ]
    spec = {'registered_at': now.isoformat(), 'source_hashes': source_hashes(),
            'candidates': candidates, 'window_days': 7, 'windows': 2,
            'minimum_completed_trades': 50, 'minimum_active_days': 5,
            'spreads': [1.6, 1.8], 'slippage': .2, 'bootstrap_seed': 7319,
            'validated_for_live': False}
    atomic_write(path, json.dumps(spec, indent=2)+'\n')
    return spec


def assess(candidate, reference, spec, start, end):
    """Evaluate equal-weight pips with paired day blocks, never account returns."""
    candidate = [r for r in candidate if r['reason'] != 'end_of_data']
    reference = [r for r in reference if r['reason'] != 'end_of_data']
    metrics = performance(candidate)
    reasons = []
    if len(candidate) < spec['minimum_completed_trades']:
        reasons.append('insufficient_completed_trades')
    active = {pd.Timestamp(r['closed_at']).date() for r in candidate}
    if len(active) < spec['minimum_active_days']:
        reasons.append('insufficient_active_days')
    if not candidate or metrics['expectancy_pips'] <= 0:
        reasons.append('no_positive_expectancy_after_modeled_costs')
    # Include zero-trade days so frequency differences do not disappear.
    days = pd.date_range(start.normalize(), end.normalize(), inclusive='left', tz='UTC')
    def totals(rows):
        grouped = {}
        for r in rows:
            day = pd.Timestamp(r['closed_at']).normalize()
            grouped[day] = grouped.get(day, 0.) + float(r['pips'])
        return np.array([grouped.get(day, 0.) for day in days])
    values, baseline = totals(candidate), totals(reference)
    if not np.isfinite(values).all() or not np.isfinite(baseline).all():
        raise ValueError('Non-finite research outcomes')
    rng = np.random.default_rng(spec['bootstrap_seed'])
    draws = rng.integers(0, len(days), size=(4000, len(days)))
    lower = float(np.quantile(values[draws].mean(axis=1), .01))
    delta_lower = float(np.quantile((values-baseline)[draws].mean(axis=1), .01))
    if lower <= 0:
        reasons.append('positive_daily_edge_not_established')
    if delta_lower <= 0:
        reasons.append('improvement_over_reference_not_established')
    base_metrics = performance(reference)
    if reference and metrics['max_drawdown_pips'] > base_metrics['max_drawdown_pips']:
        reasons.append('drawdown_worse_than_reference')
    return {'metrics': metrics, 'reference_metrics': base_metrics,
            'lower_daily_pips_99pct': lower, 'lower_daily_improvement_99pct': delta_lower,
            'reasons': reasons, 'passed': not reasons}


def evaluate(spec, frames, now, previous=None, checkpoint=None):
    start = pd.Timestamp(spec['registered_at'])
    # UTC midnight gives equal complete calendar-day blocks; registration day is excluded.
    start = start.normalize() + pd.Timedelta(days=1)
    frame = complete_m5(frames['M1']) if spec['candidates'][0]['settings']['signal_timeframe']=='M5' else frames['M1']
    result = {'registered_at': spec['registered_at'], 'evaluated_at': now.isoformat(),
              'evaluation_starts_at': start.isoformat(), 'validated_for_live': False,
              'status': 'collecting_prospective_evidence', 'runs': [], 'candidates': [],
              'note': 'Research screen only; passing requires a separate forward-practice review. No automatic promotion.',
              'limitations': ['Fixed spread/slippage midpoint OHLC approximation; excludes news, commissions, financing, portfolio and learned gates.',
                             'Daily bootstrap is an uncertainty screen, not proof; days may remain correlated.',
                             'Incomplete windows cannot qualify. Forced end closes are excluded.',
                             'Pip results are equally weighted, not account returns.']}
    for window in range(spec['windows']):
        a = start + pd.Timedelta(days=spec['window_days']*window)
        b = a + pd.Timedelta(days=spec['window_days'])
        if now < b:
            continue
        saved = [r for r in (previous or {}).get('runs', []) if r['window']==window]
        if len(saved)==len(spec['candidates'])*len(spec['spreads']):
            result['runs'].extend(saved)
            continue
        warm = frame.loc[frame.index<a].tail(300)
        held = frame.loc[(frame.index>=a)&(frame.index<b)]
        if len(warm)<90 or held.empty:
            continue
        inputs = pd.concat([warm, held])
        cache = {}
        rows_by_key = {}
        for candidate in spec['candidates']:
            name = candidate['name']
            settings = SimpleNamespace(**candidate['settings'])
            def cached(*args, **kwargs):
                f=args[2]; key=(name,str(f.index[0]),str(f.index[-1]),len(f))
                if key not in cache: cache[key]=evaluate_signal(*args,**kwargs)
                return copy.deepcopy(cache[key])
            for spread in spec['spreads']:
                retained = next((r for r in saved if r['candidate']==name and r['spread_pips']==spread), None)
                if retained is not None:
                    rows_by_key[(name,spread)] = retained['trades']
                    result['runs'].append(retained)
                    continue
                rows,_ = replay(inputs, frames['H1'], frames['D1'], settings,
                    timeframe=settings.signal_timeframe, lookback=len(held), max_trades=len(held),
                    costs=ReplayCosts(spread,spec['slippage']), evaluator=cached,
                    entry_history=300, h1_history=250, d1_history=180)
                # Exclude trades crossing a missing-price interval: their path is unknowable.
                duration = pd.Timedelta(minutes=5 if settings.signal_timeframe=='M5' else 1)
                gaps = held.index[held.index.to_series().diff()>duration]
                clean = [r for r in rows if not any(r['opened_at']<g<=r['closed_at'] for g in gaps)]
                rows_by_key[(name,spread)] = clean
                result['runs'].append({'candidate': name, 'window': window, 'start': str(a), 'end': str(b),
                    'spread_pips': spread, 'excluded_gap_trades': len(rows)-len(clean),
                    'input_sha256': hashlib.sha256(inputs.to_csv().encode()).hexdigest(),
                    'context_sha256': {tf: hashlib.sha256(frames[tf].loc[frames[tf].index<b].to_csv().encode()).hexdigest()
                                       for tf in ('H1','D1')},
                    'trades': clean, 'assessment': assess(clean,rows_by_key[('reference',spread)],spec,a,b)})
                if checkpoint:
                    checkpoint(result)
    for candidate in spec['candidates'][1:]:
        runs = [r for r in result['runs'] if r['candidate']==candidate['name']]
        complete = len(runs)==spec['windows']*len(spec['spreads'])
        passed = complete and all(r['assessment']['passed'] for r in runs)
        result['candidates'].append({'name':candidate['name'],
            'status': 'eligible_for_forward_review' if passed else ('rejected' if complete else 'collecting'),
            'reasons': sorted({reason for r in runs for reason in r['assessment']['reasons']})})
    if result['candidates'] and all(c['status']!='collecting' for c in result['candidates']):
        result['status'] = 'forward_review_required' if any(c['status']=='eligible_for_forward_review' for c in result['candidates']) else 'all_candidates_rejected'
    return result


def read_status(directory=LAB):
    try:
        report = json.loads((directory/'latest.json').read_text())
        result = {k: v for k,v in report.items() if k not in {'runs','source_hashes'}}
        checked = pd.Timestamp(result['evaluated_at'])
        if checked.tzinfo is None or (pd.Timestamp.now(tz='UTC')-checked).total_seconds()>8*3600:
            result['status'] = 'evaluation_stale'
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return {'status':'not_evaluated', 'validated_for_live':False,
                'note':'No validated improvement is available.'}


def run(directory=LAB):
    settings=get_settings()
    now=pd.Timestamp.now(tz='UTC')
    spec=register(settings,now,directory)
    if spec['source_hashes']!=source_hashes():
        result={'status':'source_changed_requires_new_experiment','validated_for_live':False,
                'evaluated_at':now.isoformat(), 'note':'Frozen code changed. Do not reuse this holdout for a changed strategy.'}
    else:
        if not settings.database_url.startswith('sqlite:///'):
            raise ValueError('Strategy lab currently requires SQLite')
        frames=load_frames(Path(settings.database_url.removeprefix('sqlite:///')),now)
        try:
            previous=json.loads((directory/'evidence.json').read_text())
        except (OSError, ValueError):
            previous=None
        def checkpoint(report):
            atomic_write(directory/'evidence.json',json.dumps(report,indent=2,default=str)+'\n')
        result=evaluate(spec,frames,now,previous,checkpoint)
        atomic_write(directory/'evidence.json',json.dumps(result,indent=2,default=str)+'\n')
    atomic_write(directory/'latest.json',json.dumps(result,indent=2,default=str)+'\n')
    atomic_write(directory/'runs'/f'{now.strftime("%Y%m%dT%H%M%S%fZ")}.json',json.dumps(result,indent=2,default=str)+'\n')
    lines=['# Strategy learning status','',f'Status: **{result["status"]}**', '',
           'Automatic execution promotion: **disabled**. Software uptime does not establish strategy quality.', '',
           result.get('note',''),'',f'Last evaluation: {now.isoformat()}', '',
           'Frozen specification: `data/research/strategy-lab/experiment.json`.',
           'Versioned evidence: `data/research/strategy-lab/runs/`.','']
    for c in result.get('candidates',[]):
        lines.append(f'- {c["name"]}: {c["status"]}; '+(', '.join(c['reasons']) or 'waiting for complete prospective windows'))
    atomic_write(ROOT/'desk/STRATEGY_LEARNING_STATUS.md','\n'.join(lines)+'\n')
    return result


if __name__=='__main__':
    print(json.dumps({k:v for k,v in run().items() if k!='runs'},default=str))
