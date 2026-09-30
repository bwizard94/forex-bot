"""Price confirmation and bounded evidence scores, shared by practice and replay."""
import math
import pandas as pd


def evidence_families(factors):
    families = set()
    for factor in factors:
        text = factor.lower()
        if text.startswith(('h1 ', 'h4 ', 'd1 ', 'm30 ')):
            families.add('higher_timeframe')
        elif any(x in text for x in ('divergence', 'liquidity sweep', 'envelope', 'ox scalp')):
            families.add('structure')
        elif any(x in text for x in ('bollinger', 'vwap', 'fair price')):
            families.add('location')
        elif any(x in text for x in ('rsi', 'stochastic', 'cci ', 'wavetrend', 'macd', 'dss', 'squeeze')):
            families.add('momentum')
        elif any(x in text for x in ('ema ', 'ema 9/21', 'lwma', 'adx ', 'supertrend', 'ewmac', 'ichimoku')):
            families.add('trend')
    return sorted(families)


def directional_strength(action, bull_factors, bear_factors):
    """Heuristic support score, never a win probability or opposing-side score."""
    if action not in {'BUY', 'SELL'}:
        return 0
    factors = bull_factors if action == 'BUY' else bear_factors
    return min(100, 10 * len(factors), 25 * len(evidence_families(factors)))


def price_confirmation(action, bars, timeframe, *, after=None):
    """A directional close beyond the previous bar, with no gap or pre-loss bar."""
    if action not in {'BUY', 'SELL'} or bars is None or len(bars) < 2:
        return False
    durations = {'M1':'1min', 'M5':'5min', 'M15':'15min', 'M30':'30min', 'H1':'1h'}
    if timeframe not in durations:
        return False
    previous, current = bars.iloc[-2], bars.iloc[-1]
    ts, prev_ts = pd.Timestamp(bars.index[-1]), pd.Timestamp(bars.index[-2])
    if ts.tzinfo is None or prev_ts.tzinfo is None or ts-prev_ts != pd.Timedelta(durations[timeframe]):
        return False
    if after is not None:
        cutoff = pd.Timestamp(after)
        cutoff = cutoff.tz_localize('UTC') if cutoff.tzinfo is None else cutoff
        if ts < cutoff:
            return False
    try:
        values = [float(current[k]) for k in ('open', 'close')] + [float(previous[k]) for k in ('high', 'low')]
    except (ValueError, TypeError, KeyError):
        return False
    if not all(math.isfinite(v) and v > 0 for v in values):
        return False
    op, close, high, low = values
    return close > op and close > high if action == 'BUY' else close < op and close < low


def reentry_reason(action, bars, timeframe, last_closed):
    """Only a same-side realized loss requires a new post-close price trigger."""
    if not last_closed or last_closed['side'] != action or last_closed['pl'] >= 0:
        return None
    if price_confirmation(action, bars, timeframe, after=last_closed['closed_at']):
        return None
    return 'Fresh-entry confirmation: after the last same-side loss, wait for a new completed directional close beyond the previous bar.'


def latest_bot_close(session, symbol):
    from sqlalchemy import select
    from src.data.storage import Trade
    return session.scalar(select(Trade).where(
        Trade.symbol == symbol, Trade.source == 'bot', Trade.venue == 'oanda',
        Trade.parent_trade_id.is_(None), Trade.status == 'closed', Trade.closed_at.is_not(None)
    ).order_by(Trade.closed_at.desc(), Trade.id.desc()).limit(1))
