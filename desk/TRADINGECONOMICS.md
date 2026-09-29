# Trading Economics — euro-area currency (EUR/USD)

Standing notes for the EUR/USD specialist. Live numbers are rewritten into
`desk/EURUSD_PLAYBOOK.md` every intel cycle. This file is the desk's memory of
**how to read** [tradingeconomics.com/euro-area/currency](https://tradingeconomics.com/euro-area/currency).

## What the page is

Trading Economics treats **Euro Area currency** as **EUR/USD**. The page is a
daily-frequency EUR/USD quote with:

- Last, daily change, monthly %, yearly %
- A model forecast ladder (quarter-end through ~12 months)
- EUR crosses (GBP, JPY, CHF, CNY, …)
- Related Euro Area / US prints that actually move this pair (inflation, policy
  rates, payrolls, unemployment)
- A euro news stream written around Fed / ECB / oil

Historical coverage on the page goes back to 1957 as a **synthetic** series
(weighted legacy European currencies). The euro itself only exists from
**1 January 1999**. Do not treat 1973's 1.87 "all-time high" as a live EUR/USD
level.

## How the bot uses it

Every 20 minutes the intel loop fetches the public HTML (no TE API key) and:

1. Cross-checks the TE last against OANDA and CurrencyFreaks (`QUOTE_WARN_PIPS`,
   default 8). TE is the **third print**, not a replacement broker feed.
2. Writes related inflation / Fed funds / ECB rate into the playbook so the
   **policy spread** is visible next to DXY.
3. Pulls TE's quarter and 12-month model. That map is slow mean-reversion, not
   a reason to fade a live H1 trend.
4. Prepends TE euro headlines into the intel book (Fed hike, ECB, oil).

Source module: `src/data/tradingeconomics.py`.

## Skim — 17 September 2026

Pulled from the live page the same day this source was wired in.

### Quote

| Field | Print |
| --- | --- |
| Last | **1.1479** (header 1.14792; table 1.1479; meta 1.1478) |
| Daily | **+0.0014 / +0.12%** |
| Month | **about −0.83% to −0.84%** |
| Year | **about −2.62% to −2.63%** |
| Tape | Euro just below $1.15, weakest since late July |

A +12 pip bounce on the day does **not** unwind a month/year of euro weakness.
Spot is still a weak-euro tape.

### Forecast (TE global macro models)

`TEForecast = [1.16, 1.17, 1.18, 1.18]`

- Quarter-end (labelled Q3 on the page): **1.16092 ≈ 1.16**
- 12 months: **1.18**

That is roughly **+120 pips** this quarter and **+320 pips** over a year versus
spot ~1.148. Use it as a slow recovery map if H1 actually turns. **Do not buy
1.16/1.18 against a live H1/D1 downtrend.** This book already paid for fading
shorts after one fat winner.

### Related prints on the same page (the EUR/USD macro)

| Print | Last | Previous | As of | Read for this pair |
| --- | --- | --- | --- | --- |
| Euro Area inflation | **3.20%** | 2.90% | Aug 2026 | EA CPI is accelerating. That can keep the ECB hiking and support EUR — but it has not stopped the euro sitting near a two-month low. |
| US inflation | **3.40%** | 3.40% | Aug 2026 | US CPI still above EA. Hot US inflation bids USD. |
| Fed funds | **4.00%** | 3.75% | Sep 2026 | First hike since July 2023, range 3.75–4.00. FOMC majority sees another hike later this year. USD-positive. |
| ECB rate | **2.65%** | 2.40% | Sep 2026 | ECB hiked last week (second hike this year). Markets still price at least one more this year; oil coming off reduces that urgency. |
| Policy spread | **Fed − ECB ≈ +1.35 pp** |  | Sep 2026 | USD still pays more. A wide USD yield advantage usually weighs on EUR/USD. |
| US non-farm payrolls | **162k** | 21k | Aug 2026 | Payrolls rebound is USD-positive until the next miss. |
| US unemployment | **4.10%** | 4.10% | Aug 2026 | Steady. Not a USD-softener on its own. |
| Euro Area unemployment | **6.40%** | 6.40% | Jul 2026 | Steady. Not the driver this week. |

### News stream (what TE says is moving EUR/USD)

1. **17 Sep — "Euro Holds Near Two-Month Low as Fed, ECB Rate Bets Rise."**
   Fed hiked to 3.75–4.00% and signalled another hike this year. Markets still
   price at least one more ECB hike, but oil is off a second day (Brent ~$105
   after Saudi comments on restoring East-West pipeline capacity). Middle East
   risk keeps oil elevated and complicates both central banks.
2. **16 Sep — "Euro Holds Near One-Month Low Ahead of Fed Decision."**
   Euro around $1.155 into the Fed. Markets were pricing ECB deposit ~2.9% by
   December (from ~2.5%) and ~3.4% by Nov 2027.
3. **14 Sep — "Euro Slides as Dollar Holds Firm Ahead of Fed Decision."**
   Oil > $100 on Gulf conflict; long-dated bonds sold. Busy CB week: Fed Wed,
   BoE Thu (hold, close vote), BoJ Fri (hike expected).

Related TE headlines on the same screen: Eurozone inflation remains elevated as
energy costs soar; ECB raises rates as expected; Eurozone growth revised to
0.6% Q2; ZEW unexpectedly weak; trade surplus highest in 9 months; wage growth
slows in Q2.

### EUR crosses (context, not traded)

The desk only trades EUR/USD. Crosses on the page for 17 Sep:

- EURGBP 0.8593 **+0.30%** on the day — euro bid vs sterling even while EUR/USD
  is heavy. That is dollar strength more than broad euro collapse.
- EURJPY 179.04 **−0.06%** / **+2.70% year** — euro still firm vs yen on the year.
- EURCHF 0.9465 **−0.03%** / **+1.31% year**.
- EURCNY 7.695 **~flat** / **−8.16% year**.

If EUR/USD is down and EURGBP is up, hunt the **dollar**, not a pan-EUR dump.

## Standing rules this page adds

- TE last is a **third EUR/USD print**. If OANDA and CurrencyFreaks disagree,
  compare both to TE. If CF is the outlier, still skip new tickets until CF
  reconverges — do not size just because TE likes OANDA.
- **Fed–ECB policy spread** belongs on the tape next to DXY. A 1%+ USD yield
  advantage is a reason to prefer shorts when H1 agrees, not a standalone
  market order.
- **Oil** is now an EUR/USD driver on this desk: a jump in Brent lifts EA
  inflation and can force the ECB, but the first shock often bids USD.
- TE's **1.16 / 1.18 model is not a long signal**. The yearly print is still
  a weaker euro. Wait for H1 to flip before treating the forecast as a hunt.
- The 1973 1.87 high is synthetic pre-euro history. Ignore it for stops and
  targets on this book.
