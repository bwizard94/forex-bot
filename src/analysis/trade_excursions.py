"""Read-only historical bid/ask reconstruction; excludes partial boundary bars."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import oandapyV20.endpoints.instruments as instruments


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def price(value):
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError('Invalid candle price')
    return result


def fetch_window(client, start, end):
    """Daily chunks stay below the broker's 5,000-candle response limit."""
    rows = {}
    cursor = start.replace(second=0, microsecond=0)
    end = end.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while cursor < end:
        until = min(cursor + timedelta(days=1), end)
        data = client.request(instruments.InstrumentsCandles('EUR_USD', params={
            'price': 'BA', 'granularity': 'M1', 'from': cursor.isoformat(),
            'to': until.isoformat(), 'smooth': False}))
        if data.get('instrument') != 'EUR_USD' or data.get('granularity') != 'M1':
            raise ValueError('Unexpected candle response')
        for row in data['candles']:
            ts = timestamp(row['time'])
            if not cursor <= ts < until:
                raise ValueError('Candle outside requested interval')
            if ts in rows:
                raise ValueError('Duplicate candle')
            rows[ts] = row
        cursor = until
    return [rows[key] for key in sorted(rows)]


def analyze(trade, candles):
    if trade['symbol'] != 'EUR/USD' or trade['ownership'] != 'bot' or trade['side'] not in {'BUY', 'SELL'}:
        raise ValueError('Expected a bot EUR/USD trade')
    start, end = timestamp(trade['opened_at']), timestamp(trade['closed_at'])
    if end <= start:
        raise ValueError('Invalid trade duration')
    entry = price(trade['entry_price'])
    bars = []
    seen = set()
    for row in candles:
        ts = timestamp(row['time'])
        if ts in seen:
            raise ValueError('Duplicate candle')
        seen.add(ts)
        if not row.get('complete') or ts < start or ts + timedelta(minutes=1) > end:
            continue
        values = {}
        for basis in ('bid', 'ask'):
            values[basis] = {key: price(row[basis][key]) for key in ('o', 'h', 'l', 'c')}
            v = values[basis]
            if not v['l'] <= min(v['o'], v['c']) <= max(v['o'], v['c']) <= v['h']:
                raise ValueError('Inconsistent OHLC')
        if any(values['ask'][key] < values['bid'][key] for key in ('o', 'c')):
            raise ValueError('Crossed bid/ask')
        bars.append((ts, values))
    bars.sort(key=lambda item: item[0])
    first = start.replace(second=0, microsecond=0)
    if first < start:
        first += timedelta(minutes=1)
    expected = max(0, int((end - first).total_seconds() // 60))
    favorable, adverse, spreads = [], [], []
    for _, values in bars:
        v = values['bid' if trade['side'] == 'BUY' else 'ask']
        favorable.append((v['h'] - entry) if trade['side'] == 'BUY' else (entry - v['l']))
        adverse.append((entry - v['l']) if trade['side'] == 'BUY' else (v['h'] - entry))
        spreads.append((values['ask']['o'] - values['bid']['o']) * 10000)
    def excursion(values):
        return str(max(Decimal(0), max(values)) * 10000) if values else None
    gaps = [{'from': a.isoformat(), 'to': b.isoformat(), 'missing_minutes': int((b-a).total_seconds()/60)-1}
            for (a, _), (b, _) in zip(bars, bars[1:]) if b-a > timedelta(minutes=1)]
    return {'trade_id': trade['trade_id'], 'side': trade['side'],
            'hold_minutes': round((end-start).total_seconds()/60, 3),
            'full_bars_observed': len(bars), 'full_wall_clock_minutes': expected,
            'unobserved_wall_clock_minutes': expected-len(bars), 'interior_gaps': gaps,
            'favorable_excursion_observed_pips': excursion(favorable),
            'adverse_excursion_observed_pips': excursion(adverse),
            'mean_bar_open_spread_pips': str(sum(spreads)/len(spreads)) if spreads else None,
            'price_pl': trade['price_pl'], 'financing': trade['financing'],
            'initial_risk': None, 'entry_rule_validity': 'unknown', 'validated_for_live': False,
            'limitations': ['Excursions cover only fully held completed M1 bars; boundary minutes are excluded.',
                           'Missing minutes include market closures and/or missing data; neither is inferred.',
                           'OHLC gives no intrabar ordering; not a simulation of alternative stops or profits.',
                           'Mean spread is sampled at bar opens, not the entry-time spread.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=Path('data/research/trade-excursions'))
    args = parser.parse_args()
    from loguru import logger
    from src.data.fetcher import OandaClient
    logger.disable('src.data.fetcher')
    source = args.history.read_bytes()
    history = json.loads(source)
    if history.get('environment') != 'practice' or not history.get('pagination_complete'):
        raise SystemExit('Expected a completed practice history snapshot')
    client = OandaClient()
    if client.settings.oanda_environment != 'practice':
        raise SystemExit('Reconstruction is practice-only')
    results = []
    try:
        for trade in history['trades']:
            if trade['ownership'] != 'bot':
                continue
            rows = fetch_window(client, timestamp(trade['opened_at']), timestamp(trade['closed_at']))
            results.append({'analysis': analyze(trade, rows), 'candles': rows})
    except Exception as exc:
        raise SystemExit(f'Reconstruction failed ({type(exc).__name__}); no report written.') from None
    report = {'schema_version': 1, 'source_sha256': hashlib.sha256(source).hexdigest(),
              'retrieved_at': datetime.now(timezone.utc).isoformat(), 'validated_for_live': False,
              'price_basis': 'OANDA EUR_USD M1 bid/ask', 'trades': results}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    with path.open('x') as out:
        json.dump(report, out, indent=2)
        out.write('\n')
    print(json.dumps({'path': str(path), 'trades': [r['analysis'] for r in results]}))


if __name__ == '__main__':
    main()
