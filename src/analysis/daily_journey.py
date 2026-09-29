"""Daily evidence-led activity journal, including days with no fills."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select
from src.data.storage import SignalRow, Trade, TradeJournal


def render_daily_journey(session, day):
    start=datetime.combine(day,datetime.min.time(),tzinfo=timezone.utc)
    end=start+timedelta(days=1)
    signals=session.scalars(select(SignalRow).where(SignalRow.source=='live',
        SignalRow.symbol=='EUR/USD',SignalRow.ts>=start,SignalRow.ts<end)).all()
    trades=session.scalars(select(Trade).where(Trade.source=='bot',Trade.venue=='oanda',
        Trade.parent_trade_id.is_(None),Trade.symbol=='EUR/USD',Trade.status=='closed',
        Trade.closed_at>=start,Trade.closed_at<end)).all()
    directional=[s for s in signals if s.action in {'BUY','SELL'}]
    blocked=[s for s in directional if s.skipped]
    holds=[s for s in signals if s.action=='HOLD']
    blockers=Counter(s.skip_reason or 'Unspecified' for s in blocked)
    hold_reasons=Counter(s.reason or 'Unspecified' for s in holds)
    pl=sum((Decimal(str(t.realized_pl)) for t in trades),Decimal(0))
    lines=[f'# Trading journey — {day.isoformat()} UTC','',
           'Latest saved live decision per bar; repeat scans are not extra opportunities.', '',
           '## Activity','',f'- Saved bar decisions: {len(signals)}',
           f'- Directional setups: {len(directional)}; blocked: {len(blocked)}; HOLD: {len(holds)}',
           f'- Confirmed primary bot closes: {len(trades)}; price P/L: {pl}',
           'Financing is separate. Human and mirrored trades are excluded. These are daily closes, not complete account returns.', '',
           '## Why the bot did not enter','']
    for reason,count in blockers.most_common(10): lines.append(f'- {count}: {reason}')
    if not blockers: lines.append('No blocked directional setups recorded.')
    lines.extend(['','## Why the strategy waited',''])
    for reason,count in hold_reasons.most_common(10): lines.append(f'- {count}: {reason}')
    if not holds: lines.append('No HOLD decisions recorded.')
    lines.extend(['','## Outcomes and recorded lessons',''])
    for t in trades:
        j=session.scalar(select(TradeJournal).where(TradeJournal.trade_id==t.id))
        lines.extend([f'### [Trade {t.id}](../trade-{t.id}.md)','',
                      f'Price P/L: {t.realized_pl}; close reason: {t.close_reason or "unknown"}',
                      f'Went right: {j.what_went_right if j and j.what_went_right else "Not recorded."}',
                      f'Went wrong: {j.what_went_wrong if j and j.what_went_wrong else "Not recorded."}',
                      f'Lesson: {j.lesson if j and j.lesson else "Not recorded."}',
                      f'Improvement to test: {j.how_to_avoid if j and j.how_to_avoid else "Not recorded."}',''])
    if not trades: lines.append('No confirmed primary bot closes today. There is no new realized-outcome evidence to claim learning from.')
    lines.extend(['','## Next review','',
                  'Compare outcomes by policy/version, side and session after costs. Investigate the most frequent blocker; do not remove it solely to increase trade count.',
                  'These are recorded facts and deterministic interpretations, not proven causes or automatic strategy changes.',''])
    return '\n'.join(lines)
