# Five trading videos — completed research review

Status: **all five full timestamped English transcripts reviewed**, with selected visual checks. Research date: September 29, 2026, Chicago. `validated_for_live=false`. These are research references and proposed experiments, not activated trading rules.

## Scope and evidence

All five original pages and descriptions were inspected. After browser transcript failures, public English captions for V1–V4 were retrieved with youtube-transcript-api; V5's complete captions were read in the native browser. Auto-generated captions can contain errors. Visual checks verified V3's stochastic settings and instrument, and V5's Fibonacci and overnight-range examples. This is not continuous audiovisual viewing or an audit of every drawn chart. Missing discretionary definitions remain explicit below. No creator's profitability claim was independently verified.

## Source cards

### V1 — TradingLab: The Only Trading Strategy You'll Ever Need

[Original video](https://www.youtube.com/watch?v=e-QmGJU1XYc), November 4, 2024.

**Extracted rules:** A bullish low becomes structurally meaningful after its subsequent upswing breaks the preceding high; small internal fluctuations alone should not reverse the trend classification. Trade demand in an uptrend and supply in a downtrend. Mark the full candle range immediately before a sharp departure; enter on the return, stop beyond the zone, and target the recent extreme. Require reward/risk above 2.5. See [structure, 1:13](https://www.youtube.com/watch?v=e-QmGJU1XYc&t=73s), [entry example, 4:30](https://www.youtube.com/watch?v=e-QmGJU1XYc&t=270s), and [payoff filter, 7:15](https://www.youtube.com/watch?v=e-QmGJU1XYc&t=435s).

**Keep:** Separate protected structure, location and available reward. **Unresolved:** reproducible pivots, impulse threshold, timeframe, zone expiry, entry edge, stop buffer, wick versus close breaks, and equality at 2.5. Profitability/backtesting assertions have no independently reviewed trade series here.

### V2 — Simple Forex: The Most Simple Forex Trading Strategy That Exists

[Original video](https://www.youtube.com/watch?v=tzN2UjfrmBQ), September 9, 2023.

**Extracted rules:** Mark a higher-timeframe trendline break, commonly M15. Seek a lower-timeframe reversal, commonly M1, to trade back toward that higher-timeframe break level. For a buy, identify the local lower high and wait for a confirmed break; the explanation requires a breakout close followed by another close above the breakout candle. Enter on a return to the break line; stop below local structure and target the higher-timeframe level. Reverse for sells. MACD helps identify a swing in one example; a demonstration uses 1R, not a universal fixed target. See [setup, 4:19](https://www.youtube.com/watch?v=tzN2UjfrmBQ&t=259s) and [confirmation, 6:53](https://www.youtube.com/watch?v=tzN2UjfrmBQ&t=413s).

**Keep:** Explicit confirmation and honest missed-entry accounting. **Unresolved:** objective trendline construction, MACD settings, precise second-close threshold and buffers. At [9:34–10:12](https://www.youtube.com/watch?v=tzN2UjfrmBQ&t=574s), an initially missed entry is reconsidered using a different level. Our replay must retain the original decision; changing a level after seeing the outcome cannot turn a miss into a win.

### V3 — Data Trader: The BEST Day Trading Strategy For Beginners in 2026

[Original video](https://www.youtube.com/watch?v=ExvoIqNglOk), March 26, 2026.

**Extracted rules:** SLC means Structure, Level, Confirmation. The example uses H4 direction and M5 entries, avoids consolidation, identifies departure zones, then seeks confirmation on the return. A previously broken supply zone requires a break back below and retest; repeated choppy crossings invalidate it. At supply, the stochastic blue line must move above the upper threshold and back below. Stop above supply; target 2R. See [timeframes, 3:39](https://www.youtube.com/watch?v=ExvoIqNglOk&t=219s), [zone history, 6:33](https://www.youtube.com/watch?v=ExvoIqNglOk&t=393s), and [confirmation, 8:47](https://www.youtube.com/watch?v=ExvoIqNglOk&t=527s).

**Visual verification:** At [9:05](https://www.youtube.com/watch?v=ExvoIqNglOk&t=545s), settings show %K length 5, %K smoothing 3, %D smoothing 3, chart timeframe, and wait for timeframe closes checked. The chart is NASDAQ 100 E-mini futures M5; upper threshold is 80.

**Keep:** Track context, zone history and trigger separately. **Unresolved:** pivot/impulse rules, quantitative chop limit and stop buffer. Nasdaq examples do not establish EUR/USD performance; H4 aggregation needs an explicit alignment and completed-bar policy.

### V4 — Trade with Pat: The ONLY Supply & Demand Trading Strategy You’ll Ever Need

[Original video](https://www.youtube.com/watch?v=17pR60KE5_E), September 19, 2026.

**Extracted rules:** Mark the opposite-color candle before displacement, wick to wick. Seek large candles, fair-value gaps and a close beyond previous structure; trade with the trend. Three entries: rejection close outside the zone, engulfing confirmation, or aggressive limit at the origin candle's body midpoint. Stops lie beyond the zone/wick; targets use prior price action with attention to opposing zones. See [zone construction, 1:41](https://www.youtube.com/watch?v=17pR60KE5_E&t=101s) and [entry variants, 9:02](https://www.youtube.com/watch?v=17pR60KE5_E&t=542s).

At [14:02](https://www.youtube.com/watch?v=17pR60KE5_E&t=842s), a close through a zone invalidates that zone. Prefer first touches; avoid aggressive limits against a fast adverse approach. Lower demand and resistance/support overlap are additional preferences.

**Keep:** Diagnose the particular zone and entry variant rather than condemning the whole strategy. **Limits:** Claimed 79.13% wins over 115 tests is unverified; costs, selection and untouched holdouts are unavailable. Candles do not prove institutional identity or remaining orders. “Large,” “slow,” and discretionary zone resizing need fixed definitions. The normal entry narrative alternates candle-close language with placement at the candle bottom; executable order semantics must be frozen before testing.

### V5 — The Moving Average: My Top 3 Trading Strategies

[Original video](https://www.youtube.com/watch?v=L68Un4fVE5E), September 9, 2026.

**Extracted rules:** [Fibonacci, 0:53](https://www.youtube.com/watch?v=L68Un4fVE5E&t=53s): after a structure break, use impulse extremes, enter at 61.8% retracement, stop at origin, target endpoint; accept missed fills. [Divergence, 3:49](https://www.youtube.com/watch?v=L68Un4fVE5E&t=229s): higher-timeframe crypto examples pair opposite price/RSI swing directions, with the first RSI extreme outside 30–70 and the next inside. [Range, 7:06](https://www.youtube.com/watch?v=L68Un4fVE5E&t=426s): narrow Tokyo range, roughly 20–30 pips, opposing breakout orders, midpoint stops, 2R targets; close remaining trades one hour after New York opens. [Bonus, 9:47](https://www.youtube.com/watch?v=L68Un4fVE5E&t=587s): commercial Stairmaster indicator, insufficient transparent algorithm for reproduction.

**Visual checks:** Fibonacci chart at 2:19 is OANDA EUR/USD M5; displayed 3.7-pip stop and 6.4-pip target are illustrative. Range chart at 7:49 is Pepperstone German40 M5, not EUR/USD.

**Limits:** RSI period, swing confirmation, session timezone, order expiry and opposite-order policy are unspecified. Both breakout directions can lose. Wider stops reduce units at fixed loss budget, contrary to the narration's sizing statement. Defer proprietary indicator claims and ambiguous bonus target wording.

## What is useful for Forex Sentinel

The following is our synthesis and proposed engineering work, not additional claims from the creators. A video is a hypothesis source, not evidence that our bot has acquired an edge.

| Priority | Improvement | Why it matters | Proposed evidence to record |
| --- | --- | --- | --- |
| 1 | Separate context, location, trigger and exit thesis | A loss can arise from different parts of a setup | Structure state, level ID, trigger time, initial stop/target, opposing level |
| 2 | Keep a lifecycle for each zone | Avoid reusing a demonstrably failed level without banning a strategy | Creation/confirmation times, bounds, touch count, invalidation close and cause |
| 3 | Compare entry variants independently | Waiting for confirmation can reduce false entries but worsen price and payoff | Limit versus rejection versus engulfing; fill rate, net R, missed trades |
| 4 | Measure reward room after costs | Attractive chart ratios can disappear after spread and stop slippage | Executable entry, expected stop fill, target distance, cost assumptions |
| 5 | Separate regime and session outcomes | One family can behave differently in trends, ranges and fast approaches | Frozen regime label, session, volatility, spread, approach speed |

V3 permits a reclaimed zone; V4 discards a broken zone. These are competing hypotheses, not rules to combine into a contradictory gate. V1's >2.5R filter, V3's 2R target and V5's approximately 1.618R Fibonacci geometry are likewise separate designs. High target ratios do not guarantee positive expectancy. Correlated structure, displacement and oscillator observations are not independent probabilities.

A session-specific experiment must not impose its hours on unrelated strategies. Preserve the user's broker-open-hours preference. The point is better selection and diagnosis, not adding every filter and starving the bot of observations.

## Proposed first experiment: zone entry comparison, revision 1

**Not implemented or active.** This specification deliberately fills discretionary gaps with our own fixed choices; it is not a verbatim reproduction of any video. Start with this single family before adding Fibonacci, divergence or range systems.

1. Use completed EUR/USD M5 bars and aligned completed H1 bars. This H1 choice is our adaptation, not V3's H4 method. Confirm swing pivots using two bars on each side and strict extreme comparisons; reject ties. Record the pivot timestamp and the later availability timestamp. Use the last two confirmed H1 swing highs and lows for up/down direction; otherwise mark neutral.
2. On M5, a qualifying displacement closes beyond the latest already-confirmed swing in the H1 direction, with body at least 1.5 times ATR(14) from the preceding completed bar. Require a three-bar gap: bullish current low above the high two bars earlier; bearish current high below that earlier low. These numerical and gap definitions are our choices.
3. The origin is the most recent opposite-color candle among the five preceding bars; skip if absent. Freeze its wick bounds and body midpoint when displacement closes. Expire after 24 M5 bars, an H1 direction change, or a completed close beyond the adverse boundary. Only the first subsequent touch is eligible. Do not retroactively register touches before creation.
4. Compare three isolated candidates: midpoint limit; first-touch candle rejecting and closing beyond the favorable edge; next-candle body engulfing the opposite-color first-touch candle. Confirmation candidates enter only on the next available quote after close. Each candidate gets one attempt per zone. Pending limits expire with the zone; no chasing or retrospective fills. A touch consumes the opportunity even if confirmation never arrives.
5. Freeze the stop beyond the adverse zone edge by one contemporaneous spread. Freeze the target at the latest already-confirmed M5 swing in the profitable direction; reject absent or wrong-side targets. Require at least 2R estimated executable reward/risk. Keep the existing minimum-stop and practice risk controls; a too-small stop means rejection, not an undocumented target/stop alteration. Record the exact deployed control values with the experiment.
6. In offline comparison, mark remaining positions to market after 90 minutes, keeping this holding policy identical across variants. Do not change existing production exits. Opposing signals cannot close or modify another candidate's independent simulated position. No pyramiding within a candidate; overlapping signals are logged as skipped.
7. Fill buys on ask and exits on bid, sells on bid and exits on ask. Use observed executable prices where available. Do not assume a bid-only touch fills a buy limit. If a bar touches both stop and target with no finer sequence, use stop-first for the conservative estimate and report ambiguity counts. Stress stop slippage separately; apply financing if an experiment crosses rollover.

Before implementation, freeze dataset boundaries, session timezone conventions, software version, risk normalization and costs in the experiment manifest. Use a chronological development/validation/final-holdout split with a 90-minute purge at boundaries, then forward practice observation. Do not select a variant or numerical threshold on the final holdout. Track every attempted variation so repeated searches cannot hide selection bias.

Compare against the frozen existing strategy and against the unfiltered zone candidate. Report trade count, unfilled/rejected opportunities, mean and median net R, profit factor, drawdown, loss tails, fill rate and results by session/regime. Use day-block uncertainty estimates rather than assuming adjacent trades are independent. If improvement is inconclusive or disappears under plausible costs, retain the current baseline and record insufficient evidence. No sample size or win rate alone establishes profitability.

## Journal design: learn from the specific event

Proposed additional fields, not claims that these fields already exist:

- **Before entry:** candidate/version, source reference, zone ID/bounds/age/touches, structure availability time, trigger, adverse approach speed, spread, opposing level, expected reward/risk and initial cash risk.
- **During trade:** maximum adverse/favorable excursion with quote side and timestamps, stop changes, time in trade, whether the target was reachable before an opposing level.
- **After exit:** broker-confirmed reason, expected versus actual fill, initial-risk-normalized P/L, separately attributable financing, and observed thesis invalidation.
- **Review:** observed facts; suspected explanation; alternative explanations; matching comparison group; proposed change; supporting sample and uncertainty; next review condition.

Example: “First-touch demand limit lost during a fast adverse approach; stop filled beyond trigger. Hypotheses: entry timing and execution cost. Compare with matched slow-approach trades and rejection entries.” This is more defensible than “demand does not work.” A losing trade is not proof of a mistake, and a winner is not proof of skill. Keep `unknown` when the necessary evidence was not recorded.

Use the same diagnostics on wins: determine whether the intended thesis occurred, whether the result depended on favorable slippage, and whether the original exit surrendered most favorable excursion. Counterfactual entry/exit comparisons remain simulated; never add them to the broker-realized results.

## Integration and completion

This supersedes the earlier partial note. Full transcript review, source summaries, selected visual verification, applicability assessment and written experiment/journal designs are complete. There are no missing-transcript tasks outstanding. Undefined source parameters are limitations of reproducing discretionary methods, not invented facts.

The hourly compiler in `src/analysis/knowledge_base.py` reads root-level desk Markdown and records document hashes in `desk/knowledge/current.json`; this document is included. See [documentation access guide](DOCUMENTATION_GUIDE.md). Compilation/indexing makes the research discoverable. It does **not** semantically implement the prose, add a new candidate to the lab, or prove that trading performance improved. These new families are not running experiments.

Related: [standing research](RESEARCH.md), [account performance review](PERFORMANCE_REVIEW_2026-09-29.md), and [desk index](INDEX.md). No trading settings, entry authorization, risk levels or active research generation were changed for this review.
