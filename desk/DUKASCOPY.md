# Dukascopy research and EUR/USD integration review

Reviewed September 25, 2026. Scope: the public research index, historical data,
JForex documentation, positioning tools, calendars, execution information and
strategy education. This is a targeted review across the relevant website
sections, not a crawl of every article. Findings below distinguish source
statements, our interpretation, implemented changes and proposed experiments.

## Main decision

Dukascopy is useful as a historical-data source, a secondary context source,
and a source of testable strategy ideas. Its articles and widgets do not prove
an EUR/USD trading edge. The immediate improvement is to preserve data meaning
before testing strategies: quote side, clock, candle interval, gaps and the
time information became available.

The active book remains EUR/USD, OANDA practice, Ox LWMA48/envelopes/DSS M5 with
H1/D1 context. This review does not change sizing, stops, event restrictions or
weekend rules. No broker migration or new network feed is implemented.

## Implemented in this review

[`src/data/dukascopy.py`](../src/data/dukascopy.py) provides an offline audit of
the operator's specific one-second export format. It accepts EUR/USD BID or
ASK files with an IANA-timezone first column and offset-bearing timestamps.
It validates the offset against that timezone, including daylight-saving
transitions; rejects duplicates, unsorted timestamps, fractional-second labels,
invalid OHLC, nonfinite numbers and negative volume; and preserves absent
seconds without filling them. Filename attribution is not authenticated vendor
provenance. Other export formats require separate adapters.

The report includes a source SHA-256, endpoint coverage, gap statistics,
observed-price M5/hourly aggregates and the largest M1 ranges. Empty aggregate
buckets stay null. Boundary-partial and full-second-grid flags describe the
observations, not guaranteed market-feed completeness. Volume semantics remain
unverified and volume is excluded from weighting and signals.

[`src/data/datasets.py`](../src/data/datasets.py) now recognizes this filename
format before the generic loader: valid exports are catalogued as S1 with their
quote side and coverage, then excluded from midpoint strategy replay. Invalid
recognized exports are skipped with a reason. This prevents these second bars
from entering the generic interval heuristic as M1, or BID prices from being
treated as midpoint prices. This is a specific adapter, not a replacement for
all generic format inference.

Run from the project directory; use a new output path each time:

```bash
.venv/bin/python -m src.data.dukascopy \
  '/Users/brandong/Downloads/EUR-USD_1Second_BID_2026-09-24_01_00-23_00_America_Chicago.csv' \
  --output data/research/dukascopy-2026-09-24-audit.json
```

The report already exists at the path above; the command deliberately refuses
to overwrite it. It uses no broker, database, settings or network client.
Both `validated_for_live` and `eligible_for_midpoint_replay` are false.

### What the supplied file actually establishes

| Measurement | Observed result |
|---|---|
| Quote basis | BID only |
| Window | Sep 24, 01:00:00–22:59:59 America/Chicago |
| UTC window | Sep 24 06:00:00–Sep 25 03:59:59 |
| Recorded rows | 36,774 |
| Seconds between endpoints, inclusive | 79,200 |
| Absent seconds | 42,426; recorded coverage 46.43% |
| Gaps longer than one second | 13,659 |
| Largest elapsed gap | 112 seconds, containing 111 absent seconds |
| First open / last close | 1.13762 / 1.13689; −7.3 pips |
| Observed high | 1.13991 at 03:07:46 Chicago |
| Observed low | 1.13590 at 08:30:01 Chicago |
| Observed high–low range | 40.1 pips |

These are calculations from the supplied file, not independently verified live
quotes. Absent records could reflect export settings, unchanged-price omission
or missing data; the file alone cannot establish the cause. Its endpoints are
not certified daily open/close. A one-day sample cannot estimate a dependable
strategy expectancy. See the [complete audit JSON](../data/research/dukascopy-2026-09-24-audit.json).

## Data and execution lessons

