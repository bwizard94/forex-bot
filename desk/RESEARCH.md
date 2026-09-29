# Forex research and validation notes

Implemented learning corrections and current limits are documented in the
[September 25 learning upgrade](LEARNING_UPGRADE_2026-09-25.md).

September 25 follow-through: [Dukascopy research and integration review](DUKASCOPY.md)
covers historical data, strategy education, positioning, calendars and execution.
It records the implemented second-bar audit and midpoint-replay exclusion,
source-quality corrections, and a prioritized experiment queue.

Reviewed **2026-09-22** for Forex Sentinel, the EUR/USD practice scalper.

This is a standing research document, not a generated performance report. Findings below distinguish published evidence, educational guidance, local code observations, and proposed experiments. No new strategy, indicator threshold, risk allocation, or execution behavior is enabled by this update. Ox + H1/D1, operator protection, the 5-pip stop floor, and existing risk limits remain the baseline.

## What deserves attention first

The strongest actionable findings are about measurement: executable prices, realistic exits, independent confirmation, and evidence that survives selection. None of the reviewed sources establishes that this bot's Ox implementation is profitable. Studies of diversified currency portfolios or monthly trends cannot establish an edge for a single-pair M5 scalper.

## 1. Strategy families and their fit

| Family | Evidence and limitations | Decision for this desk |
| --- | --- | --- |
| Trend following / momentum | Moskowitz, Ooi and Pedersen find time-series momentum across futures and forwards, including currencies, using a 12-month return signal. Currency cross-sectional momentum research also finds historical return spreads, with implementation limits. Neither tests our M5 strategy. [S1] [S2] | Keep the existing trend-pullback baseline; compare variants on the same out-of-sample EUR/USD data. |
| Range / mean reversion | Bollinger describes relative price extremes, not automatic reversal entries. Fidelity notes that RSI can stay extreme during trends. This is indicator guidance, not proof that buying every oversold reading pays. [S3] [S4] | A fade remains conditional on reversal confirmation and H1 compatibility. Extreme readings alone never establish an entry. |
| Breakout / support-resistance | Osler's bank-order research links order clustering to reversals at levels and acceleration through them. It is historical microstructure evidence from a limited sample, not validation of every modern “liquidity sweep” label. [S5] | Test a precisely defined close-and-retest setup as a challenger; do not infer hidden orders or institutional intent from a wick. |
| Intraday technical scalping | Neely and Weller found that the tested intraday rules lost their excess-return evidence after realistic costs and trading hours. The study used older data and different rules; it neither proves nor disproves this bot. [S6] | Gross replay pips are insufficient. Make execution-aware validation the prerequisite for strategy tuning. |
| Carry / cross-currency portfolios | BIS research distinguishes carry from momentum and discusses funding, liquidity, volatility and crash-risk explanations for carry returns. [S7] | Context only. This intraday, single-pair desk is not a diversified carry portfolio. Do not add pairs or hold overnight to import an unrelated result. |
| Scheduled-news reactions | EBS research finds rapid exchange-rate responses to announcement surprises and elevated activity even for releases matching expectations. Recent FOMC research distinguishes statements, press conferences and minutes. [S8] [S9] | Continue the blackout and H1-reaction approach. Investigate complete event coverage before testing post-news entries. |

These findings are not contradictory: results depend on horizon, sample, instruments, costs, and strategy selection. Prediction, a plausible market mechanism, and a realizable trading profit are different claims.

## 2. Indicators: useful roles and common misreadings

| Tool | What it contributes | Interpretation for research |
| --- | --- | --- |
| LWMA / EMA / MACD | Smoothed price direction and momentum; MACD itself is built from moving averages. [S10] | Do not count several transforms of the same price history as independent evidence. |
| ADX with directional movement | ADX describes trend strength; the directional lines supply direction. Fidelity presents 20/25 as common conventions. [S11] | Compare regime-conditioned results. These numbers are hypotheses, not validated EUR/USD settings. Falling ADX does not itself identify a reversal. |
| RSI | A momentum oscillator whose behavior depends on trend. [S4] | Existing 40/60 exclusions are local anti-chase policy, not a universal statistical law. Preserve them pending a separate tested change. |
| Bollinger Bands / BandWidth | Relative location and volatility compression. Prices can continue along an outer band; a touch alone is not a signal. [S3] | Separate expansion/continuation from confirmed rejection. A squeeze does not, by itself, specify direction. |
| ATR | Volatility and gap-aware range, not bullish/bearish direction. [S12] | Use it for normalized distances and diagnostics; a larger ATR is not a BUY vote. |
| VWAP / tick activity | OANDA candle volume counts prices, not traded currency units. [S13] | Call our calculation a feed-specific price-count-weighted reference, not global traded-volume VWAP or institutional fair value. |

