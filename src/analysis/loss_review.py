"""Evidence-led loss review. A losing outcome alone does not identify a cause."""
import math


def review_loss(trade, journal):
    context=journal.entry_context or {}
    risk=context.get('initial_risk') or {}
    evidence=context.get('decision_evidence') or {}
    quality=evidence.get('final_entry_quality') or {}
    def number(value):
        try:
            x=float(value)
            return x if math.isfinite(x) else None
        except (TypeError,ValueError):return None
    pl=number(journal.realized_pl)
    facts=[];tests=[];unknown=[]
    facts.append(f'Recorded price P/L: {pl}' if pl is not None else 'Price P/L unavailable')
    facts.append(f'Recorded exit reason: {journal.close_reason or "unknown"}')
    if journal.close_reason in (None, '', 'broker_closed'):
        unknown.append('Precise broker exit mechanism is not established by the local close-reason label')
    amount=number(risk.get('amount')) if risk.get('basis')=='entry_snapshot' and risk.get('currency')=='USD' else None
    ratio=abs(pl)/amount if pl is not None and pl<0 and amount and amount>0 else None
    if ratio is not None:
        facts.append(f'Loss / original planned stop risk: {ratio:.2f}R')
        if ratio>1.05:tests.append('Reconcile stop fill, gaps and partial exits against broker transactions; loss exceeded the original risk snapshot')
    else:unknown.append('Comparable original USD risk snapshot unavailable')
    slip=number(getattr(trade,'slippage_pips',None))
    if slip is not None:
        facts.append(f'Recorded entry slippage: {slip:.2f} pips')
        if slip>0:tests.append('Reconcile recorded entry slippage with fill direction and the entry allowance; do not attribute it to the signal strategy')
    else:unknown.append('Entry slippage unavailable')
    bid,ask,stop=number(quality.get('bid')),number(quality.get('ask')),number(risk.get('stop_pips'))
    cost=None
    if trade.symbol=='EUR/USD' and bid and ask and ask>=bid and stop and stop>0:
        cost=(ask-bid)*10000/stop
        facts.append(f'Quoted entry spread / original stop distance: {cost:.1%}')
        tests.append('Compare cost burden across comparable entries; spread is a cost, not proof of why price reversed')
    else:unknown.append('Entry spread/stop comparison unavailable')
    unknown.append('Signal failure versus ordinary losing-trade variance is not established by this outcome')
    tests.append('Compare the same timeframe, policy, session and market conditions with both winners and losers on fresh data')
    return {'version':1,'classification':'loss_requires_context' if pl is not None and pl<0 else 'non_loss',
            'facts':facts,'hypotheses_to_test':tests,'unknowns':unknown,'loss_r':ratio,
            'spread_stop_fraction':cost,'cause_proven':False,
            'recommendation':'Check current execution and market conditions; do not suspend a side or strategy solely because prior trades lost'}
