# EUR/USD article research — 13-source intake

Reviewed September 29, 2026 (America/Chicago). **10 sources reviewed; 3 inaccessible.** `validated_for_live=false`. This document contains source findings, quality assessments and proposed experiments. It does not change execution or risk settings.

## Reading and evidence policy

Source IDs A01–A13 follow the operator's link order. Findings are paraphrased; whole articles and papers are not republished. Research years and forecast horizons are retained. Educational examples, retrospective studies, macro scenarios and measured broker outcomes are different evidence classes. A source's assertion of profitability is not independently reproduced performance.

The papers' relevant methods/results were inspected through full-text extraction; selected arXiv evaluation and result pages were visually checked. ResearchGate's paper was cross-checked against its original publisher PDF. LibraryCentral required browser access. Three sources remain unresolved after public retrieval and browser attempts; no facts have been invented from their URLs.

## A01 — StoneX strategy overview

[8 of the best forex trading strategies](https://www.stonex.com/en-gb/news-and-analysis/forex-trading-strategies/), Matt Weller, May 2, 2023. **Broker education; reviewed accessible article text.**

The article distinguishes trading style from a fully specified strategy. Its catalogue includes trend, range, news, retracement, grid, carry and named time-based approaches. It emphasizes selecting a method for the trader's horizon and circumstances. Momentum oscillators can remain extreme during a sustained trend; an overbought reading alone is not a sell trigger. Scheduled news offers identifiable observation times but increased volatility.

**Use:** strategy taxonomy and regime-dependent hypotheses. **Do not import:** an implied universal “best” strategy, fixed UTC session hours without DST treatment, or grid exposure merely because it appears in the list. No reproducible EUR/USD profitability study is supplied in the reviewed text. For this bot, a session label should support analysis rather than silently reinstate a desk-hours veto.

## A02 — ScienceDirect S095741742501351X

[Supplied publisher link](https://www.sciencedirect.com/science/article/pii/S095741742501351X). **Blocked; identity and content unverified.**

Publisher retrieval returned HTTP 403, and the browser displayed a human-verification challenge. Exact-identifier searches did not establish an authoritative matching record. No title, authors, methods or results were inferred. Need an accessible publisher/author copy or the PDF before admitting findings. Similar-looking FX papers found in search are not substitutes for this identifier.

## A03 — LibraryCentral strategy article

[Forex trading strategies that work](https://librarycentral.org.uk/5044710/4AD156/PwyhUp/forex-trading-strategies-that-work). **Low-confidence educational page; browser text reviewed. Author/date not established.**

The page repeatedly describes trend, range, breakout, carry and scalping approaches, with general advice about risk and backtesting. It provides no identifiable empirical dataset or reproducible performance test in the inspected content. Repeated passages and broad success claims add little independent evidence beyond A01/A04.

**Correction:** its statement that scalpers profit from the bid–ask spread does not describe this bot's market-taking execution. The spread is a cost for such round trips; market making is a different activity. Retain only the taxonomy as low-confidence background, not as corroboration that a strategy works. No verification-overlay instructions or software were executed.

## A04 — Dukascopy strategy overview

[Top Trading Strategies in Forex](https://www.dukascopy.com/swiss/french/marketwatch/articles/top-trading-strategies-in-forex/), July 27, 2023. **Broker education; reviewed strategy/development sections.**

The article distinguishes trend, countertrend, breakout, range, mean-reversion and momentum methods; recommends defined risk, historical tests, demo practice and continued adaptation. Its discussion supports matching methods to conditions, not assuming one setup suits every market.

**Numerical correction:** the swing example sells at 1.0940 and exits at 1.0700 but calls the gain 140 pips. The displayed prices imply **240 pips** before costs. Its printed 1.1960 stop is **1,020 pips** above entry; do not silently “repair” this to a guessed intended value. This example cannot be used as a sizing template. Historical trader-loss percentages and generic 1–2% sizing guidance are not current account statistics or authorization to change our risk.

## A05 — BBVA equilibrium study

[Equilibrium of the EUR/USD exchange rate: A long-term perspective](https://www.bbvaresearch.com/wp-content/uploads/2025/03/Equilibrium-of-the-EUR-USD-exchange-rate-A-long-term-perspective.pdf), María Martínez, Alejandro Neut and David Ramírez, March 3, 2025. **Institutional macro research; 28-page PDF, executive summary, framework, regressions and conclusions inspected.**

The framework separates dollar strength from euro strength using effective-exchange-rate components, then examines financial conditions, monetary policy and reserve demand. Its March 2025 conditional equilibrium scenarios are 1.20 with financial normalization, 1.10 with persistently subdued conditions, and 1.05 with additional trade tensions. These are scenario estimates, not current quotes or near-term targets. The dollar-driver discussion includes data ending December 2024.

**Use:** separate the two sides of EUR/USD in macro annotations. **Limit:** long-run equilibrium does not time M1/M5 entries. Historical smoothed figures include an HP filter; using an ex-post smoothed series in replay would require a real-time reconstruction to avoid future-data contamination. Store publication date, model horizon and assumptions with any scenario.

## A06 — Liberty dissertation link

[Supplied PDF endpoint](https://digitalcommons.liberty.edu/cgi/viewcontent.cgi?article=3607&context=doctoral). **Blocked; content and relevance unverified.**

Public retrieval returned HTTP 403; browser navigation did not expose readable document content. No dissertation title or forex conclusion could be confirmed. The escaped ampersand in the supplied Markdown was normalized to the intended query separator. Need the PDF or an accessible repository landing page. Do not attribute generic ML or trading findings to this source.

## A07 — Guyard and Deriaz, EUR/USD direction prediction

[Predicting Foreign Exchange EURUSD direction using machine learning](https://arxiv.org/pdf/2409.04471), 2024, DOI 10.1145/3696271.3696272. **Conference paper; full methods/results reviewed, PDF pages 6 and 8 visually checked.**

Daily data combine macro releases, other markets and FX features. The study uses eight rolling validation folds and compares fixed versus monthly refitting, feature sets, PCA and stacking. Highest reported accuracy (58.52%) and highest reported return (32.48%) belong to different models: the latter is a meta decision tree with approximately 55.31% accuracy. They must not be advertised as one model's paired performance.

**Useful:** chronological refitting comparisons, publication-age features, simple-model baselines and evaluating profit separately from accuracy. **Caveats:** section 5.3 says 2023 evaluation whereas data/results/figure 9 identify 2022. The displayed return equation has no explicit spread, slippage or financing term. Macro timestamps, revisions, preprocessing-fit boundaries and stacking construction require replication checks. Published headline returns are not verified executable returns for this bot. PCA was not a universal improvement in this experiment.

## A08 — Technical-analysis case study

[RePEc record](https://ideas.repec.org/a/bfb/srdjou/2024-07_7.html) and [publisher full text](https://www.srdsjournal.eu/articles/files/2024-7%20-%20USEFULNESS%20OF%20TECHNICAL%20ANALYSIS%20IN%20THE%20FOREX%20MARKET.pdf): Miguel Lampreia, Erjola Barbullushi and Ismet Voka, *Usefulness of Technical Analysis in the Forex Market: The EUR/USD Pair*, 2024, pp. 104–112. **Descriptive chart study; methods/results/conclusion reviewed.**

The study examines daily EUR/USD in 2019 with older weekly context, using support/resistance, trendlines, candlesticks and Fibonacci. It deliberately selects a pre-COVID/pre-war period. The authors interpret the chart examples as evidence of usefulness.

**Use:** ideas for objective, prospective pattern tests. **Limit:** descriptive examples are not a costed, locked out-of-sample trading experiment; no comprehensive rule-based trade ledger is established by the reviewed analysis. Avoiding disrupted periods does not demonstrate robustness to them. The pre-1999 “EUR/USD” history also needs synthetic-series provenance before reuse. Do not adopt the paper's “highest volatility” characterization of EUR/USD as a general market fact.

## A09 — Theofilatos, Likothanassis and Karathanasopoulos

[Supplied ResearchGate record](https://www.researchgate.net/publication/346751803_Modeling_and_Trading_the_EURUSD_Exchange_Rate_Using_Machine_Learning_Techniques); [original publisher](https://etasr.com/index.php/ETASR/article/view/200); [publisher PDF](https://etasr.com/index.php/ETASR/article/download/200/135). *Modeling and Trading the EUR/USD Exchange Rate Using Machine Learning Techniques*, **2012**, DOI 10.48084/etasr.200. **Four-page paper reviewed.**

The study compares five classifiers using lagged daily returns against naive and MACD baselines. Dates span 2002–2010, with a chronological train/validation/test split. Table III reports random-forest annual return of about 7.28% after its assumed costs and 53.50% direction accuracy; these are the paper's simulated results, not a current forecast.

**Use:** compare modest models, repeat stochastic fits and measure costs. **Caveats:** the text calls Table III a validation result, while surrounding discussion refers to out-of-sample performance. Its cost model assumes roughly one pip for institutional-size transactions and treats reference-rate data as bid rates in the costing discussion. Neither that liquidity assumption nor ECB-reference-rate execution can be assumed for OANDA. Publication is 2012 despite the later ResearchGate upload. Reproduce with executable bid/ask and explicit partitions before drawing conclusions.

## A10 — ScienceDirect S1110016825012323

[Supplied publisher link](https://www.sciencedirect.com/science/article/pii/S1110016825012323). **Blocked; identity and content unverified.**

Public retrieval failed; browser access displayed the publisher's human-verification challenge. Exact-identifier search did not establish a matching authoritative record. No findings admitted. Need the PDF or accessible author/publisher copy; a different paper with similar terminology is not equivalent evidence.

## A11 — IESE dollar–euro study

[Study of the Dollar-Euro Exchange Rate](https://www.iese.edu/media/research/pdfs/DI-0620-E.pdf), Miguel A. Ariño and Miguel A. Canela, Working Paper 620, March 2006. **Historical statistical study; methods and conclusions inspected.**

The analysis covers January 1999–December 2005. It describes longer trends plus one-to-three-month cycles, while finding insufficient evidence to reject white noise for daily dollar–euro returns in its sample. A trade-weighted dollar index provides context for cross-currency movements. The cycle discussion includes an AR(1) coefficient near 0.95.

**Use:** demand a strong naive/random-walk baseline and separate descriptive fit from tradable prediction. **Limit:** the cycle parameter and its conclusion about stable volatility/no ARCH effects are sample-specific, not constants to install in a 2026 intraday bot. Retrospectively decomposing a trend does not establish that it was knowable in real time.

## A12 — FOREX.com EUR/USD white paper

[How to Trade EUR/USD: A Comprehensive Guide](https://www.filesandimages.com/Brand/forex/whitepapers/FX-UK-EU-How-to-Trade-EUR-USD.pdf), Matt Weller. **Broker education; 11-page PDF text reviewed. Publication date not established; examples include 2020–2023 data.**

The guide links EUR/USD to relative policy expectations, German–US two-year yields, economic releases and risk appetite. It explicitly treats economic-report importance as regime-dependent. Its opening-range example builds the first hour's high/low, then trades a break; it also supplies a failed-breakout illustration. Hourly return tendencies are inconsistent, and GMT charts do not necessarily adjust for DST.

**Use:** rate-differential context and a clearly bounded opening-range experiment with failure accounting. **Limits:** illustrative trades are not a backtest; pre-1999 seasonal history uses interpolated constituent currencies. Static historical averages, demographic counts and illustrative levels must not be treated as current observations. The breakout outline leaves stops, expiry and fill rules to be specified before testing.

## A13 — FOREX.com Fed-expectations commentary

[EUR/USD Update: Will Fed Expectations Keep Pressure on the Euro?](https://www.forex.com/en/news-and-analysis/eur-usd-update-will-fed-expectations-keep-pressure-on-the-euro/). **Market commentary; article body reviewed, publication date not established in the retrieved text.**

The thesis ties dollar support to relative Fed/ECB expectations and combines that narrative with range, MACD and RSI observations. However, the retrieved page contains specific policy rates, meeting dates/probabilities and technical levels without a verified as-of timestamp for this intake.

**Use:** a template for separating macro thesis, technical state, invalidation and future events. **Quarantine:** all numerical rates, probabilities, meeting dates and price levels from current decision context until dated and independently checked against primary sources. Retrieval time is not publication time. This review does not establish a current EUR/USD direction, and this article's headline is not a standing sell instruction.

## Proposed improvements derived from this review

These are our engineering proposals, not features implemented by reading these sources. They complement the [video research](VIDEO_RESEARCH_2026-09-29.md).

| Priority | Proposal | Concrete design | Evaluation |
| --- | --- | --- | --- |
| 1 | Time-aware knowledge records | Record source URL, publication/as-of time, retrieval time, horizon, access status and evidence class; undated market numbers are reference-only | Replay must never consume a fact before its release; expired commentary cannot provide current direction |
| 2 | Match model selection to trading outcomes | Track net expectancy in initial-risk units, drawdown, adverse tails, turnover, exposure and calibration alongside accuracy | Same execution assumptions and evaluation dates for all candidates; no mixing one model's accuracy with another's return |
| 3 | Causal loss comparisons | Compare losses and wins within fixed session/regime/entry/cost groups; retain specific failure labels and unknowns | Separate signal failure from fill slippage, financing and exit policy; one loss cannot establish a cause |
| 4 | Modest ML baselines | Compare logistic regression and shallow/tree models with persistence, majority direction, no-trade and the existing strategy | Chronological folds, train-only scaling/selection, time-safe out-of-fold stacking and untouched final holdout |
| 5 | Scheduled adaptation with stable evidence | Hourly compile new observations; create a new frozen challenger only on a declared refit schedule with enough newly available labels | Versioned parameters, validation dates, rejected trials and forward observations; no automatic production promotion |
| 6 | Opening-range challenger | Separately test a first-hour range using a named session/timezone, completed bars, explicit order expiry and one-attempt policy | Include false breaks, missed fills, executable sides, costs, news conditions and DST transitions |
| 7 | Macro context as optional information | Compare relative yield/policy changes and age of released data as additional features, available only after publication | Ablation against the same price-only baseline; long-term fair value never becomes a scalp price target |

### Research contract for any future implementation

Freeze the candidate, data boundaries and evaluation rule before seeing final holdout results. Train only on labels available at each fit time; purge overlapping target/holding windows at split boundaries. Fit feature selection, scalers and dimensional transforms inside each training fold. Store original release vintages where revised macro data could otherwise leak future information. Do not replace missing release time with midnight.

Start with returns and features whose information time can be proven. Align cross-market closes and holidays to the prediction timestamp. Treat broker tick volume as a venue-specific measure rather than total global FX volume. Show the incremental value of each added feature instead of accumulating correlated confirmations.

Evaluate observed bid/ask, realistic order latency, spread, stop slippage and relevant financing. Preserve a cost ledger so spread already embedded in fills is not deducted twice. Hold sizing constant when comparing signal quality; increased leverage cannot establish learning. Report uncertainty and all attempted variants, including failures. A small favorable sample or higher accuracy alone does not justify promotion.

For an opening-range prototype, define Europe/London 08:00–09:00 as an explicit **proposed** range window, not a sourced universal session definition. Freeze the range after 09:00; test a completed M5 close outside it with entry on the next quote, opposite-boundary stop, 2R target, cancellation before the next session and a predeclared holding limit. These are our candidate choices requiring validation. They do not restrict other strategies from trading during the broker's open market.

### Hourly learning versus hourly refitting

Hourly documentation updates can consolidate new trades and hypotheses. Refitting every hour on largely unchanged or unresolved outcomes can overfit recent noise. Keep three distinct records: observed facts, proposed explanations, and tested model changes. Candidate results belong to the precise model version and horizon that produced them. Wins need the same scrutiny as losses: intended setup success, favorable fill luck and an oversized position are different explanations.

## Knowledge-base receipt and scope

This root-level desk document is read by the existing hourly knowledge compiler and indexed by content hash in `desk/knowledge/current.json`. [Documentation guide](DOCUMENTATION_GUIDE.md) explains the boundary: indexing makes the research accessible as a reference; it does not semantically turn the prose into broker orders. The experiments above remain proposals.

**Completed:** findings from 10 accessible sources, quality caveats, corrections, source links, and prioritized bot-research designs. **Outstanding access:** A02, A06 and A10 require readable copies. Their records deliberately contain no inferred trading lessons. Source admission does not claim that any method has been validated for the bot or that account performance has improved.
