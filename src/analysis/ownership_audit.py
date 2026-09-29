"""Repair legacy imported closed-trade attribution using broker GET evidence only."""
from sqlalchemy import select
from src.data.storage import Trade, TradeJournal
from src.execution.trade_guard import classify_remote_trade
from src.utils import utcnow


def reconcile_legacy_closed_ownership(session, broker):
    result = {"checked": 0, "corrected": 0, "deferred": 0}
    candidates = session.scalars(select(Trade).where(
        Trade.status == "closed", Trade.source == "bot", Trade.venue == "oanda",
        Trade.signal_id.is_(None), Trade.parent_trade_id.is_(None),
    )).all()
    for trade in candidates:
        result["checked"] += 1
        try:
            row = broker.trade_details(str(trade.broker_trade_id))
            if (str(row.get("id")) != str(trade.broker_trade_id)
                    or row.get("state") != "CLOSED"
                    or row.get("instrument") != trade.symbol.replace("/", "_")):
                result["deferred"] += 1
                continue
        except Exception:
            result["deferred"] += 1
            continue
        if classify_remote_trade(row) == "bot":
            continue
        trade.source = "human"
        journal = session.scalar(select(TradeJournal).where(TradeJournal.trade_id == trade.id))
        if journal is not None:
            context = dict(journal.entry_context or {})
            context["ownership_audit"] = {"checked_at": utcnow().isoformat(),
                "previous_source": "bot", "source": "human",
                "reason": "Broker closed-trade record has no fs- ownership stamp; no local entry signal."}
            journal.entry_context = context
        result["corrected"] += 1
    session.flush()
    return result
