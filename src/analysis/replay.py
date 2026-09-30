"""Exploratory M1/M5 midpoint-OHLC replay, never an execution/performance guarantee.

Signals see completed bars; fills use the next bar. Every intervening bar is
managed. Constant spread/slippage are assumptions, not historical quotes.
Ambiguous stop/target bars resolve stop first; a new breakeven stop starts on
the following bar. No financing, commissions, news calendar, or portfolio model.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
import pandas as pd


@dataclass(frozen=True)
class ReplayCosts:
    spread_pips: float = 1.2
    slippage_pips: float = 0.2  # adverse on entry and market/stop exits

    def __post_init__(self):
        if any(not math.isfinite(x) or x < 0 for x in (self.spread_pips, self.slippage_pips)):
            raise ValueError("Replay costs must be finite and nonnegative")


def completed_bars(frame, decision_time, duration, limit):
    if frame is None or frame.empty:
        return None
    # Input indices are bar OPEN timestamps in UTC, including daily bars.
    return frame.loc[frame.index + pd.Timedelta(duration) <= decision_time].iloc[-limit:]


def replay(m5, h1, d1, settings, *, step=1, lookback=8000, max_trades=500, costs=None, evaluator=None, timeframe="M5", entry_history=180, h1_history=120, d1_history=80):
    from src.analysis.signals import evaluate_signal
    from src.analysis.mistakes import calendar_hold_reason, broker_market_hours
    from src.data.datasets import session_name

    if timeframe not in {"M1", "M5"}:
        raise ValueError("Replay supports M1 or M5")
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
    start = max(90, len(frame) - lookback)
    closed, kept = [], []
    position = pending = None
    half_spread = costs.spread_pips * 0.0001 / 2
    slip = costs.slippage_pips * 0.0001

    def close_part(px, fraction):
        position['pips'] += fraction * position['direction'] * (px - position['entry']) / 0.0001
        position['remaining'] -= fraction

    for i in range(start, len(frame)):
        ts, bar = frame.index[i], frame.iloc[i]
        if pending is not None:
            sig, decision_time = pending
            pending = None
            if ts == decision_time and not calendar_hold_reason(ts.to_pydatetime(), settings=settings):
                direction = 1 if sig.action == 'BUY' else -1
                entry = float(bar.open) + direction * (half_spread + slip)
                risk = direction * (entry - float(sig.stop_loss))
                original_risk = direction * (float(sig.entry) - float(sig.stop_loss))
                tp1 = float(sig.take_profit_1)
                tp2 = float(sig.take_profit_2 or sig.take_profit_1)
                if (original_risk + 1e-10 >= max(5, settings.min_stop_pips) * .0001
                        and risk + 1e-10 >= max(5, settings.min_stop_pips) * .0001
                        and costs.spread_pips < settings.cost_stop_fraction * (risk/.0001)
                        and costs.spread_pips <= settings.scalp_max_spread_pips
                        and direction * (tp2-entry)/risk >= settings.min_rr_ratio
                        and abs(entry - float(sig.entry)) <= settings.max_fill_slippage_pips * .0001
                        and direction * (tp1 - entry) >= .0005
                        and direction * (tp2 - tp1) >= 0):
                    position = dict(side=sig.action, direction=direction, entry=entry, sl=float(sig.stop_loss),
                                    tp1=tp1, tp2=tp2, remaining=1., partial=False, pips=0.,
                                    opened_at=ts, signal_type=sig.signal_type, strength=int(sig.strength or 0),
                                    session=session_name(ts.to_pydatetime()))
        if position is not None:
            d = position['direction']
            op, hi, lo, cl = [float(bar[k])-d*half_spread for k in ('open','high','low','close')]
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
                closed.append({k: position[k] for k in ('side','signal_type','strength','session','pips','opened_at')} | {
                    'closed_at': ts, 'reason': reason, 'spread_pips': costs.spread_pips,
                    'slippage_pips': costs.slippage_pips, 'model': 'exploratory_ohlc_v3', 'timeframe': timeframe})
                position = None
                if len(closed) >= max_trades:
                    break
        if position is not None or i == len(frame)-1 or (i-start) % max(1, step):
            continue
        decision = ts + duration
        sig = evaluator('EUR/USD',timeframe,frame.iloc[max(0,i-entry_history+1):i+1],
                        htf_bars=completed_bars(h1,decision,'1h',h1_history),
                        d1_bars=completed_bars(d1,decision,'1d',d1_history),
                        settings=settings, now=decision.to_pydatetime(), heavy=True)
        sig.source = 'history'
        if settings.confirmed_entry_policy and sig.action in {'BUY','SELL'} and closed:
            from src.analysis.entry_confirmation import reentry_reason
            last = closed[-1]
            # OHLC does not give an intrabar exit time: require a bar starting
            # after the entire exit candle to avoid using pre-exit structure.
            prior = {'side':last['side'], 'pl':last['pips'], 'closed_at':last['closed_at'] + duration}
            if reentry_reason(sig.action, frame.iloc[:i+1], timeframe, prior):
                continue
        if sig.action in {'BUY','SELL'} and sig.entry and sig.stop_loss and sig.take_profit_1:
            kept.append(sig)
            pending = sig, decision
    return closed, kept[-400:]


def performance(rows):
    """Pip statistics, not account returns; each trade has equal initial weight."""
    values = [float(r['pips']) for r in rows]
    gains, losses = sum(max(x,0) for x in values), -sum(min(x,0) for x in values)
    equity = peak = drawdown = 0.
    for value in values:
        equity += value
        peak = max(peak,equity)
        drawdown = max(drawdown,peak-equity)
    n = len(values)
    return dict(trades=n, win_rate=sum(x>0 for x in values)/n if n else 0., net_pips=sum(values),
                expectancy_pips=sum(values)/n if n else 0., profit_factor=gains/losses if losses else None,
                max_drawdown_pips=drawdown, forced_end_closes=sum(r.get('reason')=='end_of_data' for r in rows),
                validated_for_live=False)
