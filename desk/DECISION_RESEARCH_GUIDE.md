# Decision research: facts, hypotheses and activation

## What the bot must remember

- The support score is a heuristic, not a win probability. Do not increase risk on its apparent confidence.
- Separate final-target reward, position-weighted payoff and expected return. If TP1 is under five pips from the executable fill, current execution does not scale out there. Spread is already reflected in executable entry and liquidation prices; do not subtract it twice.
- Unknown commission or financing is unknown, not zero. A price-only comparison cannot be called net profitable.
- A loss is an outcome, not a diagnosis. A positive excursion is not proof that an alternative exit was executable. Completed OHLC cannot reveal the order of intrabar events.
- Every hypothesis needs a fixed definition, reference policy, code/config identity, prospective cutoff, paired outcomes and an explicit rejection criterion. Do not merge results from different policies.
- A skip has zero exposure; it is not a winning trade. Report winners harmed by a filter alongside losers avoided. Report unpaired and missing paths.
- Opportunity studies include setups skipped by execution gates. Their overlapping hypothetical trades cannot be summed into an account return.
- Preserve positions across midnight in research. Missing overnight candles are a coverage gap, never an assumed flat account or an inferred fill.
- Documentation compilation is not model training. Registered research produces evidence; promotion requires separate execution-cost and forward-practice review. Do not describe collecting evidence as an improved strategy.

## Where to look

- `PAIRED_STUDY.md`: current paired outcome counts, uncertainty, cohort comparisons and blockers.
- `DIAGNOSTIC_PAIRED.md`: hourly worker status.
- `DIAGNOSTIC_COSTS.md`: measured bid/ask stress results and missing cost assumptions.
- `POLICY_EXPERIMENTS.md`: prior frozen confirmation and holding-period study; preserved separately.
- `TRADE_REVIEW_2026-10-01.md`: broker-reconciled historical review; historical evidence, not a new rule.
- `journal/`: individual outcomes, original-risk basis and sampled excursion coverage.

## Prespecified comparisons

New paired study: immediate next-minute entry versus confirmation within five completed M1 bars versus skip. Confirmation requires a directional candle close beyond the original signal high/low; entry is the following bar. This is a separate hypothesis from the older frozen confirmation experiment.

Exit comparisons retain the immediate entry and original levels: recorded maximum hold versus half that period, and a stop tightened to +0.25R only on the next bar after observing +1R. Stops are never widened. Conservative stop-first OHLC and ambiguous post-partial breakeven handling apply. A 0.2 pip adverse entry/exit scenario accompanies measured spreads. Full net returns remain unknown without verified costs.

At least 50 paired outcomes and 10 active days per cohort are required for even an initial statistical review; the day-block interval must exclude zero improvement. These are necessary, not sufficient conditions. Portfolio constraints, broker fills, cost completeness, multiple testing and a separate forward holdout remain promotion blockers.
