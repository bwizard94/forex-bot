"""Check an existing setup against executable prices without moving its levels."""
from math import isfinite
from src.utils import pip_size


def entry_quality(signal, quote, settings):
    direction = 1 if signal.action == 'BUY' else -1
    if signal.action not in {'BUY', 'SELL'}:
        return {'allowed': False, 'reason': 'Entry quality: directional setup required'}
    entry = float(signal.entry or signal.price)
    stop = float(signal.stop_loss or 0)
    target = float(signal.take_profit_2 or signal.take_profit_1 or 0)
    first = float(signal.take_profit_1 or target)
    executable = float(quote.ask if direction == 1 else quote.bid)
    pip = pip_size(signal.symbol)
    values = (entry, stop, target, first, executable)
    if not all(isfinite(v) and v > 0 for v in values):
        return {'allowed': False, 'reason': 'Entry quality: invalid setup prices'}
    drift = direction * (executable-entry)/pip
    risk = direction * (executable-stop)
    reward = direction * (target-executable)
    cap = float(settings.max_fill_slippage_pips)
    bound = entry + direction * cap * pip
    result = {'allowed': False, 'executable_entry': executable, 'drift_pips': drift,
              'worst_entry': bound, 'reward_risk_at_quote': reward/risk if risk > 0 else None}
    if abs(drift) > cap + 1e-8:
        result['reason'] = f'Entry quality: price moved {abs(drift):.1f} pips from setup (limit {cap:.1f}); wait for a new setup'
    elif risk <= 0 or reward <= 0 or direction*(first-executable) <= 0:
        result['reason'] = 'Entry quality: price crossed the setup stop or target'
    elif risk/pip + 0.05 < settings.min_stop_pips:
        result['reason'] = 'Entry quality: executable stop distance is below the configured floor'
    elif reward/risk < settings.min_rr_ratio:
        result['reason'] = f'Entry quality: current target reward/risk {reward/risk:.2f} is below {settings.min_rr_ratio:.2f}'
    else:
        result.update(allowed=True, reason='Entry quality: executable price remains inside setup limits')
    return result
