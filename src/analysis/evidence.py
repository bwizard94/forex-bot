"""Decision-time snapshots with explicit allowlists; never serialize credentials."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return None


@lru_cache(maxsize=1)
def code_version():
    root = Path(__file__).resolve().parents[1]
    files = ('analysis/signals.py', 'analysis/entry_confirmation.py', 'analysis/indicators.py', 'analysis/growth.py',
             'analysis/reflection.py', 'analysis/evidence.py', 'execution/risk_manager.py',
             'execution/paper_broker.py',
             'analysis/entry_quality.py', 'analysis/sampling.py', 'analysis/mistakes.py', 'pipeline.py', 'config.py')
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def decision_context(*, settings, quote, account, frames, captured_at):
    names = ('trading_style', 'signal_timeframe', 'htf_bias_timeframe', 'min_stop_pips', 'practice_broker_market_hours', 'confirmed_entry_policy',
             'atr_sl_multiplier', 'atr_tp1_multiplier', 'atr_tp2_multiplier',
             'scalp_max_spread_pips', 'news_blackout_minutes', 'friday_flat_hour',
             'monday_open_skip_minutes', 'require_htf_trend', 'fade_strength_min',
             'conviction_strength_min', 'max_fill_slippage_pips', 'min_rr_ratio',
             'cost_stop_fraction', 'stale_quote_seconds', 'practice_sampling_enabled',
             'practice_sampling_until', 'practice_sampling_risk_cap', 'max_order_notional_pct',
             'risk_per_trade_pct', 'conviction_risk_pct', 'addon_risk_pct', 'fade_risk_pct',
             'daily_loss_limit_pct', 'daily_soft_halt_pct', 'practice_daily_loss_halt_enabled', 'practice_contextual_loss_review', 'max_trades_per_day', 'max_units_per_trade')
    from src.analysis.sampling import sampling_policy
    config = {name: getattr(settings, name, None) for name in names}
    bars = {}
    for label, frame in frames.items():
        bars[label] = None if frame.empty else {
            'last_bar_open': frame.index[-1],
            'last_ohlc': {key: frame.iloc[-1].get(key) for key in ('open', 'high', 'low', 'close')},
            'rows': len(frame),
        }
    return json_safe({
        'schema': 'decision_evidence_v1', 'captured_at': captured_at,
        'sampling_policy': sampling_policy(settings, captured_at),
        'code_sha256': code_version(), 'configuration': config,
        'configuration_sha256': hashlib.sha256(json.dumps(json_safe(config), sort_keys=True).encode()).hexdigest(),
        'quote': {k: getattr(quote, k, None) for k in ('bid', 'ask', 'spread', 'ts', 'source', 'tradeable')},
        'account': {k: getattr(account, k, None) for k in ('currency', 'nav', 'margin_available')},
        'bars': bars,
        'limitations': ['Configuration is an allowlisted subset.',
                        'Latest bar snapshots are not a complete replay dataset.',
                        'A recorded signal is not proof of a broker fill.'],
    })
