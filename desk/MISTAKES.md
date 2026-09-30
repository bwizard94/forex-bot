# Mistakes this EUR/USD desk is trained to refuse

> Historical educational notes. Fixed timeframe, risk, session, score and exclusion examples below are not current runtime policy. [OPERATING.md](OPERATING.md) takes precedence; negative outcomes alone do not establish these mistake labels or authorize a broad strategy ban.

Standing avoidance book, skimmed from:

- [Forex.com — Common forex trading mistakes](https://www.forex.com/en/trading-academy/courses/successful-trading-techniques/common-forex-trading-mistakes/)
- [MultiBank — Common forex trading mistakes and how to avoid them](https://multibankfx.com/en/blog/trading-101/common-forex-trading-mistakes-and-how-to-avoid-them)
- [Taurex — Forex trading mistakes](https://www.tradetaurex.com/forex-insights/forex-trading-mistakes/)
- [Titan FX — Common forex trader mistakes](https://titanfx.com/education/common-forex-trader-mistakes-and-how-to-avoid-them)
- [ForTraders — Why trading bots lose money](https://fortraders.com/blog/trading-bots-lose-money)
- [J2T — Forex trading robots](https://j2t.com/solutions/blogview/forex-trading-robots/)
- [CoinBureau — Crypto trading bot mistakes](https://coinbureau.com/guides/crypto-trading-bot-mistakes-to-avoid)
- Build-a-bot pages (OpoFinance, Pixelbrainy, Digitalogy, SocialVPS, ForexVPS, Investopedia EA, FOREX.com algo): demo first, always a stop, VPS is hosting not a strategy, fees and slippage, kill switch.

The Ox scalp already had a plan, a hard stop, news blackout, revenge cooldown, and EUR/USD-only. This file is the rest: **see the mistake, label it, refuse it**.

## Taxonomy the journal writes

Each closed desk loss can carry one or more codes:

| Code | What it means | How this bot refuses it |
| --- | --- | --- |
| `no_plan` | Ticket without a thesis | Every fill writes a journal; no thesis, no ticket |
| `no_stop` | Opened without a hard stop | ATR stop is mandatory; below the floor is a skip |
| `overleverage` | Size too large vs NAV / stop | 0.6% / 0.9% / 0.4% table, 2.5% open-risk, 100k unit cap |
| `revenge` | Re-entered too fast after a stop | 4-minute post-loss cooldown; two losses sit the session |
| `overtrading` | Too many tickets in one UTC day | Cap **8** bot fills per UTC day |
| `chasing` | Bought a spike or sold a washout | Never buy RSI≥60 / upper band / WT≥53; never short RSI≤40 / lower band / WT≤−53 |
| `news` | Traded through a high-impact print | ±30-minute EUR/USD blackout |
| `weekend_gap` | Friday close / Sunday reopen | Friday flat after **20:00 UTC**; **no Sunday tickets** |
| `session_open` | Thin Monday Tokyo open | First **45 minutes** Monday after 00:00 UTC sit out |
| `averaging_down` | Added to a loser (martingale / grid) | Add-on only onto a ticket already **+2 pips**; named anti-martingale skip |
| `fees_slippage` | Spread or fill ate the edge | Spread cap 1.8 pips; spread may not eat **25%** of the stop; fat fill cools off **20 minutes** |
| `stale_quote` | Sized off a dead print | Kill switch: OANDA quote older than **90s** is not a ticket |
| `chop_stop` | Stopped in minutes | Time-stop at 90 minutes; chop losses demand a new H1 impulse |
| `unattended` | No human kill switch | `ENABLE_TRADING=false` or dashboard pause; do not set-and-forget a runaway book |
| `overfitting` | Kitchen-sink / curve-fit model | Ox triad + H1. No Random Forest / LSTM replacing the scalp |

## Calendar (weekend gap and session open)

Spot FX gaps over the weekend. Taurex / Titan / Forex.com: do not hold into Friday close and do not scalp the Sunday reopen.

- Saturday: closed.
- Sunday: **closed**. The 21:00 UTC reopen is not a ticket.
- Friday after 20:00 UTC: **no new tickets**. Session still ends 22:00 UTC weekdays; Friday is two hours earlier so we are not the last print into the gap.
- Monday 00:00–00:45 UTC: **session-open buffer**. Tokyo is thin; wait for a committed M5.

Weekend work (Investopedia): read D1, plan Monday, sit on hands.

## Overtrading

More signals is not more edge. Cap is **8 desk fills per UTC day**. Soft daily halt, consecutive-loss sit-out, and re-entry pauses still fire first. Quality over quantity.

## Anti-martingale / no grid

ForTraders and J2T: martingale and grid robots blow up. This desk:

- Never adds to an underwater ticket (needs +2 pips first, then 0.4% add-on).
- After any real loss today, the next ticket is **reduced** size (fade risk), not conviction.
- Two consecutive losses sit until the next session open.
- Does **not** double size after a stop. Does **not** run a grid of EUR/USD slots.

## Fees, slippage, stale quotes (CoinBureau: rules before code)

- Spread > 1.8 pips: skip.
- Spread / stop ≥ 25%: skip — the scalp is paying the broker.
- Last fill slipped ≥ 1.5 pips: 20-minute cool-off.
- OANDA quote older than 90 seconds: **kill switch**, no new ticket.
- `ENABLE_TRADING=false` is the human kill switch. Dashboard pause is the same.

A VPS (SocialVPS / ForexVPS) keeps the loop alive. It is not a strategy. Unattended + martingale is how bots go to zero.

## What we already refused (kept)

- No plan / no journal.
- No stop / walking the stop.
- Revenge after a stop.
- FOMO size-up after one fat winner (median P/L, not the +$775 mean).
- Kitchen-sink ML. Regime is named (squeeze / trend / rip / washout / chop); continuation dojis are skipped.
- EUR/USD only. Operator fills stay `OPEN_ONLY`.
- News ±30 minutes.

## Build-a-bot pages: what we did **not** copy

OpoFinance / Pixelbrainy / Digitalogy / SocialVPS / ForexVPS / Investopedia robot / FOREX.com algo:

- MT4 Expert Advisor language. This book is Python + OANDA practice.
- “AI” as Random Forest / LSTM labelling the next 5–15 minutes. Rejected in 2.17.0.
- Vendor VPS as alpha. Hosting is ops, not edge.
- Set-and-forget. J2T: a robot still needs a human reviewing the book.

Kept from those pages: **demo before live** (this *is* the demo), **always a stop**, **backtest without shuffling** (`desk/HISTORY.md`), **name the regime**, **skip indecision candles**, **kill switch**, **count costs**.

Sources stay in this file. The live loop rereads it with `desk/OPERATING.md` before the next ticket.

## Research mistakes to watch — 2026-09-22

These are review notes and proposed diagnostics, **not new implemented journal codes or execution gates**. Details and sources are in [RESEARCH.md](RESEARCH.md).

| Research mistake | Review action |
| --- | --- |
| Calling one winning trade a proven setup | Show count, date range, uncertainty and selection history. Current history buckets can be tiny. |
| Selecting the best of many trials and hiding the rest | Keep every trial; account for multiple testing. [Harvey](https://people.duke.edu/~charvey/Teaching/656_2026/Public_Presentations_656/656_Follow_2026.pdf) |
| Confusing gross replay pips with executable profit | Include costs and actual exit mechanics. [Intraday FX study](https://files.stlouisfed.org/files/htdocs/wp/1999/99-016.pdf) |
| Using a higher-timeframe close before it exists | Audit availability times, not just index labels; OANDA labels candles by start time. [OANDA definitions](https://developer.oanda.com/rest-live-v20/instrument-df/) |
| Counting several related indicators as independent confirmation | Test whether each family adds information. [Bollinger's rules](https://www.bollingerbands.com/bollinger-band-rules) |
| Treating an MT4 copy or correlated add-on as another independent success | Group outcomes by originating decision and venue. |
| Assuming a completed news timer means normal liquidity | Check event coverage and observed execution conditions; spreads can widen around news. [OANDA disclosure](https://www.oanda.com/us-en/trading/spreads-margin/) |
