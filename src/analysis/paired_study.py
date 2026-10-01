"""Paired prospective opportunity research. No broker imports or order authority."""
import hashlib,json,math,sqlite3
from pathlib import Path
from datetime import datetime,timezone,timedelta
from statistics import mean
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from src.data.storage import DecisionObservation
from src.analysis.documentation import atomic_write
from src.analysis.exit_plan import payoff
from src.analysis.trade_excursions import timestamp
from src.analysis.measured_archive import load

ROOT=Path(__file__).resolve().parents[2]
DIRECTORY=ROOT/'data/research/paired-study'
VARIANTS=('immediate','confirm','skip','weighted_payoff','shorter_hold','protect')


def code_hash():
    return hashlib.sha256(b''.join(Path(__file__).with_name(n).read_bytes() for n in
        ('paired_study.py','exit_plan.py','measured_archive.py'))).hexdigest()


def registration(directory=DIRECTORY,now=None):
    directory.mkdir(parents=True,exist_ok=True);path=directory/'registration.json'
    if path.exists():return json.loads(path.read_text())
    now=now or datetime.now(timezone.utc)
    spec={'registered_at':now.isoformat(),'source_sha256':code_hash(),
          'confirmation_minutes':5,'slippage_pips':.2,'protect_trigger_r':1.,'protect_lock_r':.25,
          'minimum_pairs':50,'minimum_days':10,'variants':list(VARIANTS),
          'hypotheses':{'weighted_payoff':'Same immediate entry, reject if position-weighted gross target R falls below recorded minimum; unknown fees remain unverified.', 'confirm':'Wait up to five M1 bars for directional close beyond the original signal high/low; enter next bar.',
          'shorter_hold':'Same entry and levels; halve recorded maximum hold.',
          'protect':'Same entry; after 1R favorable movement, tighten next-bar stop to +0.25R.',
          'skip':'Zero exposure comparator; never counted as a winning trade.'},
          'authority':'research_only_no_promotion'}
    with path.open('x') as f:json.dump(spec,f,indent=2)
    return spec


