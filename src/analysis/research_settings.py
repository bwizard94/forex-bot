"""Allowlisted, immutable research configuration; no environment fallback on reload."""
import hashlib
import json
from src.analysis.strategy_lab import FIELDS
from src.config import Settings

NAMES = set(FIELDS) | set('''news_blackout_minutes max_open_positions max_same_side_positions
max_open_risk_pct risk_per_trade_pct conviction_risk_pct conviction_strength_min
addon_risk_pct fade_risk_pct fade_strength_min addon_min_profit_pips max_units_per_trade
max_order_notional_pct max_trades_per_day practice_sampling_enabled practice_sampling_risk_cap
practice_sampling_until daily_loss_limit_pct practice_daily_loss_halt_enabled
practice_contextual_loss_review daily_reduce_at_pct daily_soft_halt_pct max_drawdown_pct
lesson_lookback_days lesson_loss_high_strength lesson_loss_skip lesson_skip_hours
lesson_high_strength_min'''.split())


def freeze_settings(settings, origin='provided_settings'):
    values=settings.model_dump(mode='json', include=NAMES)
    digest=hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()
    return {'schema':'research_settings_v1','configuration':values,'sha256':digest,
            'origin':origin,'validated_for_live':False}


def thaw_settings(snapshot):
    values=snapshot['configuration']
    if set(values) != NAMES or hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()!=snapshot['sha256']:
        raise ValueError('Invalid research configuration snapshot')
    # model_validate does not invoke BaseSettings environment sources.
    defaults={k:field.default for k,field in Settings.model_fields.items()}
    return Settings.model_validate(defaults | values)
