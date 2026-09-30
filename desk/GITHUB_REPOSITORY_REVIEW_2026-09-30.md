# Public forex repository review — 2026-09-30

Status: static research and adoption proposals; not validated trading rules.

## Scope and evidence

Reviewed the supplied GitHub topic listing and six unique repositories. ForexSmartBot was supplied twice. Inspected selected source files at the commits below, not every module or dependency. Niferu's web page failed to load, but GitHub API and raw source retrieval succeeded. External programs, installers, EAs and models were not executed. README claims and backtest screenshots are not independently verified returns. This review establishes no profitable EUR/USD policy.

The topic page is a discovery catalog, not an endorsement or evidence of success: https://github.com/topics/forex-bot . No additional listed projects received a code audit.

## Repository findings

### EA31337 — strongest testing-workflow reference in this sample

The backtest workflow varies EA mode, deposit and spread and uploads result artifacts, including failure paths. Yearly Docker configurations expose scenario assumptions. Adopt the concept of reproducible cost-stress matrices and retained failed results. Do not import its multi-strategy presets as a demonstrated edge. Workflow inspection does not establish that current CI passes; mutable external actions/images and matrix artifact names need independent review before reuse. MetaTrader spread units must not be copied as OANDA pip units.

Our lab already freezes source/configuration, hashes inputs, compares chronological windows and records outcomes. Extend its surrounding research reports with predeclared cost scenarios and uniquely named artifacts rather than replacing it or changing the running experiment.