Bollinger's guidance to avoid directly related confirmation indicators is consistent with Fidelity's explanation that indicators within a category often describe the same underlying feature. **Proposed experiment:** group confirmation by role and remove one redundant family at a time, measuring out-of-sample net expectancy and opportunity loss. Do not replace the current scoring system on the strength of this reading alone. [S3] [S10]

**Local VWAP observation:** `src/analysis/indicators.py::session_vwap` resets on the UTC date and substitutes weight 1 for missing/zero volume. Its anchor and input feed therefore matter. BIS describes global FX as an OTC market surveyed across many dealers; a single feed's activity is not that market's consolidated volume. Test anchor/feed sensitivity before treating this reference as an edge. [S13] [S14]

## 3. Sessions, costs, and news

OANDA says spreads can increase around market openings/closings, news and uncertainty. This operational disclosure independently supports the importance of the cost sensitivity seen in the intraday research. Keep measured spread and slippage in the decision record; an active session is not automatically a cheap fill. [S15] [S6]

The EBS study explicitly separates daylight-saving regimes when examining intraday activity. **Proposed improvement:** keep stored timestamps in UTC, but label research sessions using `Europe/London` and `America/New_York`, including their mismatched clock-change weeks. The existing `datasets.session_name` uses fixed UTC hours; do not interpret its labels as exact year-round local sessions. This proposal does not change the desk's explicit UTC operating schedule. [S8]

**New event-coverage priority:** the August 27, 2026 revision of Acosta et al. finds substantial information in FOMC press conferences, with stronger effects than statements on many assets in their sample. Their event-study window covers the statement and subsequent conference; this is not a recommended trading blackout length. ECB material likewise separates the policy decision from the statement/Q&A. [S9] [S16]

**Proposed implementation:** represent statement, projections and press-conference/Q&A intervals explicitly, merge overlapping blackout windows, and require fresh tradable quotes and normalized spreads afterward. Preserve the existing ±30-minute rule while investigating whether the calendar contains every relevant event. A timer around the decision alone should not be assumed to cover the entire conference. No event-window code was changed here.

## 4. What “successful trading” can responsibly mean here

The CFTC's 2022 advisory reported about two-thirds of customers losing money in the disclosed Q2 2021–Q1 2022 sample. That is historical US OTC-account evidence, not today's universal failure rate and not a study identifying a winning indicator. Both the CFTC and OANDA explain that leverage magnifies losses as well as gains. [S17] [S15]

**Desk interpretation:** assess a reproducible process, not screenshots or a selected winning account. Keep fixed risk limits, reconcile broker fills, record rejected and skipped opportunities, and distinguish real venue fills from local MT4 ledger simulations. These are engineering/research recommendations; they do not create positive expectancy by themselves.

**Expectancy arithmetic (derived, not a performance claim):**

`net expectancy = p(win) × mean gross win − p(loss) × mean gross loss − mean total cost`

Include scratches separately when present. If outcomes already use actual bid/ask fills and net charges, do not subtract those costs again. For a simplified binary strategy with +6/-5 gross pips and 1 pip of round-trip cost, break-even win rate is `(5 + 1) / (6 + 5) = 54.5%`, versus 45.5% before cost. This is an illustration, not an assumed OANDA spread or bot forecast.

Use the actual partial-exit distribution. In an illustrative 1R stop / 1.2R TP1 / 2R TP2 trade, half at each target yields 1.6R gross; half at TP1 and the rest at entry yields 0.6R gross. Neither equals a full-size TP1 exit. Compute realized R against the original dollar risk, including exit costs and slippage. Report mean expectancy and median/tail diagnostics together: the median is useful for outlier detection but does not replace the mean in expected P/L.

