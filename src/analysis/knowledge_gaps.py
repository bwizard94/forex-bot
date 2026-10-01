"""Evidence completeness inventory, never a trading signal."""
from sqlalchemy import select
from src.data.storage import Trade,TradeJournal


def inventory(session):
    rows=session.execute(select(Trade,TradeJournal).join(TradeJournal,TradeJournal.trade_id==Trade.id)
        .where(Trade.symbol=='EUR/USD',Trade.source=='bot',Trade.venue=='oanda',Trade.parent_trade_id.is_(None),Trade.status=='closed')).all()
    missing={'original_risk':0,'policy_identity':0,'final_executable_quote':0,'sampled_excursion':0,'holding_policy':0}
    for t,j in rows:
        c=j.entry_context or {};d=c.get('decision_evidence') or {};r=c.get('initial_risk') or {}
        missing['original_risk']+=int(r.get('basis')!='entry_snapshot' or not r.get('amount'))
        missing['policy_identity']+=int(not d.get('code_sha256') or not d.get('configuration_sha256'))
        missing['final_executable_quote']+=int(not (d.get('final_entry_quality') or {}).get('quote_at'))
        missing['sampled_excursion']+=int(not c.get('sampled_excursion'))
        missing['holding_policy']+=int('scalp_max_hold_minutes' not in (d.get('configuration') or {}))
    return {'local_closed_primary_bot_trades':len(rows),'missing':missing,
            'required_next':['Verify fees and financing independently before claiming net expectancy.',
                'Keep legacy broker research separate when execution journals or original risk are absent.',
                'Record original policy, quote, holding period and sampled path on future trades; never invent legacy fields.'],
            'limitations':['Local ledger scope only; not a broker completeness certification.',
                           'Presence is not proof of accuracy; sampled paths are incomplete.'],
            'execution_authority':False}
