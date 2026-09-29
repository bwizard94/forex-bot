"""Frozen exploratory candidates on a shared local history; no broker clients."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import pandas as pd
from src.analysis.replay import replay, performance, ReplayCosts
from src.analysis.signals import evaluate_signal
from src.config import Settings

CANDIDATES = (
    ('M1-current', 'M1', 5.0, .35),
    ('M5-baseline', 'M5', 5.0, .25),
    ('M5-wider-setup', 'M5', 8.0, .25),
)


def complete_m5(m1):
    groups=m1.resample('5min',closed='left',label='left')
    bars=groups.agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
    return bars.loc[groups['close'].count()==5].dropna()


def load_frames(path, now):
    frames={}
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True) as c:
        for tf,minutes in [('M1',1),('H1',60),('D1',1440)]:
            f=pd.read_sql_query("SELECT ts,open,high,low,close,volume FROM bars WHERE symbol='EUR/USD' AND timeframe=? AND source='oanda' ORDER BY ts",c,params=(tf,))
            f.index=pd.to_datetime(f.pop('ts'),utc=True)
            frames[tf]=f.loc[f.index+pd.Timedelta(minutes=minutes)<=now]
    return frames


def compare(frames, progress=print):
    m1=frames['M1'];m5=complete_m5(m1)
    if len(m5)<300: raise ValueError('Need 300 complete M5 bars from the shared M1 history')
    split=m5.index[int(len(m5)*.7)]
    out={'validated_for_live':False,'split_at':str(split),'candidate_specs':CANDIDATES,
         'selection':'No live promotion. Every result remains exploratory.',
         'limitations':['Same observed M1 history; M5 bars require all five minutes.',
                        'Constant spread/slippage; not historical executable quotes.',
                        'No event-news, broker rejection, learned-gate, portfolio, sizing, financing or commission model.',
                        'Missing intervals are not reconstructed. Gap stop simulation cannot recover unseen intragap paths.',
                        'Preliminary chronological holdout only; no parameter tuning on this holdout.',
                        'Positive results with few trades are not evidence of a reliable edge.'],
         'coverage':{},'runs':[]}
    for tf,f in [('M1',m1),('M5',m5)]:
        duration=pd.Timedelta(minutes=1 if tf=='M1' else 5)
        out['coverage'][tf]={'bars':len(f),'start':str(f.index[0]),'end':str(f.index[-1]),
             'gaps':int((f.index.to_series().diff()>duration).sum()),
             'sha256':hashlib.sha256(f.to_csv().encode()).hexdigest()}
    for name,tf,stop,cost_limit in CANDIDATES:
        settings=Settings(_env_file=None,signal_timeframe=tf,min_stop_pips=stop,cost_stop_fraction=cost_limit,
                          practice_sampling_enabled=False)
        frame=m1 if tf=='M1' else m5
        train=frame.loc[frame.index<split]
        held=frame.loc[frame.index>=split]
        warm=frame.loc[frame.index<split].iloc[-180:]
        cache={}
        def cached(*args,**kwargs):
            f=args[2];key=(str(f.index[0]),str(f.index[-1]),len(f))
            if key not in cache: cache[key]=evaluate_signal(*args,**kwargs)
            return copy.copy(cache[key])
        for spread in (1.6,1.8):
            for label,f,lookback in [('development',train,len(train)),('holdout',pd.concat([warm,held]),len(held))]:
                progress(f'{name} {label} spread={spread}',flush=True)
                rows,_=replay(f,frames['H1'],frames['D1'],settings,timeframe=tf,
                             costs=ReplayCosts(spread,.2),lookback=lookback,max_trades=len(f),evaluator=cached)
                uncensored=[r for r in rows if r['reason']!='end_of_data']
                out['runs'].append({'candidate':name,'timeframe':tf,'period':label,'spread_pips':spread,
                    'metrics':performance(rows),'completed_metrics':performance(uncensored),'trades':rows})
    out['source_sha256']={p:hashlib.sha256(Path(__file__).with_name(p).read_bytes()).hexdigest()
                           for p in ['compare_strategies.py','replay.py','signals.py','indicators.py']}
    return out


def main():
    now=pd.Timestamp.now(tz='UTC')
    frames=load_frames(Path('data/forex_bot.db'),now)
    report=compare(frames)
    directory=Path('data/research/strategy-comparison');directory.mkdir(parents=True,exist_ok=True)
    path=directory/(now.strftime('%Y%m%dT%H%M%SZ')+'.json')
    path.write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# Strategy comparison — '+str(now),'','Exploratory only. No live strategy changes.','',
           '| Candidate | Period | Spread | Trades excluding forced endings | Mean pips | Net pips |',
           '| --- | --- | ---: | ---: | ---: | ---: |']
    for r in report['runs']:
        m=r['completed_metrics']
        lines.append(f"| {r['candidate']} | {r['period']} | {r['spread_pips']} | {m['trades']} | {m['expectancy_pips']:.2f} | {m['net_pips']:.2f} |")
    lines.extend(['','## Limitations','',*('- '+x for x in report['limitations']), '',
                  f'Full results and input/source fingerprints: `{path}`',''])
    md=Path('desk/STRATEGY_COMPARISON.md');md.write_text('\n'.join(lines))
    print(f'Wrote {path} and {md}. No automatic promotion.')


if __name__=='__main__': main()
