# Forex bot construction sources — review and adoption plan

Reviewed September 30, 2026 against Forex Sentinel 2.23.0 (`a3124e3`). Nine supplied sources were readable, including the GitHub README and its four Python modules. The Medium article was inaccessible through the research tool; an exact-ID search returned no results. Its contents are not treated as reviewed.

This intake contains paraphrased source findings and our own repository comparison. It does not certify returns, activate a strategy, authorize larger positions, change the current research cutoff, or substitute article instructions for operator settings.

## Main conclusion

The useful additions are better measurement and testing, not another collection of indicators. Our system already implements Python/OANDA integration, protective orders, completed-bar evaluation, deterministic signal logic, journals, hourly knowledge compilation, prospective research, process supervision and separate operator ownership. None of the supplied material establishes a profitable EUR/USD rule for this implementation.

## Source-by-source assessment

### 1. Medium / Coinmonks — access unavailable

[How to make a forex trading bot](https://medium.com/coinmonks/how-to-make-a-forex-trading-bot-7b9d814e90db)

The exact supplied URL could not be opened. No claims, code or strategy rules from this article were imported. Status: unread, pending an accessible copy.

### 2. Vocal — basic development sequence

[Automated Forex Trading: How to Build a Bot That Makes Smart Trades](https://vocal.media/education/automated-forex-trading-how-to-build-a-bot-that-makes-smart-trades)

Describes choosing a simple strategy, connecting a broker, backtesting, demo testing and monitoring. Useful as an introductory checklist; our implementation already covers these stages. It provides no reproducible EUR/USD performance study. Its around-the-clock language does not establish that the broker accepts orders continuously. No additional execution rule adopted.

### 3. LuxAlgo — strongest engineering checklist in this batch

[Building Your First Trading Bot](https://www.luxalgo.com/blog/building-your-first-trading-bot-step-by-step-guide/)

Separates chart signals from broker execution and calls for testing the whole order path, including uncertain acknowledgments, partial fills and restart reconciliation. It stresses meaningful timestamps, completed bars, realistic costs, persisted state and explicit operating modes. It also distinguishes order value from loss-at-stop exposure and cautions against treating demo fills as equivalent to real liquidity.

Adopt the checklist as an audit framework. We already have uncertainty locks, ownership checks and broker reconciliation. Remaining work is more complete replay/execution comparison and measured execution-cost reporting. The article's illustrative code is not a replacement broker adapter, and no product migration is justified.

### 4. Traders Union — workflow and overfitting cautions

[How to Write a Trading Robot](https://tradersunion.com/interesting-articles/mt4-bots/write-trading-bot/)

Recommends explicit strategy rules, backtesting, demo operation and avoiding excessive tuning to historical results. This supports our existing frozen experiment process. Its return examples do not establish a target for our EUR/USD account. Its MQL platform discussion is introductory, not a reason to replace the working OANDA adapter or assume MQL4 and MQL5 are interchangeable.

### 5. Arincen — performance depends on conditions

[Forex Trading Bots Explained](https://en.arincen.com/blog/trading-beginners/forex-trading-bots-explained)

Discusses changing performance across trending, choppy and news-driven conditions, alongside coding and backtest risks. Useful implication: record the conditions associated with each result and distinguish operational uptime from financial performance. This is not evidence for automatically switching strategies after a few losses. Treat condition-specific results as descriptive until sufficient fresh evidence exists.

### 6. PipPenguin — broad overview, limited validation evidence

[Forex Trading Bots](https://pippenguin.net/trading/learn-trading/forex-trading-bots/)

Covers bot types, operating costs, broker compatibility and monitoring. The page includes product and AI-adaptation claims without a reproducible validation record sufficient for this bot. Retain cost categories and compatibility questions. Do not infer that buying a named EA, trading more pairs, or adding machine learning will repair our edge. EUR/USD scope remains unchanged.

### 7. Investopedia — specify the edge, simplify and validate

[Build a Trading Bot: Key Insights and Strategies](https://www.investopedia.com/articles/active-trading/081315/how-code-your-own-algo-trading-robot.asp)

Emphasizes a defensible market hypothesis, clear entry/exit/sizing rules, testing across conditions and avoiding overfitting. Our inference: evaluate simpler candidate strategies and keep a written reason each should work. More indicators are not evidence of a better edge.

### 8. IG — execution assumptions and operational monitoring

[Five Steps to Building an Automated FX Trading System](https://www.ig.com/en/trading-strategies/how-to-create-an-automated-forex-trading-system-200720)

Separates system design, risk controls, coding and testing. Notes that stop fills may slip and static backtests can miss liquidity effects; unattended automation still needs oversight. Adopt more explicit stop-slippage and gap-cost stress cases. IG's guaranteed-stop product description is provider-specific and must not be assumed to apply to our OANDA practice setup.

### 9. Mo-Khalifa96 GitHub project — inspect architecture, do not transplant execution

[Repository and README](https://github.com/Mo-Khalifa96/Forex-Trading-Bot)

The author calls this an early Python/MT5 project and advises against using it for personal trading. It separates data, time and order processing and describes a SuperTrend-derived setup across multiple pairs. Modular separation and completed-candle intent are useful patterns already present in our system; the repository is not evidence of profitable operation.

Code observations, not execution tests:

- [DataProcessing.py](https://github.com/Mo-Khalifa96/Forex-Trading-Bot/blob/main/DataProcessing.py): explicitly excludes the newest candle from indicator processing. Preserve the completed-bar principle, but do not copy its indicator parameters as an established edge.
- [OrderProcessing.py](https://github.com/Mo-Khalifa96/Forex-Trading-Bot/blob/main/OrderProcessing.py): sizes from balance bands and can double lots based on price location. It also retries certain rejected requests in loops. Those choices do not implement our stop-risk sizing or uncertain-order reconciliation contract. Do not copy the sizing or retry behavior.
- [TimeProcessing.py](https://github.com/Mo-Khalifa96/Forex-Trading-Bot/blob/main/TimeProcessing.py): uses fixed UTC market-hour constants and wall-clock checks for candle updates. Our broker tradeability checks and bar timestamps are the more appropriate authority; do not transplant fixed hours.
- [Main program](https://github.com/Mo-Khalifa96/Forex-Trading-Bot/blob/main/Forex%20Trading%20Bot.py): contains nested polling loops and terminal-dependent execution. Reading the code does not verify recovery behavior. No foreign code was executed, installed or copied into our bot.

### 10. KJ Trading Systems — broad development guidance

[Guide to Creating Your Own Automated Trading Bot](https://kjtradingsystems.com/guide-to-creating-automated-trading-bot.html)

Discusses strategy selection, implementation and out-of-sample testing. Retain the separation of development and evaluation data. This particular page is an introductory overview, not a detailed validation method or a tested forex system. Its simple indicator examples are hypotheses, not enough to justify automatic oversold entries or another indicator layer.

## Repository comparison and prioritized improvements

The items below are our engineering assessment, not performance claims made by the articles.

| Priority | Proposed improvement | What exists now | Specific gap and acceptance condition |
| --- | --- | --- | --- |
| 1 | Separate performance by policy version and context | Entry snapshots contain code/config hashes; `learning_report.py` counts decision versions and includes `growth.py` closed-trade code-version buckets alongside other descriptive buckets | Join closed bot trades to their entry snapshots. Report count, realized P/L and original-risk R separately by code/config/timeframe, side, entry EMA agreement, session and cost burden. Keep unknowns explicit. Exclude human trades and mirrors. Never call old and new policy results one learning curve. |
| 2 | Measure execution friction | `entry_quality.py` checks executable quotes; broker and journals record fills and original risk | Compare direction-adjusted entry quote-to-fill slippage, stop-level-to-fill slippage and spread/stop ratio. Keep spread separate from market drift and avoid subtracting it twice from realized P/L. Report financing/commission coverage rather than assuming completeness. |
| 3 | Compare simple strategies with the current baseline | Frozen prospective lab and confirmation candidate already exist | Predeclare a small number of distinct hypotheses: trend continuation versus confirmed mean reversion, each with explicit entry, exit and invalidation rules. Evaluate each separately on the same chronological windows and costs. Do not combine them into a larger vote stack simply because one period improves. |
| 4 | Improve replay agreement with the production path | Completed-bar/next-bar replay, partials and modeled costs; operational regression tests | Add tests for decisions changed by support-score gates, rejection/uncertainty handling and management timing. Replay currently omits important production gates; say which are simulated and which are not. Require an order-event trace that can be compared with broker evidence. |
| 5 | Broaden robustness tests | Current lab uses fixed 1.6/1.8-pip spreads and 0.2-pip slippage | Predeclare wider-spread, adverse-fill and gap cases, plus sensitivity around parameters. Favor stable regions over one best point. Perform this in a separate research report before modifying frozen specifications; do not reset generation 4 for documentation work. |
| 6 | Test recovery, not only availability | Supervised service, broker-held stops, uncertainty locks, tests and local audit backups | Exercise disconnect, restart and duplicate-response cases with a fake broker or isolated database. Confirm no duplicate order and no ownership violation. A restore drill should prove backup usefulness without touching the running account. |

Highest-value next implementation: a **read-only policy/context and cost report**. It should explain whether outcomes changed because of signal behavior, position sizing, market conditions or execution friction before another strategy alteration. Start with the recorded data and state limitations; missing fields should reduce evidence coverage rather than create invented values or stall all analysis.

## Research acceptance rules

- Assess net expectancy, downside, frequency and sample size together. A high win rate or fewer trades alone is insufficient.
- Preserve winners as well as losers, bot ownership, original risk and policy lineage.
- Separate training/diagnostic periods from fresh evaluation periods. Previously inspected data cannot be relabeled untouched.
- A condition-specific bucket with few trades is a hypothesis, not an automatic exclusion or direction preference.
- Maintain the operator's practice account, risk and market-hours settings. This review does not authorize a daily halt or increased exposure.
- None of this batch overrides the negative diagnostic evidence for the unpromoted confirmation candidate in [release 2.23.0](RELEASE_2.23.0.md).

## What changed in this intake

Added this source register, code-specific comparison and prioritized implementation backlog to the documentation. Rebuilt the knowledge index and checked that it includes the new document. No execution code, strategy settings, open positions or frozen research specifications were changed. The Medium source remains the one unreviewed item.

Correction after repository comparison: closed-trade code-version buckets already exist in `growth.study_book`. Extend them with matched configuration/context and costs rather than reimplementing basic version grouping. See [repository review](GITHUB_REPOSITORY_REVIEW_2026-09-30.md).