## 5. Validate the edge before optimizing it

Bailey and López de Prado address performance inflation from multiple trials and non-normal returns with the Deflated Sharpe Ratio. Harvey independently explains how testing many candidates creates apparently significant winners by chance. A best-ranked setup needs its selection history, not only its winning trades. [S18] [S19]

**Local observations from the September 22 snapshot, not a complete backtest audit:**

- `desk/HISTORY.md` contains “best” named setups based on one to three trades. Treat those as exploratory observations, not established edges. Its September 17 report is also a saved snapshot, not a fresh run.
- `replay_desk_rules` implements an older EMA/RSI idea; its results should not be described as a complete test of the current Ox system.
- `replay_named_setups` calls the signal evaluator but defaults to stepping ten M5 rows at a time and checks exits on sampled closes. It can miss intrabar or intervening-bar exits.
- These replay loops do not explicitly model spread/commission/slippage and do not reproduce the full partial-exit, breakeven and time-stop lifecycle.
- The named replay slices H1/D1 using `loc[:ts]`. If indexes are candle-open times, this can expose a higher-timeframe close before it was available. OANDA defines candle timestamps as start times. Verify each dataset's convention before concluding whether leakage occurs. [S13]

**Proposed validation protocol, not an already-implemented gate:**

1. Freeze a baseline version and data manifest. Record vendor, bid/ask/mid convention, timezone, candle-open/close labels, completeness, gaps and duplicates.
2. Generate signals only from information available then. Make completed H1/D1 candles available at their actual close; enter at the first executable quote after a decision, not retrospectively at its signal close.
3. Model long entry at ask and exit at bid, with the reverse for shorts. Use broker-specific trigger/fill semantics, fees, slippage and gap handling. If only OHLC is available and stop and target both fall within one bar, flag ambiguity and use a conservative assumption rather than choosing the profitable sequence.
4. Replay every exit-relevant bar even if signal evaluation is throttled. Reproduce TP1, breakeven modification, TP2, time stops, session rules, risk caps and rejected orders.
5. Split chronologically into development, validation and untouched test periods. Fit thresholds and setup memory using only prior data; exclude overlapping trade outcome windows across boundaries. Reusing the holdout turns it into development data.
6. Keep a record of every parameter/strategy trial, including failed ones. Prefer a stable neighborhood of settings over one sharp optimum. Use block-aware uncertainty estimates, and investigate multiple-testing corrections when selecting among many candidates.
7. Report net expectancy, count, net profit factor, realized R, drawdown, tail losses, time in market and costs, broken out by session/regime and period. Count independent episodes; add-ons and MT4 copies are not independent evidence.
8. Stress costs using both observed distributions and a declared adverse scenario. A proposed 1.5× cost scenario is a sensitivity check, not a published standard. Forward-test the frozen candidate on practice, including fill/reconciliation behavior, before considering promotion.

No universal “30/100 trades proves success” threshold follows from these sources. Predeclare the sample horizon and confidence method; few observations or intervals spanning zero mean the edge remains uncertain.

## 6. Prioritized experiment queue

All items are **proposed**, require code/tests, and retain the current practice limits.

| Priority | Experiment | Question and comparison |
| --- | --- | --- |
| 1 | Execution-aware replay and availability audit | Does baseline net expectancy survive realistic fills/exits and completed H1/D1 timing? This comes before indicator optimization. |
| 2 | Full central-bank event coverage | Are trades permitted during statement-to-conference gaps or Q&A? Compare missed events and execution quality before P/L. |
| 3 | Confirmation-family ablation | Does removing redundant votes improve out-of-sample net results without simply fitting one period? |
| 4 | Regime-specific pullback versus confirmed range rejection | Compare each frozen setup separately; use existing regime features first. Preserve current anti-chase rules. |
| 5 | Breakout-and-retest challenger | Define levels from prior completed bars, a close through the level, and a later retest/hold. Test against the unchanged baseline; a wick alone is not sufficient. |
| 6 | Session and exit diagnostics | Measure DST-aware sessions plus maximum adverse/favorable excursion. Test any later exit change independently; never widen an existing stop as an experiment. |

