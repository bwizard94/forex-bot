"""Winner/loser comparisons and overlapping exposure; observations, not causes."""
from collections import defaultdict
from datetime import timezone
from src.analysis.growth import _desk_closed, _score, hour_bucket
from src.analysis.context_report import number


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def loss_attribution(session):
    paired,trades=_desk_closed(session,'EUR/USD')
    book=[t for t in trades.values() if t.source=='bot' and t.venue=='oanda' and t.parent_trade_id is None]
    groups=defaultdict(list)
    evidence=[]
    for j,t in paired:
        if t is None or t not in book or t.status!='closed': continue
        ctx=j.entry_context or {};d=ctx.get('decision_evidence') or {};q=d.get('quote') or {}
        risk=ctx.get('initial_risk') or {};stop=number(risk.get('stop_pips')) if risk.get('basis')=='entry_snapshot' else None
        bid,ask=number(q.get('bid')),number(q.get('ask'))
        burden=(ask-bid)*10000/stop if bid and ask and ask>=bid and stop and stop>0 else None
        opened=utc(t.opened_at)
        overlap=None if opened is None else sum(1 for other in book if other.id!=t.id and utc(other.opened_at)
            and (utc(other.opened_at),other.id)<(opened,t.id)
            and (other.closed_at is None or utc(other.closed_at)>opened))
        dimensions={'side':t.side,'session':hour_bucket(t.opened_at) if opened else 'unknown',
                    'htf_bias':j.htf_bias or 'unknown','setup':j.fingerprint or 'unknown',
                    'overlap_at_entry':'unknown' if overlap is None else str(overlap),
                    'spread_stop_fraction':'unknown' if burden is None else ('<=0.15' if burden<=.15 else '<=0.25' if burden<=.25 else '>0.25')}
        for dimension,value in dimensions.items():groups[(dimension,value)].append(j)
        excursion=ctx.get('sampled_excursion') or {}
        amount=number(risk.get('amount')) if risk.get('basis')=='entry_snapshot' and risk.get('currency')=='USD' else None
        pl=number(j.realized_pl)
        policy_id=(str(d['code_sha256'])+':'+str(d['configuration_sha256'])) if d.get('code_sha256') and d.get('configuration_sha256') else None
        evidence.append({'policy_id':policy_id,'realized_r':pl/amount if pl is not None and amount and amount>0 else None,'trade_id':t.id,'realized_pl':number(j.realized_pl),'outcome':j.outcome,
                         'overlap_at_entry':overlap,'spread_stop_fraction':burden,
                         'sampled_mfe_r':excursion.get('mfe_r'),'sampled_mae_r':excursion.get('mae_r'),
                         'initial_risk_usd':number(risk.get('amount')) if risk.get('basis')=='entry_snapshot' and risk.get('currency')=='USD' else None})
    rows=[]
    for (dimension,value),items in sorted(groups.items()):
        rows.append({'dimension':dimension,'value':value,'all':_score(items,key=value,scope=dimension).as_dict(),
                     'winners':_score([j for j in items if j.outcome=='win'],key=value,scope=dimension).as_dict(),
                     'losers':_score([j for j in items if j.outcome=='loss'],key=value,scope=dimension).as_dict()})
    from src.analysis.promotion_review import rollback_assessment
    current_policy=next((t['policy_id'] for t in reversed(evidence) if t['policy_id']),None)
    watch=rollback_assessment([t for t in evidence if t['policy_id']==current_policy]) if current_policy else {'state':'unknown_policy'}
    return {'rollback_watch':watch,'groups':rows,'trades':evidence,'validated_for_live':False,
            'limitations':['Dimensions overlap; never sum different dimensions as separate losses.',
                           'Dollar losses and original-risk R answer different questions; sizing can dominate dollar comparisons.',
                           'Trade overlap is recorded exposure, not proof that overlapping trades caused losses.',
                           'Quote-sampled excursions are lower bounds on actual intratrade extremes; legacy missing paths stay unknown.']}
