> Current operator override (September 29): practice trading is resumed with existing
> risk gates; research-only blocking is disabled. Autonomous research continues
> independently. Knowledge compilation runs every hour. Earlier pause descriptions
> below are historical and superseded by this instruction.

# Strategy lab: measurable improvement before more orders

Implemented September 29, 2026. The active service is **research-only**:
`STRATEGY_RESEARCH_ONLY=true`. New orders and the dashboard enable action are
blocked; existing-position management, quotes, scans and journals continue.
The 0.1% planned risk / 0.5% daily limits remain configured, but do not authorize
orders while research-only is enabled. Midnight does not remove this block.

## What runs automatically

The existing background service runs a separate research process at startup and
every six hours. It has a 30-minute timeout and cannot overlap another scheduled
run. Completed cost/candidate runs are checkpointed so a timeout does not discard
finished comparisons. Failures replace the visible status with `evaluation_failed`; status becomes
stale after eight hours. This requires the Mac and service to remain running.
The process loads local completed OANDA bars read-only and has no broker client.

On its first run, it freezes the current entry settings, code hashes and UTC
registration time. It registers a reference plus two hypotheses: one extra
confluence requirement, and an eight-pip minimum stop. These are experiments,
not conclusions about the cause of the previous losses. The spread gate is frozen
at registration, even if the operational sampling trial later expires.

Evaluation starts at the next UTC midnight, so previously inspected history cannot
be relabeled as unseen evidence. Two consecutive seven-calendar-day windows are
evaluated independently; incomplete windows cannot qualify. Completed window
results are preserved and reused, not repeatedly refitted. Changing strategy code
invalidates the experiment rather than silently reusing its holdout. A new version
is automatically registered as a new experiment with a new future cutoff by the continuous controller.

## Acceptance screen

Each candidate must pass both windows at both 1.6- and 1.8-pip spreads, with 0.2-pip
adverse slippage. Every window/cost case needs at least 50 completed trades across
five active UTC days, positive expectancy, and positive 99% lower bootstrap bounds
for daily pips and improvement over the unchanged reference. Day blocks include
zero-trade days. Drawdown cannot exceed a reference that has completed trades.
Forced end-of-window closes and trades crossing missing-price intervals are
excluded and reported. Insufficient samples cannot be labeled successful.

The bootstrap is a conservative research screen, not statistical proof: days can
remain correlated, the sample can be short, and multiple hypotheses remain a risk.
Pips have equal trade weights and do not represent account returns. The simulator
uses midpoint OHLC with constant costs; it does not reproduce news filters, learned
restrictions, portfolio sizing, commission, financing or broker execution. Context
lookbacks now match production's 300 entry / 250 H1 / 180 D1 bars for this lab.

Passing means **eligible for forward review**, never automatic broker promotion.
The continuous controller may select it as the next simulation-only reference
after verifying all required window/cost cases passed.
The service does not modify live strategy settings from a lab result. Rejected
candidates retain their reasons; no candidate is rescued by increasing size.
If both candidates fail, the controller retains the research reference and starts
a new experiment automatically. It tries unused combinations first within a bounded
5/6/8/10-pip stop and confluence grid; after exhaustion, it can retest configurations
on fresh periods without erasing their earlier failures. It does not invent arbitrary
strategies, increase risk, or relax evidence thresholds. No profitable improvement
has yet been established.

## Evidence and operator visibility

- `data/research/strategy-lab/experiments/generation-NNNN/experiment.json`: frozen settings, hypotheses and source hashes.
- `evidence.json`: completed-window evidence retained between checks.
- `runs/`: versioned evaluation reports, including trades and input/context hashes.
- `latest.json`: current status, read by `/api/state` and the Overview panel.
- [Generated learning status](STRATEGY_LEARNING_STATUS.md): latest result for desk readers.

The dashboard separates strategy evidence from service availability. The API's
health response explicitly describes its scope as availability, not profitability.
Manual research command: `.venv/bin/python -m src.analysis.continuous_lab`.
No manual command is needed during normal operation. The persistent controller
keeps generation IDs, rejected outcomes and the simulated reference in
`data/research/strategy-lab/controller.json`. Each generation has its own evidence
and reports. The earlier single-experiment files remain untouched as an archive.

The controller uses a process lock and resumes partial evaluation checkpoints after
a failure. It rolls over completed or source-invalidated experiments automatically.
A finished period still lacking evaluable data after a 12-hour grace period is
archived as insufficient evidence, never treated as a winner. Failures retry the
same generation; no human relearn command is required. Operating settings and
broker entries remain protected by research-only mode.

Regression coverage includes parameter/cutoff persistence, future-only windows,
rejection of tiny positive samples and forced closes, comparison against the
reference, source-change invalidation, reuse of completed windows, worker failures,
and order/enable blocking in research-only mode.
