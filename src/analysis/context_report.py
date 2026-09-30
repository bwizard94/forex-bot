"""Descriptive matched-context attribution, with explicit missing evidence."""
from collections import defaultdict
import math
from src.analysis.growth import _desk_closed, _score, hour_bucket


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def contextual_report(session):
    groups = defaultdict(list)
    costs = defaultdict(list)
    paired, _ = _desk_closed(session, 'EUR/USD')
    for journal, trade in paired:
        if (trade is None or trade.status != 'closed' or trade.source != 'bot'
                or trade.venue != 'oanda' or trade.parent_trade_id is not None):
            continue
        ctx = journal.entry_context or {}
        evidence = ctx.get('decision_evidence') or {}
        config = evidence.get('configuration') or {}
        key = (evidence.get('code_sha256') or 'unknown',
               evidence.get('configuration_sha256') or 'unknown',
               config.get('signal_timeframe') or 'unknown', trade.side,
               hour_bucket(trade.opened_at) if trade.opened_at else 'unknown',
               journal.htf_bias or 'unknown')
        groups[key].append(journal)
        quote = evidence.get('quote') or {}
        bid, ask = number(quote.get('bid')), number(quote.get('ask'))
        spread = (ask-bid)*10000 if bid is not None and ask is not None and 0 < bid <= ask else None
        risk = ctx.get('initial_risk') or {}
        stop = number(risk.get('stop_pips')) if risk.get('basis') == 'entry_snapshot' else None
        ratio = spread/stop if spread is not None and stop is not None and stop > 0 else None
        fill = number(trade.fill_price)
        executable = ask if trade.side == 'BUY' else bid
        slip = ((fill-executable)*10000*(1 if trade.side == 'BUY' else -1)
                if fill is not None and fill > 0 and executable is not None and executable > 0 else None)
        costs[key].append((spread, ratio, slip))
    rows = []
    for key, journals in sorted(groups.items()):
        row = dict(zip(('code_sha256','configuration_sha256','timeframe','side','session','htf_bias'), key))
        row['performance'] = _score(journals, key='context', scope='descriptive').as_dict()
        row['recorded_closed_trades'] = len(journals)
        for i, name in enumerate(('entry_spread_pips','spread_to_initial_stop','quote_to_fill_adverse_pips')):
            values = [c[i] for c in costs[key] if c[i] is not None]
            row[name] = {'samples': len(values), 'missing': len(journals)-len(values),
                         'mean': sum(values)/len(values) if values else None}
        rows.append(row)
    return {'comparisons': compare_versions(rows), 'groups': rows, 'closed_trades': sum(len(v) for v in groups.values()),
            'validated_for_live': False,
            'limitations': ['Compare versions only within matching timeframe, side, session and higher-timeframe bias; groups are not randomized.',
                           'Quote-to-fill includes latency and price movement since the decision quote; it is not isolated broker slippage.',
                           'Costs are diagnostic, never subtracted again from realized P/L. Financing and commission coverage is not certified.',
                           'Unknown evidence remains unknown; small groups do not establish an edge.']}


def compare_versions(rows, minimum_samples=30):
    """Pair only matched recorded contexts; no automatic winner or promotion."""
    from itertools import combinations
    contexts = defaultdict(list)
    for row in rows:
        key=tuple(row[k] for k in ('timeframe','side','session','htf_bias'))
        if 'unknown' not in key:
            contexts[key].append(row)
    result=[]
    for key, group in sorted(contexts.items()):
        for a,b in combinations(group,2):
            if a['code_sha256']=='unknown' or b['code_sha256']=='unknown': continue
            if a['configuration_sha256']=='unknown' or b['configuration_sha256']=='unknown': continue
            if (a['code_sha256'],a['configuration_sha256'])==(b['code_sha256'],b['configuration_sha256']): continue
            pa,pb=a['performance'],b['performance']
            enough=min(pa['r_samples'],pb['r_samples'])>=minimum_samples
            result.append({'context':dict(zip(('timeframe','side','session','htf_bias'),key)),
                'a':a,'b':b,'minimum_r_samples_per_group':minimum_samples,
                'evidence_status':'descriptive_only' if enough else 'insufficient_samples',
                'mean_r_difference_b_minus_a':pb['mean_r']-pa['mean_r'] if pa['mean_r'] is not None and pb['mean_r'] is not None else None,
                'warning':'Different dates and costs remain confounders; this is not a causal comparison or promotion test.'})
    return result