def outcome(p,captured,bars,variant,spec,now):
    if variant=='skip':return {'status':'complete','pips':0.,'traded':False,'reason':'skip'}
    side=p['action'];sign=1 if side=='BUY' else -1
    cfg=p.get('decision_context',{}).get('configuration',{})
    if 'scalp_max_hold_minutes' not in cfg:return {'status':'missing_hold_policy'}
    hold=float(cfg['scalp_max_hold_minutes'])
    if not math.isfinite(hold) or not 0<hold<=1440:return {'status':'invalid_hold'}
    if variant=='shorter_hold':hold=max(1,hold/2)
    start=captured.replace(second=0,microsecond=0)+timedelta(minutes=1)
    def row(ts):return bars.get(ts.isoformat())
    if variant=='confirm':
        original=p.get('decision_context',{}).get('bars',{}).get('signal',{}).get('last_ohlc',{})
        try:level=float(original['high' if sign==1 else 'low'])
        except (KeyError,TypeError,ValueError):return {'status':'missing_confirmation_level'}
        if not math.isfinite(level) or level<=0:return {'status':'missing_confirmation_level'}
        for minute in range(spec['confirmation_minutes']):
            ts=start+timedelta(minutes=minute);r=row(ts)
            if ts+timedelta(minutes=1)>now:return {'status':'pending'}
            if r is None:return {'status':'coverage_gap'}
            op=(float(r['bid']['o'])+float(r['ask']['o']))/2
            cl=(float(r['bid']['c'])+float(r['ask']['c']))/2
            if sign*(cl-op)>0 and sign*(cl-level)>0:
                start=ts+timedelta(minutes=1);break
        else:return {'status':'complete','pips':0.,'traded':False,'reason':'confirmation_expired'}
    r=row(start)
    if start+timedelta(minutes=1)>now:return {'status':'pending'}
    if r is None:return {'status':'coverage_gap'}
    slip=spec['slippage_pips']*.0001
    entry=float(r['ask' if sign==1 else 'bid']['o'])+sign*slip
    stop=float(p['stop_loss']);first=float(p['take_profit_1']);final=float(p['take_profit_2'])
    plan=payoff(side,entry,stop,first,final)
    if plan['status']!='measured_payoff':return {'status':'complete','pips':0.,'traded':False,'reason':'levels_crossed_before_fill'}
    if variant=='weighted_payoff':
        minimum=cfg.get('min_rr_ratio')
        if minimum is None:return {'status':'missing_rr_policy'}
        if plan['weighted_target_r']<float(minimum):
            return {'status':'complete','pips':0.,'traded':False,'reason':'weighted_payoff_below_minimum'}
    remaining=1.;realized=0.;initial_risk=abs(entry-stop);partial=False
    end=start+timedelta(minutes=math.ceil(hold))
    def close(price,reason,ts):
        pips=(realized+remaining*sign*(price-sign*slip-entry))*10000
        return {'status':'complete','traded':True,'pips':pips,'net_pips':None,'reason':reason,
                'opened_at':start.isoformat(),'closed_at':ts.isoformat(),'original_stop_pips':initial_risk*10000,
                'price_r':pips/(initial_risk*10000),'fees_verified':False}
    ts=start
    while ts<end:
        if ts+timedelta(minutes=1)>now:return {'status':'pending'}
        r=row(ts)
        if r is None:return {'status':'coverage_gap'}
        v={k:float(v) for k,v in r['bid' if sign==1 else 'ask'].items()}
        adverse=v['l'] if sign==1 else v['h'];favorable=v['h'] if sign==1 else v['l']
        if sign*(adverse-stop)<=0:
            return close(min(v['o'],stop) if sign==1 else max(v['o'],stop),'stop',ts)
        if not partial and plan['partial_eligible_at_quote'] and sign*(favorable-first)>=0:
            realized+=.5*sign*(first-sign*slip-entry);remaining=.5;partial=True
            stop=entry
            # Conservative same-bar return after partial; ordering is unknowable.
            if sign*(adverse-stop)<=0:return close(stop,'partial_then_breakeven_ambiguous',ts)
        if sign*(favorable-final)>=0:return close(final,'target',ts)
        if variant=='protect' and sign*(favorable-entry)>=spec['protect_trigger_r']*initial_risk:
            protected=entry+sign*spec['protect_lock_r']*initial_risk
            stop=max(stop,protected) if sign==1 else min(stop,protected)
        if ts+timedelta(minutes=1)>=end:return close(v['c'],'time',ts+timedelta(minutes=1))
        ts+=timedelta(minutes=1)
    return {'status':'pending'}


def paired_metrics(rows,variant):
    pairs=[r for r in rows if r['outcomes']['immediate']['status']=='complete' and r['outcomes'][variant]['status']=='complete']
    diffs=[r['outcomes'][variant]['pips']-r['outcomes']['immediate']['pips'] for r in pairs]
    by_day={}
    for r,d in zip(pairs,diffs):by_day.setdefault(r['captured_at'][:10],[]).append(d)
    interval=None
    if len(by_day)>=2:
        import random
        rng=random.Random(7319);days=list(by_day.values());draws=[]
        for _ in range(500):
            sample=[x for day in rng.choices(days,k=len(days)) for x in day]
            draws.append(mean(sample))
        draws.sort();interval=[draws[12],draws[487]]
    return {'pairs':len(pairs),'active_days':len(by_day),'mean_delta_pips':mean(diffs) if diffs else None,
            'day_block_bootstrap_95pct':interval,'unpaired':len(rows)-len(pairs),
            'baseline_trades':sum(bool(r['outcomes']['immediate'].get('traded')) for r in pairs),
            'candidate_trades':sum(bool(r['outcomes'][variant].get('traded')) for r in pairs),
            'baseline_winners_harmed':sum(r['outcomes']['immediate']['pips']>0 and d<0 for r,d in zip(pairs,diffs)),
            'baseline_losses_improved':sum(r['outcomes']['immediate']['pips']<0 and d>0 for r,d in zip(pairs,diffs))}