Journal fields to consider: strategy version, regime, event distance, quote age, bid/ask, requested and filled price, all fees, original risk, partial fills, exit reason, MAE/MFE, and skip/reject reason. Retain broker/source identifiers so human tickets and venue copies cannot contaminate desk-performance statistics.

## Sources and evidence scope

Sources were retrieved on 2026-09-22. Publication dates below refer to the source itself where verified, not search-index dates. Academic/central-bank papers are historical empirical evidence; broker/indicator-author materials explain mechanics and interpretation, not audited profitability.

[S1]: https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum
[S2]: https://www.bis.org/publications/working-paper-366-currency-momentum-strategies
[S3]: https://www.bollingerbands.com/bollinger-band-rules
[S4]: https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/rsi
[S5]: https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.pdf
[S6]: https://files.stlouisfed.org/files/htdocs/wp/1999/99-016.pdf
[S7]: https://www.bis.org/publ/qtrpdf/r_qt1112x.htm
[S8]: https://www.federalreserve.gov/pubs/ifdp/2004/823/ifdp823.pdf
[S9]: https://www.frbsf.org/wp-content/uploads/wp2025-30.pdf
[S10]: https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Transcript_Tech%20analysis.pdf
[S11]: https://www.fidelity.com/viewpoints/active-investor/average-directional-index-ADX
[S12]: https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr
[S13]: https://developer.oanda.com/rest-live-v20/instrument-df/
[S14]: https://www.bis.org/statistics/rpfx25_fx.htm
[S15]: https://www.oanda.com/us-en/trading/spreads-margin/
[S16]: https://www.ecb.europa.eu/press/press_conference/html/index.en.html
[S17]: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/CustomerAdvisory_MustKnowForex.html
[S18]: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
[S19]: https://people.duke.edu/~charvey/Teaching/656_2026/Public_Presentations_656/656_Follow_2026.pdf

- [S1] Moskowitz, Ooi and Pedersen, *Time Series Momentum* — author research summary; longer-horizon multi-asset evidence.
- [S2] Menkhoff et al., *Currency Momentum Strategies* — BIS Working Paper 366 (2011); cross-sectional currencies.
- [S3] John Bollinger, *Bollinger Band Rules* — indicator creator's guidance.
- [S4], [S11], [S12] Fidelity indicator guides — RSI, ADX/DMI and ATR; educational definitions.
- [S5] Osler, *Currency Orders and Exchange-Rate Dynamics* (March 2001) — bank conditional-order evidence.
- [S6] Neely and Weller, *Intraday Technical Trading in the Foreign Exchange Market* (January 10, 2001 revision).
- [S7] BIS, *Drivers of carry and currency momentum* (December 12, 2011) — literature synthesis.
- [S8] Chaboud et al., Federal Reserve IFDP 823 (November 2004) — EBS prices/activity around releases.
- [S9] Acosta et al., FRBSF Working Paper 2025-30 (August 27, 2026 revision) — FOMC event study, empirical sample through December 2024.
- [S10] Fidelity, *Technical analysis for volatile times* — educational transcript.
- [S13] OANDA v20 instrument definitions — authoritative field semantics.
- [S14] BIS, April 2025 OTC turnover survey release — market structure; no turnover estimate is used as an entry signal.
- [S15] OANDA US spreads/margin page — venue disclosure; actual costs must come from the account/feed.
- [S16] ECB press-conference page — distinct decision and Q&A communications.
- [S17] CFTC, *Eight Things You Should Know Before Trading Forex* (2022) — advisory with explicitly dated account statistics.
- [S18] Bailey and López de Prado, *The Deflated Sharpe Ratio* (July 31, 2014 version).
- [S19] Campbell Harvey, *Follow the Science*, Finance 656 (2026) — independent multiple-testing and bootstrap discussion.

## Implementation follow-through — September 22

The [reliability upgrade](RELIABILITY_UPGRADE_2026-09-22.md) implements the first
execution and replay corrections: completed higher-timeframe bars, next-bar
entries, continuous exit checks, cost assumptions, partial lifecycle, and an
offline chronological holdout report. Legacy replay and unvalidated historical
buckets are excluded from live growth decisions. Tick-level bid/ask validation,
full news-event coverage, financing, portfolio risk simulation and genuine
out-of-sample/forward evidence remain outstanding; this does not establish an edge.
