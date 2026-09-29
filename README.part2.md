## What this project is

Forex Sentinel is a **single-pair trading desk in software**. It:

- Pulls live EUR/USD quotes and M1/M5/H1/D1 candles from **OANDA v20 practice** (the same account that executes).
- Cross-checks mids with **CurrencyFreaks** and uses **Twelve Data** only as a candle backup (rate-limited; the live loop must not depend on it).
- Scores deterministic **BUY / SELL / HOLD** on **M5**, with **H1** as the map and **D1** as bias.
- Sizes off ATR, places **practice** market orders, journals every fill in English, restudies expectancy, and rewrites a playbook it will reread on the next cycle.
- Mirrors desk fills onto a **MetaTrader 4 demo** when credentials exist (Wine terminal on Linux and/or the operator’s laptop on the same MetaQuotes account).
- Serves a **hub** so a human can see quotes, the marked tape, journals, news, briefings, and pause trading.

It is **not** a broker, not a signals-for-sale product, and not a research notebook that happens to have a `buy()` function.

---

## What it is trying to achieve

The operator’s intent, accumulated in this repo:

1. **Become a better EUR/USD scalper** — small, calculated risk, more than one open ticket when the tape is worth it, not “constant buying,” not a swing that sits through D1.
2. **Survive** — preserve capital (Dukascopy #1). Stops are mandatory. Daily halt and drawdown breaker exist so one hole does not blow the book.
3. **Learn in public (to itself)** — every fill gets a thesis; every close gets a post-mortem; fingerprints that keep losing get skipped; historical EUR/USD is replayed into `setup_memory`.
4. **Stay honest with the teacher** — if the human puts a 1-unit SELL on the OANDA demo, the bot must **leave it alone** and still be able to trade beside it.
5. **See the same ticket on two demos** — OANDA practice + MT4 demo, one hunt, two venues.
6. **Notice news without trading the headline** — harvest EUR/USD wires at 05:00 UTC, guess lean, score later M5, compile category hit-rates. The Ox scalp still fires the ticket.

Success is **positive expectancy on EUR/USD scalps after costs**, with a journal that explains why — not a high win count, not more indicators, not a new pair.

---

## Setup and run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# or copy .env from the operator Drive / Desktop forex folder (practice keys)
# never commit .env
python -m src.main
```

Open `http://127.0.0.1:8765`.

### Secrets (`.env`, gitignored)

A successor AI **cannot place demo fills from git alone**. Practice keys live in a private `.env` on the operator’s **Google Drive / Desktop `forex` folder** (same tree as this README on Drive). After `git clone` / `git pull`, copy that `.env` beside `README.md`. Do not commit it. Do not paste tokens into PRs or chat.

Filled on the Drive copy so the desk can trade demos: OANDA practice, Twelve Data, CurrencyFreaks, MT4 MetaQuotes-Demo login + trade password + bridge secret, `ENABLE_TRADING=true`. Still empty (optional — the loop still runs): Slack bot token, Composio / Sheets, Tavily, MetaApi. Keep `OANDA_ENVIRONMENT=practice`. Keep the Drive folder private (owner only).

The single-file README on git `main` (commit 1beb63b) is the canonical brief. Concatenate README.part1.md + this file for the Drive copy.

## Safety

This talks to **OANDA practice** when `OANDA_ENVIRONMENT=practice`. `ENABLE_TRADING=false` or hub Pause stops new orders. Do not switch to live fxTrade unless a human explicitly accepts that risk.