Sources: [workflow](https://github.com/EA31337/EA31337/blob/9b9bd38c4e49dd6916f4fe3936e50e97fca7a692/.github/workflows/backtest.yml), [scenario configuration](https://github.com/EA31337/EA31337/blob/9b9bd38c4e49dd6916f4fe3936e50e97fca7a692/docker/backtest/Advanced/all-yearly/2019/docker-compose.yml).

### trentstauff/FXBot — useful separation, unsuitable execution transplant

Separate historical and streaming strategy classes, lagged features and turnover costs are useful educational patterns. LiveTrader discards the unfinished resampled bar. Our completed-bar pipeline already covers that principle.

The inspected live trader tracks position in memory, sends doubled units to reverse direction, and calls close_position from its destructor. That is a poor fit for our broker-reconciled, OPEN_ONLY, human-trade-preserving account. Backtester.resample calls resample without aggregation or assignment, so it does not actually replace the stored data. Default trading_cost is zero; passing costs is essential. Keep the interface idea, not its execution lifecycle or an assumption of realistic fills.

Sources: [live trader](https://github.com/trentstauff/FXBot/blob/306a638c26cc81ac0c5b202ed54e7b73e0717d21/livetrading/LiveTrader.py), [base backtester](https://github.com/trentstauff/FXBot/blob/306a638c26cc81ac0c5b202ed54e7b73e0717d21/backtesting/Backtester.py), [lagged model example](https://github.com/trentstauff/FXBot/blob/306a638c26cc81ac0c5b202ed54e7b73e0717d21/backtesting/MLClassificationBacktest.py).

### VoxHash/ForexSmartBot — useful analytics concept; validation defect

PerformanceAttribution groups trades by strategy and time/symbol dimensions. This supports contextual reporting, but its return_pct is P/L divided by traded notional, not account return; zero-P/L trades enter the losing count. Our reports should keep scratches explicit and distinguish account returns, pips and original-risk R.

WalkForwardAnalyzer._test_strategy receives a strategy but never uses it: it computes price-series returns and drawdown. Therefore those walk-forward numbers do not test the candidate strategy. The default test windows also overlap. Its core backtester signals and fills at the same close; that path is not a realistic substitute for our next-bar cost-aware replay. These observations concern these specific modules, not every alternate backtest implementation in the repository.

Adopt the analytics questions and add evaluator sanity checks to our validation backlog. Do not adopt its walk-forward result as strategy evidence or its advertised adaptation as proof of learning.

Sources: [attribution](https://github.com/VoxHash/ForexSmartBot/blob/f8e215afe676fd494f194ebb5bf31d2ee8eb9b20/forexsmartbot/analytics/performance_attribution.py), [walk-forward](https://github.com/VoxHash/ForexSmartBot/blob/f8e215afe676fd494f194ebb5bf31d2ee8eb9b20/forexsmartbot/optimization/walk_forward.py), [core backtester](https://github.com/VoxHash/ForexSmartBot/blob/f8e215afe676fd494f194ebb5bf31d2ee8eb9b20/forexsmartbot/core/backtester.py).

### raidastauras/Trading-Bot — research examples, not an upgrade to our execution

The project explores feature engineering and several predictive models. In train_logistic_regression_v2.py, repeated checkpoint scoring uses both test and cross-validation performance. Those sets therefore participate in selection; they cannot also serve as untouched final evidence. The inspected objective uses directional price changes without an explicit spread/commission deduction. Its live main restores a saved TensorFlow model; model complexity is not evidence of autonomous improvement.

Adopt the lesson of separating development, selection and a final untouched evaluation. Keep our existing prospective registration. Do not replace the current EUR/USD entry system with these saved models.

Sources: [training/selection](https://github.com/raidastauras/Trading-Bot/blob/5b375d80e13923596d0bc902a761dc78e6437ef2/train_logistic_regression_v2.py), [live script](https://github.com/raidastauras/Trading-Bot/blob/5b375d80e13923596d0bc902a761dc78e6437ef2/main.py).

### tanvird3/TradingRobot — simple rules, weaker ownership/restart handling

SuperMao makes Bollinger/MACD conditions inspectable and uses a magic-number check. However, the entry indicators use shift zero, i.e. the forming bar. The order helper checks magic without an explicit symbol match; the magic formula combines timeframe and a small selection of symbol characters. OrderId is process memory, while initialization does not recover it from existing orders. Do not transplant this as an improvement to broker ownership and restart reconciliation.

Simple named strategy specifications are useful. This implementation does not establish that adding Bollinger/MACD votes improves our outcomes.

Sources: [EA](https://github.com/tanvird3/TradingRobot/blob/e6bfc9c27be98add57e40404fcca7143de9cf03e/SuperMao.mq4), [ownership helper](https://github.com/tanvird3/TradingRobot/blob/e6bfc9c27be98add57e40404fcca7143de9cf03e/openordercheck.mqh).

### Niferu/forex-trading-robots — management examples conflict with account isolation

Inspected InsideBars, MoneyManager and Pyramid examples. MoneyManager modifies positions selected by symbol without a magic ownership filter in the inspected loops. Pyramid uses account-wide position counts; its close/modify loops filter direction without symbol/magic ownership. Its initial sell supplies no stop, relying on later management, and sizing uses balance/10000 rather than original stop risk.

These patterns can interfere with unrelated/manual positions and are not suitable for our shared practice account. Do not adopt them. Broker stops at entry and exact owned-ticket management remain the better fit. The short README's testing claims are not accompanied by a verified track record in this review.

Sources: [money manager](https://github.com/Niferu/forex-trading-robots/blob/9c81cac331225aa596700fe78a0219bc59b1981b/ExpertAdvisors/MoneyManager.mq5), [pyramid](https://github.com/Niferu/forex-trading-robots/blob/9c81cac331225aa596700fe78a0219bc59b1981b/ExpertAdvisors/Pyramid.mq5).

## Comparison with our current implementation

Checked src/analysis/growth.py, learning_report.py, replay.py, strategy_lab.py, documentation.py, knowledge_base.py, operating policy and CI configuration.

Correction to the previous article assessment: growth.study_book already groups CLOSED bot trades by entry-time code hash, and learning_report includes those buckets. Version-based performance reporting is not absent. The useful extension is matched version/config/context analysis and execution-cost coverage, not duplicating the existing version bucket.

| Priority | Proposed improvement | Acceptance evidence |
| --- | --- | --- |
| 1 | Evaluator sanity cases: no-trade, forced long, forced short and adverse costs | A known price path produces independently calculated, different strategy results; no-trade stays flat and costs affect fills correctly. Check existing replay tests before adding redundant cases. |
| 2 | Broader research cost matrix with preserved run artifacts | Explicit pip units, input/config/code hashes, unique scenario names, errors retained, and realistic spread/slippage assumptions. Keep the current registered experiment frozen. |
| 3 | Extend existing version buckets with context and cost attribution | Matched timeframe/session/direction, original-risk R, sample counts, scratches, unknown coverage; reconcile totals to primary bot closes. No duplicate mirrors or operator trades. |
| 4 | Historical-to-runtime parity and restart drills | Completed bars, identical candidate settings, known handling of gaps and uncertain orders, fake-broker restart tests; no external account mutation during testing. |

These are engineering priorities, not claims that any one change will reverse losses. Promoting an entry rule still needs cost-aware chronological and forward-practice evidence. No strategy, account risk, daily-halt setting or broker position was changed by this review.

## Source snapshots and reuse

No external source code was copied into the application. GitHub metadata showed GPL-3.0 for EA31337; ForexSmartBot includes a license with additional conditions (API reports NOASSERTION). The other four repository metadata responses had no detected license. Public visibility is not a license grant; any future code import requires checking the actual applicable terms. Independently implemented concepts are preferred here.

- [trentstauff/FXBot](https://github.com/trentstauff/FXBot/tree/306a638c26cc81ac0c5b202ed54e7b73e0717d21): `306a638c26cc81ac0c5b202ed54e7b73e0717d21`
- [EA31337/EA31337](https://github.com/EA31337/EA31337/tree/9b9bd38c4e49dd6916f4fe3936e50e97fca7a692): `9b9bd38c4e49dd6916f4fe3936e50e97fca7a692`
- [VoxHash/ForexSmartBot](https://github.com/VoxHash/ForexSmartBot/tree/f8e215afe676fd494f194ebb5bf31d2ee8eb9b20): `f8e215afe676fd494f194ebb5bf31d2ee8eb9b20`
- [raidastauras/Trading-Bot](https://github.com/raidastauras/Trading-Bot/tree/5b375d80e13923596d0bc902a761dc78e6437ef2): `5b375d80e13923596d0bc902a761dc78e6437ef2`
- [tanvird3/TradingRobot](https://github.com/tanvird3/TradingRobot/tree/e6bfc9c27be98add57e40404fcca7143de9cf03e): `e6bfc9c27be98add57e40404fcca7143de9cf03e`
- [Niferu/forex-trading-robots](https://github.com/Niferu/forex-trading-robots/tree/9c81cac331225aa596700fe78a0219bc59b1981b): `9c81cac331225aa596700fe78a0219bc59b1981b`