def run(settings,directory=DIRECTORY,now=None,market=None):
    now=now or datetime.now(timezone.utc);spec=registration(directory,now)
    if spec['source_sha256']!=code_hash():return {'state':'invalidated_source_change','validated_for_live':False}
    bars=load() if market is None else market
    from sqlalchemy.engine import make_url
    dbpath=Path(make_url(settings.database_url).database).resolve()
    engine=create_engine('sqlite://',creator=lambda:sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True))
    rows=[];seen=set();excluded={}
    try:
        with Session(engine) as session:
            query=select(DecisionObservation).where(DecisionObservation.symbol=='EUR/USD',
                DecisionObservation.captured_at>=timestamp(spec['registered_at']).replace(tzinfo=None)).order_by(DecisionObservation.id)
            for obs in session.scalars(query).yield_per(200):
                p=obs.payload;ctx=p.get('decision_context') or {}
                if p.get('action') not in {'BUY','SELL'}:continue
                key=(str(p.get('ts')),p['action'],ctx.get('code_sha256'),ctx.get('configuration_sha256'))
                if key in seen:continue
                seen.add(key)
                if p.get('timeframe')!='M1' or not all(p.get(k) for k in ('stop_loss','take_profit_1','take_profit_2')):
                    excluded['unsupported_or_missing_levels']=excluded.get('unsupported_or_missing_levels',0)+1;continue
                if not key[2] or not key[3] or not p.get('ts'):
                    excluded['missing_lineage']=excluded.get('missing_lineage',0)+1;continue
                captured=obs.captured_at.replace(tzinfo=timezone.utc) if obs.captured_at.tzinfo is None else obs.captured_at
                try:outcomes={v:outcome(p,captured,bars,v,spec,now) for v in VARIANTS}
                except (ValueError,TypeError,KeyError):
                    excluded['malformed_evidence']=excluded.get('malformed_evidence',0)+1;continue
                rows.append({'observation_id':obs.id,'captured_at':captured.isoformat(),'cohort':str(key[2])+':'+str(key[3]),
                    'side':p['action'],'execution_skipped':bool(p.get('skipped')),'skip_reason':p.get('skip_reason'),
                    'outcomes':outcomes})
    finally:engine.dispose()
    cohorts={}
    for cohort in sorted({r['cohort'] for r in rows}):
        subset=[r for r in rows if r['cohort']==cohort]
        cohorts[cohort]={v:paired_metrics(subset,v) for v in VARIANTS if v!='immediate'}
    gates={c:{v:{'sample_floor_met':m['pairs']>=spec['minimum_pairs'] and m['active_days']>=spec['minimum_days'],
        'positive_interval':bool(m['day_block_bootstrap_95pct'] and m['day_block_bootstrap_95pct'][0]>0),
        'promotion_allowed':False} for v,m in comparisons.items()} for c,comparisons in cohorts.items()}
    result={'gates':gates,'hypotheses':spec['hypotheses'],'registered_at':spec['registered_at'],'state':'collecting' if not rows else 'evaluated','finished_at':now.isoformat(),'opportunities':len(rows),
        'cohorts':cohorts,'excluded':excluded,'source_sha256':spec['source_sha256'],'validated_for_live':False,
        'blockers':['No automatic promotion: opportunity study is not a portfolio backtest.',
            'Require at least 50 paired outcomes across 10 days per cohort; uncertainty must exclude zero.',
            'Commission, financing, real fills and broker rejection parity remain unverified.'],
        'limitations':['M1 only; one opportunity per candle/side/code/config. Repeated evaluations deduplicated.',
            'Includes execution-skipped directional setups; not an execution-eligible portfolio.',
            'Positions continue across midnight to exit; no daily forced liquidation. Incomplete paths stay pending or gaps.',
            'Executable bid/ask and 0.2-pip adverse entry/exit scenario; prices after decision only.',
            'Observed gaps exclude pairs; report coverage selection bias. No account-return or causal claim.']}
    atomic_write(directory/'outcomes.json',json.dumps(rows,indent=2))
    atomic_write(directory/'latest.json',json.dumps(result,indent=2))
    atomic_write(ROOT/'desk/PAIRED_STUDY.md','# Paired decision and exit study\n\n'+json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    import argparse
    from src.analysis.research_settings import thaw_settings
    p=argparse.ArgumentParser();p.add_argument('--settings-snapshot',type=Path,required=True)
    p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    cfg=thaw_settings(json.loads(a.settings_snapshot.read_text())).model_copy(update={'database_url':'sqlite:///'+str(a.database.resolve())})
    with a.output.open('x') as f:json.dump(run(cfg),f,indent=2)
