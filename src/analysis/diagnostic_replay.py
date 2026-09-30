"""Versioned diagnostic replay, separate from frozen v3 prospective experiments.

Adds entry diagnostics, multiple simultaneous positions and explicit assumed
news/commission/carry inputs. Portfolio risk is a fixed fraction per ticket, not
an account ledger or replica of adaptive sizing. No broker access.
"""
from __future__ import annotations

import math
from collections import Counter
from src.analysis.execution_assumptions import ExecutionAssumptions
import pandas as pd


from src.analysis.replay import ReplayCosts, completed_bars


def replay(m5, h1, d1, settings, *, step=1, lookback=8000, max_trades=500, costs=None, evaluator=None, timeframe="M5", entry_history=180, h1_history=120, d1_history=80, diagnostics=None, assumptions=None):
    from src.analysis.signals import evaluate_signal
    from src.analysis.mistakes import calendar_hold_reason, broker_market_hours
    from src.data.datasets import session_name

    if timeframe not in {"M1", "M5"}:
        raise ValueError("Replay supports M1 or M5")
    diagnostics = diagnostics if diagnostics is not None else {}
    rejects = Counter()
    diagnostics.update(evaluations=0, directional_signals=0, accepted_entries=0, rejections=rejects)
    assumptions = assumptions or ExecutionAssumptions()
    positions = []
    nav = assumptions.initial_nav_usd
    daily_entries = Counter()
    duration = pd.Timedelta(minutes=1 if timeframe == "M1" else 5)
    costs = costs or ReplayCosts()
    evaluator = evaluator or evaluate_signal
    if m5 is None or m5.empty:
        return [], []
    frame = m5.sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None or frame.index.has_duplicates:
        raise ValueError("Replay requires unique timezone-aware bar-open timestamps")
    frame = frame.copy()
    frame.index = frame.index.tz_convert('UTC')
    if (frame.index.to_series().diff().dropna() < duration).any():
        raise ValueError(f"Resample input to {timeframe} before replay")
    if not all(math.isfinite(float(x)) and float(x) > 0 for x in frame[['open','high','low','close']].to_numpy().flat):
        raise ValueError("Replay prices must be finite and positive")
    if ((frame.high < frame[['open','close','low']].max(axis=1)) | (frame.low > frame[['open','close','high']].min(axis=1))).any():
        raise ValueError("Invalid OHLC geometry")
    if assumptions.market_bars is not None and assumptions.market_timeframe!=timeframe:
        raise ValueError('Measured quote timeframe does not match replay')
    measured = {pd.Timestamp(k):v for k,v in (assumptions.market_bars or {}).items()}
    if assumptions.market_bars is not None and any(ts not in measured for ts in frame.index):
        raise ValueError('Measured bid/ask coverage incomplete; refusing synthetic gap fills')
    start = max(90, len(frame) - lookback)
    closed, kept = [], []
    position = pending = None
    half_spread = costs.spread_pips * 0.0001 / 2
    slip = costs.slippage_pips * 0.0001

    def close_part(px, fraction):
        position['pips'] += fraction * position['direction'] * (px - position['entry']) / 0.0001
        position['commission_usd'] += assumptions.commission_usd(position['units']*fraction)
        position['remaining'] -= fraction

    for i in range(start, len(frame)):
        ts, bar = frame.index[i], frame.iloc[i]
        quote_bar = measured.get(ts)
        entry_spread = (float(quote_bar['ask']['o'])-float(quote_bar['bid']['o']))*10000 if quote_bar else costs.spread_pips
        if pending is not None:
            sig, decision_time = pending
            pending = None
            calendar = calendar_hold_reason(ts.to_pydatetime(), settings=settings)
            if ts != decision_time:
                rejects['missing_next_bar'] += 1
            elif calendar:
                rejects['calendar_hold'] += 1
            elif assumptions.news_blocked(ts, settings.news_blackout_minutes):
                rejects['news_blackout'] += 1
            else:
                direction = 1 if sig.action == 'BUY' else -1
                entry = (float(quote_bar['ask' if direction==1 else 'bid']['o']) if quote_bar else float(bar.open)+direction*half_spread)+direction*slip
                risk = direction * (entry - float(sig.stop_loss))
                original_risk = direction * (float(sig.entry) - float(sig.stop_loss))
                tp1 = float(sig.take_profit_1)
                tp2 = float(sig.take_profit_2 or sig.take_profit_1)
                from src.analysis.sampling import sampling_policy
                policy = sampling_policy(settings,ts.to_pydatetime())
                risk_fraction = min(settings.risk_per_trade_pct, policy['risk_cap'] or settings.risk_per_trade_pct)
                units = min(settings.max_units_per_trade, int(max(0,nav)*risk_fraction/risk)) if risk>0 else 0
                if settings.max_order_notional_pct:
                    units=min(units,int(max(0,nav)*settings.max_order_notional_pct/entry))
                reserved=sum(p['initial_risk_usd'] for p in positions)
                checks = {
                    'positive_size': units>0,
                    'addon_not_paying': all(direction*((float(quote_bar['bid' if direction==1 else 'ask']['o']) if quote_bar else float(bar.open)-direction*half_spread)-p['entry'])/.0001>=settings.addon_min_profit_pips for p in positions if p['side']==sig.action),
                    'original_stop_floor': original_risk + 1e-10 >= max(5,settings.min_stop_pips)*.0001,
                    'fill_stop_floor': risk + 1e-10 >= max(5,settings.min_stop_pips)*.0001,
                    'spread_to_stop': entry_spread < policy['cost_stop_fraction']*(risk/.0001),
                    'spread_cap': entry_spread <= settings.scalp_max_spread_pips,
                    'reward_risk': risk > 0 and direction*(tp2-entry)/risk >= settings.min_rr_ratio,
                    'fill_distance': abs(entry-float(sig.entry)) <= settings.max_fill_slippage_pips*.0001,
                    'target_distance': direction*(tp1-entry) >= .0005,
                    'target_order': direction*(tp2-tp1) >= 0,
                    'daily_entry_cap': daily_entries[ts.date()] < settings.max_trades_per_day,
                    'position_cap': len(positions) < settings.max_open_positions,
                    'same_side_cap': sum(p['side']==sig.action for p in positions) < settings.max_same_side_positions,
                    'open_risk_cap': reserved+units*risk <= max(0,nav)*settings.max_open_risk_pct+1e-10,
                }
                failed = [name for name, passed in checks.items() if not passed]
                if failed:
                    rejects[failed[0]] += 1
                    for name in failed:
                        diagnostics.setdefault('all_failed_checks', Counter())[name] += 1
                else:
                    position = dict(side=sig.action, direction=direction, entry=entry, sl=float(sig.stop_loss),
                                    tp1=tp1, tp2=tp2, remaining=1., partial=False, pips=0.,
                                    opened_at=ts, signal_type=sig.signal_type, strength=int(sig.strength or 0),
                                    session=session_name(ts.to_pydatetime()), risk_fraction=risk_fraction,
                                    financing_pips=0., last_charge=ts, units=units, initial_risk_usd=units*risk, commission_usd=assumptions.commission_usd(units))
                    positions.append(position)
                    diagnostics['accepted_entries'] += 1
                    daily_entries[ts.date()] += 1
        for position in list(positions):
            hours = (ts-position['last_charge']).total_seconds()/3600
            position['financing_pips'] += assumptions.financing(position['side'],position['last_charge'],ts,position['remaining'])
            position['last_charge'] = ts
            d = position['direction']
            op, hi, lo, cl = ([float(quote_bar['bid' if d==1 else 'ask'][k]) for k in ('o','h','l','c')] if quote_bar else [float(bar[k])-d*half_spread for k in ('open','high','low','close')])
            stop = position['sl']
            stop_hit = lo <= stop if d == 1 else hi >= stop
            reason = None
            # Gapped stop fills at the adverse open; all other ambiguous bars stop first.
            gap_stop = op <= stop if d == 1 else op >= stop
            if gap_stop:
                px = min(op, stop) if d == 1 else max(op, stop)
                close_part(px-d*slip, position['remaining'])
                reason = 'stop'
            elif ((ts-position['opened_at']).total_seconds() >= settings.scalp_max_hold_minutes*60
                  or (not broker_market_hours(settings) and ts.weekday() == 4 and ts.hour >= settings.friday_flat_hour)):
                close_part(op-d*slip, position['remaining'])
                reason = 'time_or_friday'
            elif stop_hit:
                close_part(stop-d*slip, position['remaining'])
                reason = 'stop'
            else:
                hit1 = hi >= position['tp1'] if d == 1 else lo <= position['tp1']
                hit2 = hi >= position['tp2'] if d == 1 else lo <= position['tp2']
                if hit1 and not position['partial']:
                    close_part(position['tp1']-d*slip, .5)
                    position['partial'] = True
                    position['sl'] = position['entry']
                if hit2:
                    close_part(position['tp2'], position['remaining'])
                    reason = 'target'
            if i == len(frame)-1 and position['remaining'] > 0:
                close_part(cl-d*slip, position['remaining'])
                reason = 'end_of_data'
            if reason:
                position['gross_pips'] = position['pips']
                position['charged_commission_pips'] = position['commission_usd']/(position['units']*.0001) if assumptions.commission_structure is not None else assumptions.commission_pips_roundtrip
                position['pips'] += position['financing_pips'] - position['charged_commission_pips']
                position['simulated_pl_usd']=position['pips']*.0001*position['units']
                nav+=position['simulated_pl_usd']
                closed.append({k: position[k] for k in ('side','signal_type','strength','session','pips','gross_pips','financing_pips','opened_at','units','initial_risk_usd','simulated_pl_usd')} | {
                    'closed_at': ts, 'reason': reason, 'spread_pips': costs.spread_pips,
                    'slippage_pips': costs.slippage_pips, 'commission_pips': position['charged_commission_pips'], 'model': 'diagnostic_ohlc_v5', 'timeframe': timeframe})
                positions.remove(position)
        if len(closed) >= max_trades and not positions:
            break
        if i == len(frame)-1 or (i-start) % max(1, step):
            continue
        decision = ts + duration
        sig = evaluator('EUR/USD',timeframe,frame.iloc[max(0,i-entry_history+1):i+1],
                        htf_bars=completed_bars(h1,decision,'1h',h1_history),
                        d1_bars=completed_bars(d1,decision,'1d',d1_history),
                        settings=settings, now=decision.to_pydatetime(), heavy=True)
        diagnostics['evaluations'] += 1
        sig.source = 'history'
        if sig.action in {'BUY','SELL'}:
            diagnostics['directional_signals'] += 1
        else:
            rejects['signal_hold'] += 1
            diagnostics.setdefault('hold_reasons',Counter())[getattr(sig,'reason','unspecified') or 'unspecified'] += 1
        if settings.confirmed_entry_policy and sig.action in {'BUY','SELL'} and closed:
            from src.analysis.entry_confirmation import reentry_reason
            last = closed[-1]
            # OHLC does not give an intrabar exit time: require a bar starting
            # after the entire exit candle to avoid using pre-exit structure.
            prior = {'side':last['side'], 'pl':last['pips'], 'closed_at':last['closed_at'] + duration}
            if reentry_reason(sig.action, frame.iloc[:i+1], timeframe, prior):
                rejects['reentry_condition'] += 1
                continue
        if sig.action in {'BUY','SELL'} and sig.entry and sig.stop_loss and sig.take_profit_1:
            kept.append(sig)
            pending = sig, decision
        elif sig.action in {'BUY','SELL'}:
            rejects['missing_signal_levels'] += 1
    diagnostics['simulated_final_nav_usd']=nav
    diagnostics['sizing_model']='baseline-risk USD units, max units/notional, overlap caps; excludes conviction and adaptive reductions'
    return closed, kept[-400:]
