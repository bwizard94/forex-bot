"""Explicit scenario inputs; absent history is never presented as known zero cost."""
from dataclasses import dataclass
import math
import pandas as pd


@dataclass(frozen=True)
class ExecutionAssumptions:
    # Optional measured bid/ask candles indexed by UTC bar-open ISO timestamps.
    market_bars: dict | None = None
    market_timeframe: str = "M1"
    # Explicit signed pips charged at supplied rollover timestamps by side.
    rollovers: tuple = ()
    initial_nav_usd: float = 10000.
    commission_structure: dict | None = None
    commission_pips_roundtrip: float = 0.
    long_carry_pips_per_day: float = 0.
    short_carry_pips_per_day: float = 0.
    # Event records require an event time, known-at time, impact and currency.
    events: tuple = ()
    provenance: str = 'hypothetical_zero_fees_no_calendar'

    def __post_init__(self):
        if self.market_timeframe not in {"M1","M5"}:raise ValueError("Invalid market timeframe")
        if self.commission_structure is not None:
            c=self.commission_structure
            if any(not math.isfinite(float(c[k])) or float(c[k])<0 for k in ('commission','minimumCommission')) or not math.isfinite(float(c['unitsTraded'])) or float(c['unitsTraded'])<=0:
                raise ValueError('Invalid commission structure')
        if not math.isfinite(self.initial_nav_usd) or self.initial_nav_usd<=0: raise ValueError('Invalid simulated NAV')
        for row in self.rollovers:
            if pd.Timestamp(row['ts']).tzinfo is None:raise ValueError('Rollover needs timezone')
            if any(not math.isfinite(float(row[k])) for k in ('BUY','SELL')):raise ValueError('Invalid rollover')
        if self.market_bars is not None:
            for ts,row in self.market_bars.items():
                if pd.Timestamp(ts).tzinfo is None:raise ValueError('Market bars need timezone')
                for side in ('bid','ask'):
                    v={k:float(row[side][k]) for k in ('o','h','l','c')}
                    if not all(math.isfinite(x) and x>0 for x in v.values()) or not v['l']<=min(v['o'],v['c'])<=max(v['o'],v['c'])<=v['h']:
                        raise ValueError('Invalid executable candle')
                if any(float(row['bid'][k])>float(row['ask'][k]) for k in ('o','c')):raise ValueError('Crossed quote')
        for value in (self.commission_pips_roundtrip,self.long_carry_pips_per_day,self.short_carry_pips_per_day):
            if not math.isfinite(value): raise ValueError('Non-finite execution cost')
        if self.commission_pips_roundtrip < 0: raise ValueError('Negative commission')
        for event in self.events:
            for key in ('ts','known_at'):
                if pd.Timestamp(event[key]).tzinfo is None: raise ValueError('Event times require timezone')

    def commission_usd(self, units):
        if self.commission_structure is None:return 0.
        c=self.commission_structure
        return max(float(c['minimumCommission']),abs(units)*float(c['commission'])/float(c['unitsTraded']))

    def financing(self, side, start, end, remaining):
        if self.rollovers:
            return remaining*sum(float(r[side]) for r in self.rollovers if start<pd.Timestamp(r['ts'])<=end)
        return self.carry_pips_per_day(side)*(end-start).total_seconds()/86400*remaining

    def carry_pips_per_day(self, side):
        return self.long_carry_pips_per_day if side=='BUY' else self.short_carry_pips_per_day

    def news_blocked(self, ts, minutes):
        latest = {}
        for e in sorted(self.events, key=lambda e: pd.Timestamp(e['known_at'])):
            if pd.Timestamp(e['known_at']) <= ts:
                latest[e.get('event_id') or (e.get('title'),e.get('currency'),e['ts'])] = e
        return any(e.get('currency') in {'EUR','USD'} and e.get('impact')=='High'
                   and abs((pd.Timestamp(e['ts'])-ts).total_seconds()) <= minutes*60
                   for e in latest.values())


def archived_assumptions(directory):
    import json
    events=[]
    for path in sorted((directory/'calendar').glob('*.json')):
        events.extend(json.loads(path.read_text()))
    # Fees are not inferred from balance changes or confused with realized losses.
    # Operator-supplied explicit cost calibration can be added locally.
    calibration=directory/'execution-costs.json'
    values=json.loads(calibration.read_text()) if calibration.exists() else {}
    allowed={'commission_pips_roundtrip','long_carry_pips_per_day','short_carry_pips_per_day'}
    if set(values)-allowed: raise ValueError('Unexpected execution calibration fields')
    profile_path=directory/'broker-cost-current.json'
    if profile_path.exists():
        profile=json.loads(profile_path.read_text())
        if profile.get('currency')=='USD':
            values['initial_nav_usd']=float(profile['nav'])
            if profile.get('commission') is not None:values['commission_structure']=profile['commission']
    return dict(values, events=events, provenance=('current_broker_commission_profile' if values.get('commission_structure') is not None else 'explicit_local_cost_calibration' if calibration.exists() else
                'fees_unknown_zero_cost_reference')+'; observed_calendar_only_no_historical_completeness_claim')
