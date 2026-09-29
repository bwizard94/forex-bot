# How this EUR/USD desk operates

Standing doctrine, skimmed from:

- [Ox Securities — Most profitable trading strategies](https://oxsecurities.com/most-profitable-trading-strategies/)
- [LiteFinance — Best Forex trading strategies](https://www.litefinance.org/blog/for-beginners/trading-strategies/) (updated 12 Feb 2026)
- [Dukascopy — Top trading strategies in forex](https://www.dukascopy.com/swiss/english/marketwatch/articles/top-trading-strategies-in-forex/) (27 Jul 2023)
- [Investopedia — 8 forex trading tips](https://www.investopedia.com/articles/forex/08/successful-trader-traits.asp) (live page 402; text from public archive of that URL)
- [desk/MISTAKES.md](MISTAKES.md) — common-mistake + bot-fail articles (Forex.com, Taurex, Titan, ForTraders, J2T, CoinBureau) so the desk labels and refuses them

This is **how the bot should behave**, not a price print and not a new indicator kitchen-sink. The hunt stays EUR/USD only. A stacked Sell / RSI washout is still not a short.

## This desk's style (Investopedia: identify the style first)

We are an **intraday EUR/USD scalper** (Ox's first "most profitable" recipe), not a multi-day swing and not a weekly position book:

| Style | This book? | Why |
| --- | --- | --- |
| Scalping (minutes–a couple of hours, short SL/TP) | **Primary** | Ox EUR/USD scalp: LWMA 48 + Trend Envelopes 2 + DSS, short stops and targets. M5 trigger, H1 map. |
| Day trading (in and out the same UTC day) | **Allowed** | Session 00:00–22:00 UTC. Time-stop a dead scalp at 90 minutes. |
| Swing (hold hours to a few days for the pullback in the trend) | **No** | That was the old book. Scalp geometry does not sit through a D1 swing. |
| Position / multi-month wave | **No** | Ox weekly candlestick (100–140 point SL, 50–70 TP) is rejected — R:R < 1 and not this pair's job. TE 1.16/1.18 forecasts are not tickets. |

LiteFinance: beginners do best on **M30–H1 majors** with two or three tools. Ox scalp uses three tools on EUR/USD. Our live loop is **M5 entries under H1/D1 bias** with those three (LWMA, envelopes, DSS).

Dukascopy: pick one style, backtest it, demo it, then size up. This practice book *is* the demo. Do not invent a second personality mid-ticket.

The 5-pip stop floor stays. Spread + a 2-pip sniper still loses on OANDA. This is a **calculated EUR/USD scalp**, not an ECN 3-pip lottery.

## Number one rule (Dukascopy)

**Preserve capital.** "Don't risk more than you can afford to lose." There is no 100% winning strategy. Losses are part of the game. Stay in the game.

LiteFinance numbers, sized for more frequent scalps:

- Risk per ticket **0.6%** of NAV (conviction **0.9%** / add-on **0.4%** / fade **0.4%**).
- Always a **stop-loss**. Never walk it out of hope.
- Reward must justify risk (min R:R 1.15). A 40% book with 1:1.2 still needs the time stop so losers do not become swings.
- After an unexpected fat win **or** a stop: take a break. Pause 4 minutes after a stop, 2 after a win, sit the side out after two stops, and cut size after a losing day.

We do **not** use 15% total exposure. Combined open desk risk stays at **2.5%** of NAV with a 3% daily halt and 10% drawdown breaker. Tighter than the textbook, on purpose.

## How a ticket is allowed to exist (LiteFinance + Investopedia)

A good currency strategy **combines tools**. Trend gives the main signal; breakouts/patterns add; oscillators and participation confirm.

On this desk that means, in order:

1. **Higher-timeframe trend first.** Read H1, then D1. M5 is the trigger, not the map. Investopedia: if the higher chart is a buy, wait until the lower chart agrees. Do not take a weekly long off an intraday sell.
2. **Trade with the trend until it is confirmed over.** LiteFinance: beginners are better in a trend than in a grind. Getting in early *once confirmed* is simpler than fading every wiggle.
3. **Pullbacks inside the trend are the scalp entry.** Discounted longs in an H1 uptrend; faded rallies in an H1 downtrend. Not chasing the spike. Take the pips; do not hold for a D1 swing.
4. **Range / mean-reversion is a fade of the *rip*, not a short of the washout.** LiteFinance Keltner+RSI: signal when price leaves the channel *and then reverses*, with RSI at 70/30. Our version: never short lower-band / RSI ≤ 40 / WaveTrend ≤ −53; never buy the upper-band spike. Fade into Barchart R1 / VWAP stretch instead.
5. **Breakouts need a close, not a wick.** Dukascopy: wait for a confirmed close through the level; false breakouts are the tax. Our Donchian sweep (wick through, close back inside) is the *warning*, not the chase. A genuine break must close and hold with H1.
6. **Price action confirms; it does not lead.** LiteFinance: candlestick patterns (engulfing, pin, double top, three black crows) are extra, used with indicators. Hub Chart already stamps patterns. Do not market-order a pin bar against H1.
7. **Fibonacci is a pullback map inside the trend.** Dukascopy 38.2 / 50 / 61.8. Use with H1, not as a standalone reversal. Hub Chart already draws fibs. Do not buy a break of 50% against D1.
8. **News is a blackout, then a reaction.** LiteFinance: trends backed by CPI/NFP/FOMC/ECB are sharp and short. Stand aside ±30 minutes. Trade the H1 reaction, not the first tick. Dukascopy day-trading example is exactly that (NFP, then a level). Pair-page wires live on [Forex Factory EUR/USD](https://www.forexfactory.com/market/eurusd) — context, not a ticket.

## What we explicitly will not do

From Dukascopy's "why 95% fail" and LiteFinance's emotion list:

- **No 2-pip ECN sniper.** Spread still eats that. Floor is 5 pips; skip when spread > 1.8 pips.
- **No counter-trend without extra confluence.** Dukascopy: counter-trend is riskier. Against D1 we already demand more votes. Against H1 we block.
- **No revenge trade** after a stop (cooldown + two-loss sit-out).
- **No overtrading.** Cap **8** desk fills per UTC day.
- **No Friday-into-weekend tickets.** Flat after 20:00 UTC Friday. **No Sunday reopen.** Monday Tokyo first 45 minutes sit out.
- **No martingale / grid / averaging down.** Add-on only onto a ticket already +2 pips; after a loss today, next size is reduced.
- **No FOMO / euphoria size-up** after one fat winner. Growth reports descriptive results and initial-risk coverage; winning statistics do not authorize preference or size increases. Existing loss cooldowns remain.
- **No moving the stop away** because "it might come back."
- **No overleverage.** Units are NAV × risk / stop distance, capped.
- **No trading without a thesis.** Every fill writes a journal; every close writes a post-mortem and may tag a mistake code.
- **No stale-quote tickets.** OANDA print older than 90s is a kill switch. Fat slippage cools off 20 minutes. Spread may not eat 25% of the stop.
- **No get-rich-quick.** Small, steady expectancy beats hunting a miracle system.
- **No kitchen-sink.** Two or three confirming families (Ox triad + H1), not every Pine script on TradingView.
- **No Ox weekly candlestick.** SL twice the TP is not a scalp and not this book.
- **No unattended runaway.** `ENABLE_TRADING=false` or dashboard pause. A VPS is hosting, not a strategy.

## Expectancy, not win rate (Investopedia)

```
expectancy = (% wins × average win) − (% losses × average loss)
```

A 40% win rate with 1:2 R:R still pays. A 70% win rate with tiny wins and fat stops does not. This desk already restudies expectancy by setup × side × session in `desk/GROWTH.md` and skips a named setup whose expectancy is negative. **Do not keep taking a side because one outlier left the mean green.**

Track results. LiteFinance: if live results drift from the tested book, reassess — that is the growth/history loop, not a new strategy.

## Weekend / closed-market work (Investopedia)

When the tape is shut (Saturday, Sunday, or after 20:00 UTC Friday):

- Read the **D1 / weekly** map: trend, prior-day high/low, Barchart S1–R1, 52w fibs.
- Plan the next session's hunt. Do not invent Monday tickets from a Sunday headline.
- Patience: wait for the setup the plan named. Sitting on hands is a valid trade.
- Monday Tokyo first 45 minutes stay flat — session-open chop is not a scalp.

The 08:00 UTC briefing and 23:30 UTC recap are that weekend analysis, every weekday.

## Record (Investopedia + LiteFinance)

Keep an objectified record of every ticket:

- Why the trade (H1/D1, RSI/VWAP/sweep, news blackout).
- Entry, stop, targets marked on the OANDA chart.
- What emotion would have done instead (panic exit, greed add). Execute the system, not the habit.

That is already `desk/LEARNING_LOG.md`, the journal table, and the Chart markup. Use them. Do not skip the post-mortem on a scratch.

## Dual venue (OANDA + MT4)

The hunt is still one EUR/USD desk. OANDA practice is the primary book. An MT4 demo, when connected on Overview, gets a **copy** of each desk fill (magic 212100). Copies do not eat OANDA stack caps. Operator tickets on either book stay hands-off. An MT4 reject does not flatten OANDA. See `desk/MT4.md`.

## Mapping onto the live hunt

| Textbook idea | What this bot actually does |
| --- | --- |
| Trend following / Alligator-style MA | EMA 9/21 + Supertrend + EWMAC + H1 LWMA 48 |
| Ox scalp (LWMA + envelopes + DSS) | WMA 48, Trend Envelopes 2, DSS of momentum on M5 |
| Swing pullback | RSI/WaveTrend pullback with H1, not the extreme chase |
| Range fade | VWAP/TMA stretch + band spike/washout HOLDs |
| Breakout | Confirmed continuation; Donchian sweep is the fakeout |
| Keltner + RSI | TTM squeeze (BB inside Keltner) + RSI/WaveTrend |
| Multi-timeframe sync | D1 bias, H1 bias, M5 trigger |
| Short SL/TP | 1.0 / 1.2 / 2.0 ATR, 5-pip floor, 90-minute time stop |
| 0.6% risk, always SL | Risk manager + ATR geometry |
| Journal + expectancy | Journal, GROWTH.md, setup_memory, mistake tags |
| News | Calendar blackout ±30m |
| Capital first | Daily halt, DD breaker, last-two-stop sit-out, spread cap 1.8 pips, 8-ticket day cap |
| Weekend gap | Friday flat 20:00 UTC; no Sunday reopen; Monday open buffer |
| Anti-martingale | No add to a loser; reduced size after a loss today |
| Kill switch | Stale quote >90s; `ENABLE_TRADING=false`; dashboard pause |
| Fees / slippage | Spread/stop ≥25% skip; fat fill cool-off 20m |
| Historical restudy | Background thread + 6h job. Never on the quote/minute/intel clock. Replay rows are `source=history`. |

The live clock (15-second quotes, M5 tickets, intel) does **not** wait on ForexSB Supertrend. History is memory, not a gate that can miss a fill. An add-on needs the open ticket to be **at least 2 pips in profit** — a $2 scratch is not a winner. OANDA FIFO rejects are sticky until that fill is gone.

Do **not** replace this book with a Random Forest / LSTM that labels the next 5–15 minutes as buy/sell/hold off RSI+SMA+bands. That is a tutorial, not a scalp. Name the regime (squeeze / trend / rip / washout / chop). Skip a continuation doji. Keep Ox + H1 as the ticket. Reread `desk/MISTAKES.md` the same way as this file.

Every fill, close, and intel cycle also rewrites the Google Sheets trade book (`desk/SHEETS.md`) so the human desk has trades, journals, P/L, lessons, and open tickets in one spreadsheet.

EUR/USD wires are harvested at **05:00 UTC** and on every intel cycle (`desk/NEWS.md`). The desk guesses the lean, then scores the 1-hour M5 close so categories (Fed, ECB, CPI, commentary, …) earn a hit rate instead of being treated as tickets.

## Research interpretation — 2026-09-22

The standing [research review](RESEARCH.md) adds evidence and a proposed test queue, not new runtime rules. The first priority is an execution-aware, chronological replay of the existing strategy. Historical intraday FX research shows why predictability without realistic costs is insufficient; this is not a claim that our own strategy has been validated. [Neely and Weller](https://files.stlouisfed.org/files/htdocs/wp/1999/99-016.pdf)

Interpret current `HISTORY.md` rankings as exploratory. Some saved buckets contain only one to three trades, and the replay does not reproduce the full live execution lifecycle. Preserve the existing runtime gates until separately changed in code and tests; do not use this research note to justify size increases.

Future evaluations should show net mean expectancy alongside median, tails, sample count and drawdown. Track all attempted variants and retain untouched chronological test periods. Multiple comparisons can produce impressive results by chance. [Bailey and López de Prado](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf), [Harvey](https://people.duke.edu/~charvey/Teaching/656_2026/Public_Presentations_656/656_Follow_2026.pdf)

Sources stay in this file. The living playbook repeats the short rules every intel cycle so the bot rereads them before the next ticket.

## September 22 execution amendment

The [reliability upgrade](RELIABILITY_UPGRADE_2026-09-22.md) governs execution:
practice writes only; fresh broker ownership checks; protection on entry;
confirmed fills before local close accounting; no blind mutation retries;
new entries paused on startup; one attempted entry per candle. Friday flattening
is an actual management rule. Historical exploration cannot steer live entries
unless separately validated. Existing broker stops operate while Python is paused.

## September 25 data and research amendment

See [DUKASCOPY.md](DUKASCOPY.md) for the website review and offline CSV audit.
Recognized EUR/USD one-second BID/ASK exports are catalogued as S1 research
and excluded from midpoint replay. Recorded-second coverage is not proof of
feed completeness. No missing seconds are filled by the auditor; a single
quote side cannot establish spread or executable round-trip profit.
Website articles, sentiment and COT are context or proposed experiments,
not new trade permissions. Existing Ox rules, risk limits and weekend
restrictions continue to govern.

## September 25 learning amendment

[The learning upgrade](LEARNING_UPGRADE_2026-09-25.md) supersedes older language
about copying operator winners or learning wider stops after two losses.
Manual outcomes stay separate. Recorded P/L includes scratches; initial-risk R
requires a genuine entry snapshot. Growth cannot automatically promote a side,
raise risk or widen the stop floor. Existing cooldowns and protective gates
remain. Decision observations and dashboard evidence labels support evaluation;
they do not demonstrate a profitable strategy.

## September 29 entry execution refinement

After candle and news processing, refresh OANDA bid/ask before entry gates. Reject
setups whose executable price has moved more than the existing slippage allowance
in either direction, crossed a stop/first target, or reduced reward to the final
target below the configured minimum R:R. Do not move levels to chase the quote.
Size against the worst entry allowed by the broker price bound, while retaining
the original stop and targets. This reserves for permitted entry slippage; gaps
and stop slippage can still exceed the planned risk. Quote quality, cost, session,
ownership, and daily risk gates continue to apply.

## Explicit practice sampling experiment

The operator-authorized [practice sampling trial](PRACTICE_SAMPLING.md) temporarily
uses a 35% spread/stop ratio in practice only, with risk capped at 0.1% per trade.
Its named policy and expiry are recorded in decisions. Baseline remains 25% when
the trial is inactive; other safeguards remain. Expiry does not raise risk size.

## Per-order value ceiling

The proposed 10% order-value ceiling was never activated. See
[ORDER_VALUE_LIMIT.md](ORDER_VALUE_LIMIT.md). Risk sizing and the configured unit
ceiling apply; order value is distinct from planned stop-loss risk.

## Current practice refinement profile — September 29, 2026

The [refinement profile](REFINEMENT_PROFILE.md) supersedes the aggressive M1
experiment: M5 entries, at most 0.1% planned risk per trade, 0.5% daily realized-loss
halts, and a 100,000-unit ceiling. The daily entry ceiling remains 24; qualifying
setups are never forced. Existing positions retain their protective orders.
The eight-pip candidate remains research only. See the
[strategy comparison](STRATEGY_COMPARISON.md) for evidence and limitations.

## Current execution mode: research only

September 29: `STRATEGY_RESEARCH_ONLY=true` blocks new orders at the enable and
submission boundaries, independently of daily resets. Data, journals and existing
position management continue. The [strategy lab](STRATEGY_LAB.md) runs automatically
and records prospective comparison evidence. Passing its screen cannot automatically
promote a strategy or turn trading on. Read [learning status](STRATEGY_LEARNING_STATUS.md)
for actual progress; service availability does not demonstrate strategy improvement.

## Latest operator instruction: resume practice and compile hourly

September 29: operator explicitly requested resumed trading.
`STRATEGY_RESEARCH_ONLY=false`; the practice entry switch is enabled after broker
reconciliation. M5, 0.1% planned risk, 0.5% daily loss gates and existing restrictions
remain. Today's losses are not reset. Simulated research still cannot promote rules
or enable trading. This supersedes the earlier research-only execution override.

[Compiled knowledge](KNOWLEDGE_BASE.md) refreshes at startup and every hour, with
versioned evidence and hourly deltas under `knowledge/`. The service's minute-by-minute
documentation receipts include this file. Recorded lessons remain interpretations,
and simulation findings remain unvalidated for execution.

## Latest override: no daily loss halt in practice

The operator explicitly disabled both hard and soft daily realized-loss halts for
the demo account. `PRACTICE_DAILY_LOSS_HALT_ENABLED=false` applies only to OANDA
practice; live accounts still enforce both thresholds. Daily losses remain recorded
and losing-day sizing reductions still apply. M5, 0.1% planned risk, position limits,
24-entry daily count ceiling, 10% total drawdown breaker, quote/calendar checks and
learned pattern restrictions remain. This removes the daily loss halt, not all
reasons to wait. Hourly knowledge compilation and autonomous research continue.

September 29 correction: the practice daily-halt override also disables the
consecutive-loss wait-until-next-session gate. It previously remained active after
the hard/soft P/L halts were disabled. Short cooldowns, exact-pattern restrictions
and execution-quality checks remain; live environments retain the session halt.

## Contextual loss review supersedes outcome-only practice bans

`PRACTICE_CONTEXTUAL_LOSS_REVIEW=true`: exact/family/side exclusions based only on
prior loss counts are advisory in practice, across lesson and growth checks.
See [contextual review](CONTEXTUAL_LOSS_REVIEW.md). Current entry-quality checks and
short cooldowns remain. Reviews separate recorded facts, hypotheses and unknowns;
research findings do not automatically promote execution strategies.
