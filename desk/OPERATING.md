# EUR/USD operating policy

Updated for 2.23.0. This document supersedes the original fixed M5 hours, risk percentages, daily halts and outcome-based strategy bans. Runtime configuration and broker-confirmed state determine actual behavior; educational material is not an instruction to change them.

## Execution and ownership

- EUR/USD practice trading only for this installation. A new process starts paused; restore an authorized enabled state only after reconciliation.
- Only `fs-` OANDA tickets belong to the bot. Human/unstamped positions remain hands off. MT4 ledger copies and partial exits are not independent OANDA trades.
- Use completed bars on the configured signal timeframe with completed H1/D1 context. The current operator uses M1; M5 references in educational notes are historical examples.
- Broker market availability and configured quote/news/cost checks govern entries. Do not introduce an arbitrary Chicago 5 p.m. cutoff.
- Keep broker-held stops and bounded sizing. Never widen a stop to recover a loss, increase risk to compensate, or promote a strategy from a winning streak.
- Daily-loss halts are configuration-controlled. The operator has disabled them for this practice account; reporting changes must not re-enable them.

## Entry evidence

The support score uses only the selected direction. Trend indicators, momentum oscillators, location, higher-timeframe context and structure are grouped; each family caps its score contribution. The score is a heuristic, not a probability of profit. These families may still be correlated; grouping does not prove statistical independence.

A committed-candle label requires the candle body to agree with the proposed side. H1 direction alone does not prove that an M1 pullback is finished.

`CONFIRMED_ENTRY_POLICY=false` is the release default. The proposed reversal and re-entry checks are recorded in each directional decision as shadow evidence. If enabled for an explicitly selected experiment, a countertrend/fade must close directionally beyond the preceding completed bar, using contiguous bars; a same-side entry after the latest bot loss needs a fresh bar that starts after that close. This is a price condition, not a whole-strategy ban. The September 30 diagnostic comparison did not establish improvement, so the operator's execution policy has not been switched to this candidate.

## Journal and learning

Broker trade totals determine realized P/L. Resolve final exit reasons from closing transactions matching the exact trade; never infer a stop/target from price proximity. Missing attribution stays unknown without replacing confirmed P/L or blocking reconciliation.

Contextual journals separate recorded outcomes, observable entry context and hypotheses. A quick loss does not prove chop; a winning trade does not prove a repeatable edge. Compare winners and losers under the same timeframe, costs, risk and policy version.

Knowledge compilation runs hourly. Strategy research runs at startup and every six hours, with frozen prospective experiments. Invalidated or incomplete experiments are not completed evaluations. A changed strategy begins a new version/cutoff; preserve the old evidence. Research selects research references only and does not automatically change broker settings.

The research candidate set now includes the confirmation policy alongside stop/confluence variants. No validated profitable policy is claimed. Evaluate costs, expectancy, drawdown, frequency and uncertainty; do not optimize only win rate or enlarge risk to manufacture larger winners.

## Research provenance

Preserve capital and measure net expectancy. This is an intraday scalp system;
a losing scalp must not silently become a swing position. LWMA, envelopes and
DSS are inherited research tools, not evidence of profitability. MetaTrader copies
are a dual venue integration with separate ownership and accounting.

Historical educational sources: [Ox Securities](https://oxsecurities.com/most-profitable-trading-strategies/),
[LiteFinance](https://www.litefinance.org/blog/for-beginners/trading-strategies/),
[Dukascopy](https://www.dukascopy.com/swiss/english/marketwatch/articles/top-trading-strategies-in-forex/),
and [Investopedia](https://www.investopedia.com/articles/forex/08/forex-trading-tips.asp).
These references motivated experiments; their generic claims do not validate this implementation.

## Sources and further detail

- [Scalping research](SCALPING.md) and [research references](RESEARCH.md): educational context, not current account settings.
- [Contextual loss review](CONTEXTUAL_LOSS_REVIEW.md), [strategy lab](STRATEGY_LAB.md) and [refinement process](STRATEGY_REFINEMENT_PROCESS.md).
- [2.23.0 changes and validation](RELEASE_2.23.0.md).

Keep credentials, broker evidence, databases, generated journals and knowledge revisions local. Source publication must not include them.
