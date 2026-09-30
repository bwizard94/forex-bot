# Forex Sentinel

EUR/USD analysis and OANDA practice trading, with a local dashboard, trade journals,
hourly knowledge compilation and autonomous strategy experiments. Python 3.12.

## Run locally

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your own OANDA practice credentials.
python -m src.main
```

Open http://127.0.0.1:8765/. New processes start with entries paused. To explicitly
arm practice entries, set ENABLE_TRADING=true in your private .env and use the
trading control after broker reconciliation. Never commit credentials.

```sh
python -m pytest -q
node tests/dashboard_actions.cjs
```

Run tests with the example/default settings, independently of any active account's
custom .env profile. Tests do not prove profitability.

## Documentation

Read [standing project guidance](README.part1.md), [setup reference](README.part2.md),
[operating rules](desk/OPERATING.md), [scalping rules](desk/SCALPING.md),
[background service](desk/BACKGROUND_SERVICE.md), and
[documentation guide](desk/DOCUMENTATION_GUIDE.md).

The [five-video research review](desk/VIDEO_RESEARCH_2026-09-29.md) records
timestamped source findings and proposed EUR/USD experiments. These proposals
are documented research, not activated strategies.

The [13-source article review](desk/ARTICLE_RESEARCH_2026-09-29.md) separates
strategy education, machine-learning studies, long-term macro research and dated
market commentary, with access limitations and proposed validation work.

The [additional research and news review](desk/RESEARCH_NEWS_2026-09-30.md)
records four new works, one duplicate and the [Forex Factory primary news policy](desk/FOREXFACTORY.md).
Version 2.22.1 reports news-source availability and fallback use in the News view
and health endpoint. Forex Factory requests use a five-minute retry/cache interval;
blocked primary access does not masquerade as a working feed.

The [forex bot design review](desk/BOT_DESIGN_RESEARCH_2026-09-30.md) compares
commercial EAs and open frameworks. Release 2.22.2 adds recurring indicator
lookahead and warm-up diagnostics, visible in Overview and Health.

The [strategy lab](desk/STRATEGY_LAB.md) evaluates prospective experiments without
automatically promoting them into broker execution. [Contextual loss review](desk/CONTEXTUAL_LOSS_REVIEW.md)
separates observations from causal hypotheses. No profitable strategy is established.
Some operating notes record the original operator's demo experiments; clone defaults
and your own explicit configuration determine your actual risk and entry policy.

## Source snapshot and private runtime data

This repository contains application code, tests, static assets, scripts and selected
operating documentation. Credentials, broker databases, logs, generated trade journals,
knowledge revisions, research datasets and bundled archives stay local and are ignored.
The bot regenerates runtime documents under desk/ and stores local data under data/.
References to generated reports become available after the corresponding jobs run.

The supplied macOS service and launcher describe the original installation paths;
adjust them for your machine before installing. Closing a chat does not stop an
installed background service, but the host must remain running and connected.

Remotes: [GitHub](https://github.com/bwizard94/forex-bot) · [GitLab](https://gitlab.com/bwizard/forex-bot).

Release 2.23.0 fixes selected-direction support scores, caps correlated indicator
families, corrects exit attribution and experiment counts, and replaces causal
claims in contextual journals with evidence and hypotheses. Reversal/re-entry
filters are evaluated in shadow and prospective research; the diagnostic comparison
did not establish improvement. See [release evidence](desk/RELEASE_2.23.0.md).

The [bot-construction article review](desk/ARTICLE_BOT_BUILDING_2026-09-30.md)
compares ten supplied links (nine readable) with the implementation and prioritizes
policy-specific performance measurement, execution costs and replay agreement.

The [public repository code review](desk/GITHUB_REPOSITORY_REVIEW_2026-09-30.md)
compares six unique projects, records concrete validation and ownership weaknesses,
and identifies testing and attribution improvements worth evaluating.

The [research validation upgrade](desk/RESEARCH_VALIDATION_UPGRADE_2026-09-30.md)
adds evaluator controls, a standalone five-scenario cost matrix and matched-context
performance/cost attribution. These reports do not change trading policy.

[Release 2.24.0](desk/RELEASE_2.24.0.md) schedules attribution hourly and active-settings
cost diagnostics every six hours, with rejection reasons, matched-version comparisons
and separate execution research for news, portfolio caps and fees.

[Release 2.25.0](desk/RELEASE_2.25.0.md) adds loss concentration reports, ongoing
sampled trade excursions, separate prospective entry/exit experiments, measured
execution research, and evidence-gated promotion/rollback plans.
