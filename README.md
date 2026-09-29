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
