# Strategy refinement: evidence before larger risk

Goal: seek positive expectancy after costs across multiple periods. No system can
promise regular profits, and increasing trade count or risk does not demonstrate
improvement. Two stopped trades identify losses, not a statistically reliable cause.

## Implemented comparison

Run `.venv/bin/python -m src.analysis.compare_strategies` from the project directory.
It reads the local database without creating broker clients or changing settings.
It compares frozen M1/5-pip, M5/5-pip and M5/8-pip candidates. M5 candidates use only
complete five-minute groups from the same observed M1 data. The 70/30 time split
is shared across candidates. Cost scenarios are 1.6 and 1.8 pips plus 0.2 pip adverse
slippage on entries/market exits. Versioned JSON reports retain trade lists, source
fingerprints and input hashes; STRATEGY_COMPARISON.md summarizes results.

The replay now supports M1 explicitly, preserves original stop prices rather than
shifting stops after a fill, checks entry costs/drift/reward-risk, and enables the
same heavy indicator calculation flag as the live evaluator. Fills happen after
signal completion. Forced end-of-sample closes are reported separately from the
primary completed-trade figures. Regression tests cover fixed-stop costs, timeframe
completion, ambiguous stop-first bars and exclusion of incomplete M5 groups.

## Practical decision rules

1. Reject candidates that lose after costs on the held-out period; do not rescue
   them by increasing risk or tuning repeatedly on that same period.
2. Treat a small positive sample as inconclusive. As an initial research screen,
   require at least 50 completed holdout trades across distinct sessions and a new
   untouched period before considering forward testing. This number is a screen,
   not statistical proof or permission to trade.
3. Compare expectancy, drawdown and cost sensitivity, alongside side/session
   concentration. Do not rank by win rate alone or include human/MT4 duplicates.
4. Check the proposed candidate using historical bid/ask and event coverage before
   a bounded, small-size practice test. Preserve the baseline for comparison.
5. Promote only after out-of-sample and forward results support the change. No
   automatic live promotion is implemented by this comparison.

## Limits

Local coverage has gaps; absent prices are not filled in. Midpoint OHLC and fixed
spread are approximations. The replay excludes broker rejection, financing,
commissions, dynamic lesson/cooldown gates, portfolio/risk sizing and news filters.
Its retained indicator lookbacks differ from the live pipeline (180 entry bars,
120 H1 and 80 daily bars versus up to 300/250/180). Therefore these are exploratory
candidate screens, not a reproduction of production or evidence that a backtest
profit will persist. Do not use the report to claim account returns.

No live entry settings, risk budgets or existing positions are changed by running
this command. During this task the service was checked and found trading-enabled;
that operator setting was left unchanged.

## First comparison outcome

Report: `data/research/strategy-comparison/20260929T144912Z.json`.
At 1.6-pip spread, completed holdout trades were M1: 10, -3.20 net pips;
M5/5-pip: 0 qualifying trades; M5/8-pip: 6, +14.25 net pips. At 1.8 spread,
M1 held-out net fell to -13.07 pips while M5/8-pip remained +13.55 pips.
However the wider M5 candidate lost -19.17/-31.08 pips in development. It is a
hypothesis for additional testing, not a selected profitable strategy. None meets
the research sample-size screen. Zero trades must not be interpreted as break-even
performance of a tradable strategy.

Input coverage: 3,186 M1 bars with 14 gaps; 627 complete M5 groups with 12 gaps.
Validation: 348 Python tests passed under baseline test settings. No live policy
or risk parameters were changed or promoted by this work.
