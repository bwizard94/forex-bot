# EUR/USD scalp book — Ox Securities

> Historical educational notes. Fixed timeframe, risk, session, score and exclusion examples below are not current runtime policy. [OPERATING.md](OPERATING.md) takes precedence; negative outcomes alone do not establish these mistake labels or authorize a broad strategy ban.

Source: [Most Profitable Trading Strategies](https://oxsecurities.com/most-profitable-trading-strategies/) (Ox Securities).

The page's three "most profitable" recipes are **scalping**, a weekly candlestick fade, and Parabolic SAR + EMA 5/25/50. This desk **adopts the scalp**. The weekly candlestick (100–140 point stop, 50–70 point target) is position trading with a worse-than-1 R:R — we do not take it. Parabolic + triple EMA is a trend system; Supertrend + EMA 9/21 already covers that confirmation.

A strategy is not foolproof. Ox: review it against live results and market conditions. That is already `desk/GROWTH.md`.

## What Ox's scalp actually is

Ox designs the scalp for **short-term EUR/USD** with **short stop-loss and take-profit**. Their chart is **H1**. Tools:

| Ox tool | Period | Long | Short |
| --- | --- | --- |
| Linear weighted MA (LWMA) | 48 | Candle **above** LWMA | Candle **below** LWMA |
| Trend Envelopes V2 | 2 | Close **breaks the orange line up** | Close **breaks the blue line down** |
| DSS of momentum | — | Additional line **green and above** the dotted signal | Additional line **orange and below** the dotted signal |

H1 LWMA 48 is a two-day trend filter. The envelope period 2 is the trigger. DSS is the momentum confirm.

## How this bot runs it

We do **not** paste MT4 "Trend Envelopes V2" onto OANDA. We run the same triad in pandas on every M5 bar, with H1 still the map:

1. **LWMA 48** — linear weighted MA of close. H1 close vs H1 LWMA 48 is a vote (Ox's H1 filter).
2. **Trend Envelopes period 2** — EMA of highs (orange) and EMA of lows (blue). A long is a close through orange; a short is a close through blue.
3. **DSS of momentum** — double-smoothed stochastic of typical-price momentum. Green = line above signal; orange = line below.

When all three agree **and** H1 is not against the trade, that is an **Ox scalp triad** ticket. Geometry is short:

| Level | Scalp book |
| --- | --- |
| Stop | 1.0 × ATR (floor 5 pips — OANDA + the chopped-stop lesson) |
| Take profit 1 | 1.2 × ATR (half off, stop to breakeven) |
| Take profit 2 | 2.0 × ATR |
| Risk | 0.6% base / 0.9% conviction |
| Spread cap | **1.8 pips** — skip until London/NY compresses |
| Time stop | **90 minutes** — flatten a bot scalp that is still open (operator tickets stay hands-off) |
| News | still ±30 minutes blackout |

The washout rule still wins: never **short** RSI ≤ 40 / lower band / WaveTrend ≤ −53; never **buy** the spike. The inverse is the scalp: **fade the rip** — sell an RSI ≥ 60 / upper-band spike when H1 is not bullish; buy the washout bounce when H1 is not bearish.

## What we will not copy from that page

- Weekly candlestick "spring" with SL twice the TP. Expectancy math fails.
- Guessing entries without the triad. Ox: the strategy tells you when to move.
- Kitchen-sink. Minimum lagging tools, simple rules, then journal.

Live triad values are in the signal confluence (`Ox scalp triad`, `LWMA 48`, `Trend Envelopes`, `DSS of momentum`). Standing notes stay in this file; `desk/OPERATING.md` is the style lock.

## Indicator interpretation — research addendum, 2026-09-22

An upper/lower-band touch is not enough to establish a reversal, and RSI can remain extreme during a trend. Thus “fade the rip” still needs confirmation; the existing anti-chase exclusions remain local policy. [Bollinger's rules](https://www.bollingerbands.com/bollinger-band-rules), [Fidelity RSI guide](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/rsi)

ADX measures strength, not direction; ATR measures volatility. Neither supplies an extra directional vote by itself. Common indicator thresholds are not validated parameters for this M5 desk. [ADX guide](https://www.fidelity.com/viewpoints/active-investor/average-directional-index-ADX), [ATR guide](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr)

Our VWAP is a UTC-day reference weighted by the supplied feed's activity. OANDA candle volume is a price count; it is not global transacted volume. Missing/zero weights become 1 in our implementation. Interpret the result accordingly. [OANDA candle definitions](https://developer.oanda.com/rest-live-v20/instrument-df/)

See [RESEARCH.md](RESEARCH.md) for proposed confirmation-family ablations, regime comparisons and a breakout/retest challenger. No indicator, threshold, stop or target was changed by this document update.
