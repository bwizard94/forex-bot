"""Pre-registered entry/exit hypotheses; a separate frozen prospective experiment."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from src.analysis.documentation import atomic_write
from src.analysis.research_settings import freeze_settings, thaw_settings
from src.analysis.strategy_lab import source_hashes, assess
from src.analysis.replay import performance, ReplayCosts
from src.analysis.diagnostic_replay import replay
from src.analysis.compare_strategies import complete_m5

ROOT=Path(__file__).resolve().parents[2]
DIRECTORY=ROOT/'data/research/policy-experiments'


def hashes():
    return source_hashes() | {name:hashlib.sha256((ROOT/'src/analysis'/name).read_bytes()).hexdigest()
        for name in ('policy_experiments.py','diagnostic_replay.py','execution_assumptions.py','research_settings.py','promotion_review.py')}


def register(settings, now, directory=DIRECTORY):
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'registration.json'
    if path.exists(): return json.loads(path.read_text())
    now=pd.Timestamp(now)
    if now.tzinfo is None:raise ValueError('Registration requires timezone')
    spec={'registered_at':now.isoformat(),'start':(now.normalize()+pd.Timedelta(days=1)).isoformat(),
          'end':(now.normalize()+pd.Timedelta(days=22)).isoformat(),'source_hashes':hashes(),
          'baseline':freeze_settings(settings),'minimum_completed_trades':50,'minimum_active_days':5,
          'bootstrap_seed':7319,'spreads':[1.6,1.8],'windows':3,'window_days':7,
          'candidates':[{'name':'confirmed-entry','changes':{'confirmed_entry_policy':True},
                         'hypothesis':'Test local confirmation rather than acting on higher-timeframe alignment alone.'},
                        {'name':'shorter-hold','changes':{'scalp_max_hold_minutes':max(5,settings.scalp_max_hold_minutes//2)},
                         'hypothesis':'Test whether an earlier time exit reduces adverse persistence; giveback is not yet established.'}],
          'validated_for_live':False}
    # Refuse reset or clobber of an existing registration.
    with path.open('x') as out:json.dump(spec,out,indent=2)
    return spec


def evaluate(spec, frames, now, previous=None):
    """One completed-day/candidate/cost chunk per bounded worker invocation."""
    now=pd.Timestamp(now);end=pd.Timestamp(spec['end']);start=pd.Timestamp(spec['start'])
    if spec['source_hashes']!=hashes():return {'status':'invalidated_source_change','validated_for_live':False}
    if now<start+pd.Timedelta(days=1):return {'status':'collecting_prospective_evidence','start':spec['start'],'end':spec['end'],'validated_for_live':False}
    runs=list((previous or {}).get('chunks',[]))
    settings=thaw_settings(spec['baseline']);tf=settings.signal_timeframe
    data=frames['M1'] if tf=='M1' else complete_m5(frames['M1'])
    completed={(r['day'],r['candidate'],r['spread_pips']) for r in runs}
    candidates=[{'name':'baseline','changes':{}}]+spec['candidates']
    for day in range(21):
        a=start+pd.Timedelta(days=day);b=a+pd.Timedelta(days=1)
        if now<b:break
        for spread in spec['spreads']:
            for c in candidates:
                if (day,c['name'],spread) in completed:continue
                held=data.loc[(data.index>=a)&(data.index<b)]
                warm=data.loc[data.index<a].tail(180)
                if held.empty:
                    runs.append({'day':day,'candidate':c['name'],'spread_pips':spread,'trades':[],'coverage':'no_bars'})
                elif len(warm)<90:
                    return {'status':'insufficient_warmup','chunks':runs,'validated_for_live':False}
                else:
                    frame=pd.concat([warm,held])
                    rows,_=replay(frame,frames['H1'],frames['D1'],settings.model_copy(update=c['changes']),
                                  timeframe=tf,lookback=len(held),max_trades=len(frame),costs=ReplayCosts(spread,.2))
                    rows=[r for r in rows if pd.Timestamp(r['opened_at'])>=a and r['reason']!='end_of_data']
                    runs.append({'day':day,'candidate':c['name'],'spread_pips':spread,'trades':rows,'coverage':'observed_bars'})
                return {'status':'evaluating_completed_days','chunks':runs,'completed_chunks':len(runs),'required_chunks':126,'validated_for_live':False}
    if len(runs)<126:return {'status':'collecting_prospective_evidence','chunks':runs,'completed_chunks':len(runs),'required_chunks':126,'validated_for_live':False}
    assessments=[]
    for window in range(3):
        a=start+pd.Timedelta(days=window*7);b=a+pd.Timedelta(days=7)
        for spread in spec['spreads']:
            def rows(name):
                return [t for r in runs if window*7<=r['day']<(window+1)*7 and r['candidate']==name and r['spread_pips']==spread for t in r['trades']]
            reference=rows('baseline')
            for c in spec['candidates']:
                assessments.append({'candidate':c['name'],'window':window,'spread_pips':spread,
                                    'assessment':assess(rows(c['name']),reference,spec,a,b)})
    eligible=[c['name'] for c in spec['candidates'] if all(r['assessment']['passed'] for r in assessments if r['candidate']==c['name'])]
    return {'status':'forward_review_required' if eligible else 'no_candidate_passed','eligible':eligible,
            'runs':assessments,'chunks':runs,'source_hashes':spec['source_hashes'],'validated_for_live':False,
            'limitations':['Three seven-day prospective windows; the third is forward shadow confirmation.',
                           'Each daily replay starts flat; forced daily endings are censored. Results are not continuous-account returns.',
                           'Missing bars remain coverage gaps; costs and full execution parity must pass separate review.']}


def job(settings):
    """Fast while collecting; evaluation delegates to the bounded research worker."""
    from src.analysis.compare_strategies import load_frames
    from sqlalchemy.engine import make_url
    now=pd.Timestamp.now(tz='UTC');spec=register(settings,now)
    if (DIRECTORY/'result.json').exists() and spec['source_hashes']==hashes():return json.loads((DIRECTORY/'result.json').read_text())
    frames={} if now<pd.Timestamp(spec['start'])+pd.Timedelta(days=1) else load_frames(Path(make_url(settings.database_url).database),now)
    previous=json.loads((DIRECTORY/'latest.json').read_text()) if (DIRECTORY/'latest.json').exists() else None
    result=evaluate(spec,frames,now,previous)
    from src.analysis.promotion_review import save_plan
    save_plan(spec,result,DIRECTORY/'promotion')
    atomic_write(DIRECTORY/'latest.json',json.dumps(result,indent=2,default=str))
    if result['status'] in {'forward_review_required','no_candidate_passed'}:
        atomic_write(DIRECTORY/'result.json',json.dumps(result,indent=2,default=str))
    atomic_write(ROOT/'desk/POLICY_EXPERIMENTS.md','# Prospective entry/exit experiments\n\n'+json.dumps({k:v for k,v in result.items() if k not in {'runs','chunks'}},indent=2)+'\n\nNo execution promotion. Registration and prior results are immutable.\n')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--settings-snapshot',type=Path,required=True)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    settings=thaw_settings(json.loads(args.settings_snapshot.read_text())).model_copy(update={'database_url':'sqlite:///'+str(args.database.resolve())})
    result=job(settings)
    with args.output.open('x') as out:json.dump(result,out,indent=2,default=str)
