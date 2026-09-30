# EUR/USD research and news intake — 30 September 2026

Status: reference research, not validated execution rules. Five supplied research
links represent four new works and one duplicate of a previously reviewed work.
Forex Factory is the operator-selected primary headline discovery source; this
preference is not a claim that every contributor is equally reliable.

## R01 — Novel news sentiment and trading costs

Kebe and Uhl, *High-Frequency Effects of Novel News on the EURUSD Exchange Rate*,
online 2022, Journal of Behavioral Finance.
[Supplied article](https://www.tandfonline.com/doi/full/10.1080/15427560.2022.2100386).
Canonical ID: DOI 10.1080/15427560.2022.2100386.

Access: publisher-indexed abstract, introduction, backtest and conclusion passages;
direct full-page retrieval failed. Not every methods table was inspected.
The 2003–2018 study finds delayed relationships between novel Euro-specific news
sentiment and EUR/USD, with a relationship change around the financial/debt crises.
Its hourly strategy's attractive gross performance did not survive transaction
costs. The reported one-way 0.5-basis-point cost case already produced negative
performance over the full period. This is evidence against treating sentiment
accuracy or gross returns as an executable edge.

Proposed experiment: cluster repeated stories, preserve first-observed timestamps,
and compare raw versus smoothed sentiment under the same chronological holdout
and measured execution costs. These proposals are ours, not demonstrated improvements.

## R02 — Market structure and volatility

BIS, December 2022 Quarterly Review,
[The global foreign exchange market in a higher-volatility environment](https://www.bis.org/publications/qr-202212/global-foreign-exchange-market-higher-volatility-environment).
Access: full public article.

The April 2022 survey reports approximately $7.5 trillion daily global FX turnover.
Growth included interdealer activity and shorter-maturity derivatives; frequent
rollover mechanically raises turnover. Greater bilateral trading also reduces
visibility relative to multilateral venues. These are historical market-structure
observations, not today's liquidity measurements.

Engineering implication (inference): do not equate a broker's tick count with
global volume, or use aggregate FX turnover to assume cheap EUR/USD fills.
Evaluate each session with actual spread, slippage, latency and rejection rates.
A larger market can still be expensive for this bot at a particular instant.

## R03 — Duplicate machine-learning study

[Supplied RePEc record](https://ideas.repec.org/p/arx/papers/2409.04471.html)
points to [arXiv 2409.04471](https://arxiv.org/abs/2409.04471), the Guyard/Deriaz
study already reviewed as A07 in [the article review](ARTICLE_RESEARCH_2026-09-29.md).
Canonical evidence identity: arXiv:2409.04471; DOI 10.1145/3696271.3696272.

This is an alternative catalogue entry, not independent replication. Retain A07's
limitations concerning evaluation dates, model-specific accuracy versus returns,
and absent explicit execution-cost treatment. Do not give this source a second
vote when ranking research support.

## R04 — Interest-rate events do not give a fixed direction

Carvalho, Couto and Pimentel, *EUR/USD Exchange Rate Characterization:
Study of Events*, Economies 10(12), 294, 24 November 2022.
[Supplied publisher page](https://www.mdpi.com/2227-7099/10/12/294);
[accessible publisher article at EconStor](https://www.econstor.eu/bitstream/10419/328594/1/economies-10-00294.pdf).
Canonical ID: DOI 10.3390/economies10120294.

Access: article text through the institutional PDF; publisher direct retrieval
failed. The study selects 12 interest-rate events during 1999–2020 and compares
daily returns against a mean-adjusted baseline. It finds significant abnormal
returns for some event windows, but no consistently predictable direction after
rate changes. Twelve selected events and daily horizons cannot establish an
intraday entry rule or a profitable costed strategy.

Proposed experiment: distinguish scheduled event, released surprise, and observed
price reaction. Compare post-event continuation and reversal separately, using
only information available at decision time. Do not encode “rate hike = buy”
as a universal rule.

## R05 — Technical indicators as hypotheses

Bhavani and Pichai, *A Study of the Euro and U.S Dollar in the Foreign Exchange
Market Using Technical Analysis Tools*, 2016.
[Supplied author-uploaded article](https://www.researchgate.net/publication/312623592_A_STUDY_OF_THE_EURO_AND_US_DOLLAR_IN_THE_FOREIGN_EXCHANGE_MARKET_USING_TECHNICAL_ANALYSIS_TOOLS).
Access: full extracted article text. ResearchGate's 2017 upload is not its
publication year.

The discussion illustrates stochastic, RSI, Bollinger Bands and parabolic SAR.
The conclusion describes weekly closes over 2014–2016, while examples also
reference 2013. Chart interpretations and qualitative claims do not constitute
a reproducible costed, held-out trade ledger. SAR wording is ambiguous enough
that it should not be transcribed into code without independent specification.

Proposed experiment: test a simple baseline and add one indicator at a time.
Measure incremental net expectancy and drawdown; do not count several
price-derived indicators as independent evidence. The paper is educational
input, not proof of a profitable strategy.

## News-source policy and implementation

[Forex Factory news](https://www.forexfactory.com/news) is now the first source
attempted by the news harvester and takes precedence before result limits.
The global stream is filtered with the existing EUR/USD macro relevance filter.
Fed/ECB and other feeds remain available for corroboration and fetch failures.
The separate calendar feed is retained.

The public page mixes reporting, analysis and comments and identifies originating
publishers. Preserve the Forex Factory story URL; follow its original-report
link when investigating a claim. Verify release figures against the issuing
central bank/statistical agency. Comments and advertisements are not evidence.

Current automated parser limitations: it captures headline text and Forex Factory
story URLs, not the original publisher URL or a verified publication timestamp.
Fetch time is not publication time. Automatic original-source extraction,
semantic novelty clustering and latency-aware news backtests remain proposed
work, not completed capabilities. Missing dates must not be fabricated.
See [standing news guidance](FOREXFACTORY.md).

## Evaluation queue — proposed, not activated

1. News novelty and provenance: canonical story clusters, known versus missing
   publication time, original release link, first seen and decision timestamps.
2. Cost-aware news ablation: identical frozen price strategy with and without
   news features; chronological train/validation/test splits; no future revisions.
3. Contextual event study: EUR/USD session, event surprise, spread and volatility
   at entry; distinguish normal market loss from reproducible execution defects.
4. Indicator simplification: one-feature additions against the same baseline,
   accounting for all attempted variants and reporting failed variants too.

Promotion requires positive net evidence on untouched data and forward practice,
with enough observations and uncertainty estimates. Indexing this document makes
it retrievable; it does not train a model or change its execution rules.

## Verification of this change

All 390 Python tests passed, including source priority, fallback, challenge-page
rejection and prevention of general-news quote extraction. A direct public HTTP
probe outside the restricted sandbox returned HTTP 403. Web research could read
the page, but unattended bot access is currently blocked. Backup feeds remain
necessary. The running trading service was not restarted for this research task;
source changes take effect on its next controlled reload. Knowledge compilation
was run immediately and both document hashes were verified in the index.

### Follow-up release 2.22.1

The operator subsequently authorized deployment and publication to both remotes.
Added source availability and fallback diagnostics to Health and the News
dashboard, shared five-minute request caching/backoff, and explicit research
documents in the documentation-read audit. Verification: 394 Python tests and
48 dashboard action scenarios passed; JavaScript syntax and Git whitespace checks
passed. Deployment results are recorded in BACKGROUND_SERVICE.md.
