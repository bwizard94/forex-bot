"""Summarize unique live bar decisions, not repeated scanner observations."""
from collections import Counter
from datetime import timedelta
from sqlalchemy import select
from src.data.storage import SignalRow


def decision_health(session, now):
    rows = session.scalars(select(SignalRow).where(
        SignalRow.source == 'live', SignalRow.symbol == 'EUR/USD',
        SignalRow.ts >= now-timedelta(hours=24), SignalRow.ts <= now)).all()
    reasons = Counter()
    directional = 0
    for row in rows:
        if row.action not in {'BUY', 'SELL'}:
            continue
        directional += 1
        if not row.skipped:
            continue
        reason = (row.skip_reason or '').lower()
        category = ('Entry price/quality' if reason.startswith('entry quality:') else
                    'Spread/cost' if 'spread' in reason else
                    'Quote freshness' if 'stale' in reason or 'bid/ask' in reason else
                    'Paused' if 'paused' in reason else
                    'Other risk/session rules')
        reasons[category] += 1
    return {'window_hours': 24, 'unique_bar_decisions': len(rows),
            'directional_setups': directional, 'holds': len(rows)-directional,
            'blocked_setups': sum(reasons.values()),
            'blockers': [{'reason': k, 'count': v} for k,v in reasons.most_common()],
            'note': 'Latest saved decision per bar; passing a gate does not confirm a fill.'}
