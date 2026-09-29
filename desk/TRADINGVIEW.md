# TradingView — EUR/USD hub + hunt memory

Public pages:

- [tradingview.com/symbols/EURUSD](https://www.tradingview.com/symbols/EURUSD/) — **seventh print** (OANDA last, TV ratings, performance, volatility, community idea levels)
- [tradingview.com/scripts](https://www.tradingview.com/scripts/) — community Pine catalog mapped onto this hunt

The desk does **not** paste Pine onto the OANDA book. It skims both pages, keeps
facts that fit **this** EUR/USD specialist, stores them here, and **runs the
mapped tools** on live M5/H1 bars. A stacked Sell / oversold oscillator still
is not a license to short the washout.

## EURUSD hub (18 Sep 2026 ~18:45 UTC)

Page: EURUSD on OANDA. The quote widget is JS; the reliable last is the FAQ
**current rate 1.14810**. Live `trade.price` / daily bar sat ~1.14814 with day
range 1.14744–1.14826. A **Market closed** badge can appear on Friday afternoon
— that is widget state, not a desk halt (FX typically runs until ~21:00 UTC Fri).

| Field | Print | How this book reads it |
| --- | --- | --- |
| Last | **1.14810** | Seventh print vs OANDA. Context only. |
| 1 day / 5d / 1m | −0.05% / **−1.23%** / −0.91% | Soft day after a hard week. Do not buy the first bounce as a regime change. |
| 6m / YTD / 1y | −1.01% / −2.37% / **−2.89%** | Agrees with TE / Investing.com weaker-euro yearly tape. |
| 5y / 10y / all | −2.16% / +2.81% / +24.92% | Long-horizon context. Not a ticket. |
| TV technicals | today **Sell**, 1W **Sell**, 1M **Neutral** | Sell + Sell is crowded with Barchart 72% / Investing Strong Sell. **1M Neutral** means do not treat this as a new downtrend. |
| Volatility | **0.32%** | Quiet tape. Do not size as if a news shock is already in. |
| Oscillators / MAs / Summary gauges | Neutral in the HTML | FAQ labels beat the unlabeled gauges. |

Community ideas on the hub were **mixed**. That mix is the lesson:

| Idea | Side | Levels this desk keeps |
| --- | --- | --- |
| EURUSD BUY SETUP | Crowd long | Buy zone **1.1480–1.1510**, targets 1.1580 / 1.1620 / 1.1660–1.1680 |
| Bearish Continuation (2H) | Short | Resistance **1.1580–1.1590**, support objective **1.1455** |
| H1 Bearish Pennant | Short | Continuation only on a close that holds below pennant support |
| Breakdown toward 1.1500 | Short | Path after trend-line break — still not a market order at the day low |
| Resistance rejection → 1.1560 | Short | 1.1560 as a support *target*, not a buy-the-break |

**Standing rule from this page:** TV Sell today + 1W Sell + crowd BUY at 1.1480
is the same washout trap as Barchart 72% Sell / Investing Strong Sell / FXStreet
RSI 32. Do not short the day low. Do not buy the crowd's 1.1480–1.1510 zone as
if it were a fresh long. Fade rips into 1.1580–1.1590 if H1 is still down; wait
for a close that holds if you want continuation lower.

Live last and ratings are fetched every intel cycle. Standing notes here still
apply if the HTML is challenged.

## What the catalog is

TradingView's scripts page is the public Pine marketplace: indicators and
strategies the community actually publishes. Featured cards rotate. The
permanent value is the *classes* of idea that keep showing up — fair-price
vs continuation, TMA trend, liquidity sweeps, EWMAC trend strength,
contrarian exhaustion, S/R confluence, volume-spike classification — plus
the classics every EUR/USD chart on TV already has: Supertrend, TTM Squeeze,
session VWAP, Donchian, Ichimoku Kumo, WaveTrend.

## Scripts skim (17 Sep 2026)

Featured / visible cards and the call on each:

| Script | Keep? | Why |
| --- | --- | --- |
| Reaction Path [BullByte] | **Yes** | Fair price + reaction vs continuation + exhaustion. Maps to session VWAP + ATR displacement. |
| Colored TMA Trend [josseliani] | **Yes** | TMA color-change is late when price is already far — that *is* the stretch filter. |
| ICT Setup 05 Liquidity Sweep & OB Retest | **Yes** | Wick through prior high/low, close back, then wait. Donchian sweep on M5. |
| EWMAC Trend Signals [QuantAlgo] | **Yes** | Vol-normalized EMA spread as trend *strength*, not just direction. |
| Strong Contrarian Zones | **Yes** | Exhaustion at climactic swings. Same lesson as the −$81 lower-band short. |
| Support Resistance Confluence [AxeAlgo] | **Yes** | Zones from clustered swings. Read with Barchart S1/R1 and prior-day high/low. |
| Volume Spike Radar [AxeAlgo] | **Yes** | Tick-volume z vs range: expansion vs absorption. |
| Liquidity Heatmap & Sweep Radar | **Yes** | Same sweep idea as ICT — already Donchian. |
| Auto Trendlines [ITA] | Context | Hub Chart already draws trend lines from swings. |
| Linear Regression Channel Fit | Context | Slope/fit audit. Not a ticket. Stretch from VWAP/TMA covers the chase. |
| Delta Run Confluence | Context | True delta needs order-flow. Approximate with consecutive expansion bars. |
| SATTAM MarketMind | Partial | Heikin-Ashi workspace — do not switch the live book to HA candles. |
| TBR Stats+ (NY 08:00–12:00) | Context | London/NY overlap 12:00–16:00 UTC is already inside the session window. |
| QRB Quarterly Break Range | Context | Structure map, not an M5 trigger. |
| Structure Break Volume Profile | Context | BOS/CHoCH is the sweep/retest family. |
| Strong GEX Liquidations | **No** | Options gamma / liquidation heat. Not FX spot. |
| Gold M15 Signal Engine | **No** | Tuned for XAU. |
| Lorentzian Classifier AI | **No** | Black-box kNN. This book stays deterministic. |
| Sector Breadth Balance | **No** | Equities. |
| RTH Gaps and Expected Move | **No** | Cash-session / VIX. FX does not gap that way. |
| QuantumForexTrader SniperFusion | **No** | Calibrated for ZEC M5. Keep only the "wait for confluence" habit. |

## How the hunt uses them (live)

On every M5 bar the desk now computes:

1. **Session VWAP** (UTC day) — Reaction Path fair price.
2. **Supertrend** (ATR 10 × 3) — trend vote and flip trigger.
3. **TTM Squeeze** — Bollinger inside Keltner. Continuation waits for the fire.
4. **Donchian 20** — wick through prior channel then close back = liquidity sweep.
5. **Ichimoku Kumo** — above / inside / below cloud as a filter, not a market order.
6. **WaveTrend** — oversold ≤ −53 is the same washout as RSI ≤ 40.
7. **TMA 21** — stretch ≥ 1.8 ATR from TMA/VWAP = do not chase continuation.
8. **EWMAC 16/64** — |reading| ≥ 0.5 is trend strength for continuation.
9. **Tick-volume z** — expansion can participate; absorption does not.

Standing rules that still win:

- Never short the lower band / RSI ≤ 40 / WaveTrend ≤ −53 bounce.
- Never buy the upper band / RSI ≥ 60 / WaveTrend ≥ 53 spike.
- H1-aligned continuation is valid *unless* squeeze is on or price is stretched from fair price.
- A liquidity sweep is a trigger, not a market order against H1, and not a washout short.
- TV Sell today + crowd BUY at 1.1480 is **not** a ticket.

## What this is not

- The `/scripts/` catalog is still not a price print. The `/symbols/EURUSD/` hub **is** the seventh print (context only).
- Not a Pine interpreter. The catalog is memory; pandas/numpy is the hunt.
- Not a kitchen sink. GEX, gold engines, equity breadth, and AI classifiers stay out.
- Not a community-ideas copy desk. Mixed BUY 1.1480 vs bearish 1.1455 is memory, not an order.

Live catalog cards and the EURUSD last are fetched every intel cycle. Standing
hunt ideas and the washout rule apply even if the HTML is challenged. The playbook
sections **TradingView (EURUSD hub)** and **TradingView (scripts)** are rewritten
from the snapshot; this file stays the long memory.
