# Extra datasets

Forex Sentinel fills this folder on startup from [ForexSB historical EUR/USD](https://forexsb.com/historical-forex-data) (DukasCopy via `data.forexsb.com`). It writes:

- `EURUSD_M5_forexsb.csv`
- `EURUSD_H1_forexsb.csv` (resampled from M30)
- `EURUSD_D1_forexsb.csv` (resampled from M30)
- `cache/EURUSD5.lb.gz` and `cache/EURUSD30.lb.gz` (raw feed, not studied as tables)

You can also drop your own files here. The desk studies them on startup and whenever they change, then writes `desk/HISTORY.md`.

A Cursor cloud agent cannot see folders on your Desktop. When you run this bot **on your computer**, it also looks in:

- `Desktop/extra datasets`
- `Desktop/forex/extra datasets`
- any Desktop folder whose name contains `dataset`
- `EXTRA_DATASETS_DIR` if you set an absolute path in `.env`

To feed files into the cloud desk, copy them into this project's `extra datasets/` folder (or drag them onto the chat).

Useful extras:

- EUR/USD OHLCV (CSV, TSV, TXT, JSON, JSONL, Parquet)
- Histdata ASCII dumps (`YYYYMMDD HHMMSS;open;high;low;close;volume`, with or without a header)
- Forexite / Yahoo Finance exports
- Zip archives of any of the above
- Optional context: DXY, US 10Y, VIX, gold

The desk does **not** treat this folder as a second live feed. Its legacy
exploratory study:

1. Replays the live EMA 9/21 + RSI idea
2. Names each setup (continuation, band+RSI, MACD cross, stochastic, CCI, divergence)
3. Stores those signal types plus EMA/RSI/MACD/Stoch/ADX/CCI snapshots in SQLite (`setup_memory`, `indicators`, `signals`)
4. Produces exploratory setup summaries; unvalidated historical buckets cannot
   steer live entries by default under the September 22 reliability upgrade.

Restudy from the hub **History** or **Setups** tabs, or `POST /api/history`.

## Research qualification — 2026-09-22

Current replay summaries are exploratory, not a complete execution backtest of
the live Ox strategy. The legacy replay uses EMA/RSI; the named replay evaluates
signals but checks exits at sampled closes and omits the full cost/partial-exit
lifecycle. Higher-timeframe candle availability also needs auditing against each
vendor's timestamp convention. Do not interpret a one-trade “best setup” as a
validated edge.

See [the standing research review](../desk/RESEARCH.md) for the source-backed
validation plan. Preserve vendor, timezone, bid/ask/mid convention, candle label
and completeness metadata with future datasets. The
[reliability upgrade](../desk/RELIABILITY_UPGRADE_2026-09-22.md) governs the
current historical-validation gates.

## Dukascopy second exports — 2026-09-25

Files named `EUR-USD_1Second_BID_...csv` or `EUR-USD_1Second_ASK_...csv`, with
the supplied timezone/OHLC/Volume layout, are audited and catalogued as S1,
then excluded from midpoint replay. Invalid recognized files are skipped with
a reason. Do not rename them as M1 or midpoint data to bypass this check.

For a detailed offline JSON report, run `python -m src.data.dukascopy INPUT.csv
--output NEW_REPORT.json` from the project environment. Output paths must be
new. The report preserves gaps, quote side, timestamp/coverage limitations and
a source fingerprint; it never fills absent seconds. See
[DUKASCOPY.md](../desk/DUKASCOPY.md) for the tested command, source review and
the supplied September 24 file's results.
