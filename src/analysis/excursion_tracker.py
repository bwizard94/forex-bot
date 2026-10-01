"""Observe executable quotes; never mutate orders, stops or original risk."""
from datetime import datetime, timezone
from sqlalchemy import select
from src.analysis.context_report import number
from src.analysis.loss_attribution import utc
from src.data.storage import Trade, TradeJournal, session_scope


def update_excursion(trade, journal, quote, now, max_age=90):
    if trade.source!='bot' or trade.venue!='oanda' or trade.parent_trade_id is not None or trade.status not in {'open','partial'}: return False
    if str(getattr(quote,'source','')).lower()!='oanda' or not getattr(quote,'tradeable',False):return False
    ts=utc(quote.ts)
    if ts is None or not 0 <= (now-ts).total_seconds() <= max_age: return False
    if not trade.opened_at or ts<utc(trade.opened_at): return False
    bid,ask=number(quote.bid),number(quote.ask)
    if bid is None or ask is None or not 0<bid<=ask: return False
    ctx=dict(journal.entry_context or {});risk=ctx.get('initial_risk') or {}
    fill=number(risk.get('fill'));stop=number(risk.get('stop_pips'))
    if risk.get('basis')!='entry_snapshot' or fill is None or fill<=0 or stop is None or stop<=0:return False
    previous=dict(ctx.get('sampled_excursion') or {})
    if previous.get('last_quote_at') and ts<=datetime.fromisoformat(previous['last_quote_at']):return False
    mark=bid if trade.side=='BUY' else ask
    pips=(mark-fill)*10000*(1 if trade.side=='BUY' else -1)
    gap=(ts-datetime.fromisoformat(previous['last_quote_at'])).total_seconds() if previous.get('last_quote_at') else (ts-utc(trade.opened_at)).total_seconds()
    previous.update(mfe_pips=max(previous.get('mfe_pips',0),pips,0),
                    mae_pips=max(previous.get('mae_pips',0),-pips,0),
                    first_quote_at=previous.get('first_quote_at',ts.isoformat()),last_quote_at=ts.isoformat(),
                    samples=previous.get('samples',0)+1,max_sample_gap_seconds=max(previous.get('max_sample_gap_seconds',0),gap),
                    basis='sampled_executable_quote_lower_bound',last_mark_pips=pips)
    previous['mfe_r']=previous['mfe_pips']/stop;previous['mae_r']=previous['mae_pips']/stop
    ctx['sampled_excursion']=previous;journal.entry_context=ctx
    return True


def observe(pipeline):
    from src.execution.trade_guard import classify_remote_trade
    with pipeline._lock:
        quotes=dict(pipeline._quotes)
        owned={str(t['id']) for t in getattr(pipeline,'_remote_open',[]) if classify_remote_trade(t)=='bot'}
        now=datetime.now(timezone.utc)
        updated=eligible=0
        with session_scope() as session:
            pairs=session.execute(select(Trade,TradeJournal).join(TradeJournal,TradeJournal.trade_id==Trade.id)
                .where(Trade.symbol=='EUR/USD',Trade.status.in_(['open','partial']))).all()
            for t,j in pairs:
                q=quotes.get(t.symbol)
                if q is not None and str(t.broker_trade_id) in owned:
                    eligible+=1
                    updated+=int(update_excursion(t,j,q,now,pipeline.settings.stale_quote_seconds))

    import json
    from src.analysis.documentation import atomic_write
    from src.analysis.research_jobs import REPORTS
    atomic_write(REPORTS/'excursions-status.json',json.dumps({'state':'observing',
        'finished_at':now.isoformat(),'eligible_open_trades':eligible,'updated_trades':updated,
        'note':'Fresh executable samples only; missing risk and missed ticks are not reconstructed.'}))