**Quote side matters.** Dukascopy's history API explicitly selects BID or ASK
and distinguishes the forming bar from completed history. Its export interface
offers multiple granularities. Our file contains second OHLC, not every ordered
tick. A high and low within the same second do not reveal which came first.
[Historical data](https://www.dukascopy.com/swiss/english/marketwatch/historical/),
[history bars API](https://www.dukascopy.com/wiki/en/development/strategy-api/historical-data/history-bars/)

**Clock settings change chart comparisons.** JForex separates display timezone
from day-start settings and provides trading-break filtering. Matching the
display clock alone does not guarantee matching daily candles. Future imports
must record timezone, UTC offset, session anchor, bar-open versus bar-close
labels, and completion status. Our adapter explicitly labels bar-open timing
as an assumption of this supplied format.
[JForex preferences](https://dukascopy.com/wiki/en/manuals/jforex4-desktop/preferences/)

**Historical candles can manufacture an intrabar path.** JForex's tester offers
tick filtering and candle interpolation modes, including synthetic OHLC paths.
A stop/target outcome from interpolated candles is therefore model-dependent.
Use ordered bid/ask ticks for execution-sensitive tests, or report ambiguous
same-bar outcomes conservatively. Its order-fill rules also belong to that
venue and should not be copied into OANDA execution without verification.
[Strategy tester](https://www.dukascopy.com/wiki/en/manuals/jforex4-desktop/strategy-tester/)

**Published average spread is not the cost of the next trade.** JForex documents
a prior-week spread statistic excluding the settlement window, and its displayed
day range uses high ASK minus low BID. Neither is directly comparable to this
file's BID-only range or an actual rollover fill. Record contemporaneous spread
and fill slippage from our execution venue.
[New-order documentation](https://dukascopy.com/wiki/en/manuals/jforex4-desktop/new-order/)

Dukascopy commissions and rollover conventions are useful reminders to model
round-trip costs and financing, but they are venue/account-specific. The JForex
Java API is a separate broker integration, not a drop-in Python/OANDA endpoint.
[Fees](https://www.dukascopy.com/swiss/english/about/fee-schedule/),
[overnight policy](https://www.dukascopy.com/swiss/english/forex/forex-trading-accounts/overnight/),
[JForex API](https://www.dukascopy.com/swiss/english/forex/api/jforex-api/)

Independent field check: OANDA documents separate bid, ask and midpoint candles,
start timestamps, completion flags and a volume field counting prices. That
definition must not be assumed to describe Dukascopy's export Volume column.
[OANDA instrument definitions](https://developer.oanda.com/rest-live-v20/instrument-df/)

## News, calendar and positioning

The supplied research index mixes fundamental, technical and other market
coverage. Much of the visible recent material is unrelated to EUR/USD. An
eventual ingestion layer should select by article content and economic
relevance: EUR/USD directly, Fed/ECB policy, US/euro-area inflation and activity,
or documented cross-market dollar drivers. A keyword or URL category alone is
insufficient. Preserve author, canonical URL, publication timestamp, retrieval
timestamp and article type. Analyst scenarios should retain their original
horizon and invalidation conditions.
[Research index](https://www.dukascopy.com/swiss/english/marketwatch/market-news/Market-News-and-Research/)

The economic calendar describes event times, currencies, importance and
previous/forecast/actual values. It can provide a secondary human cross-check
for the existing calendar, but no usable automated widget endpoint was verified
here. Keep the existing ±30-minute major-event restriction. A future event
record should separate scheduled time, first public release time, ingestion
time, revisions, units and missing values. A revised historical actual cannot
be silently substituted for the number known when a signal fired.
[Economic calendar](https://www.dukascopy.com/swiss/english/marketwatch/calendars/eccalendar/)

SWFX sentiment is a venue-specific positioning measure updated every 30
minutes. Its consumer and provider views are mechanically opposing sides;
they are not two independent confirmations. It is not a global spot-volume
measure. A possible research feature is the last available consumer imbalance,
with its age recorded. Neither a contrarian nor trend-following interpretation
has been validated for our strategy.
[SWFX sentiment](https://www.dukascopy.com/swiss/english/marketwatch/sentiment/)

The COT page maps euro futures positioning to EUR/USD context. Use the CFTC's
primary timing: generally Friday 3:30 p.m. Eastern for Tuesday-close positions,
subject to its release schedule. Do not use a fixed UTC release time year-round,
or make Tuesday positions available in Tuesday's backtest. Define net exposure
explicitly as long minus short using the actual chosen report fields; do not
mix legacy and Traders in Financial Futures participant categories.
[Dukascopy COT](https://www.dukascopy.com/swiss/english/marketwatch/cot/),
[CFTC release definitions](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)

## Strategy ideas worth testing

These are proposed experiments, not enabled signals. The site's trend,
pullback, range and breakout articles broadly overlap the existing book. Their
useful contribution is a vocabulary for explicit conditions, not evidence for
adding many indicators. General examples of leverage or 1–2% risk do not
override our existing risk limits.
[Strategy overview](https://www.dukascopy.com/swiss/english/marketwatch/articles/top-trading-strategies-in-forex/),
[scalping](https://www.dukascopy.com/swiss/english/marketwatch/articles/forex-scalping-strategies/)

| Experiment | Definition to freeze before testing | What would justify keeping it |
|---|---|---|
| Completed-bar breakout/retest | Use an already-known session extreme; require a completed M5 close beyond it and a later retest. Freeze tolerance, expiry and invalidation before the holdout. | Improvement over the same Ox baseline after costs, including failed breakouts and missed trades. |
| Trend/pullback context | Compare unchanged Ox entries across predeclared completed-H1 slope and volatility buckets. | Stable net expectancy across multiple independent periods, not a single best bucket. |
| Range filter | Measure room to an already-known opposing level and expected all-in cost before entry. | Fewer costly low-room trades without a larger loss of profitable opportunities. |
| Session context | Label observations with DST-aware London/New York clocks and holidays; retain exact UTC times. | Persistent cost-adjusted differences, including weeks when DST dates differ. |
| SWFX/COT context | Use only snapshots genuinely available before the decision, with age and category metadata. | Incremental performance beyond price/context alone on untouched dates. |

Support/resistance role reversal and retests offer testable price patterns.
They do not establish the existence or intent of institutional orders at a
level. Similarly, smart-money terminology such as structure breaks can be
translated into measurable OHLC conditions; stop-hunt narratives cannot be
deduced from a wick. Keep narrative labels out of automatic trade permission.
[Support/resistance](https://www.dukascopy.com/swiss/english/marketwatch/articles/support-and-resistance/),
[Smart Money Concept](https://www.dukascopy.com/swiss/english/marketwatch/articles/smart-money-concept/)

The pivot tool offers several incompatible calculation methods. If tested,
choose one formula and session anchor in advance and compute it from completed
prior-session data. A pivot touch is not automatic evidence of reversal.
[Pivot levels](https://www.dukascopy.com/swiss/english/marketwatch/pivot/)

The trading-plan article's journal emphasis is useful: our journal should
preserve the decision-time evidence, setup version, rejection reason, expected
cost, actual fill, subsequent excursion and exit reason. These are proposed
audit fields, not all newly implemented fields. Article examples of capital,
sizing or schedules are not our operating instructions.
[Trading plan](https://www.dukascopy.com/swiss/english/marketwatch/articles/trading-plan/)

## Source-quality findings that affect decisions

1. **A current webpage is not a current forecast.** The euro forecast page is
   titled for 2025 and dated August 28, 2024. It contains later-year projections,
   but those are not fresh September 2026 analyst views. Exclude it from any
   current 24/48/72-hour forecast synthesis.
   [Forecast article](https://www.dukascopy.com/swiss/english/marketwatch/articles/euro-to-dollar-forecast/)
2. **A directional example contains reversed labels.** The risk article's
   ¥55 million receivable example starts at USD/JPY 110. At 120 the dollar is
   stronger and the receivable converts to about $458,333; at 100 the dollar is
   weaker and it converts to $550,000. The article's directional headings are
   reversed. Its arithmetic does not rescue those labels. Independently check
   examples before converting prose into code.
   [Risk article](https://www.dukascopy.com/swiss/english/marketwatch/articles/forex-risk-management/)
3. **Session marketing is not a volatility model.** The sessions article makes
   large transaction-share and EUR/USD movement claims without supporting
   evidence in the reviewed text, and presents fixed GMT overlap hours.
   Do not encode those numbers as expected ranges or all-year session times.
   Measure our data and handle DST explicitly.
   [Trading sessions](https://www.dukascopy.com/swiss/english/marketwatch/articles/forex-trading-sessions/)

## Validation and implementation queue

**Completed:** offline S1 audit, quote-side exclusion from midpoint replay,
source fingerprint and saved audit of the supplied file. Tests cover bad
timestamps/OHLC, DST fallback, sparse and empty buckets, BID/ASK attribution,
other-pair rejection, source preservation, non-overwrite behavior and the
historical-loader replay exclusion. Full offline suite: **261 passed** on
September 25, 2026. There are 240 existing sqlite datetime-adapter deprecation
warnings from ForexSB tests. Passing tests establish these code behaviors,
not trading profitability or broker execution correctness.

**Next data requirement:** obtain many days across quiet, trending, release and
rollover regimes with both quote sides, preferably ordered ticks. Establish
timestamp and omitted-record semantics with the export settings. Paired
one-second OHLC is still insufficient to reconstruct synchronized intrasecond
bid/ask paths; averaging separate highs and lows does not produce valid midpoint
extrema. Retain source files, hashes and acquisition settings.

**Next engineering work:** develop a separate execution-aware replay input
contract; add commission/financing and event availability; reconcile sessions
to DST; then evaluate the unchanged strategy before adding one experiment at a
time. Keep development, validation and final holdout periods chronological.
Report net expectancy, sample size, drawdown, tail losses, turnover, cost
sensitivity and rejected opportunities. Log every attempted variant and use
the multiple-testing safeguards in [RESEARCH.md](RESEARCH.md).

**Next context work:** verify a supported endpoint and usage terms before
automating sentiment, calendar or article collection. Capture historical
snapshots prospectively if authentic point-in-time archives are unavailable.
Compare the existing calendar with primary release schedules; stop treating a
successful webpage fetch as evidence of complete economic-event coverage.

**Operational boundary:** Friday flat remains 20:00 UTC; there is no Sunday
reopen execution; preserve Monday's 45-minute opening buffer. A weekend
72-hour plan can include observation and preparation, not implied authorization
to trade Sunday. No bot process was restarted for this research.

## Access limits and additional sections inspected

The average-spreads, market-hours, technical-indicators and online-news pages
were inspected, but embedded live numerical payloads and a supported automated
feed were not verified. Their availability in navigation is not a completed
integration. Some fetches redirected to unrelated homepage material; those
responses were not used as article evidence. No claim here depends on a live
widget quote, an authenticated account, or a purported fresh expert consensus.

- [Average spreads](https://www.dukascopy.com/swiss/english/marketwatch/average-spreads/)
- [FX market hours](https://www.dukascopy.com/swiss/english/marketwatch/fx-market-hours/)
- [Technical indicators](https://www.dukascopy.com/swiss/english/marketwatch/technical-indicators/)
- [Online news widget](https://www.dukascopy.com/swiss/english/marketwatch/online-news-widget/)

This is research and software validation, not a guarantee of future returns.
