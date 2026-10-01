"""Independent exploratory cost matrix; never edits registered experiments."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import pandas as pd
from src.analysis.compare_strategies import load_frames, complete_m5
from src.analysis.replay import performance, ReplayCosts
from src.analysis.diagnostic_replay import replay
from src.analysis.research_settings import freeze_settings, thaw_settings
from src.analysis.execution_assumptions import ExecutionAssumptions
from src.analysis.signals import evaluate_signal
from src.analysis.strategy_lab import source_hashes
from src.config import Settings

SCENARIOS = ((1.2, .1), (1.6, .2), (1.8, .2), (2.5, .5), (3., 1.))


def stress(frames, settings, evaluator=None, assumptions=None):
    tf = settings.signal_timeframe
    if tf not in {'M1','M5'}: raise ValueError('Diagnostic replay supports M1/M5 only')
    frame = frames['M1'] if tf=='M1' else complete_m5(frames['M1'])
    assumptions = assumptions or ExecutionAssumptions()
    if len(frame) < 92:
        raise ValueError('Need at least 92 completed signal-timeframe bars')
    evaluator = evaluator or evaluate_signal
    cache = {}
    def cached(*args, **kwargs):
        key = args[2].index[-1]
        if key not in cache:
            cache[key] = evaluator(*args, **kwargs)
        return copy.copy(cache[key])
    report = {'validated_for_live': False, 'timeframe': tf,
              'settings_snapshot': freeze_settings(settings),
              'market_evidence': {'mode':'measured_bid_ask' if assumptions.market_bars is not None else 'synthetic_spread', 'timeframe':assumptions.market_timeframe,'bars':len(assumptions.market_bars or {}), 'sha256':hashlib.sha256(json.dumps(assumptions.market_bars,sort_keys=True).encode()).hexdigest()},
              'execution_assumptions': {'commission_pips_roundtrip':assumptions.commission_pips_roundtrip,
                 'long_carry_pips_per_day':assumptions.long_carry_pips_per_day,
                 'short_carry_pips_per_day':assumptions.short_carry_pips_per_day,
                 'events':list(assumptions.events),'rollovers':list(assumptions.rollovers),'initial_nav_usd':assumptions.initial_nav_usd,'commission_structure':assumptions.commission_structure,'provenance':assumptions.provenance},
              'source_hashes': source_hashes(),
              'diagnostic_source_hashes': {p:hashlib.sha256(Path(__file__).with_name(p).read_bytes()).hexdigest() for p in ('diagnostic_replay.py','execution_assumptions.py','research_settings.py')},
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'input_sha256': {k: hashlib.sha256(v.to_csv().encode()).hexdigest() for k,v in frames.items()},
              'coverage': {'bars':len(frame), 'start':str(frame.index[0]), 'end':str(frame.index[-1])},
              'limitations': ['Exploratory observed history, not an untouched holdout.',
                             'Costs may block entries and change trade selection; aggregate P/L need not decrease monotonically.',
                             'Midpoint or measured executable OHLC; no broker rejection or learned gates; simulated USD sizing is not an exact adaptive account ledger.',
                             'News only from supplied point-in-time events; carry is a continuous scenario rate, not broker rollover accounting.'], 'runs': []}
    scenarios = SCENARIOS if assumptions.market_bars is None else ((0,.1),(0,.2),(0,.5))
    for spread, slip in scenarios:
        run = {'scenario': f'measured-spread-slippage-{slip}' if assumptions.market_bars is not None else f'spread-{spread}-slippage-{slip}', 'spread_pips': spread, 'slippage_pips': slip}
        try:
            diagnostics = {}
            rows, _ = replay(frame, frames['H1'], frames['D1'], settings, timeframe=tf,
                             lookback=len(frame), max_trades=len(frame), costs=ReplayCosts(spread,slip), evaluator=cached, diagnostics=diagnostics, assumptions=assumptions)
            run.update(status='complete', diagnostics=diagnostics, metrics=performance(rows),
                       completed_metrics=performance([r for r in rows if r['reason'] != 'end_of_data']), trades=rows)
        except Exception as exc:
            run.update(status='error', error=f'{type(exc).__name__}: {exc}')
        report['runs'].append(run)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New JSON file; refuses overwrite')
    parser.add_argument('--settings-snapshot', type=Path, help='Frozen active-process allowlist')
    parser.add_argument('--assumptions', type=Path, help='Explicit commission, carry and point-in-time event JSON')
    parser.add_argument('--bars', type=int, default=2000)
    args = parser.parse_args()
    if args.bars < 92:
        parser.error('--bars must be at least 92')
    # Reserve output before expensive analysis, preventing accidental overwrite.
    with args.output.open('x') as handle:
        try:
            frames = load_frames(args.database, pd.Timestamp.now(tz='UTC'))
            frames['M1'] = frames['M1'].tail(args.bars)
            settings = thaw_settings(json.loads(args.settings_snapshot.read_text())) if args.settings_snapshot else Settings(_env_file=None,signal_timeframe='M1')
            assumptions = ExecutionAssumptions(**json.loads(args.assumptions.read_text())) if args.assumptions else None
            if assumptions is not None and assumptions.market_bars:
                from dataclasses import replace
                measured={pd.Timestamp(k):v for k,v in assumptions.market_bars.items()}
                # Bound to measured coverage, but never silently drop interior missing bars.
                a,b=min(measured),max(measured)
                frames['M1']=frames['M1'].loc[(frames['M1'].index>=a)&(frames['M1'].index<=b)]
                if settings.signal_timeframe=='M5':
                    aggregated={}
                    for ts in complete_m5(frames['M1']).index:
                        chunk=[measured.get(ts+pd.Timedelta(minutes=i)) for i in range(5)]
                        if any(r is None for r in chunk):continue
                        aggregated[str(ts)]={side:{'o':rows[0]['o'],'h':max(float(r['h']) for r in rows),
                            'l':min(float(r['l']) for r in rows),'c':rows[-1]['c']}
                            for side in ('bid','ask') for rows in [[r[side] for r in chunk]]}
                    assumptions=replace(assumptions,market_bars=aggregated,market_timeframe='M5')
            result = stress(frames, settings, assumptions=assumptions)
            result['settings_snapshot']['origin'] = 'active_process_allowlist' if args.settings_snapshot else 'repository_defaults_with_process_environment' 
        except Exception as exc:
            json.dump({'status':'error','error':f'{type(exc).__name__}: {exc}'},handle)
            raise
        json.dump(result, handle, indent=2, default=str, allow_nan=False)
    if any(r['status']=='error' for r in result['runs']):
        parser.exit(1, 'Some scenarios failed; error evidence retained.\n')


if __name__ == '__main__':
    main()
