# FXStreet — EUR/USD forecast, news, and analysis

Standing notes for the EUR/USD specialist. Live numbers are rewritten into
`desk/EURUSD_PLAYBOOK.md` every intel cycle. This file is the desk's memory of
**how to read** [fxstreet.com/currencies/eurusd](https://www.fxstreet.com/currencies/eurusd).

Direct HTTP often hits Cloudflare. A blocked fetch never stops the intel cycle.
The skim below is from 17 September 2026.

## What the page is

FXStreet's EUR/USD hub is a **daily wrap**, not a live order book:

- A lead on why spot is moving today
- Daily technicals: 100-day SMA, Bollinger (20, 2), RSI(14), listed resistance
- A fundamental wrap: Fed, ECB speakers, oil, US 10Y, DXY, claims, HICP
- A crowd poll (1 week / ~1 month / 1 quarter)
- Primer copy on EUR/USD as a Major, ECB, Fed, Lagarde

It is slower than OANDA M5. Use it for **levels and the narrative**, not for
fills. The desk still only trades EUR/USD.

## How the bot uses it

Every 20 minutes the intel loop tries the public HTML and:

1. Cross-checks the FXStreet last against OANDA (fourth print, after
   CurrencyFreaks and Trading Economics). A miss or Cloudflare block is logged,
   not a halt.
2. Writes daily bias, RSI, and the resistance ladder into the playbook.
3. Pulls FedWatch, claims, DXY, WTI, US 10Y, and EA HICP from the wrap.
4. Records the crowd poll. **Crowd is not a ticket.**

Source module: `src/data/fxstreet.py`.

## Skim — 17 September 2026

### Lead

EUR/USD traded modestly higher as falling oil pulled US Treasury yields off
their recent highs and the dollar trimmed part of its post-Fed gains. Spot
**around 1.1492, +0.24% on the day**, hovering near levels last seen on
**31 July**. That is a bounce on a weak-euro tape, not a trend change.

### Daily technicals (FXStreet)

Bearish near-term bias. Spot holds **below all major reference lines**. The
100-day SMA and the Bollinger (20, 2) middle sit overhead. Even the **lower
Bollinger band now acts as initial resistance**.

| Level | Print | Role |
| --- | --- | --- |
| RSI(14) | **32.29** | Near oversold. Selling is stretched; bears still control the structure. |
| Former lower BB | **1.1485** | Immediate resistance |
| 100-day SMA | **1.1550** | Caps a bounce |
| BB middle | **1.1605** | Next supply |
| BB upper | **1.1720** | Broader supply. Spot would need to reclaim this zone to ease the bearish tone. |

FXStreet lists **no meaningful supports below the market**. That is not a
license to short the washout. This book already paid −$81 shorting the lower
band with RSI oversold. **Do not short RSI ~32 at/under the lower band.** If
anything, wait for a failed rally into **1.1485 / 1.1550**.

### Fundamentals on the same page

| Print | Read for this pair |
| --- | --- |
| WTI ~**$95.50**, −2% | Saudi rerouting / pipeline-recovery hopes ease supply worry. Oil off = less EA inflation impulse, less ECB-hike urgency, and yields off highs. |
| US 10Y ~**4.94%** (was 5.04% earlier this week, highest since 2007) | Yields easing lets EUR/USD bounce; they are still high. |
| Fed | Unanimous **+25 bp to 3.75–4.00%**, first hike since 2023. **16 of 18** officials see at least one more quarter-point by year-end. |
| CME FedWatch | ~**50%** chance of another hike in **October**. Extra Fed tightening **caps** EUR/USD recoveries even if the ECB is also hiking. |
| Jobless claims | **196k** vs 206k prior vs 208k expected. A beat supports USD. |
| DXY | ~**100.08** after **100.37** intraday (strongest since 31 July). |
| EA HICP final Aug | Headline revised to **3.2%**, core **2.4%**. |
| Makhlouf (ECB) | “Risks to inflation remain on the upside.” “Can't rule out anything at future meetings.” |
| Rehn (ECB) | Last week's hike was warranted. Inflation outlook “somewhat mixed.” EZ economy resilient; no second-round effects so far. |

Net: dollar still has the higher yield and a hawkish Fed path. The bounce is
oil/yields coming off, not a euro bid.

### Crowd poll (updated 11 Sep, 15:00 GMT)

| Horizon | Bullish | Bearish | Sideways |
| --- | --- | --- |
| 1 week | 33% | **67%** | 0% |
| ~1 month | 21% | 43% | 36% |
| 1 quarter | **60%** | 27% | 13% |

Near-term crowd is short; quarter-out crowd is long. That is the same 1.16/1.18
recovery story Trading Economics models. **Do not buy the quarter poll against
a live H1 downtrend. Do not pile into the 67% 1-week bearish crowd at RSI 32.**

### Session primer (useful, already how this desk is built)

EUR/USD is a Major (> half of FX volume). Quiet in Asia; volume rises with
Europe, dips at European lunch, rises again when the US opens. This desk's
session is already 00:00–22:00 UTC (Tokyo through New York). ECB President
Christine Lagarde (since 1 Nov 2019) and Fed/FOMC copy on the page match the
existing news blackout around EUR/USD high-impact prints.

## Standing rules this page adds

- FXStreet last is a **fourth print**. Cloudflare may block it. Sit out on
  OANDA vs CurrencyFreaks disagreement regardless.
- **1.1485 / 1.1550 / 1.1605 / 1.1720** are the resistance ladder until H1
  reclaims them. They are fade zones for rips, not long triggers.
- RSI 32 on a bearish daily is the **same setup that stopped this book**. Do
  not short it.
- FedWatch ~50% October hike **caps** bounces. A 1.1492 bounce after a Fed hike
  is expected mean-reversion, not a regime change.
- Oil down + 10Y off highs can lift EUR/USD a few hours. Trade H1 reaction,
  not the first oil tick.
- Crowd polls are a contrary check, not a signal.
