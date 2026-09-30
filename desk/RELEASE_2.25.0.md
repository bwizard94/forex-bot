# 2.25.0 — loss diagnosis, trade paths and prospective policy tests

## Implemented

1. The hourly learning report now breaks out direction, session, setup,
   higher-timeframe bias, spread/stop burden and concurrent bot exposure. Each
   group compares winners, losers and all outcomes in dollars and original-risk R.
   Groups overlap and must not be summed across dimensions. These are observed
   associations, not explanations of causality.
2. Every 15 seconds, fresh OANDA executable quotes can update open, remotely
   confirmed bot trades with sampled favorable/adverse excursion in pips and R.
   BUY uses bid; SELL uses ask. Original entry risk stays fixed even after stop or
   position changes. Samples, first/last observations and maximum gap are retained
   in the existing journal JSON and rendered in generated trade documents.
   Stale, duplicate, non-OANDA, pre-entry and human-trade observations are rejected.
   Observed extremes are lower bounds, not a full tick path. No legacy excursions
   or initial risk are invented.
3. Separate immutable entry/exit experiments compare the frozen baseline with
   local confirmation and half the current maximum holding period (minimum five
   minutes). Three future seven-day windows are registered; the final window is
   forward shadow confirmation. An hourly bounded worker evaluates one completed
   day/candidate/cost chunk, saves it, and resumes on the next invocation. It does
   not require a manual relearn request. Each daily replay starts flat and forced
   endings are excluded, a limitation of this diagnostic experiment. Both 1.6 and
   1.8 pip cost cases must pass independently; no extra indicators are stacked.
4. Diagnostic replay v5 accepts measured bid/ask OHLC and rejects incomplete or
   mismatched timeframe coverage. Entry uses the executable side and exits use the
   liquidation side. It models simulated USD unit sizing, unit/notional caps,
   reserved open risk, same-side limits and profitable-add-on requirements.
   Explicit timestamped rollover charges replace continuous carry when supplied.
   Broker commission schedules support per-fill minimums, including partial exits.
   The scheduled cost job refreshes current practice-account instrument metadata;
   absent commissions remain unknown, not inferred zero. A read-only candle export
   tool retrieves completed M1 bid/ask data; it never modifies execution records.
5. Promotion review verifies candidate identity, frozen code, complete passing
   windows and separate execution-cost validation. It saves an immutable plan with
   the prior settings and rollback thresholds. Post-deployment monitoring requires
   at least 20 closed trades from one policy with valid original-risk R. A 5R
   drawdown or last-20 total at/below -3R requests rollback review. Missing evidence
   requests review instead of claiming success. These modules do not themselves
   write broker settings; no candidate has earned execution eligibility.

## Initial diagnosis and validation

The local report snapshot contained 22 closed primary bot trades with recorded
price P/L of -2253.82. SELL: 11 trades, -1800.32, mean -0.718R. BUY: 11 trades,
-453.50, mean -0.690R. This shows why dollar losses alone can misidentify the worse
entry direction: the risk-normalized means are similar. Eight overlap-session
BUY losses totaled -471, about -1.006R per trade. All 22 showed zero other primary
bot trades open at their recorded entry times; overlapping exposure was not
established as the cause in this snapshot. Partial/copy records and manual trades
are excluded. This is local recorded price P/L, not an all-cost account return.

Retrieved 4,295 completed OANDA M1 bid/ask candles. A 360-bar measured-price smoke
run completed all three slippage scenarios, with one completed simulated trade
per scenario; this verifies the integration, not profitability. Known-path unit
checks independently verify executable-side prices, commission minimums, signed
rollover timing, immutable risk, and rejection of incomplete coverage.

The current broker instrument response omitted a commission specification.
Current financing metadata is not historical rate evidence and does not establish
the account's exact charge clock. Unknown costs remain explicit; alternative
historical orders cannot inherit actual fees from unrelated broker transactions.
The measured-price smoke used a prerelease v5 implementation with its source hashes
preserved in the private report; the released model tag is diagnostic_ohlc_v5.

## Evidence and operational boundaries

Generation 0004 and its original replay remain untouched. The new policy experiment
has its own registration, checkpoints, hashes, result and promotion records under
`data/research/policy-experiments`. On source change it invalidates rather than
resetting the cutoff. Reports and generated journals feed the hourly knowledge job.
Promotion and rollback plans are evidence review artifacts, not completed broker
actions. No new strategy is activated merely because code tests pass.

Sizing remains an approximation: USD-only synthetic accounting; no conviction
boosts, adaptive reductions, margin engine or exact broker fill queue. Fully held
OHLC cannot reveal intrabar ordering. Live sampled MFE/MAE cannot certify missed
extremes or the exact exit tick. Quote history is not a guarantee of fills.

Broker definitions used for commission units/minimums and financing metadata:
[OANDA instrument primitives](https://developer.oanda.com/rest-live-v20/primitives-df/).
The commission specification is in account currency per traded unit quantity;
financing exposes directional rates and charging-day multipliers, while the exact
charge time depends on the account's division/trading group.

Read-only measured candle export:

```sh
.venv/bin/python -m src.analysis.market_evidence --days 3 --output data/research/NEW-market.json
```

Use that JSON with `cost_stress --assumptions` and a matching frozen settings
snapshot. The measured candle timeframe must match the replay timeframe. A request
near the present is bounded to completed minutes to avoid a future end timestamp.

## Deployment verification

On September 30, 2026, version 2.25.0 restarted successfully and restored the
previously enabled practice-entry state through the broker-reconciling API.
The service reported warm and trading enabled. Attribution and experiment
registration completed; the executable-quote observer reported observing with
zero eligible open bot trades at that check. The registered prospective interval
is October 1 through October 22 UTC. The longer scheduled cost-stress run was
still processing at verification; measured-price smoke results are separate.

Validation: 455 Python tests passed with private operator configuration excluded
from test defaults; 48 dashboard regression scenarios passed. Existing SQLite
datetime-adapter deprecation warnings remain.
