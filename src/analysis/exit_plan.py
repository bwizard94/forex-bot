"""Position-weighted target payoff, not an expected return or entry permission."""
from math import isfinite
from src.execution.trade_guard import MIN_TP1_PIPS, partial_close_units


def payoff(side, entry, stop, first, final, *, units=None, fee_pips=None):
    values=(entry,stop,first,final)
    if side not in {'BUY','SELL'} or not all(isfinite(float(x)) and float(x)>0 for x in values):
        return {'status':'invalid_levels'}
    sign=1 if side=='BUY' else -1
    risk=(entry-stop)*sign*10000
    one=(first-entry)*sign*10000;two=(final-entry)*sign*10000
    if risk<=0 or one<=0 or two<one:return {'status':'invalid_levels'}
    if units is not None and (not isinstance(units,int) or units<1):return {'status':'invalid_units'}
    partial=one+1e-9>=MIN_TP1_PIPS and (units is None or units>=2)
    weight=(partial_close_units(units)/units if units is not None else .5) if partial else 0.
    reward=weight*one+(1-weight)*two
    if fee_pips is not None and (not isfinite(fee_pips) or fee_pips<0):raise ValueError('Invalid fees')
    return {'status':'measured_payoff','partial_fraction':weight,'units_known':units is not None,
            'partial_eligible_at_quote':partial,'risk_pips':risk,'runner_only_r':two/risk,
            'weighted_target_pips':reward,'weighted_target_r':reward/risk,
            'net_target_r':None if fee_pips is None else (reward-fee_pips)/risk,
            'fee_pips':fee_pips,'fee_status':'unknown' if fee_pips is None else 'explicit_scenario',
            'spread_basis':'already included by executable entry; do not subtract twice',
            'limitation':'Conditional payoff if targets fill; not probability-weighted expectancy. Actual fill may change TP1 eligibility.'}
