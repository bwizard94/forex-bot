# 2.26.0 — paired decision research and measured execution evidence

## Five refinements

1. Entry evidence now records position-weighted target payoff alongside runner-only
   reward/risk, accounting for the five-pip TP1 minimum and integer partial sizing
   when submitted units are known. Net payoff remains unknown without explicit
   fees; executable prices already include spread. The new diagnostic flags whether
   weighted gross payoff meets the existing minimum. It does not silently replace
   the active entry gate; a paired candidate tests the proposed filter.
2. A separate immutable prospective study compares immediate next-M1-bar entry,
   five-minute directional breakout confirmation, skipping, and weighted-payoff
   filtering on the same recorded directional opportunities. It deduplicates
   repeated same-candle/side/code/config observations and separates policy cohorts.
   It includes skipped setups as opportunity research, not execution-eligible orders.
3. Completed OANDA practice M1 bid/ask candles are archived every fifteen minutes
   in a separate SQLite file. First-seen records are retained. Six-hour cost research
   now uses measured prices, with M5 aggregation when needed; incomplete coverage
   fails rather than substituting synthetic prices. The prior frozen experiment
   keeps its original assumptions. Broker fee/financing completeness remains unknown.
4. Exit-only comparisons keep the immediate entry fixed: the recorded holding
   period versus half that period, and next-bar stop protection at +0.25R after
   observed +1R. Levels are never widened. Conservative stop-first and ambiguous
   post-partial breakeven handling prevent optimistic OHLC path assumptions.
5. Progress includes paired counts, days, uncertainty, winners harmed, losses
   improved, trade counts, cohort identity and promotion blockers. Hypothetical
   positions continue across midnight until their own exit; missing/incomplete
   paths remain excluded or pending, not forced daily closes. Research runs hourly.

## Additional knowledge and evidence improvements

Holding-period settings now enter decision-time snapshots instead of being assumed
later. The payoff implementation participates in execution evidence code identity.
The hourly knowledge compiler stores structured paired-study results and an evidence
inventory: missing original risk, policy identity, final quote, sampled path and hold
policy. DECISION_RESEARCH_GUIDE.md and generated PAIRED_STUDY.md/KNOWLEDGE_GAPS.md
are part of the bot's documented reference-read receipt.

## Limits and validation

The new study starts at registration and does not backfill historical results as
prospective evidence. It uses normalized equal-half scale-outs, measured executable
OHLC and a fixed 0.2-pip adverse fill scenario. It has no portfolio/margin allocation
or broker rejection model. Overlapping opportunity outcomes cannot be summed into
account returns. Fees, financing, quote-to-fill differences and broker reconciliation
remain separately labeled; this is not a calibrated net-return model.

At least 50 paired outcomes and ten days per cohort are required for initial review,
with a positive day-block uncertainty interval. These do not permit promotion:
execution parity, verified costs, multiple-testing review and a separate forward
holdout remain required. No automatic broker strategy promotion was added.

The existing policy experiment's frozen source hashes remain unchanged. A measured
360-bar smoke run completed all three slippage cases (14, 13 and 4 completed
simulated trades); this verifies the integration, not profitability.

Deployment verified October 1, 2026 UTC: version 2.26.0 warm, practice trading
enabled after broker reconciliation. Market archive and paired-study workers
completed their first invocation; quote observation is running. The full scheduled
cost matrix was still running at verification. New prospective registration:
2026-10-01T15:44:48.602185+00:00. Existing registration source hashes match.
Validation: 470 Python tests and 48 dashboard checks passed.
