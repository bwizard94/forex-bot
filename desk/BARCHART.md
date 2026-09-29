# Barchart — Euro/U.S. Dollar (^EURUSD)

Standing notes for the EUR/USD specialist. Live numbers are rewritten into
`desk/EURUSD_PLAYBOOK.md` every intel cycle. This file is the desk's memory of
**how to read** [barchart.com/forex/quotes/^EURUSD](https://www.barchart.com/forex/quotes/%5EEURUSD).

Direct HTTP often hits CloudFront or a 202 bot interstitial. A blocked fetch
never stops the intel cycle. The skim below is from 17 September 2026 ~14:51 CT.

## What the page is

Barchart's ^EURUSD hub is a **quote + positioning wrap**, not a live order book:

- Last, bid/ask, day range, open, previous close, YTD / 52-week high-low
- Weighted alpha, relative strength, 5-day change
- Barchart Technical Opinion (percent Sell/Buy)
- Daily pivot ladder **R3–S3** (real supports — FXStreet listed none)
- 52-week Fibonacci 61.8 / 50 / 38.2
- Commitment of Traders (specs, leveraged funds, commercials, asset managers)
- Related: $DXY, FXE, Euro FX futures
- A euro/dollar commentary lead (claims, housing, Fed)

It is slower than OANDA M5. Use it for **supports, crowding, and range**, not
for fills. The desk still only trades EUR/USD.

## How the bot uses it

Every 20 minutes the intel loop tries the public HTML and:

1. Cross-checks the Barchart last against OANDA (fifth print, after
   CurrencyFreaks, Trading Economics, and FXStreet). A miss or CloudFront
   block is logged, not a halt.
2. Writes daily S1–S3 / R1–R3 and 52-week fibs into the playbook.
3. Reads COT spec and leveraged-fund net. **Crowded shorts are not a ticket.**
4. Records the 72% Strong Sell opinion. **Opinion is not a ticket.**

Source module: `src/data/barchart.py`.

## Skim — 17 September 2026 (~14:51 CT)

### Quote

Last **1.14799**, +0.00159 (**+0.14%**). Bid/ask 1.14796 / 1.14801. Day
**1.14565–1.14977**. Open 1.14642, previous close 1.14640.

| Print | Value | Read for this pair |
| --- | --- | --- |
| YTD / 52w high | **1.20806** (−4.99% from high) | Spot is still a weak-euro tape. |
| YTD / 52w low | **1.13246** (+1.36% off the low) | Room under the market exists. |
| Weighted alpha | **−2.40** | Medium-term drift is down. |
| Relative strength | **35.07** (+2.89) | Soft, not a reversal. |
| 5-day change | **−1.15%** | The bounce is inside a down week. |

That 0.14% bounce is oil/yields off post-Fed highs — the same story FXStreet
and Trading Economics told. It is **not** a trend change.

### Technical opinion

**Strong Sell**, **72% Sell**, average short-term outlook to maintain
direction. Long-term indicators fully support continuation.

72% Strong Sell does **not** license shorting RSI ~32 at the day low. This
book already paid −$81 doing that. A crowded sell opinion at a washout is
the same trap as FXStreet's 67% 1-week bearish crowd.

### Daily pivots (the missing supports)

FXStreet listed resistance only. Barchart fills the hole:

| Level | Print | Role |
| --- | --- | --- |
| R3 | **1.16220** | Far supply |
| R2 | **1.15893** | Aligns with FXStreet 100-day SMA zone |
| R1 | **1.15266** | First fade for rips. Not a breakout buy. |
| Last | 1.14799 | Inside the day. |
| S1 | **1.14312** | **First real support.** |
| S2 | **1.13985** | Next demand |
| S3 | **1.13358** | Near the 52-week low 1.13246 |

Do not buy a break of the **1.14977** day's high. Fade failed rallies into
**R1 1.15266**. If H1 is still down, the next hunt is a failed bounce — not
a market-sell at S1.

### 52-week Fibonacci

| Level | Print |
| --- | --- |
| 52w high | 1.20806 |
| 61.8% | **1.17918** |
| 50% | **1.17026** |
| 38.2% | **1.16134** |
| Last | 1.14799 |
| 52w low | 1.13246 |

Spot is **below every 52-week fib**. Reclaiming 1.16134 would be the first
hint the yearly downswing is pausing. Until then, 1.16/1.18 recovery models
(Trading Economics, FXStreet quarter poll) are still fade-the-forecast.

### Commitment of Traders (as of 8 Sep 2026)

| Group | Long | Short | Net |
| --- | --- | --- |
| Non-commercials (specs) | 198,509 | 241,125 | **net short ~42.6k** |
| Leveraged funds | 94,808 | 128,093 | **net short ~33.3k** |
| Commercials | 593,162 | 586,432 | slightly net long |
| Asset / manager | 484,443 | 233,765 | net long |

Specs and levered funds are **already short**. Do not add to that crowding
into S1. Asset managers holding the long side is why washout shorts keep
getting squeezed a few hours — exactly the −$81 lower-band ticket.

### Related tape

| Symbol | Last | Note |
| --- | --- | --- |
| $DXY | **100.21** | Still firm vs the July lows. |
| FXE | 105.92 | Euro ETF echoing the pair. |
| E6Z26 | 1.15200 | Euro FX futures sit up at Barchart R1. |

### Commentary lead

“Dollar Slightly Lower as T-Note Yields Fall.” DXY −0.03% off a 1.5-month
high. Claims **196k** vs 207k expected (8-week low — USD support). Housing
starts **−2.6%** miss. Fed **+25 bp** and another hike this year still on
the table. Dollar losses were limited. Same Fed-path cap FXStreet's FedWatch
~50% October hike described.

## Standing rules this page adds

- Barchart last is a **fifth print**. CloudFront may block it. Sit out on
  OANDA vs CurrencyFreaks disagreement regardless.
- **S1 1.14312 / S2 1.13985 / S3 1.13358** are the demand ladder until H1
  reclaims them. They are bounce-risk for shorts, not long triggers.
- **R1 1.15266 / R2 1.15893** are fade zones for rips. Do not buy a break of
  the 1.14977 day's high.
- **72% Strong Sell** plus specs already net short is crowding. Do not chase
  it at the day low or with RSI oversold.
- Spot **−4.99% from the 52-week high**, below all 52w fibs. That agrees
  with TE's yearly −2.6% weaker euro. Do not buy the 1.16/1.18 recovery map
  against live H1.
- Claims beats and a hawkish Fed path **cap** EUR/USD bounces even when
  yields dip for a session.
