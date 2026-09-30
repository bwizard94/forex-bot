# Forex bot design review — 30 September 2026

Scope: public commercial forex EAs, an open forex robot, and reusable engineering
from open trading frameworks. This is a design review, not a recommendation to
buy an EA, a performance audit, or proof of a profitable EUR/USD strategy.
No third-party code, binaries, paid settings or credentials were imported.

## What “successful” evidence would require

A named, current live account with broker-linked history, visible open equity,
drawdown, deposits/withdrawals, costs, settings/version and enough independent
trading periods is stronger evidence than a vendor's winning screenshot.
Account verification does not establish which code generated each order or
whether selected accounts represent all configurations. Myfxbook distinguishes
broker-history verification from proof of trading privileges; neither by itself
certifies a future edge. [Verification definitions](https://www.myfxbook.com/help/knowledge-base/verification/).

I could review public designs and documentation, but could not independently
establish a reproducible, currently profitable EUR/USD bot from these sources.
Commercial source code and full configuration histories were not available.
Framework maturity is engineering evidence, not a profitable strategy.

## Commercial and operating examples

### Forex Fury — conditional participation, not guaranteed frequency

The vendor describes a low-volatility range method, condition filters and a
limited trading window; it lists multiple live and demo configurations. It also
states that results vary with broker, settings and market conditions. These are
vendor disclosures, not independently reproduced results.
[Official product and FAQ](https://www.forexfury.com/).

The linked account-owner profile could not be retrieved directly (HTTP 403):
[Myfxbook profile](https://www.myfxbook.com/members/forexfuryreal).
No vendor return or win-rate claim is adopted as fact.

Transferable hypothesis: tag range versus trend conditions and compare a
range-specific challenger to the current baseline under identical costs.
Do not copy a one-hour trading restriction: our operator wants eligibility
throughout open-market hours. Conditional setup quality can vary by session
without forbidding the whole session.

### Forex Flex EA — shadow observations and explicit configuration versions

The vendor describes virtual trades used to observe conditions before real
entries, configurable news exclusion, multiple strategy presets and account
results tied to different configurations. Its page also includes grid-family
configurations and basket exits. Claims of superior entries are unverified.
[Official features and description](https://forexflexea.com/).

Useful inference: preserve shadow decisions and outcomes separately from broker
fills; retain the exact candidate version. Our prospective lab already freezes
candidate settings and separates simulated selection from execution. A richer
shadow portfolio could be added later, but must model spread, fill availability,
overlapping positions and costs. Do not copy grid recovery or basket risk merely
because a selected account chart looks attractive.

### Darwinex / Thales — scenario context with structured execution

The Thales FAQ describes expert-led event interpretation and systematic execution
and risk, using historical event analogues selected within a predefined framework.
This is a hybrid process, not an off-the-shelf autonomous EA.
[Provider process description](https://thales.darwinex.com/faq).

The public THA page confirms a listed product and trading-history start in 2017,
but its retrieved return/drawdown fields were blank. I did not substitute old
marketing figures for those missing current statistics.
[Broker-hosted product record](https://www.darwinex.com/invest/THA).

Transferable hypothesis: record expectations and alternative scenarios before an
event, then compare like-for-like outcomes. Do not let a post-loss narrative become
a supposedly known pre-trade signal. Our bot still needs a costed forward test
before adding an event-reaction strategy.

## Open implementations and engineering references

### EA31337 — explicit strategy modules and release-bound settings

EA31337 is an open MQL forex robot/framework for MT4/MT5. Its documentation
describes EUR/USD-oriented default presets and warns against mixing settings from
different releases. Broker and symbol validation remain necessary.
[Repository and README](https://github.com/EA31337/EA31337);
[project best practices](https://github.com/EA31337/EA31337/wiki/Best-practices).

Adopt the separation of strategy implementation, settings and evaluation identity.
Our lab already hashes research sources and freezes parameters. The new diagnostic
also records source hashes and parameters and marks old results invalid after
changes. No claim of verified profitable defaults is made. Its GPL code was not
copied into this project.

### Freqtrade — test whether indicators secretly use future information

Freqtrade's lookahead analysis compares baseline and sliced runs to detect
future-dependent calculations. It explicitly warns that untriggered signals can
escape detection. Its recursive analysis compares indicator outputs across
startup-history lengths; it does not prove that a difference changed an entry.
These are crypto-framework engineering methods, not forex performance evidence.
[Lookahead analysis](https://docs.freqtrade.io/en/stable/lookahead-analysis/);
[recursive analysis](https://docs.freqtrade.io/en/stable/recursive-analysis/).

Adopted here: a native, bounded prefix audit and history-length sensitivity report
for our own indicators. It does not copy Freqtrade code or replace our engine.

### FreqAI — autonomous retraining still needs expiration and forward validation

FreqAI documents sliding train/test windows, model expiration and continual
learning. It explicitly labels its incremental-learning approach experimental,
with overfitting and local-minimum risks.
[Running FreqAI](https://www.freqtrade.io/en/stable/freqai-running/).

Our inference: “learn continuously” should mean repeatedly generate falsifiable
evidence, retain failures and expire stale results. It should not mean increase
confidence because more updates ran. Existing prospective experiment rollover is
retained. No neural model or automatic strategy promotion was added.

### QuantConnect / LEAN — execution assumptions are part of the strategy

QuantConnect exposes fill/slippage models and documents differences between
backtests and live execution, including stale prices.
[Fill models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/supported-models);
[slippage](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts);
[live reconciliation](https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading/reconciliation).

Already present: completed-bar decisions, next-bar replay entries, modeled
spread/slippage and conservative ambiguous-bar stops. Remaining research:
calibrate cost assumptions against actual fills by session and volatility; quote
history is needed before claiming historical executable bid/ask simulation.
Do not equate the current midpoint replay with an exact broker simulator.

### NautilusTrader — broker reports define operational truth

NautilusTrader documents startup and continuous execution reconciliation against
venue order, fill and position reports, and retained event state.
[Execution reconciliation](https://nautilustrader.io/docs/latest/concepts/execution/reconciliation/);
[backtesting architecture](https://nautilustrader.io/docs/latest/concepts/backtesting/).

Already present: broker-confirmed state and explicit bot ownership. Preserve
operator trades and unresolved-order evidence. The useful lesson is recovery and
reconciliation discipline, not migration to a larger framework during a live
practice session.

## Implemented in release 2.22.2

- Native indicator audit reads at most 4,500 recent OANDA M1 rows through a
  read-only SQLite connection; only completed M1 bars form complete M5 bars.
- Six prefix checkpoints compare past indicator values with and without future
  bars. Separate 150/300/450-bar histories are compared with a 600-bar reference.
- Reports include input/code hashes, settings, coverage, untested columns and
  numeric differences. Insufficient data, failure, stale code/settings and stale
  results are distinct states. Passing a sample is not exhaustive proof.
- Runs in a separate process at startup and every six hours via the existing
  research job, with a 90-second bound. Audit failure does not suppress the
  prospective strategy worker.
- Overview and Health expose its status; generated INDICATOR_AUDIT.md and versioned
  JSON reports enter the existing documentation and hourly knowledge workflow.
- Audit findings are diagnostic. They cannot suspend a strategy, enable orders,
  adjust risk or promote an experiment.

Initial local sample: 600 M5 bars, 77 indicator columns, six prefix checkpoints,
zero lookahead mismatches. Shorter histories produced numeric differences;
at the 300-bar checkpoint these included a tiny ADX difference and an EWMAC
difference. Those are measurements, not evidence of a losing trade or a reason
to increase trading risk. Runtime evidence is versioned locally under
data/research/indicator-audit/ and is not published with account data.

Validation: 403 Python tests and 48 dashboard action scenarios passed, including
deliberately leaky indicators, recursive sensitivity, stale/failure reporting and
research-worker isolation.

## Prioritized follow-up experiments

| Experiment | Why it could help | Acceptance evidence |
| --- | --- | --- |
| Warm-up impact on actual decisions | Numeric differences may or may not change entries | Compare frozen signal decisions at matching timestamps; investigate changed decisions before altering history lengths |
| Cost calibration by session | Fixed costs can overstate a small scalp edge | Fill-versus-decision slippage distribution and unseen cost-stressed replay |
| Regime-specific range challenger | Commercial range bots restrict participation by conditions | Pre-register the regime classifier; compare net results and drawdown on future windows |
| Shadow execution portfolio | Learn about rejected opportunities without enlarging broker exposure | Realistic fills, concurrent exposure limits, independent labels and separate accounting |
| Event scenario journal | Distinguish surprise, first reaction and follow-through | Timestamped pre-event expectations and later outcomes; no revised-data leakage |

These are proposed experiments, not completed capabilities. Preserve the existing
risk controls and broker-open-hours policy while testing them.
