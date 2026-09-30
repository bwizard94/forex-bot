# Release 2.23.0 — entry evidence and loss-review corrections

## Deployed corrections

- Scores use the selected side, not whichever side has more indicators. Related momentum/trend tools share family caps. Scores remain heuristic, not calibrated probabilities; the grouping does not prove independence.
- Committed-close labels require a candle body pointing in the proposed trade direction.
- OANDA exit attribution verifies a final closing fill for the exact ticket. Partial exits or nearby prices cannot manufacture a stop/target reason. Attribution failure preserves confirmed P/L and leaves cause unknown.
- Contextual journals record observable EMA alignment and outcome, while separating hypotheses from proven causes. They do not infer chop from a quick loss or promise improved odds from a higher score.
- Learning status separates completed evaluations from invalidated archives, both in generated status and the dashboard. There is still no validated profitable strategy.
- Updated operating documentation takes precedence over historical risk/session/banning examples.

## Implemented, but not promoted

`CONFIRMED_ENTRY_POLICY` remains **false**. New reversal and same-side re-entry checks run as saved shadow evidence on directional decisions. The prospective research proposer includes `confirmed-reversals` as a candidate.

The candidate requires at least two evidence families. A fade or a trade opposed to the local EMA direction needs a directional close beyond the prior bar. Following the latest same-side bot loss, it requires a new bar beginning after that loss and closing beyond the prior bar. Missing/nonfinite data and gaps cannot confirm a reversal. Operator trades, ledger copies and rejected orders do not determine the prior loss. Replay conservatively treats the exit candle's end as the close time.

The candidate is not an execution upgrade: the diagnostic comparison below failed to establish an improvement. Activating it anyway would substitute an unproven filter for an unproven baseline. The current entry policy continues with corrected evidence/scoring, existing risk caps and the operator's demo trading authorization; no daily halt or risk increase was introduced.

## Diagnostic comparison

Observed EUR/USD M1 midpoint OHLC, 2,400 recent bars, shared chronological early/late segments, completed bars only, 300/250/180 signal/H1/D1 histories. Both use 0.2-pip modeled adverse slippage and the spreads below. Baseline source was preserved before edits. Partial exits aggregate within each trade; forced final-bar closes are excluded.

| Policy | Segment | Spread pips | Completed trades | Net pips | Mean pips/trade | Max drawdown pips |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| baseline | early | 1.6 | 19 | -18.88 | -0.99 | 29.70 |
| baseline | early | 1.8 | 17 | -20.19 | -1.19 | 25.76 |
| baseline | late | 1.6 | 26 | -70.46 | -2.71 | 70.46 |
| baseline | late | 1.8 | 23 | -74.98 | -3.26 | 74.98 |
| confirmed | early | 1.6 | 14 | +5.11 | +0.37 | 18.70 |
| confirmed | early | 1.8 | 11 | +0.19 | +0.02 | 19.00 |
| confirmed | late | 1.6 | 18 | -74.06 | -4.11 | 74.06 |
| confirmed | late | 1.8 | 11 | -69.90 | -6.35 | 69.90 |

Interpretation: early-period improvement did not generalize to the late segment. At 1.6-pip spread late mean loss worsened; at 1.8 pips the new filter selected eleven losing trades. Lower total loss with fewer trades is not sufficient evidence of an edge. Do not promote the candidate from this comparison.

All these dates were already exposed to analysis; neither segment is an untouched validation set. Results are diagnostic, equally weighted pips, not account return forecasts. Constant spread and midpoint bars do not reproduce historical quotes. News, rejected orders, dynamic lesson gates, portfolio sizing, commission and financing are omitted. Replay does not model all production score-dependent gates. The confirmation check is included for the candidate only. No historical P/L improvement is claimed for the scoring/accounting bug fixes.

Local artifacts (ignored): `data/research/policy-review-2.23.0/comparison.json` and `baseline_signals.py`. Input hashes, source hashes, per-trade outputs and comparison assumptions are retained there. Private broker/account evidence is not published.

## Research and operating continuity

This changes strategy source, so the prospective controller archives the previous generation and starts a fresh cutoff. This is an invalidation, not a successful completed experiment. The new candidate needs fresh prospective evidence. Research references never automatically authorize broker settings or increase risk.

Knowledge compilation remains hourly and research checks run at startup/every six hours. `desk/knowledge` revisions preserve what was recorded at each compilation. Past trade narratives require broker evidence before correction; do not rewrite outcomes or pretend historical lessons were known at entry.

## Verification

Regression coverage includes selected-side scoring, family caps, wrong-direction candle tags, confirmation/re-entry chronology, missing data, exclusion of human/mirror/rejected trades, contextual journal claims, exact broker exit matching and honest experiment counts. Validation: 425 Python tests and 48 dashboard regression scenarios passed; JavaScript syntax check passed. GitHub and GitLab now run the Python and dashboard regressions on pushes. No claim of profitability follows from tests passing.
