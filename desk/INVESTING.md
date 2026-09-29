# Investing.com — EUR/USD

Standing notes for the EUR/USD specialist. Live numbers are rewritten into
`desk/EURUSD_PLAYBOOK.md` every intel cycle. This file is the desk's memory of
**how to read** [investing.com/currencies/eur-usd](https://www.investing.com/currencies/eur-usd).

Direct HTTP often hits Cloudflare 403. A blocked fetch never stops the intel
cycle. The skim below is from 17 September 2026 ~16:15 (page clock).

## What the page is

Investing.com's EUR/USD hub is a **quote + multi-TF technical + calendar wrap**:

- Last, bid/ask, day range, open, previous close, 52-week range, 1-year change
- Technical summary by timeframe (1m paid; 30m / hourly / 5h / daily / weekly / monthly)
- Related quotes including **CME euro futures**
- An economic calendar filtered onto the pair (EUR and USD prints with actual / forecast / previous)
- CFTC EUR speculative net positions
- Economy / forex news and analysis

It is slower than OANDA M5. Use it for **timeframe agreement, calendar actuals,
and CME vs R1**, not for fills. The desk still only trades EUR/USD.

## How the bot uses it

Every 20 minutes the intel loop tries the public HTML and:

1. Cross-checks the Investing.com last against OANDA (sixth print, after
   CurrencyFreaks, Trading Economics, FXStreet, and Barchart). A miss or
   Cloudflare block is logged, not a halt.
2. Writes the 30m–monthly technical summary into the playbook.
3. Pulls CME euro futures, CFTC EUR net, claims, EA CPI, and housing starts.
4. Records euro/dollar headlines. **Headlines are not a ticket.**

Source module: `src/data/investing.py`.

## Skim — 17 September 2026 (~16:15)

### Quote

Last **1.1475**, +0.0010 (**+0.09%**). Bid/ask **1.1474 / 1.1476** (0.2 pip —
tighter than a tradable OANDA spread, quote-page mid). Day **1.1456–1.1498**.
Open and previous close **1.1465**. 52-week **1.1325–1.2079**. 1-year
**−2.86%**.

That is the same bounce-inside-a-down-year as TE (−2.6%) and Barchart
(−2.83% 52w). Not a trend change.

### Multi-timeframe technicals

| Horizon | Rating |
| --- | --- |
| 30 minute | **Strong Sell** |
| Hourly | **Strong Sell** |
| 5 hours | **Strong Sell** |
| Daily | **Strong Sell** |
| Weekly | **Strong Sell** |
| Monthly | **Sell** |
| Summary / indicators / MAs | **Strong Sell** |

This is more stacked than Barchart's single 72% Sell. It is **still not a
license to short RSI ~32 at the day low**. The same stacked-sell crowd is
why this book paid −$81 on the lower-band bounce.

### CME euro futures

Front CME **1.1519** (+0.06%). That sits on Barchart **R1 1.15266**. Futures
are already at the cash fade zone. Do not buy a break of the 1.1498 day's
high because CME printed 1.1519.

### Pair-page calendar (17 Sep actuals)

| Print | Actual | Cons | Read |
| --- | --- | --- |
| US initial claims | **196k** | 207k | Beat. USD support. Same print FXStreet/Barchart used. |
| Continuing claims | 1,730k | 1,780k | Also a beat. |
| Housing starts | **1.275M** | 1.32M | Miss (−2.6% m/m). Soft housing, not enough to unwind the Fed hike. |
| Building permits | 1.394M | 1.40M | Miss. |
| Philly Fed | 37.80 | 31.30 | Beat vs cons, down from 47.40. Still expansion. |
| Pending home sales | +0.30% | −0.20% | Small beat. |
| EA CPI YoY | **3.20%** | 3.30% | Slight miss vs cons, up from 2.90%. Matches FXStreet HICP 3.2%. |
| EA core CPI | **2.40%** | 2.40% | In line, down from 2.50%. |
| CFTC EUR specs (prev) | **−42.6k** | — | Same crowding as Barchart non-commercials net short ~42.6k. |

Friday 18 Sep still on the page: **German PPI**, **Lagarde speaks**, US
industrial production / capacity utilization. Stand aside ±30 minutes through
Lagarde.

### News on the same page

- “Dollar pauses after Fed rally as yields, oil retreat” (Reuters) — the bounce.
- “Fed Delivers Hawkish Hike, Dollar Rallies but Gold Recovers” — hike is the
  regime; gold bounce is not a euro bid.
- “US Rates Steady After Thursday’s Surge and the Greenback Consolidates”
  (Marc Chandler) — consolidation, not reversal.

Ignore the Ferrari / Touax company slides that share the rail. They are not
EUR/USD.

### Related tape on the page

DXY futures ~**99.97** (−0.01%), WTI **$101.31** (−1.09%), Brent **$104.16**,
gold ~**4382**, VIX **15.44**. Oil off and yields off is the same bounce
FXStreet described. Dollar index still near the post-Fed high.

## Standing rules this page adds

- Investing.com last is a **sixth print**. Cloudflare may block it. Sit out on
  OANDA vs CurrencyFreaks disagreement regardless.
- Daily+weekly **Strong Sell** agrees with Barchart 72% Sell. That is crowding.
  Do not chase it at the day low.
- **CME ~1.1519** is a fade into Barchart R1, not a long trigger.
- **CFTC EUR −42.6k** is the same spec crowding. Do not add.
- A claims beat **caps** EUR/USD bounces even when oil/yields dip for a session.
- EA CPI 3.2% / core 2.4% is not a hawkish ECB surprise versus the Fed path.
- 1-year **−2.86%** agrees with TE. Do not buy the 1.16/1.18 recovery map
  against live H1.
- Lagarde on Friday: stand aside through the speech, then trade the H1 reaction.
