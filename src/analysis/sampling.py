"""Explicit, time-bounded EUR/USD practice sampling policy."""
from datetime import datetime, timezone


def sampling_policy(settings, now=None):
    now = now or datetime.now(timezone.utc)
    until = getattr(settings, 'practice_sampling_until', None)
    requested = bool(getattr(settings, 'practice_sampling_enabled', False))
    enabled = requested and settings.oanda_environment == 'practice'
    active = enabled and until is not None and until.tzinfo is not None and now < until
    cap = settings.practice_sampling_risk_cap
    name = f'practice-cost35-risk{cap*100:g}pct-{settings.signal_timeframe}-v2'
    return {'name': name if enabled else 'baseline',
            'enabled': enabled, 'active': active,
            'expires_at': until.isoformat() if until else None,
            'cost_stop_fraction': .35 if active else settings.cost_stop_fraction,
            # Expiry must never increase size automatically.
            'risk_cap': cap if enabled else None,
            'status': 'active' if active else ('expired_or_no_deadline' if enabled else 'disabled')}
