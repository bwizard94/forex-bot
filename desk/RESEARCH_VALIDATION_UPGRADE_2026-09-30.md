# Research validation and attribution upgrade — 2026-09-30

Implemented independently from the repository review. No imported third-party code,
execution-policy changes, account-risk changes or registered experiment resets.

## Evaluator controls

`tests/test_research_priorities.py` exercises forced long, short and no-trade
strategies on the same known path. Expected outcomes are calculated independently:
+2/-2 pips before costs, minus spread and twice adverse slippage; no-trade remains
flat. Existing replay tests also cover next-bar fills, stop-first ambiguity, gaps,
partial targets, breakeven timing, completed context and cost rejection.

## Cost matrix

Run from the project root, using a NEW output path:

```sh
.venv/bin/python -m src.analysis.cost_stress --database data/forex_bot.db --bars 2000 --output data/research/cost-stress-NEW.json
```

This standalone tool uses completed OANDA M1/H1/D1 history, reads SQLite without
write access, and tests spread/slippage pairs in pips: (1.2,0.1), (1.6,0.2),
(1.8,0.2), (2.5,0.5), (3.0,1.0). Each scenario retains outcomes, completed-trade
metrics and failures. It refuses to overwrite an existing report. Input and source
hashes and allowlisted configuration are included. No tokens or account snapshots
are exported.

The CLI deliberately uses repository defaults with M1 selected, not the operator's
private .env profile. It is a research baseline, not a reproduction of current
account trading. Normal entry gates remain active: expensive scenarios can have
zero trades. More adverse costs can change which trades are selected; aggregate
P/L is not guaranteed to decrease monotonically. Forced end-of-data exits are
reported separately. Observed history is exploratory, not a new untouched holdout.
No commission, financing, news, learned-gate or portfolio model is claimed.

## Matched-context attribution

```sh
.venv/bin/python -m src.analysis.learning_report --database data/forex_bot.db --output data/research/context-NEW.json
```

The existing read-only audit now includes `contextual_attribution`: closed primary
bot trades grouped jointly by recorded code hash, configuration hash, timeframe,
side, session and higher-timeframe bias. Compare versions within matching contexts;
this is descriptive conditioning, not proof of causality. Very small groups should
not select a strategy.

Existing outcome statistics include scratches, monetary P/L and R calculated only
from recorded original USD risk. Cost diagnostics include entry bid/ask spread,
spread/original stop, and direction-adjusted decision-quote-to-fill movement. The
last includes latency and market movement; it is not isolated broker slippage.
Each diagnostic includes available and missing counts. Costs are never deducted
again from realized P/L. Manual trades, mirror venues and partial-child records
are excluded. Missing legacy evidence remains unknown.

The first local read-only report covered 21 closed trades in nine context groups,
with quote-spread coverage for all 21. These counts are a snapshot, not an ongoing
profitability claim. Private reports stay under ignored data/research/.

## Operation

Both tools are on-demand research commands and require no service restart. They do
not replace the hourly knowledge job or promote experiments. The active generation
0004 source hashes were verified unchanged. Results and this guide are available
through the desk knowledge compilation; incorporation is not execution authority.

## Initial cost-run evidence

On 2,000 completed M1 bars from September 29 10:03 UTC through September 30
19:27 UTC, the repository-default M1 baseline at 1.2-pip spread / 0.1-pip
slippage completed 36 simulated trades, totaling -48.92 pips (mean -1.36 pips).
The other four cost scenarios completed with zero trades under the retained
entry restrictions. Zero-trade outcomes provide no evidence of profitability.
These are equal-weight replay pips, not account P/L or a validated forward test.
The private scenario artifact is data/research/cost-stress-20260930.json.

Validation: 436 Python tests passed with Settings .env loading disabled only
inside the test process; 48 dashboard scenarios and JavaScript syntax passed.
The operator configuration and running process were not modified for tests.

## Superseded operating details

Release 2.24.0 now schedules these diagnostics and uses frozen active settings for
scheduled cost runs. Its separate v4 replay adds multiple positions and explicit
news/fee assumptions. The initial v3 default-M1 results above remain historical
and must not be combined with the new model. See [release notes](RELEASE_2.24.0.md).
